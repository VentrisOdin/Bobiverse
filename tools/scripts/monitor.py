#!/usr/bin/env python
"""
bobctl monitor

Real-time streaming dashboard for the Bobiverse.
Shows node status, task summary, and Dev Council stats.
"""

import os
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from requests import RequestException

from rich.live import Live
from rich.layout import Layout
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://100.111.201.26:5080")
DEFAULT_REFRESH = float(os.getenv("BOBCTL_MONITOR_INTERVAL", "1.0"))  # seconds


def _safe_get(path: str, default: Any) -> Any:
    url = ORCHESTRATOR_URL.rstrip("/") + path
    try:
        resp = requests.get(url, timeout=1.5)
        resp.raise_for_status()
        return resp.json()
    except RequestException:
        return default


def fetch_nodes() -> List[Dict[str, Any]]:
    """
    Fetch worker nodes from /nodes and inject a synthetic 'orchestrator' node
    so the dashboard always shows Prime Bob itself.
    """
    nodes = _safe_get("/nodes", [])

    # Build a synthetic orchestrator node
    host = socket.gethostname()
    orch_name = os.getenv("BOBIVERSE_ORCHESTRATOR_NAME", "orchestrator")

    # Pretend it's just seen "now" so it shows as online
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    orch_node = {
        "name": orch_name,
        "role": "orchestrator",
        "tailscale_ip": None,  # could be filled from env later if you like
        "capabilities": ["prime_bob"],
        "last_seen": now,
        "load": "-",
        "free_memory_mb": "-",
        "active_councils": [],
        "host": host,
        "orchestrator_url": ORCHESTRATOR_URL,
    }

    # Put orchestrator at the top
    return [orch_node] + (nodes or [])


def fetch_tasks(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Expected shape (example):

    [
      {
        "task_uuid": "...",
        "high_level_type": "dev",
        "submitted_at": "2025-12-05T18:59:01.123456Z",
        "final_status": "running" | "pending" | "completed" | "failed",
        "last_execution_id": "...",
        ...
      },
      ...
    ]
    """
    return _safe_get(f"/db/tasks?limit={limit}", [])


def iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Handle both "...Z" and offset forms
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        # Normalise: if no timezone, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def human_age(dt_obj: Optional[datetime]) -> str:
    if not dt_obj:
        return "?"
    now = datetime.now(timezone.utc)
    delta = now - dt_obj
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d}"


def build_nodes_panel(nodes: List[Dict[str, Any]]) -> Panel:
    """
    Adapted to your actual /nodes response, e.g.:

    {
      "name": "data-mainpc",
      "role": "worker",
      "tailscale_ip": "100.x.x.x",
      "capabilities": ["shell", "python", "dev"],
      "last_seen": "2025-12-07T17:35:32.599280Z",
      "load": 0.0x,
      "free_memory_mb": 6119,
      "active_councils": ["dev"]
    }
    """
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Node", style="bold")
    table.add_column("Role")
    table.add_column("Status")
    table.add_column("Load")
    table.add_column("Free Mem (MB)")
    table.add_column("Active Councils")
    table.add_column("Last Seen (age)")
    table.add_column("Tailscale IP")

    now = datetime.now(timezone.utc)

    for n in nodes:
        # Derive status from last_seen freshness
        last_seen_dt = iso_to_dt(n.get("last_seen"))
        if last_seen_dt:
            age_sec = (now - last_seen_dt).total_seconds()
        else:
            age_sec = None

        if age_sec is None:
            status = "unknown"
        elif age_sec < 15:
            status = "online"
        elif age_sec < 60:
            status = "stale"
        else:
            status = "offline"

        status_text = Text(status)
        if status == "online":
            status_text.stylize("bold green")
        elif status == "stale":
            status_text.stylize("bold yellow")
        else:
            status_text.stylize("bold red")

        councils = ", ".join(n.get("active_councils") or [])
        last_seen_age = human_age(last_seen_dt)

        table.add_row(
            str(n.get("name") or "?"),
            str(n.get("role") or "?"),
            status_text,
            f"{n.get('load', '-')}",
            f"{n.get('free_memory_mb', '-')}",
            councils or "-",
            last_seen_age,
            str(n.get("tailscale_ip", "-")),
        )

    return Panel(table, title="[b]Nodes[/b]", border_style="cyan")


def build_tasks_panel(tasks: List[Dict[str, Any]]) -> Panel:
    # Aggregate counts
    pending = running = completed = failed = 0
    newest = None
    oldest = None

    for t in tasks:
        status = (t.get("final_status") or "").lower()
        if status in ("pending", "queued"):
            pending += 1
        elif status in ("running", "in_progress"):
            running += 1
        elif status in ("completed", "done"):
            completed += 1
        elif status in ("failed", "error"):
            failed += 1

        # Try multiple possible timestamp fields from the API
        ts_raw = (
            t.get("submitted_at")
            or t.get("created_at")
            or t.get("created_at_utc")
            or t.get("updated_at")
        )
        sub_at = iso_to_dt(ts_raw)
        if sub_at:
            if oldest is None or sub_at < oldest:
                oldest = sub_at
            if newest is None or sub_at > newest:
                newest = sub_at

    # Summary table
    summary_table = Table(box=box.SIMPLE_HEAVY, expand=True)
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Value")

    total = len(tasks)
    summary_table.add_row("Total tasks (last N)", str(total))
    summary_table.add_row("Pending", str(pending))
    summary_table.add_row("Running", str(running))
    summary_table.add_row("Completed", str(completed))
    summary_table.add_row("Failed", str(failed))
    summary_table.add_row("Oldest age", human_age(oldest))
    summary_table.add_row("Newest age", human_age(newest))

    # Recent tasks table
    recent_table = Table(box=box.MINIMAL, show_header=True, expand=True)
    recent_table.add_column("UUID", no_wrap=True)
    recent_table.add_column("Type", style="magenta")
    recent_table.add_column("Status")
    recent_table.add_column("Age")

    # Sort newest first
    tasks_sorted = sorted(
        tasks,
        key=lambda t: iso_to_dt(
            t.get("submitted_at") or t.get("created_at") or t.get("created_at_utc") or t.get("updated_at")
        ) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:10]

    for t in tasks_sorted:
        status = (t.get("final_status") or "").lower()
        status_text = Text(status or "?")
        if status in ("running", "in_progress"):
            status_text.stylize("bold green")
        elif status in ("pending", "queued"):
            status_text.stylize("yellow")
        elif status in ("failed", "error"):
            status_text.stylize("bold red")
        else:
            status_text.stylize("dim")

        ts_raw = t.get("submitted_at") or t.get("created_at") or t.get("created_at_utc") or t.get("updated_at")
        age = human_age(iso_to_dt(ts_raw))
        recent_table.add_row(
            (t.get("task_uuid") or "")[:8] + "…",
            str(t.get("high_level_type") or "-"),
            status_text,
            age,
        )

    # Combine summary + recent into a grid
    grid = Table.grid(expand=True)
    grid.add_row(summary_table)
    grid.add_row(recent_table)

    return Panel(grid, title="[b]Tasks[/b]", border_style="magenta")


def build_dev_panel(tasks: List[Dict[str, Any]]) -> Panel:
    """
    Extract dev-focused metrics from tasks list.
    """
    dev_tasks = [t for t in tasks if (t.get("high_level_type") or "").startswith("dev")]
    total = len(dev_tasks)

    # Last 3 summaries
    last_three = sorted(
        dev_tasks,
        key=lambda t: iso_to_dt(
            t.get("submitted_at") or t.get("created_at") or t.get("created_at_utc") or t.get("updated_at")
        ) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:3]

    # Latency stats: look at durations from executions if embedded
    durations: List[float] = []
    running_task: Optional[Dict[str, Any]] = None

    for t in dev_tasks:
        # Recognise a running one
        status = (t.get("final_status") or "").lower()
        if status in ("running", "in_progress") and running_task is None:
            running_task = t

        # If task has a "last_duration_ms" field we can use it
        d_ms = t.get("last_duration_ms")
        if isinstance(d_ms, (int, float)) and d_ms > 0:
            durations.append(d_ms / 1000.0)

    avg_latency = sum(durations) / len(durations) if durations else None

    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    model = os.getenv("DEV_BOB_MODEL", "DeepSeek-Coder:6.7b (configured)")
    table.add_row("Model", model)
    table.add_row("Total dev tasks (window)", str(total))
    table.add_row(
        "Avg latency (s, if reported)",
        f"{avg_latency:.2f}" if avg_latency is not None else "-",
    )

    if running_task:
        ts_raw = (
            running_task.get("submitted_at")
            or running_task.get("created_at")
            or running_task.get("created_at_utc")
            or running_task.get("updated_at")
        )
        age = human_age(iso_to_dt(ts_raw))
        table.add_row("Current dev task", (running_task.get("task_uuid") or "")[:8] + "…")
        table.add_row("Current dev age", age)
    else:
        table.add_row("Current dev task", "None")

    # Last 3 summaries
    lt_table = Table(box=box.MINIMAL)
    lt_table.add_column("When")
    lt_table.add_column("Summary")

    for t in last_three:
        ts_raw = t.get("submitted_at") or t.get("created_at") or t.get("created_at_utc") or t.get("updated_at")
        ts = iso_to_dt(ts_raw)
        ts_str = ts.astimezone(timezone.utc).strftime("%H:%M:%S") if ts else "?"
        summary = t.get("output_summary") or t.get("title") or "(no summary)"
        if len(summary) > 80:
            summary = summary[:77] + "…"
        lt_table.add_row(ts_str, summary)

    grid = Table.grid(expand=True)
    grid.add_row(table)
    grid.add_row(Panel(lt_table, title="Last 3 dev tasks", border_style="dim"))

    return Panel(grid, title="[b]Dev Council[/b]", border_style="green")


def build_layout(nodes: List[Dict[str, Any]], tasks: List[Dict[str, Any]]) -> Layout:
    layout = Layout()

    layout.split_column(
        Layout(name="upper", size=14),
        Layout(name="middle", size=14),
        Layout(name="lower"),
    )

    layout["upper"].update(build_nodes_panel(nodes))
    layout["middle"].update(build_tasks_panel(tasks))
    layout["lower"].update(build_dev_panel(tasks))

    return layout


def monitor_loop(refresh: float = DEFAULT_REFRESH) -> None:
    with Live(auto_refresh=False, screen=True) as live:
        while True:
            nodes = fetch_nodes()
            tasks = fetch_tasks(limit=100)
            layout = build_layout(nodes, tasks)
            live.update(layout, refresh=True)
            time.sleep(refresh)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Bobiverse real-time monitor (bobctl monitor)")
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=DEFAULT_REFRESH,
        help="Refresh interval in seconds (default: %(default)s)",
    )
    args = parser.parse_args()
    monitor_loop(refresh=args.interval)


if __name__ == "__main__":
    main()
