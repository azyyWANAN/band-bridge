#!/usr/bin/env python3
"""
身体账本 Body Ledger —— 用户的身体数据底座（通用架构 · 账本层）

使命：把 data/*.json 里的原始推送，每日沉淀成 ledger.jsonl 的一行。
架构：采集(data) -> 账本(ledger) -> 信号(周期相位/异常/趋势) -> 决策(scheduler)
原则：只进不出；先积累后判断；一切以关怀为目的；基线滚动自适应。

2026-08-21 开账。等 push.py 扩展字段后，rhr 曲线/深睡占比/turnOver 会陆续有真值。
"""
import json
import glob
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
LEDGER = os.path.join(BASE, "ledger.jsonl")


def load_day_records(day):
    """读某天落地的全部推送文件"""
    recs = []
    for f in sorted(glob.glob(os.path.join(DATA, f"*{day}*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                recs.append(json.load(fh))
        except Exception:
            pass
    return recs


def merge_daily(recs):
    """当天多次推送 -> 一天一行指标。心率步数取最后一次；睡眠取当天最长一段。"""
    if not recs:
        return None
    recs = sorted(recs, key=lambda r: str(r.get("_received_at", "")))
    last = recs[-1]
    sleeps = [r.get("sleep") or {} for r in recs]
    longest = max(sleeps, key=lambda s: s.get("total_min") or 0, default={})
    total = longest.get("total_min") or 0
    return {
        "date": last.get("day") or datetime.now().strftime("%Y-%m-%d"),
        "heart_rate_last": last.get("heart_rate"),
        "heart_time": last.get("heart_time"),
        "day_hr_avg": last.get("day_hr_avg"),
        "rhr_sleep": longest.get("hr_avg"),          # 睡时平均心率，静息心率的一号候选
        "steps": last.get("steps"),
        "calories": last.get("calories"),
        "active_min": last.get("active_minutes"),
        "sleep_total_min": total,
        "sleep_light": longest.get("light"),
        "sleep_deep": longest.get("deep"),
        "sleep_rem": longest.get("rem"),
        "sleep_awake": longest.get("awake"),
        "sleep_deep_ratio": round((longest.get("deep") or 0) / max(total, 1), 3),
        "turn_over": longest.get("turn_over"),        # 等 push.py v3 扩展
        "stress": last.get("stress"),                  # 等 push.py v3 扩展
        "battery": last.get("battery"),
        "push_count": len(recs),
    }


def append_ledger(metrics):
    """同一天重复跑会覆盖当天那行（幂等），按日期排序写回。"""
    rows = []
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
    rows = [r for r in rows if r.get("date") != metrics["date"]]
    metrics["recorded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows.append(metrics)
    rows.sort(key=lambda r: r["date"])
    with open(LEDGER, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def run():
    day = datetime.now().strftime("%Y-%m-%d")
    recs = load_day_records(day)
    m = merge_daily(recs)
    if not m:
        print(f"[body_ledger] {day} 无数据，跳过")
        return
    append_ledger(m)
    print(
        f"[body_ledger] {day} 已入账: "
        f"心率{m['heart_rate_last']} 步数{m['steps']} "
        f"睡眠{m['sleep_total_min']}min 睡时RHR{m['rhr_sleep']}"
    )


if __name__ == "__main__":
    run()
