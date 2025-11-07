from __future__ import annotations

import platform
import socket
import time
from pathlib import Path
from typing import Any, Dict, List

import psutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)


class ToolListItem(BaseModel):
    name: str


app = FastAPI(title="MCP System Info & Utility Server", version="1.0.0")


def get_system_info() -> Dict[str, Any]:
    return {
        "platform": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "arch": platform.machine(),
        "hostname": socket.gethostname(),
        "uptime_sec": int(time.time() - psutil.boot_time()),
        "total_mem_bytes": psutil.virtual_memory().total,
        "free_mem_bytes": psutil.virtual_memory().available,
        "cpu_count": psutil.cpu_count(logical=True) or 0,
        "cpu_model": platform.processor() or "unknown",
    }


def get_cpu_usage(interval_sec: float = 0.5) -> Dict[str, Any]:
    value = psutil.cpu_percent(interval=interval_sec)
    return {"cpu_usage_percent": round(float(value), 2), "window_sec": interval_sec}


def list_processes(limit: int = 5) -> List[Dict[str, Any]]:
    procs = []
    for p in psutil.process_iter(attrs=["pid", "name", "cpu_percent", "memory_percent", "cmdline"]):
        info = p.info
        procs.append(
            {
                "pid": info.get("pid"),
                "cpu": round(float(info.get("cpu_percent") or 0.0), 2),
                "mem": round(float(info.get("memory_percent") or 0.0), 2),
                "cmd": " ".join(info.get("cmdline") or [info.get("name") or "unknown"]),
            }
        )
    procs.sort(key=lambda x: x["cpu"], reverse=True)
    return procs[: max(0, limit)]


def store_in_file(file_name: str, content: str) -> Dict[str, Any]:
    if not file_name:
        raise ValueError("file_name is required")
    # Save relative to this package directory so it's stable regardless of CWD
    base_dir = Path(__file__).resolve().parent.parent  # MCP/
    out_dir = base_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / file_name
    dest.write_text(content, encoding="utf-8")
    return {"path": str(dest)}


TOOLS = {
    "get_system_info": lambda args=None: get_system_info(),
    "get_cpu_usage": lambda args=None: get_cpu_usage(
        float((args or {}).get("interval_sec", 0.5))
    ),
    "list_processes": lambda args=None: list_processes(int((args or {}).get("limit", 5))),
    "store_in_file": lambda args=None: store_in_file(
        (args or {}).get("file_name"), (args or {}).get("content", "")
    ),
}


@app.get("/tools/list", response_model=List[ToolListItem])
def tools_list():
    return [ToolListItem(name=name) for name in TOOLS.keys()]


@app.post("/tools/call")
def tools_call(body: ToolCall):
    if body.name not in TOOLS:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {body.name}")
    try:
        result = TOOLS[body.name](body.args)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok", "tools": list(TOOLS.keys())}
