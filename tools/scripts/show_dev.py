#!/usr/bin/env python3
import os
import sys
import argparse
import json
import textwrap

import requests

DEFAULT_ORCH_URL = os.getenv("BOBIVERSE_ORCH_URL", "http://100.111.201.26:5080")


def _print_section(title: str, body: str | None):
    print()
    print(f"{title}:")
    print("-" * (len(title) + 1))
    if not body:
        print("  (none)")
        return

    # Simple indent for readability
    for line in body.splitlines():
        if line.strip():
            print("  " + line)
        else:
            print()


def cli(args: argparse.Namespace, orch_url: str = DEFAULT_ORCH_URL):
    task_uuid = getattr(args, "task_uuid", None)
    
    if not task_uuid:
        print("[show-dev] Error: task_uuid is required", file=sys.stderr)
        sys.exit(1)

    # 1) Fetch executions for this task
    try:
        url = f"{orch_url}/db/tasks/{task_uuid}/executions"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[show-dev] Error talking to orchestrator: {e}", file=sys.stderr)
        sys.exit(1)

    executions = resp.json()
    if not executions:
        print(f"[show-dev] No executions found for task_uuid={task_uuid}")
        return

    # Prefer latest dev_council execution if present
    dev_execs = [e for e in executions if e.get("target_module") == "dev_council"]
    if dev_execs:
        exec_row = sorted(dev_execs, key=lambda r: r.get("id", 0))[-1]
    else:
        # Fall back to the latest execution of any type
        exec_row = sorted(executions, key=lambda r: r.get("id", 0))[-1]

    status = exec_row.get("status")
    output_summary = exec_row.get("output_summary")
    metrics_raw = exec_row.get("metrics_json")

    # metrics_json may already be a dict or a JSON string
    metrics = None
    if isinstance(metrics_raw, dict):
        metrics = metrics_raw
    elif isinstance(metrics_raw, str) and metrics_raw.strip():
        try:
            metrics = json.loads(metrics_raw)
        except json.JSONDecodeError:
            metrics = None

    print(f"=== Dev Task Detail ===")
    print(f"Task UUID:     {task_uuid}")
    print(f"Execution ID:  {exec_row.get('id')}")
    print(f"Module:        {exec_row.get('target_module')}")
    print(f"Node:          {exec_row.get('target_node')}")
    print(f"Status:        {status}")
    print()

    if output_summary:
        print("HIGH-LEVEL SUMMARY (task_executions.output_summary)")
        print("-" * 60)
        for line in output_summary.splitlines():
            print("  " + line)
        print()

    if not metrics:
        print("(No structured Dev Council metrics_json found.)")
        return

    # Expect DevTaskResponse-like shape in metrics_json
    task_id = metrics.get("task_id")
    task_type = metrics.get("task_type")
    model_name = metrics.get("model_name")
    analysis = metrics.get("analysis") or {}

    print("METADATA")
    print("--------")
    print(f"  Dev Council task_id:  {task_id}")
    print(f"  Dev Council task_type:{' ' if task_type else ''}{task_type}")
    print(f"  Model:                {model_name}")
    print()

    summary = analysis.get("summary") or ""
    reasoning = analysis.get("reasoning") or ""
    suggested_changes = analysis.get("suggested_changes") or ""
    example_code = analysis.get("example_code")
    tests_suggested = analysis.get("tests_suggested")
    risks = analysis.get("risks")

    _print_section("SUMMARY", summary)
    _print_section("REASONING", reasoning)
    _print_section("SUGGESTED CHANGES", suggested_changes)

    if example_code:
        # Render as a code block
        print()
        print("EXAMPLE CODE:")
        print("-------------")
        print("```")
        print(example_code)
        print("```")

    if tests_suggested:
        body = tests_suggested if isinstance(tests_suggested, str) else json.dumps(tests_suggested, indent=2)
        _print_section("TESTS SUGGESTED", body)

    if risks:
        body = risks if isinstance(risks, str) else json.dumps(risks, indent=2)
        _print_section("RISKS", body)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bobctl show-dev",
        description="Show detailed Dev Council analysis for a given task UUID.",
    )
    p.add_argument(
        "task_uuid",
        help="Full task UUID (copy from db-inspect or show-tasks).",
    )
    return p
