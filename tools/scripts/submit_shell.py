def cli(args, orch_url: str) -> None:
    """
    Placeholder for future shell-task support.

    This command is intentionally a NO-OP until the orchestrator
    implements /tasks/shell or equivalent.
    """
    print("[submit-shell] Not implemented yet.")
    print("  Orchestrator does not currently expose a /tasks/shell endpoint.")
    print("  This is a placeholder so `bobctl submit-shell` doesn't break.")
    print("  When you're ready, we can wire this to a real shell-task route.")
