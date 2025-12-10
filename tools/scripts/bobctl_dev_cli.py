# tools/scripts/bobctl_dev_cli.py

import argparse
import os
import sys
from typing import List

from .bobctl_utils import (
    prepare_single_file_payload,
    prepare_stdin_payload,
    prepare_directory_payload,
    submit_dev_task_to_orchestrator,
)


def build_dev_parser() -> argparse.ArgumentParser:
    """
    Build the 'bobctl dev' subcommand parser.
    """
    parser = argparse.ArgumentParser(prog="bobctl dev", add_help=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_dev_subcommand(name: str, default_ask: str):
        sub = subparsers.add_parser(
            name,
            help=f"{name.capitalize()} code using Dev Bob.",
        )
        sub.add_argument(
            "path",
            nargs="?",
            default=None,
            help="Path to file or directory to process. Omit when using --stdin.",
        )
        sub.add_argument(
            "--ask",
            default=default_ask,
            help="Natural language instructions for Dev Bob.",
        )
        sub.add_argument(
            "--stdin",
            action="store_true",
            help="Read code from stdin instead of a file/path.",
        )
        sub.add_argument(
            "--orch-url",
            default=None,
            help="Override orchestrator URL (otherwise env/default is used).",
        )
        return sub

    add_dev_subcommand(
        "analyse",
        "Analyse this code and report issues & improvements.",
    )
    add_dev_subcommand(
        "fix",
        "Find and fix bugs / obvious issues.",
    )
    add_dev_subcommand(
        "refactor",
        "Refactor code according to best practices.",
    )

    return parser


def bobctl_dev_command(argv: List[str]) -> int:
    """
    Entry point for 'bobctl dev ...'.

    Called from the main bobctl dispatcher with the remaining arguments.
    """
    parser = build_dev_parser()
    args = parser.parse_args(argv)

    instructions = args.ask
    orch_url = args.orch_url

    # Decide which payload builder to use
    if args.stdin:
        payload = prepare_stdin_payload(instructions)
    else:
        if not args.path:
            parser.error("Must provide a path or use --stdin.")

        path = args.path
        if os.path.isfile(path):
            payload = prepare_single_file_payload(path, instructions)
        elif os.path.isdir(path):
            payload = prepare_directory_payload(path, instructions)
        else:
            parser.error(f"Path is neither a file nor a directory: {path}")

    # Tag Dev Bob “intent” for the LLM (analyse/fix/refactor)
    payload["intent"] = args.command

    # Submit to orchestrator
    try:
        resp = submit_dev_task_to_orchestrator(
            payload=payload,
            instructions=instructions,
            orch_url=orch_url,
        )
    except Exception as e:
        print(f"[ERROR] Failed to submit Dev task: {e}", file=sys.stderr)
        return 1

    task_uuid = (
        resp.get("task_uuid")
        or resp.get("uuid")
        or resp.get("id")
        or "<unknown>"
    )

    print(f"[Dev Bob] Task submitted.")
    print(f"  Mode      : {payload['mode']}")
    print(f"  Intent    : {payload['intent']}")
    print(f"  Task UUID : {task_uuid}")
    print("")
    print("You can inspect it with:")
    print(f"  ./bobctl show-dev {task_uuid}")

    return 0


if __name__ == "__main__":
    # Allow running this module directly for local testing:
    sys.exit(bobctl_dev_command(sys.argv[1:]))
