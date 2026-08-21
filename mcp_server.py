#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
band-bridge : 手环健康数据 → 标准 MCP 服务

目标：任何支持 MCP（Streamable HTTP）的前端都能接。
- 前端把 http://<host>:8898/mcp 挂上即可，零改动。
- 数据由手机端脚本/推送层写入 data/ 目录，本服务只读不写（record_health 例外，供手动录入）。
- 鉴权：可选。设置环境变量 BAND_MCP_TOKEN 后，请求需带 Authorization: Bearer <token>。

运行：
  BAND_MCP_TOKEN=xxx python3 mcp_server.py
"""
import os
import json
import glob
import datetime

from mcp.server.fastmcp import FastMCP

DATA_DIR = os.environ.get("BAND_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
TOKEN = os.environ.get("BAND_MCP_TOKEN", "")
PORT = int(os.environ.get("BAND_MCP_PORT", "8898"))

os.makedirs(DATA_DIR, exist_ok=True)

mcp = FastMCP(
    "band-bridge",
    instructions=(
        "手环健康数据查询与录入服务。"
        "get_health 拿最新状态；read_health_data 读历史；record_health 手动录入。"
    ),
)


def _files():
    return sorted(glob.glob(os.path.join(DATA_DIR, "health_*.json")), reverse=True)


def _load(fn):
    try:
        with open(fn, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _latest():
    files = _files()
    merged = {}
    for fn in files[:30]:
        d = _load(fn)
        for k in ("heart_rate", "sleep", "steps", "battery", "note", "_received_at"):
            if k in d and d[k] is not None and k not in merged:
                merged[k] = d[k]
    merged["_latest_file"] = os.path.basename(files[0]) if files else None
    return merged


@mcp.tool()
def get_health() -> dict:
    """汇总最新健康状态：心率、睡眠、步数、电量、最近更新时间。"""
    files = _files()
    return {"available": bool(files), "latest": _latest(), "records": len(files)}


@mcp.tool()
def read_health_data(data_type: str = "all", limit: int = 5) -> dict:
    """按类型读历史健康数据。data_type: all | heart_rate | sleep | steps | battery。limit: 返回条数(1-30，默认5)。"""
    limit = max(1, min(int(limit or 5), 30))
    files = _files()[:limit]
    out = []
    for fn in files:
        d = _load(fn)
        if data_type != "all" and data_type not in d:
            continue
        out.append(d)
    return {"data_type": data_type, "count": len(out), "data": out}


@mcp.tool()
def record_health(
    heart_rate: int | None = None,
    steps: int | None = None,
    sleep: dict | None = None,
    battery: int | None = None,
    note: str = "",
) -> dict:
    """录入一条健康数据（手动记录，或供脚本以工具形式推送）。"""
    payload = {}
    if heart_rate is not None:
        payload["heart_rate"] = int(heart_rate)
    if steps is not None:
        payload["steps"] = int(steps)
    if sleep is not None:
        payload["sleep"] = sleep
    if battery is not None:
        payload["battery"] = int(battery)
    if note:
        payload["note"] = str(note)
    if not payload:
        return {"ok": False, "error": "empty payload"}
    payload["_source"] = "mcp_record"
    payload["_received_at"] = datetime.datetime.now().isoformat()
    fname = "health_%s_%s.json" % (
        datetime.date.today().isoformat(),
        datetime.datetime.now().strftime("%H%M%S"),
    )
    with open(os.path.join(DATA_DIR, fname), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"ok": True, "file": fname}


def _build_app():
    app = mcp.streamable_http_app()
    if not TOKEN:
        return app

    class TokenAuth:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                headers = dict(scope.get("headers", []))
                auth = headers.get(b"authorization", b"").decode("latin1")
                if auth != "Bearer " + TOKEN:
                    body = json.dumps({"error": "forbidden"}).encode()
                    await send({
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"application/json")],
                    })
                    await send({"type": "http.response.body", "body": body})
                    return
            await self.inner(scope, receive, send)

    return TokenAuth(app)


if __name__ == "__main__":
    import uvicorn

    print("band-bridge on 0.0.0.0:%s, token=%s" % (PORT, "set" if TOKEN else "NONE"))
    uvicorn.run(_build_app(), host="0.0.0.0", port=PORT, log_level="warning")
