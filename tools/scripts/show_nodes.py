import requests


def cli(args, orch_url: str) -> None:
    url = f"{orch_url}/nodes"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print(f"[show-nodes] Error calling {url}: {e}")
        return

    nodes = resp.json()

    if not nodes:
        print("No nodes registered.")
        return

    # Header
    print(f"{'NAME':20} {'ROLE':10} {'LOAD':8} {'FREE_MB':8} {'LAST_SEEN':27} CAPABILITIES")
    print("-" * 90)

    for n in nodes:
        # We now know the exact keys from your orchestrator
        name = str(n.get("name", ""))
        role = str(n.get("role", ""))
        load = n.get("load", "")
        free_mb = n.get("free_memory_mb", "")
        last_seen = str(n.get("last_seen", ""))
        caps = n.get("capabilities", [])

        # Format values
        load_str = f"{load:.3f}" if isinstance(load, (int, float)) else str(load)
        free_str = str(free_mb)
        caps_str = ", ".join(caps) if isinstance(caps, list) else str(caps)

        print(f"{name:20} {role:10} {load_str:8} {free_str:8} {last_seen:27} {caps_str}")
