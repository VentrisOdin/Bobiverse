#!/usr/bin/env python
import argparse
import sys
from pathlib import Path
from importlib import import_module

TOOLS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TOOLS_DIR / "scripts"
DASH_DIR = TOOLS_DIR / "dashboards"

DEFAULT_ORCH_URL = "http://100.111.201.26:5080"


def ensure_on_path():
    for p in (SCRIPTS_DIR, DASH_DIR):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def main():
    ensure_on_path()

    parser = argparse.ArgumentParser(
        prog="bobctl",
        description="Prime Bob command-line control tool.",
    )
    parser.add_argument(
        "--orch-url",
        default=DEFAULT_ORCH_URL,
        help=f"Orchestrator base URL (default: {DEFAULT_ORCH_URL})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ----- subcommands -----

    # show-nodes
    p = subparsers.add_parser("show-nodes", help="List registered nodes")
    p.set_defaults(handler="show_nodes:cli")

    # show-tasks
    p = subparsers.add_parser("show-tasks", help="List recent tasks")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(handler="show_tasks:cli")

    # submit-dev
    p = subparsers.add_parser("submit-dev", help="Submit Dev Council task")
    p.add_argument("description")
    p.add_argument("--details")
    p.set_defaults(handler="submit_dev:cli")

    # submit-shell
    p = subparsers.add_parser("submit-shell", help="Submit shell command task")
    p.add_argument("command")
    p.add_argument("--target-node")
    p.set_defaults(handler="submit_shell:cli")

    # submit-python
    p = subparsers.add_parser("submit-python", help="Submit Python code/file task")
    p.add_argument("file_or_code")
    p.add_argument("--target-node")
    p.set_defaults(handler="submit_python:cli")

    # tail orchestrator logs
    p = subparsers.add_parser("tail-orch-logs", help="Tail orchestrator logs")
    p.set_defaults(handler="tail_orchestrator_logs:cli")

    # db inspect
    p = subparsers.add_parser("db-inspect", help="Inspect DB (generic)")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(handler="db_inspect:cli")

    # live status dashboard
    p = subparsers.add_parser("live-status", help="Live node/task dashboard")
    p.add_argument("--interval", type=float, default=2.0)
    p.set_defaults(handler="live_status:cli")

    args = parser.parse_args()

    module_name, func_name = args.handler.split(":")
    mod = import_module(module_name)
    func = getattr(mod, func_name)

    return func(args, orch_url=args.orch_url)


if __name__ == "__main__":
    main()
