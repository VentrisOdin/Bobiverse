#!/usr/bin/env python
import argparse
import os
import subprocess
import sys
from pathlib import Path
from importlib import import_module

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(TOOLS_DIR, "scripts")
DASH_DIR = os.path.join(TOOLS_DIR, "dashboards")

DEFAULT_ORCH_URL = "http://100.111.201.26:5080"


def cmd_monitor(args: argparse.Namespace) -> None:
    """
    Run the TUI monitor (bobctl monitor).
    """
    script_path = os.path.join(TOOLS_DIR, "scripts", "monitor.py")
    cmd = [sys.executable, script_path]
    if args.interval is not None:
        cmd += ["--interval", str(args.interval)]
    subprocess.call(cmd)


def cmd_top(args: argparse.Namespace) -> None:
    """
    Run the task-centric TUI top (bobctl top).
    """
    script_path = os.path.join(TOOLS_DIR, "scripts", "top.py")
    cmd = [sys.executable, script_path]
    if args.interval is not None:
        cmd += ["--interval", str(args.interval)]
    subprocess.call(cmd)

# Command registry: name -> (handler, help, extra_args)
COMMANDS = {
    "show-nodes": {
        "handler": "show_nodes:cli",
        "help": "List registered nodes",
        "args": [],
    },
    "show-tasks": {
        "handler": "show_tasks:cli",
        "help": "List recent tasks",
        "args": [("--limit", {"type": int, "default": 20})],
    },
    "show-dev": {
        "handler": "show_dev:cli",
        "help": "Show Dev Council tasks",
        "args": [
            ("task_uuid", {"type": str, "nargs": "?", "default": None, "help": "Optional task UUID to show details"}),
            ("--limit", {"type": int, "default": 20}),
        ],
    },
    "submit-dev": {
        "handler": "submit_dev:cli",
        "help": "Submit Dev Council task",
        "args": [
            ("description", {"type": str}),
            ("--details", {"type": str, "default": None}),
        ],
    },
    "submit-shell": {
        "handler": "submit_shell:cli",
        "help": "Submit shell command (stub)",
        "args": [
            ("command", {"type": str}),
            ("--target-node", {"type": str, "default": None}),
        ],
    },
    "submit-python": {
        "handler": "submit_python:cli",
        "help": "Submit Python code (stub)",
        "args": [
            ("file_or_code", {"type": str}),
            ("--target-node", {"type": str, "default": None}),
        ],
    },
    "tail-orch-logs": {
        "handler": "tail_orchestrator_logs:cli",
        "help": "Tail orchestrator logs",
        "args": [],
    },
    "db-inspect": {
        "handler": "db_inspect:cli",
        "help": "Inspect tasks + executions DB",
        "args": [("--limit", {"type": int, "default": 20})],
    },
    "live-status": {
        "handler": "dashboards.live_status:cli",
        "help": "Live node/task dashboard",
        "args": [("--interval", {"type": float, "default": 2.0})],
    },
}


def ensure_on_path():
    """
    Ensure both scripts/ and dashboards/ directories are importable.
    """
    for p in (SCRIPTS_DIR, DASH_DIR):
        p_str = str(p)
        if p_str not in sys.path:
            sys.path.insert(0, p_str)


def main():
    ensure_on_path()

    parser = argparse.ArgumentParser(prog="bobctl", description="Bobiverse control tool")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    parser.add_argument(
        "--orch-url",
        default=DEFAULT_ORCH_URL,
        help=f"Orchestrator base URL (default: {DEFAULT_ORCH_URL})",
    )

    # Dynamically register all commands
    for name, config in COMMANDS.items():
        p = subparsers.add_parser(name, help=config["help"])
        p.set_defaults(handler=config["handler"])
        
        for arg_def in config["args"]:
            arg_name = arg_def[0]
            arg_kwargs = arg_def[1] if len(arg_def) > 1 else {}
            p.add_argument(arg_name, **arg_kwargs)

    # ---- monitor ----
    p_monitor = subparsers.add_parser(
        "monitor",
        help="Real-time system monitor (nodes, tasks, dev council)",
    )
    p_monitor.add_argument(
        "-i",
        "--interval",
        type=float,
        default=1.0,
        help="Refresh interval in seconds (default: 1.0)",
    )
    p_monitor.set_defaults(func=cmd_monitor)

    # ---- top ----
    p_top = subparsers.add_parser(
        "top",
        help="Task-centric top view (running, pending, council hot spots)",
    )
    p_top.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0.5,
        help="Refresh interval in seconds (default: 0.5)",
    )
    p_top.set_defaults(func=cmd_top)

    args = parser.parse_args()

    # Handle direct function calls (monitor, top)
    if hasattr(args, "func"):
        return args.func(args)

    # Handle module-based handlers (existing commands)
    module_name, func_name = args.handler.split(":")
    mod = import_module(module_name)
    func = getattr(mod, func_name)

    return func(args, orch_url=args.orch_url)


if __name__ == "__main__":
    main()
