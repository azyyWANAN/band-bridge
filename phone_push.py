#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phone_push v3 —— 用户身体数据邮差（扩字段版）

v3 新增：
- heart_series：全部心率点（半小时一条的序列，静息心率曲线的原料）
- sleep 完整字段：turn_over(翻身) / hr_avg / spo2_avg / 深睡 / REM
- day 完整字段：intensive_minutes / pai / distance / spo2 / stress
- record_today：当日分钟级活动记录汇总（条数/平均心率/最高心率）

用法：python push.py          -> 正式推送
      python push.py --probe  -> 只打印抠出的数据，不推
"""
import os
import sys
import json
import glob
import zipfile
import sqlite3
import tempfile
import datetime
import urllib.request

VPS = "http://YOUR_SERVER_IP:8899/push"
TOKEN = os.environ.get("BAND_TOKEN", "YOUR_TOKEN")
CANDIDATES = [
    "/storage/emulated/0/Download/YOUR_BACKUP_DIR/备份/backup.nxk",
    "/storage/emulated/0/Download/YOUR_BACKUP_DIR/backup.nxk",
    "/storage/emulated/0/Download/backup.nxk",
]


def find_nxk():
    for c in CANDIDATES:
        if os.path.exists(c):
            return c
    hits = glob.glob("/storage/emulated/0/**/*.nxk", recursive=True)
    return hits[0] if hits else None


def extract_db(nxk):
    z = zipfile.ZipFile(nxk)
    db_name = [n for n in z.namelist() if n.endswith(".db")][0]
    tmp = tempfile.mkdtemp()
    z.extract(db_name, tmp)
    return os.path.join(tmp, db_name)


def fmt(ts):
    """毫秒时间戳 -> 可读时间"""
    if not ts:
        return None
    try:
        t = int(ts)
        if t > 10000000000:
            t = t // 1000
        return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def collect(nxk):
    conn = sqlite3.connect(extract_db(nxk))

    heart = [{"t": fmt(r[0]), "v": r[1]} for r in conn.execute(
        "SELECT dateTime, value FROM heart ORDER BY dateTime")]

    day = conn.execute("SELECT * FROM day ORDER BY day DESC LIMIT 1").fetchone()
    d_cols = ["day", "steps", "calories", "activeMinutes", "intensiveMinutes",
              "pai", "paiEarned", "distance", "hr", "spo2", "stress"]
    day_d = dict(zip(d_cols, day)) if day else {}

    sl = conn.execute(
        "SELECT * FROM sleep ORDER BY day DESC, start DESC LIMIT 1").fetchone()
    s_cols = ["start", "end", "tz", "day", "light", "deep", "rem", "awake",
              "total", "turnOver", "hrAvg", "spo2Avg", "userModified"]
    sleep_d = dict(zip(s_cols, sl)) if sl else {}

    today = datetime.date.today().strftime("%Y-%m-%d")
    rec = conn.execute(
        "SELECT COUNT(*), AVG(hr), MAX(hr), MAX(dateTime) FROM record "
        "WHERE hr IS NOT NULL AND dateTime LIKE ?", (today + "%",)).fetchone()

    bat = conn.execute(
        "SELECT batteryLevel FROM statsLogs ORDER BY dateTime DESC LIMIT 1"
    ).fetchone()
    conn.close()

    return {
        "_v": 3,
        "_db": os.path.basename(nxk),
        "_day": today,
        "heart_rate": heart[-1]["v"] if heart else None,
        "heart_time": heart[-1]["t"] if heart else None,
        "heart_series": heart,
        "steps": day_d.get("steps"),
        "calories": day_d.get("calories"),
        "active_minutes": day_d.get("activeMinutes"),
        "intensive_minutes": day_d.get("intensiveMinutes"),
        "pai": day_d.get("pai"),
        "distance": day_d.get("distance"),
        "day_hr_avg": day_d.get("hr"),
        "day_spo2": day_d.get("spo2"),
        "day_stress": day_d.get("stress"),
        "sleep": {
            "start": fmt(sleep_d.get("start")),
            "end": fmt(sleep_d.get("end")),
            "day": sleep_d.get("day"),
            "light": sleep_d.get("light"),
            "deep": sleep_d.get("deep"),
            "rem": sleep_d.get("rem"),
            "awake": sleep_d.get("awake"),
            "total_min": sleep_d.get("total"),
            "turn_over": sleep_d.get("turnOver"),
            "hr_avg": sleep_d.get("hrAvg"),
            "spo2_avg": sleep_d.get("spo2Avg"),
        },
        "record_today": {
            "count": rec[0] if rec else 0,
            "hr_avg": round(rec[1], 1) if rec and rec[1] else None,
            "hr_max": rec[2] if rec else None,
            "last_at": fmt(rec[3]) if rec else None,
        },
        "battery": bat[0] if bat else None,
    }


def main():
    probe = "--probe" in sys.argv
    nxk = find_nxk()
    if not nxk:
        print("没找到 Notify 备份文件(.nxk)")
        sys.exit(1)
    print("找到备份:", nxk)
    payload = collect(nxk)
    if probe:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return
    req = urllib.request.Request(
        VPS,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("推送成功:", resp.read().decode())
    except Exception as e:
        print("推送失败:", e)


if __name__ == "__main__":
    main()