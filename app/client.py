from __future__ import annotations

import argparse
import json
from typing import Any, Dict

import requests


def call(base: str, name: str, args: Dict[str, Any] | None = None) -> Any:
    r = requests.post(f"{base}/tools/call", json={"name": name, "args": args or {}})
    r.raise_for_status()
    return r.json()["result"]


def generate_health_report(base: str) -> str:
    sysinfo = call(base, "get_system_info")
    cpu = call(base, "get_cpu_usage", {"interval_sec": 0.5})
    procs = call(base, "list_processes", {"limit": 5})

    lines = []
    lines.append("System Health Report")
    lines.append("====================")
    lines.append("")
    lines.append("System Info:")
    for k in [
        "platform",
        "release",
        "version",
        "arch",
        "hostname",
        "uptime_sec",
        "total_mem_bytes",
        "free_mem_bytes",
        "cpu_count",
        "cpu_model",
    ]:
        lines.append(f"- {k}: {sysinfo.get(k)}")

    lines.append("")
    lines.append(f"CPU Usage: {cpu['cpu_usage_percent']}% (window {cpu['window_sec']}s)")

    lines.append("")
    lines.append("Top Processes (by CPU):")
    for p in procs:
        lines.append(f"- pid={p['pid']} cpu={p['cpu']}% mem={p['mem']}% cmd={p['cmd']}")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="MCP client orchestrator")
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="MCP server base URL")
    parser.add_argument("--out", default="health_report.txt", help="Output file name")
    args = parser.parse_args()

    report = generate_health_report(args.base)
    saved = call(args.base, "store_in_file", {"file_name": args.out, "content": report})
    print(saved["path"])


if __name__ == "__main__":
    main()

