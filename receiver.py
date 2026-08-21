#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
band-bridge · 数据接收端（端口8899，可选）

手机端脚本/应用把手环数据 POST 到这里，本服务落盘成 JSON，
band-bridge（8898）读取同一目录对外提供 MCP 工具。

鉴权：可选。设置环境变量 BAND_RECEIVER_TOKEN 后，请求需带 Authorization: Bearer <token>。
（默认复用 BAND_MCP_TOKEN，若单独设置则用 BAND_RECEIVER_TOKEN。）

推送格式示例：
  POST /push
  {"heart_rate": 76, "steps": 5230, "sleep": {"deep": 92, "light": 401, "total": 493}, "battery": 61}
"""
import os
import json
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

DATA_DIR = os.environ.get("BAND_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
TOKEN = os.environ.get("BAND_RECEIVER_TOKEN") or os.environ.get("BAND_MCP_TOKEN", "")
PORT = int(os.environ.get("BAND_RECEIVER_PORT", "8899"))

os.makedirs(DATA_DIR, exist_ok=True)


def _now():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class Handler(BaseHTTPRequestHandler):
    def _check(self):
        auth = self.headers.get("Authorization", "")
        if TOKEN and auth != "Bearer " + TOKEN:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return False
        return True

    def do_POST(self):
        if not self._check():
            return
        length = int(self.headers.get("content-length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"bad json")
            return
        data["_received_at"] = _now()
        data["_source"] = "push"
        fname = "health_%s_%s.json" % (datetime.date.today().isoformat(), _now())
        with open(os.path.join(DATA_DIR, fname), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        if not self._check():
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "dir": DATA_DIR}).encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("band receiver on 0.0.0.0:%s, token=%s" % (PORT, "set" if TOKEN else "NONE"))
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
