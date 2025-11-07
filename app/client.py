from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass


def list_tools(base: str) -> List[str]:
    try:
        r = requests.get(f"{base}/tools/list", timeout=5)
        r.raise_for_status()
        return [t["name"] for t in r.json()]
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Could not reach MCP server at {base}. Is it running? Original error: {e}"
        )


def call(base: str, name: str, args: Dict[str, Any] | None = None) -> Any:
    try:
        r = requests.post(
            f"{base}/tools/call", json={"name": name, "args": args or {}}, timeout=10
        )
        r.raise_for_status()
        return r.json()["result"]
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Failed calling tool '{name}' at {base}. Check server logs. Original error: {e}"
        )


def generate_health_report(base: str, top_n: int = 5, cpu_window: float = 0.5) -> str:
    sysinfo = call(base, "get_system_info")
    cpu = call(base, "get_cpu_usage", {"interval_sec": cpu_window})
    procs = call(base, "list_processes", {"limit": top_n})

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


def try_gemini_agent(base: str, goal: str, out_file: Optional[str]) -> Optional[str]:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        import google.generativeai as genai

        print("startinggggg Agenttttttttttttttt")
        genai.configure(api_key=api_key)

        function_declarations = [
            {
                "name": "get_system_info",
                "description": "Get OS, memory, CPU and uptime info",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_cpu_usage",
                "description": "Measure CPU usage over a small window",
                "parameters": {
                    "type": "object",
                    "properties": {"interval_sec": {"type": "number", "description": "Time window in seconds (default: 0.5)"}},
                },
            },
            {
                "name": "list_processes",
                "description": "List top processes by CPU",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "description": "Number of top processes (default: 5)"}},
                },
            },
            {
                "name": "store_in_file",
                "description": "Save content to a file on the MCP server output directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_name": {"type": "string", "description": "Name of the file to create"},
                        "content": {"type": "string", "description": "Content to write to the file"},
                    },
                    "required": ["file_name", "content"],
                },
            },
        ]

        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            tools={"function_declarations": function_declarations},
            system_instruction=(
                "You are an autonomous agent with tools. "
                "When asked to generate a health report, call get_system_info, get_cpu_usage, and list_processes to gather data, "
                "then format the data into a comprehensive report and save it using store_in_file. "
                "Always save the report to a file when requested."
            ),
        )

        chat = model.start_chat()
        print(f"Sendinggggggggggg goal: {goal}")
        resp = chat.send_message(goal)

        accumulated: Dict[str, Any] = {}
        loops = 0
        while loops < 3 and hasattr(resp, "candidates"):
            loops += 1
            made_tool_call = False
            for cand in resp.candidates or []:
                for part in getattr(cand.content, "parts", []) or []:
                    fc = getattr(part, "function_call", None)
                    if not fc:
                        continue
                    name = fc.name
                    if isinstance(fc.args, str):
                        args = json.loads(fc.args)
                    elif hasattr(fc.args, 'items'):
                        args = dict(fc.args)
                    else:
                        args = {}
                    print(f"[Gemini Agent] Calling tool: {name}")
                    print(f"[Gemini Agent] Arguments: {json.dumps(args, indent=2)}")
                    result = call(base, name, args)
                    print(f"[Gemini Agent] Result: {json.dumps(result, indent=2)}")
                    accumulated[name] = result
                    made_tool_call = True
                    try:
                        from google.ai.generativelanguage import Content, Part, FunctionResponse

                        response_part = Part(
                            function_response=FunctionResponse(
                                name=name,
                                response={"result": result}
                            )
                        )
                        resp = chat.send_message(Content(parts=[response_part]))
                    except Exception as send_err:
                        print(f"[Gemini Agent] Error sending response: {send_err}")
                        try:
                            resp = chat.send_message(
                                f"Tool {name} returned: {json.dumps(result)}"
                            )
                        except:
                            raise send_err
            if not made_tool_call:
                break

        if out_file and "store_in_file" not in accumulated:
            content = None
            if "get_system_info" in accumulated and "get_cpu_usage" in accumulated and "list_processes" in accumulated:
                print("[Gemini Agent] Generating health report from collected data...")
                content = generate_health_report(base)
            if not content and hasattr(resp, "text") and resp.text:
                content = resp.text
            if content:
                print(f"[Gemini Agent] Saving to file: {out_file}")
                stored = call(base, "store_in_file", {"file_name": out_file, "content": content})
                return stored.get("path")

        if hasattr(resp, "text") and resp.text:
            print(f"[Gemini Agent] Final response: {resp.text}")
            return resp.text
        print(f"[Gemini Agent] Accumulated results: {json.dumps(accumulated, indent=2)}")
        return json.dumps(accumulated)
    except Exception as e:
        print(f"[Gemini Agent] Error: {e}")
        return None


def deterministic_agent(base: str, goal: str, out_file: Optional[str]) -> str:
    g = goal.lower()
    tools = set(list_tools(base))

    if "health" in g and ("report" in g or "summary" in g):
        report = generate_health_report(base)
        if out_file and "store_in_file" in tools:
            saved = call(base, "store_in_file", {"file_name": out_file, "content": report})
            return saved["path"]
        return report

    if "cpu" in g and "usage" in g:
        cpu = call(base, "get_cpu_usage", {"interval_sec": 0.5})
        return json.dumps(cpu, indent=2)
    if "process" in g:
        procs = call(base, "list_processes", {"limit": 5})
        return json.dumps(procs, indent=2)

    return json.dumps({"available_tools": sorted(tools)}, indent=2)


def main():
    parser = argparse.ArgumentParser(description="MCP client agent that selects tools to achieve a goal")
    parser.add_argument(
        "--base",
        default=os.getenv("BASE_URL", "http://127.0.0.1:8000"),
        help="MCP server base URL (defaults to BASE_URL in MCP/.env)",
    )
    parser.add_argument("--goal", default="Create a system health report and save it to a file.", help="High-level goal for the agent")
    parser.add_argument("--out", default="health_report.txt", help="Output file name (when applicable)")
    args = parser.parse_args()

    result = try_gemini_agent(args.base, args.goal, args.out)
    if result is None:
        print("Gemini not availableeeeeeeeeeeee...")
        result = deterministic_agent(args.base, args.goal, args.out)
    print("\n=== Final Result ===")
    print(result)


if __name__ == "__main__":
    main()
