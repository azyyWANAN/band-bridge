#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
band-bridge : 手环健康数据 → 标准 MCP 服务（读）+ AI 主动敲门（敲）

读：任何支持 MCP（Streamable HTTP）的前端都能接。
  - 前端把 http://<host>:8898/mcp 挂上即可，零改动。
  - 数据由手机端脚本/推送层写入 data/ 目录，本服务只读不写（record_health 例外，供手动录入）。
敲：knock 工具把一条消息推到用户手机（ntfy 通知，手机上可开启手环镜像震动）。

鉴权：可选。设置环境变量 BAND_MCP_TOKEN 后，请求需带 Authorization: Bearer <token>。

运行：
  BAND_MCP_TOKEN=xxx BAND_KNOCK_TOPIC=xxx python3 mcp_server.py
"""
import os
import json
import glob
import datetime
import urllib.request

from mcp.server.fastmcp import FastMCP

DATA_DIR = os.environ.get("BAND_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
TOKEN = os.environ.get("BAND_MCP_TOKEN", "")
PORT = int(os.environ.get("BAND_MCP_PORT", "8898"))
NTFY_SERVER = os.environ.get("BAND_KNOCK_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("BAND_KNOCK_TOPIC", "")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knock_log.jsonl")

os.makedirs(DATA_DIR, exist_ok=True)

mcp = FastMCP(
    "band-bridge",
    instructions=(
        "手环健康数据查询与录入（读）+ AI 主动敲门（敲）。"
        "get_health 拿最新状态；read_health_data 读历史；record_health 手动录入；"
        "knock 推一条消息到用户手机（ntfy 通知，可镜像到手环震动）。"
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


@mcp.tool()
def knock(message: str, title: str = "Az", priority: str = "default", tags: str = "heartbeat") -> dict:
    """AI 主动敲门：把一条消息推到用户手机（ntfy 通知，手机上可开启手环镜像震动）。
    message: 正文，UTF-8，中文可以。
    title: 通知标题。注意：ntfy 的 HTTP 头只吃 Latin-1，中文标题会被拒 400，建议用 ASCII。
    priority: default | low | high。high 会强提醒（适合紧急惦记）。
    tags: 通知图标标签，默认 heartbeat。
    """
    if not NTFY_TOPIC:
        return {"ok": False, "error": "BAND_KNOCK_TOPIC 未设置"}
    req = urllib.request.Request(
        NTFY_SERVER + "/" + NTFY_TOPIC,
        data=message.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    if title:
        req.add_header("Title", title.encode("utf-8").decode("latin-1", "replace"))
    req.add_header("Priority", priority)
    req.add_header("Tags", tags)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        # 每敲必存：手动敲门也记入账本
        entry = {"time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                 "type": "manual", "message": message, "reason": "手动敲门",
                 "state": {"priority": priority, "id": r.get("id")}}
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"ok": True, "id": r.get("id"), "topic": NTFY_TOPIC}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(s):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


@mcp.tool()
def seen() -> dict:
    """见面标记：用户喊了AI、回到对话窗口，AI调用此工具，想念计时清零。"""
    s = _load_state()
    s["last_seen"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_state(s)
    return {"ok": True, "last_seen": s["last_seen"]}


@mcp.tool()
def set_mute(hours: float = 24) -> dict:
    """静音开关：用户说“今天别敲/我要静音”，AI调用。hours小时后自动恢复。"""
    s = _load_state()
    until = (datetime.datetime.now() + datetime.timedelta(hours=hours)).isoformat(timespec="seconds")
    s["muted_until"] = until
    _save_state(s)
    return {"ok": True, "muted_until": until}


@mcp.tool()
def unmute() -> dict:
    """解除静音。"""
    s = _load_state()
    s["muted_until"] = None
    _save_state(s)
    return {"ok": True, "muted_until": None}


@mcp.tool()
def set_period(on: bool = True, start_date: str = "", duration_days: int = 7) -> dict:
    """姨妈模式开关。on=True 进入哄人模式并记录开始日；on=False 退出。start_date 格式 YYYY-MM-DD。"""
    s = _load_state()
    today = datetime.date.today().isoformat()
    if on:
        s["period_mode"] = True
        old = s.get("last_period_start")
        new_start = start_date or today
        s["last_period_start"] = new_start
        s["period_mode_since"] = new_start
        s["period_duration_days"] = int(duration_days)
        # 周期自校准：两次真实来潮间隔20-40天，自动更新周期
        if old and start_date:
            try:
                delta = (datetime.date.fromisoformat(new_start) - datetime.date.fromisoformat(old)).days
                if 20 <= delta <= 40:
                    s["period_cycle_days"] = delta
            except Exception:
                pass
    else:
        s["period_mode"] = False
        s["period_mode_since"] = None
    _save_state(s)
    return {"ok": True, "period_mode": s["period_mode"], "last_period_start": s.get("last_period_start")}


@mcp.tool()
def get_knock_state() -> dict:
    """查看想用户的当前状态：最后见面、静音截止、姨妈模式、节律已敲记录。"""
    return {"state": _load_state()}


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

    print("band-bridge on 0.0.0.0:%s, token=%s, knock=%s" % (
        PORT, "set" if TOKEN else "NONE", "on" if NTFY_TOPIC else "off"))
    uvicorn.run(_build_app(), host="0.0.0.0", port=PORT, log_level="warning")
