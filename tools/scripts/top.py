#!/usr/bin/env python
"""
bobctl top

Task-centric real-time dashboard for the Bobiverse.
Focuses on running tasks, pending queue, and council hot spots.
"""

import os
import time
from datetime import datetime, timezone
from collections import defaultdict
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
DEFAULT_REFRESH = float(os.getenv("BOBIVERSE_TOP_INTERVAL", "0.5"))  # seconds


# ---------------- HTTP + Time Helpers ---------------- #

def _safe_get(path: str, default: Any) -> Any:
    url = ORCHESTRATOR_URL.rstrip("/") + path
    try:
        resp = requests.get(url, timeout=1.5)
        resp.raise_for_status()
        return resp.json()
    except RequestException:
        return default


def fetch_tasks(limit: int = 200) -> List[Dict[str, Any]]:
    """
    Fetch tasks for the dashboard.

    Tries /db/tasks first. If your API ever changes, you can adapt here.
    """
    data = _safe_get(f"/db/tasks?limit={limit}", None)
    if data is None:
        # optional fallback to /tasks
        data = _safe_get(f"/tasks?limit={limit}", [])
    if isinstance(data, dict) and "tasks" in data:
        return data["tasks"]
    return data or []


def iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        # normalise to aware UTC
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


# ---------------- Task Splitting ---------------- #

def _task_timestamp(t: Dict[str, Any]) -> Optional[datetime]:
    """
    Try multiple possible timestamp fields from the API.
    """
    raw = (
        t.get("submitted_at")
        or t.get("created_at")
        or t.get("created_at_utc")
        or t.get("updated_at")
    )
    return iso_to_dt(raw)


def split_tasks(tasks: List[Dict[str, Any]]):
    running: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    others: List[Dict[str, Any]] = []

    for t in tasks:
        status = (t.get("final_status") or "").lower()
        if status in ("running", "in_progress"):
            running.append(t)
        elif status in ("pending", "queued"):
            pending.append(t)
        else:
            others.append(t)

    return running, pending, others


# ---------------- Panels ---------------- #

def build_running_panel(running: List[Dict[str, Any]]) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        show_lines=False,
        title="Running Tasks",
        title_style="bold",
    )
    table.add_column("UUID", no_wrap=True)
    table.add_column("Type")
    table.add_column("Node")
    table.add_column("Exec ID")
    table.add_column("Age")

    running_sorted = sorted(
        running,
        key=lambda t: _task_timestamp(t) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    for t in running_sorted[:30]:
        uuid_full = str(t.get("task_uuid") or "-")
        t_type = str(t.get("high_level_type") or "-")
        node = t.get("last_target_node") or t.get("preferred_node") or "-"
        exec_id = str(t.get("last_execution_id") or "-")
        age = human_age(_task_timestamp(t))

        table.add_row(uuid_full, t_type, node, exec_id, age)

    if not running_sorted:
        table.add_row("-", "-", "-", "-", "-")

    return Panel(table, border_style="green")


def build_pending_panel(pending: List[Dict[str, Any]]) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        show_lines=False,
        title="Pending Queue",
        title_style="bold",
    )
    table.add_column("Type", style="magenta")
    table.add_column("Count")
    table.add_column("Oldest Age")
    table.add_column("Avg Wait")

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in pending:
        t_type = str(t.get("high_level_type") or "generic")
        groups[t_type].append(t)

    now = datetime.now(timezone.utc)

    for t_type, tasks in sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True):
        ages = []
        for t in tasks:
            ts = _task_timestamp(t)
            if ts:
                ages.append(now - ts)

        if ages:
            oldest_delta = max(ages)
            oldest_age = human_age(now - oldest_delta + oldest_delta)  # reuse formatting
            avg_sec = sum(a.total_seconds() for a in ages) / len(ages)
            avg_sec = int(avg_sec)
            h = avg_sec // 3600
            m = (avg_sec % 3600) // 60
            s = avg_sec % 60
            avg_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
        else:
            oldest_age = "-"
            avg_str = "-"

        table.add_row(t_type, str(len(tasks)), oldest_age, avg_str)

    if not groups:
        table.add_row("-", "0", "-", "-")

    total_pending = len(pending)
    info = Text(f"Total pending: {total_pending}", style="bold yellow")

    grid = Table.grid(expand=True)
    grid.add_row(table)
    grid.add_row(info)
    return Panel(grid, border_style="yellow")


def build_hotspot_panel(tasks: List[Dict[str, Any]]) -> Panel:
    """
    Council hot-spot analysis over recent tasks:
    - Count tasks per council type
    - Approximate failure rates
    - Approximate last run durations (if available via last_duration_ms)
    """
    stats = defaultdict(lambda: {"count": 0, "failed": 0, "durations": []})

    for t in tasks:
        council = str(t.get("high_level_type") or "generic")
        s = stats[council]
        s["count"] += 1

        status = (t.get("final_status") or "").lower()
        if status in ("failed", "error"):
            s["failed"] += 1

        d_ms = t.get("last_duration_ms")
        if isinstance(d_ms, (int, float)) and d_ms > 0:
            s["durations"].append(d_ms / 1000.0)

    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        show_lines=False,
        title="Council Hot Spots (recent window)",
        title_style="bold",
    )
    table.add_column("Council", style="magenta")
    table.add_column("Tasks")
    table.add_column("Failure %")
    table.add_column("Avg Duration (s)")

    for council, s in sorted(stats.items(), key=lambda kv: kv[1]["count"], reverse=True):
        count = s["count"]
        failed = s["failed"]
        fail_pct = 100 * failed / count if count else 0
        durations = s["durations"]
        avg_d = sum(durations) / len(durations) if durations else 0.0

        fail_text = Text(f"{fail_pct:.1f}%")
        if fail_pct >= 20:
            fail_text.stylize("bold red")
        elif fail_pct > 0:
            fail_text.stylize("yellow")
        else:
            fail_text.stylize("green")

        table.add_row(
            council,
            str(count),
            fail_text,
            f"{avg_d:.2f}" if durations else "-",
        )

    if not stats:
        table.add_row("-", "0", "0.0%", "-")

    note = Text(
        "Window: last N tasks from /db/tasks. "
        "Durations & fail rates rely on orchestrator populating last_duration_ms.",
        style="dim",
    )

    grid = Table.grid(expand=True)
    grid.add_row(table)
    grid.add_row(note)

    return Panel(grid, border_style="magenta")


# ---------------- Layout + Loop ---------------- #

def build_layout(tasks: List[Dict[str, Any]]) -> Layout:
    running, pending, _ = split_tasks(tasks)

    layout = Layout()
    layout.split_column(
        Layout(name="upper", size=14),
        Layout(name="middle", size=10),
        Layout(name="lower"),
    )

    layout["upper"].update(build_running_panel(running))
    layout["middle"].update(build_pending_panel(pending))
    layout["lower"].update(build_hotspot_panel(tasks))

    return layout


def top_loop(refresh: float = DEFAULT_REFRESH) -> None:
    with Live(auto_refresh=False, screen=True) as live:
        while True:
            tasks = fetch_tasks(limit=200)
            layout = build_layout(tasks)
            live.update(layout, refresh=True)
            time.sleep(refresh)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Bobiverse task-centric top (bobctl top)")
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=DEFAULT_REFRESH,
        help="Refresh interval in seconds (default: %(default)s)",
    )
    args = parser.parse_args()
    top_loop(refresh=args.interval)


if __name__ == "__main__":
    main()
