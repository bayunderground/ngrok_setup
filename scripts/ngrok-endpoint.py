#!/usr/bin/env python3
"""Print the active ngrok TCP endpoint for local SSH as host:port."""
import json
import sys
import urllib.request

API = "http://127.0.0.1:4040/api/tunnels"
TIMEOUT = 3


def active_endpoint():
    with urllib.request.urlopen(API, timeout=TIMEOUT) as resp:
        tunnels = json.load(resp).get("tunnels", [])
    for tunnel in tunnels:
        if tunnel.get("proto") == "tcp" and tunnel.get("config", {}).get("addr", "").endswith(":22"):
            url = tunnel.get("public_url", "")
            if url.startswith("tcp://"):
                return url[len("tcp://"):]
    return None


def main():
    try:
        endpoint = active_endpoint()
    except OSError as exc:
        print(f"ngrok agent API unreachable: {exc}", file=sys.stderr)
        return 2
    if not endpoint:
        print("no active TCP endpoint for port 22", file=sys.stderr)
        return 1
    print(endpoint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
