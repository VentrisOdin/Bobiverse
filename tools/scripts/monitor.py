#!/usr/bin/env python
"""
bobctl monitor

Real-time streaming dashboard for the Bobiverse.
Shows node status, task summary, and Dev/Architect Bob stats.
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
        "submitted_at": "...Z",
        "final_status": "running" | "pending" | "completed" | "failed",
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
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
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
    /nodes example:

    {
      "name": "data-mainpc",
      "role": "worker",
      "tailscale_ip": "100.x.x.x",
      "capabilities": ["shell", "python", "dev"],
      "last_seen": "2025-12-07T17:35:32.599280Z",
      "load": 0.0x,
      "free_memory_mb": 6119,
      "active_councils": ["dev_council", "architect_bob"]
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

    recent_table = Table(box=box.MINIMAL, show_header=True, expand=True)
    recent_table.add_column("UUID", no_wrap=True)
    recent_table.add_column("Type", style="magenta")
    recent_table.add_column("Status")
    recent_table.add_column("Age")

    tasks_sorted = sorted(
        tasks,
        key=lambda t: iso_to_dt(
            t.get("submitted_at")
            or t.get("created_at")
            or t.get("created_at_utc")
            or t.get("updated_at")
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

        ts_raw = (
            t.get("submitted_at")
            or t.get("created_at")
            or t.get("created_at_utc")
            or t.get("updated_at")
        )
        age = human_age(iso_to_dt(ts_raw))
        recent_table.add_row(
            (t.get("task_uuid") or "")[:8] + "…",
            str(t.get("high_level_type") or "-"),
            status_text,
            age,
        )

    grid = Table.grid(expand=True)
    grid.add_row(summary_table)
    grid.add_row(recent_table)

    return Panel(grid, title="[b]Tasks[/b]", border_style="magenta")


def node_status_from_name(nodes: List[Dict[str, Any]], name: str) -> str:
    """
    Look up a node by name in the nodes list and return a status string:
    'online', 'stale', 'offline', or 'unknown'.

    This is used to show Dev Bob / Architect Bob status even if they
    aren't explicitly listed in active_councils.
    """
    now = datetime.now(timezone.utc)

    for n in nodes:
        if str(n.get("name")) != name:
            continue

        last_seen_dt = iso_to_dt(n.get("last_seen"))
        if not last_seen_dt:
            return "unknown"

        age_sec = (now - last_seen_dt).total_seconds()
        if age_sec < 15:
            return "online"
        elif age_sec < 60:
            return "stale"
        else:
            return "offline"

    return "unknown"


def _council_status_text(
    nodes: List[Dict[str, Any]],
    council_keys: List[str],
    fallback_node: Optional[str] = None,
) -> Text:
    """
    Infer council status (online/stale/offline/missing) from nodes' active_councils + last_seen.
    council_keys = any of these values present in node['active_councils'] (to allow aliasing).
    fallback_node = if not present in active_councils, fall back to node's own online/offline state.
    """
    now = datetime.now(timezone.utc)
    ages: List[float] = []

    # First: use active_councils if present
    for n in nodes:
        active = n.get("active_councils") or []
        if not isinstance(active, list):
            continue

        if not any(k in active for k in council_keys):
            continue

        last_seen_dt = iso_to_dt(n.get("last_seen"))
        if not last_seen_dt:
            continue

        age_sec = (now - last_seen_dt).total_seconds()
        if age_sec >= 0:
            ages.append(age_sec)

    # If no council-level ages found, optionally fall back to node status
    if not ages and fallback_node:
        for n in nodes:
            if n.get("name") == fallback_node:
                last_seen_dt = iso_to_dt(n.get("last_seen"))
                if not last_seen_dt:
                    break
                age_sec = (now - last_seen_dt).total_seconds()
                if age_sec < 15:
                    return Text("online (node)", style="bold green")
                elif age_sec < 60:
                    return Text("stale (node)", style="bold yellow")
                else:
                    return Text("offline (node)", style="bold red")

    # Truly missing
    if not ages:
        return Text("missing", style="bold red")

    # Council found — determine freshness
    min_age = min(ages)
    if min_age < 15:
        return Text("online", style="bold green")
    elif min_age < 60:
        return Text("stale", style="bold yellow")
    else:
        return Text("offline", style="bold red")


def build_dev_panel(nodes: List[Dict[str, Any]], tasks: List[Dict[str, Any]]) -> Panel:
    """
    Dev-, Architect-, and Knowledge-Bob focused metrics from tasks + node status.
    This panel ALWAYS shows Dev Bob, Architect Bob, and Knowledge Bob, even if missing.
    """
    # ----- Dev tasks -----
    dev_tasks = [
        t for t in tasks
        if (t.get("high_level_type") or "").startswith("dev")
    ]
    dev_total = len(dev_tasks)

    dev_last_three = sorted(
        dev_tasks,
        key=lambda t: iso_to_dt(
            t.get("submitted_at")
            or t.get("created_at")
            or t.get("created_at_utc")
            or t.get("updated_at")
        ) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:3]

    dev_durations: List[float] = []
    dev_running_task: Optional[Dict[str, Any]] = None

    for t in dev_tasks:
        status = (t.get("final_status") or "").lower()
        if status in ("running", "in_progress") and dev_running_task is None:
            dev_running_task = t

        d_ms = t.get("last_duration_ms")
        if isinstance(d_ms, (int, float)) and d_ms > 0:
            dev_durations.append(d_ms / 1000.0)

    dev_avg_latency = sum(dev_durations) / len(dev_durations) if dev_durations else None

    # ----- Knowledge tasks -----
    knowledge_tasks = [
        t for t in tasks
        if (t.get("high_level_type") or "") == "knowledge"
    ]
    knowledge_total = len(knowledge_tasks)

    knowledge_last_three = sorted(
        knowledge_tasks,
        key=lambda t: iso_to_dt(
            t.get("submitted_at")
            or t.get("created_at")
            or t.get("created_at_utc")
            or t.get("updated_at")
        ) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:3]

    knowledge_durations: List[float] = []
    knowledge_running_task: Optional[Dict[str, Any]] = None

    for t in knowledge_tasks:
        status = (t.get("final_status") or "").lower()
        if status in ("running", "in_progress") and knowledge_running_task is None:
            knowledge_running_task = t

        d_ms = t.get("last_duration_ms")
        if isinstance(d_ms, (int, float)) and d_ms > 0:
            knowledge_durations.append(d_ms / 1000.0)

    knowledge_avg_latency = (
        sum(knowledge_durations) / len(knowledge_durations)
        if knowledge_durations else None
    )

    # ----- Models and locations from env or defaults -----
    dev_model = os.getenv("DEV_BOB_MODEL", "DeepSeek-Coder:6.7b (configured)")
    architect_model = os.getenv("ARCHITECT_BOB_MODEL", "llama3 (planned/default)")
    knowledge_model = os.getenv("KNOWLEDGE_BOB_MODEL", "llama3.1 (configured)")

    dev_node = os.getenv("DEV_BOB_NODE_NAME", "data-mainpc")
    architect_node = os.getenv("ARCHITECT_BOB_NODE_NAME", "data-mainpc")
    knowledge_node = os.getenv("KNOWLEDGE_BOB_NODE_NAME", "data-mainpc")

    dev_port = os.getenv("DEV_BOB_PORT", "8011")
    architect_port = os.getenv("ARCHITECT_BOB_PORT", "8012")
    knowledge_port = os.getenv("KNOWLEDGE_BOB_PORT", "8021")

    # ----- Status derived from node last_seen -----
    dev_status_raw = node_status_from_name(nodes, dev_node)
    architect_status_raw = node_status_from_name(nodes, architect_node)
    knowledge_status_raw = node_status_from_name(nodes, knowledge_node)

    def style_status(s: str) -> Text:
        txt = Text(s or "unknown")
        if s.startswith("online"):
            txt.stylize("bold green")
        elif s.startswith("stale"):
            txt.stylize("bold yellow")
        elif s.startswith("offline"):
            txt.stylize("bold red")
        else:
            txt.stylize("dim")
        return txt

    dev_status = style_status(dev_status_raw)
    architect_status = style_status(architect_status_raw)
    knowledge_status = style_status(knowledge_status_raw)

    # ----- Top table: council status + stats -----
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    # Dev Bob rows
    table.add_row("Dev Bob status", dev_status)
    table.add_row("Dev Bob node", dev_node)
    table.add_row("Dev Bob port", dev_port)
    table.add_row("Dev Bob model", dev_model)
    table.add_row("Total dev tasks (window)", str(dev_total))
    table.add_row(
        "Avg dev latency (s, if reported)",
        f"{dev_avg_latency:.2f}" if dev_avg_latency is not None else "-",
    )
    if dev_running_task:
        ts_raw = (
            dev_running_task.get("submitted_at")
            or dev_running_task.get("created_at")
            or dev_running_task.get("created_at_utc")
            or dev_running_task.get("updated_at")
        )
        age = human_age(iso_to_dt(ts_raw))
        table.add_row(
            "Current dev task",
            (dev_running_task.get("task_uuid") or "")[:8] + "…",
        )
        table.add_row("Current dev age", age)
    else:
        table.add_row("Current dev task", "None")

    # Architect Bob rows – always shown
    table.add_row("Architect Bob status", architect_status)
    table.add_row("Architect Bob node", architect_node)
    table.add_row("Architect Bob port", architect_port)
    table.add_row("Architect Bob model", architect_model)

    # Knowledge Bob rows – always shown
    table.add_row("Knowledge Bob status", knowledge_status)
    table.add_row("Knowledge Bob node", knowledge_node)
    table.add_row("Knowledge Bob port", knowledge_port)
    table.add_row("Knowledge Bob model", knowledge_model)
    table.add_row("Total knowledge tasks (window)", str(knowledge_total))
    table.add_row(
        "Avg knowledge latency (s, if reported)",
        f"{knowledge_avg_latency:.2f}" if knowledge_avg_latency is not None else "-",
    )
    if knowledge_running_task:
        ts_raw = (
            knowledge_running_task.get("submitted_at")
            or knowledge_running_task.get("created_at")
            or knowledge_running_task.get("created_at_utc")
            or knowledge_running_task.get("updated_at")
        )
        age = human_age(iso_to_dt(ts_raw))
        table.add_row(
            "Current knowledge task",
            (knowledge_running_task.get("task_uuid") or "")[:8] + "…",
        )
        table.add_row("Current knowledge age", age)
    else:
        table.add_row("Current knowledge task", "None")

    # ----- Bottom: last 3 dev + last 3 knowledge tasks -----
    dev_table = Table(box=box.MINIMAL)
    dev_table.add_column("When")
    dev_table.add_column("Summary")

    for t in dev_last_three:
        ts_raw = (
            t.get("submitted_at")
            or t.get("created_at")
            or t.get("created_at_utc")
            or t.get("updated_at")
        )
        ts = iso_to_dt(ts_raw)
        ts_str = ts.astimezone(timezone.utc).strftime("%H:%M:%S") if ts else "?"
        summary = t.get("output_summary") or t.get("title") or "(no summary)"
        if len(summary) > 80:
            summary = summary[:77] + "…"
        dev_table.add_row(ts_str, summary)

    knowledge_table = Table(box=box.MINIMAL)
    knowledge_table.add_column("When")
    knowledge_table.add_column("Summary")

    for t in knowledge_last_three:
        ts_raw = (
            t.get("submitted_at")
            or t.get("created_at")
            or t.get("created_at_utc")
            or t.get("updated_at")
        )
        ts = iso_to_dt(ts_raw)
        ts_str = ts.astimezone(timezone.utc).strftime("%H:%M:%S") if ts else "?"
        # Prefer output_summary (which is the human answer)
        summary = t.get("output_summary") or t.get("question") or "(no summary)"
        if len(summary) > 80:
            summary = summary[:77] + "…"
        knowledge_table.add_row(ts_str, summary)

    # Build a proper bottom grid (no method chaining that returns None)
    bottom_grid = Table.grid(expand=True)
    bottom_grid.add_row(
        Panel(dev_table, title="Last 3 dev tasks", border_style="dim"),
        Panel(knowledge_table, title="Last 3 knowledge tasks", border_style="blue"),
    )

    # Compose final grid
    grid = Table.grid(expand=True)
    grid.add_row(table)
    grid.add_row(Panel(bottom_grid, border_style="dim"))

    return Panel(grid, title="[b]Bobs (Dev, Architect & Knowledge)[/b]", border_style="green")


def build_layout(nodes: List[Dict[str, Any]], tasks: List[Dict[str, Any]]) -> Layout:
    layout = Layout()

    layout.split_column(
        Layout(name="upper", ratio=1),
        Layout(name="middle", ratio=1),
        Layout(name="lower", ratio=2),  # more room for Dev + Architect Bob
    )

    layout["upper"].update(build_nodes_panel(nodes))
    layout["middle"].update(build_tasks_panel(tasks))
    layout["lower"].update(build_dev_panel(nodes, tasks))

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
