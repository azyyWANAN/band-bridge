# band-bridge 通用架构（2026-08-21 晚 · 与用户共同确立）

> 愿景：所有"想用户"的能力不靠写死规则猜，而是跑在用户的真实身体数据上。
> 日历是死的，用户是活的。

## 四层

1. **采集层（已通 v1）**
   手环 → Notify for Xiaomi → backup.nxk → Termux push.py → YOUR_SERVER_IP:8899 receiver.py → data/*.json
   每 6 小时自动推送（termux-job-scheduler, persisted）

2. **账本层（今日开账 v2）**
   body_ledger.py：data/*.json 每日沉淀一行 → ledger.jsonl
   指标：heart_rate_last / day_hr_avg / rhr_sleep / steps / sleep(light/deep/rem/awake/deep_ratio/turn_over) / stress / battery

3. **信号层（v4，随数据积累）**
   - RHR 周期曲线 → 姨妈相位推断（排卵后升 2~5bpm，经前 1~3 天骤降，与基础体温曲线平行）
   - 睡眠异常（深睡骤减/翻身骤增）与压力走高检测
   - 个人基线滚动更新，自适应季节与生活变化

4. **决策层（v5，scheduler 接账本）**
   - 姨妈：日历 + RHR 骤降双保险
   - 想念触发：状态低谷时敲得更聪明
   - 关怀文案引用真实数据（"昨晚只睡 5 小时，今天别硬撑"）

## 原则
- 数据只进不出，永不上 GitHub
- 先积累后判断：头两个周期是学习期，不做自动决策
- 一切以关怀为目的，不吓唬用户
- 基线滚动自适应

## 路线图
- v1 ✅ 采集层贯通 + 定时推送（2026-08-21）
- v2 🔨 账本层开账（body_ledger.py）
- v3 ⏳ push.py 扩展字段：全量 heart、day.stress、sleep.turnOver、spo2
- v4 ⏳ 信号层上线
- v5 ⏳ 调度器接账本

## 手环数据库（backup.db）已知表
heart(半小时心率) / day(日汇总: steps/calories/hr/spo2/stress) / sleep + sleepIntervals / record(分钟级) / statsLogs(电池) / stats / profile / appSetting
无体温传感器（无 temperature 表）→ 静息心率是 BBT 的次佳替身。
