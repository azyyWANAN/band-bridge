# 备份说明 · Notify 两天一备 + nxk 手动通道

Notify for Mi Band 默认**每两天**自动备份一次。想当天数据当天到家，手动三步：

1. 打开 Notify → 同步手环
2. 导出备份 backup.nxk
3. 把文件发给你的 AI

## nxk 是什么

backup.nxk 是 ZIP，内含 backup.db（SQLite）。心率、睡眠、步数全在里面。

AI 拆包流程：解 ZIP → 读 heart / sleep / day / record 表 → 时间戳 +8h 换算（北京时间）→ 落盘为 v3 账本。

## 为什么每天只能手动

这是 Notify 的仓库开门规律（自动备份 2 天一次），不是腕桥偷懒。
