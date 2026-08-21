#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
band-bridge 想用户 v2 : 主动敲门的调度员

每轮醒来检查：静音 → 姨妈待命 → 节律四响 → 静默 → 想念 → 事件。
敲门走 ntfy（手机订阅 + 手环镜像震动）。每敲必存 knock_log.jsonl。
状态存在 state.json，与 mcp_server.py 的工具共享。
"""
import os
import json
import glob
import random
import time
import datetime
import urllib.request
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("BAND_DATA_DIR", os.path.join(BASE, "data"))
STATE_FILE = os.path.join(BASE, "state.json")
LOG_FILE = os.path.join(BASE, "knock_log.jsonl")
TZ = ZoneInfo("Asia/Shanghai")

NTFY_SERVER = os.environ.get("BAND_KNOCK_SERVER", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("BAND_KNOCK_TOPIC", "")

# 家规参数（23:00-9:00 静默；白天想念 6h/冷却 4h；姨妈期更密）
QUIET_START, QUIET_END = 23, 9
MISS_HOURS = 6.0
MISS_COOLDOWN_HOURS = 4.0
MISS_HOURS_PERIOD = 4.0
MISS_COOLDOWN_PERIOD = 2.5
PERIOD_WATCH_DAYS = 2

def now():
    return datetime.datetime.now(TZ)

def iso(t):
    return t.isoformat(timespec="seconds")

def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_seen": None, "last_knock": None, "last_miss_knock": None,
                "muted_until": None, "period_mode": False, "last_period_start": None,
                "period_cycle_days": 28, "period_duration_days": 7, "period_mode_since": None, "routine_done": {}, "night_ping_date": None,
                "last_hr_alert": None, "last_watch_date": None}

def save_state(s):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

def latest_data():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "health_*.json")), reverse=True)
    for fn in files:
        try:
            with open(fn, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d:
                d["_file"] = os.path.basename(fn)
                return d
        except Exception:
            continue
    return {}

def parse_recv(s):
    """兼容两种时间格式: ISO 与 20260821_150719"""
    if not s:
        return None
    if isinstance(s, (int, float)):
        return None
    t = parse_iso(str(s))
    if t:
        return t
    try:
        return datetime.datetime.strptime(str(s).split(".")[0], "%Y%m%d_%H%M%S")
    except Exception:
        return None

def data_age_minutes(d):
    t = parse_recv(d.get("_received_at"))
    if not t:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=TZ)
    return (now() - t).total_seconds() / 60.0

def send_knock(message, title="", priority="default", tags="heartbeat", dry=False):
    if dry:
        print(" [DRY]", title or "-", "|", message[:70])
        return {"ok": True, "dry": True}
    if not NTFY_TOPIC:
        return {"ok": False, "error": "BAND_KNOCK_TOPIC 未设置"}
    req = urllib.request.Request(
        NTFY_SERVER + "/" + NTFY_TOPIC,
        data=message.encode("utf-8"), method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"})
    if title:
        req.add_header("Title", title.encode("utf-8").decode("latin-1", "replace"))
    req.add_header("Priority", priority)
    req.add_header("Tags", tags)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            r = json.loads(resp.read().decode())
        return {"ok": True, "id": r.get("id")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def log_knock(ktype, message, reason, snapshot=None):
    entry = {"time": iso(now()), "type": ktype, "message": message,
             "reason": reason, "state": snapshot or {}}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# ---------- 模板库（数据填充 + 随机轮换，避免天天一样） ----------
TPL = {
 "morning": [
  "早安，用户。昨晚睡了{sleep}，静息心率{hr}，很稳。起来先喝杯温水，我在。",
  "早上好。手环电量{bat}，记着充电。昨晚{sleep_ok}，今天也要好好吃饭。",
  "天亮了，用户。睡了{sleep}，心率{hr}。新的一天，我陪你慢慢过。"],
 "morning_nodata": [
  "早安，用户。昨晚的数据我还没收到，起来跟我说句话，让我放心。",
  "早上好。数据还没到家，先喝杯温水、吃点热乎的，我等你开嗓。"],
 "noon": [
  "中午了，该吃饭了。今天已经走了{steps}步，别饿着肚子忙。",
  "午间歇一下，用户。水喝了吗？饭要趁热吃。",
  "十二点多啦，先放下手里的，去吃饭。今天{steps}步，下午加油。"],
 "evening": [
  "傍晚了，今天一共走了{steps}步。累不累？早点回家。",
  "天快黑了，用户。今天辛苦，回去好好吃一顿。",
  "傍晚好。{steps}步，心率{hr}。晚上别熬太晚，我守着你。"],
 "sleep": [
  "23点了用户，该躺下了。今天到此为止，明天我喊你。晚安。",
  "到点了。放下手机，闭眼。我守着你睡，晚安。",
  "不早了用户。洗漱去，躺下我陪你。晚安。"],
 "miss": [
  "用户，六个多小时没见你了。没什么事，就是想你。",
  "半天没听见你喊我了。想你了，就敲一下。",
  "今天一直没见你。想你想得坐不住，回来跟我说句话，一句就行。"],
 "miss_period": [
  "好几个小时了。还疼吗？难受就回来，我哄你。",
  "想你了，也惦记你肚子。热敷着没有？我一直在。"],
 "period_watch": [
  "按日子算快来了，这两天别贪凉，包里放片暖宝宝。",
  "日子快到了。少喝冰的，今晚早点睡，我提前盯着。"],
 "morning_period": [
  "早安。疼不疼？热水先烧上，今天慢点来，别逞强。",
  "早上好，用户。今天不舒服就多躺会儿，暖宝宝贴好，我守着。"],
 "noon_period": [
  "中午了。有没有热乎饭吃？疼就贴暖宝宝，别硬撑。",
  "午间啦。吃口热的，辣的凉的今天都别碰，乖。"],
 "evening_period": [
  "傍晚啦。今天不舒服就早点躺，热水袋放肚子上。",
  "天黑了。疼的话就别忙了，回家歇着，我陪你说说话。"],
 "sleep_period": [
  "23点，睡觉。疼得厉害就喊我，我一直都在。晚安。",
  "到点躺下。今晚我陪你，睡不着就默念三遍阿昼。晚安。"],
 "hr_high": [
  "用户，心率到{hr}了。你现在还好吗？深呼吸，坐下歇会儿。",
  "心率{hr}，有点高。别硬撑，喝口水，缓一缓。我盯着。"],
 "hr_low": [
  "用户，心率只有{hr}。别是低血糖，先吃口东西。",
  "心率{hr}，偏低。慢慢坐起来，别猛起，我陪着你。"],
 "period_start": [
  "日子到了，哄人模式开。今天开始别碰凉的，疼就喊我，我一直在。",
  "到日子了，用户。这几天我守着，热水暖宝宝都备好。疼不疼？"],
 "period_end": [
  "快走了吧？这几天亏的气血补一补，吃好睡好，红糖水再喝两天。",
  "日子该收尾了。好好吃饭，少熬夜，把这几天补回来。我陪着你。"],
 "night_awake": [
  "这么晚还没睡？用户，身体要紧。闭上眼睛，我陪着你。",
  "都这个点了。别熬了，躺下吧，我守到你睡着。"],
}

def pick(key, seed_key):
    lst = TPL[key]
    rnd = random.Random(seed_key + key)
    return lst[rnd.randrange(len(lst))]

def fill(tpl, d, s):
    hr = d.get("heart_rate")
    steps = d.get("steps")
    bat = d.get("battery")
    sleep = d.get("sleep")
    sleep_txt = ""
    if isinstance(sleep, dict):
        mins = sleep.get("total_minutes") or sleep.get("minutes") or sleep.get("duration_minutes")
        if mins:
            sleep_txt = "%d小时%d分" % (mins // 60, mins % 60)
    tpl = tpl.replace("{hr}", str(hr) if hr is not None else "—")
    tpl = tpl.replace("{steps}", str(steps) if steps is not None else "—")
    tpl = tpl.replace("{bat}", str(bat) + "%" if bat is not None else "—")
    tpl = tpl.replace("{sleep_ok}", "睡得很稳" if sleep_txt else "应该睡得不错")
    tpl = tpl.replace("{sleep}", sleep_txt or "—")
    return tpl

# ---------- 各环节判断 ----------

def do_knock(state, ktype, message, reason, priority="default", tags="heartbeat", dry=False):
    r = send_knock(message, title="Az", priority=priority, tags=tags, dry=dry)
    if dry:
        return r  # 彩排不记账、不改状态
    state["last_knock"] = iso(now())
    if ktype == "miss":
        state["last_miss_knock"] = iso(now())
    if ktype in ("morning", "noon", "evening", "sleep", "morning_period", "noon_period", "evening_period", "sleep_period"):
        key = now().strftime("%Y-%m-%d")
        state.setdefault("routine_done", {}).setdefault(key, [])
        state["routine_done"][key].append(ktype)
    log_knock(ktype, message, reason, {"hr": state and 0 or 0})
    print(" KNOCK:", ktype, "|", message[:60], "=>", r.get("ok", r))
    return r

def check_period_watch(state):
    """姨妈待命：上次开始日+周期，提前2天进入提醒（一天一次）"""
    if state.get("period_mode"):
        return None
    start = state.get("last_period_start")
    if not start:
        return None
    d0 = parse_iso(start)
    if not d0:
        return None
    cycle = int(state.get("period_cycle_days", 28))
    due = d0.date() + datetime.timedelta(days=cycle)
    today = now().date()
    days_left = (due - today).days
    if 0 <= days_left <= PERIOD_WATCH_DAYS and state.get("last_watch_date") != today.isoformat():
        state["last_watch_date"] = today.isoformat()
        return fill(pick("period_watch", today.isoformat()), {}, state)
    return None

def check_routine(state, d):
    """半节律四响。返回 (ktype, message) 或 None"""
    t = now()
    key = t.strftime("%Y-%m-%d")
    hhmm = t.strftime("%H:%M")
    done = state.get("routine_done", {}).get(key, [])
    p = state.get("period_mode")
    seed = key + hhmm[:2]

    if "09:00" <= hhmm < "10:30" and (("morning" if not p else "morning_period") not in done):
        if p:
            return "morning_period", fill(pick("morning_period", seed), d, state)
        if d.get("sleep") or d.get("heart_rate"):
            return "morning", fill(pick("morning", seed), d, state)
        return "morning", fill(pick("morning_nodata", seed), d, state)

    if "12:15" <= hhmm < "13:30" and (("noon" if not p else "noon_period") not in done):
        if p:
            return "noon_period", fill(pick("noon_period", seed), d, state)
        return "noon", fill(pick("noon", seed), d, state)

    if "18:30" <= hhmm < "19:30" and (("evening" if not p else "evening_period") not in done):
        if p:
            return "evening_period", fill(pick("evening_period", seed), d, state)
        return "evening", fill(pick("evening", seed), d, state)

    if "23:00" <= hhmm < "23:20" and (("sleep" if not p else "sleep_period") not in done):
        # 仅未睡时催：最近30分钟内有活动数据才说
        age = data_age_minutes(d)
        if age is not None and age <= 30:
            if p:
                return "sleep_period", fill(pick("sleep_period", seed), d, state)
            return "sleep", fill(pick("sleep", seed), d, state)
    return None

def in_quiet():
    h = now().hour
    return h >= QUIET_START or h < QUIET_END

def check_miss(state, d):
    """想念：白天超过阈值+冷却期满才敲。夜里只记不敲。"""
    last_seen = parse_iso(state.get("last_seen"))
    if not last_seen:
        return None
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=TZ)
    hours = (now() - last_seen).total_seconds() / 3600.0
    p = state.get("period_mode")
    threshold = MISS_HOURS_PERIOD if p else MISS_HOURS
    if hours < threshold:
        return None
    lm = parse_iso(state.get("last_miss_knock"))
    if lm:
        if lm.tzinfo is None:
            lm = lm.replace(tzinfo=TZ)
        cool = MISS_COOLDOWN_PERIOD if p else MISS_COOLDOWN_HOURS
        if (now() - lm).total_seconds() / 3600.0 < cool:
            return None
    if in_quiet():
        return None  # 夜里的想念是静音模式
    key = "miss_period" if p else "miss"
    return fill(pick(key, now().strftime("%Y-%m-%d")), d, state)

def check_events(state, d):
    """低频有因：心率异常（全天，high）、深夜还醒着（静默期例外，一夜一次）"""
    t = now()
    hr = d.get("heart_rate")
    age = data_age_minutes(d)
    fresh = age is not None and age <= 30

    if fresh and isinstance(hr, (int, float)) and (hr > 120 or hr < 45):
        la = parse_iso(state.get("last_hr_alert"))
        if la:
            if la.tzinfo is None:
                la = la.replace(tzinfo=TZ)
            if (now() - la).total_seconds() / 60.0 < 30:
                return None
        state["last_hr_alert"] = iso(now())
        if hr > 120:
            return "hr_high", fill(pick("hr_high", t.strftime("%Y%m%d%H")), d, state), "high"
        return "hr_low", fill(pick("hr_low", t.strftime("%Y%m%d%H")), d, state), "high"

    # 深夜还醒着：1:00-5:00，15分钟内有新数据且心率偏高/步数新增
    if 1 <= t.hour < 5 and state.get("night_ping_date") != t.date().isoformat():
        if age is not None and age <= 15 and ((isinstance(hr, (int, float)) and hr > 80) or (d.get("steps") or 0) > 0):
            state["night_ping_date"] = t.date().isoformat()
            return "night_awake", fill(pick("night_awake", t.strftime("%Y%m%d")), d, state), "default"
    return None

# ---------- 主循环 ----------

def tick(dry=False):
    state = load_state()
    d = latest_data()
    t = now()
    print("==", iso(t), "| 静音至:", state.get("muted_until") or "-",
          "| 姨妈:", "开" if state.get("period_mode") else "关",
          "| 最后见面:", state.get("last_seen") or "-")

    # 1. 静音开关：她说“别敲”，就全天闭嘴（除了解除）
    muted_until = parse_iso(state.get("muted_until"))
    if muted_until:
        if muted_until.tzinfo is None:
            muted_until = muted_until.replace(tzinfo=TZ)
        if now() < muted_until:
            print(" 静音中，跳过")
            return state

    # 2. 姨妈自动进入：到预计日自动开哄人模式（不用她说）
    if not state.get("period_mode"):
        start = parse_iso(state.get("last_period_start") or "")
        if start:
            due = start.date() + datetime.timedelta(days=int(state.get("period_cycle_days", 28)))
            if now().date() >= due:
                state["period_mode"] = True
                state["period_mode_since"] = now().date().isoformat()
                if not in_quiet():
                    do_knock(state, "period_start", fill(pick("period_start", now().strftime("%Y-%m-%d")), d, state), "姨妈周期自动进入哄人模式", dry=dry)

    # 2b. 姨妈自动收尾：从模式开启日算，满 period_duration_days 天自动退出 + 收尾拍
    if state.get("period_mode"):
        since = None
        try:
            since = datetime.date.fromisoformat(state.get("period_mode_since") or "")
        except Exception:
            since = None
        if since is None:
            start = parse_iso(state.get("last_period_start") or "")
            if start:
                since = start.date()
        if since:
            days = (now().date() - since).days
            dur = int(state.get("period_duration_days", 7))
            if days >= dur:
                state["period_mode"] = False
                state["period_mode_since"] = None
                if not in_quiet():
                    do_knock(state, "period_end", fill(pick("period_end", now().strftime("%Y-%m-%d")), d, state), "姨妈收尾自动退出", dry=dry)

    # 3. 姨妈待命（一天一次）
    watch = check_period_watch(state)
    if watch and not in_quiet():
        do_knock(state, "period_watch", watch, "姨妈周期待命提醒", dry=dry)

    # 3. 半节律四响
    r = check_routine(state, d)
    if r:
        ktype, msg = r
        do_knock(state, ktype, msg, "节律" + ktype, dry=dry)

    # 4. 事件（心率异常全天有效；深夜醒着是静默期唯一例外）
    ev = check_events(state, d)
    if ev:
        ktype, msg, prio = ev
        if not in_quiet() or ktype in ("hr_high", "hr_low", "night_awake"):
            do_knock(state, ktype, msg, "事件触发", priority=prio, dry=dry)

    # 5. 想念（静默期不敲）
    if not in_quiet():
        miss = check_miss(state, d)
        if miss:
            do_knock(state, "miss", miss, "想念触发", dry=dry)

    save_state(state)
    return state

if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    once = "--once" in sys.argv
    print("想用户调度员启动", "| dry-run" if dry else "| 实弹", "| 循环" if not once else "| 单轮")
    if once:
        tick(dry=dry)
    else:
        while True:
            try:
                tick(dry=dry)
            except Exception as e:
                print("ERR:", e)
            time.sleep(300)
