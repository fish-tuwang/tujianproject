# 采集频率调整

2026-11-11按用户要求调整服务器自动采集，版本0.11.2；无数据库迁移或数据重导，不创建依赖电脑在线的Codex提醒任务。

| 图鉴 | 自动检查 | 本次部署核对的下次触发（北京时间） |
|---|---|---|
| 多美卡 | 每48小时03:00，增量 | 2026-11-13 03:00 |
| 高达 | 每周日03:30，增量 | 2026-11-15 03:30 |
| 宝可梦 | 停用 | 无 |

多美卡沿用现有队列和单来源互斥，将原每日增量及周日全量任务替换为唯一的tomica-incremental任务。IntervalTrigger固定以2026-01-01 03:00为相位，跨月、跨年或重启仍保持172800秒间隔。取消自动宝可梦任务，部署前后均无宝可梦活动任务或可重试失败项；手动管理命令、原有记录与图片缓存预热保留。

高达沿用独立systemd服务，OnCalendar改为Sun *-*-* 03:30:00 Asia/Shanghai，保留Persistent与动态APP_IMAGE；安装脚本显式重启timer，避免已有活动定时器保留旧节奏。旧单元备份在服务器backups/schedule-20261111T134006，部署及频率变更事件记录于原私有deploy日志。

实际终端验证：

- 本地执行`.venv/Scripts/python.exe -m pytest backend/tests/test_sync.py backend/tests/test_gunpla_deploy.py backend/tests/test_audit.py backend/tests/test_auth_deploy.py -q --tb=short`，退出0，`35 passed, 1 skipped in 4.52s`；跳过为Windows上的POSIX日志轮转。
- 发布器在真实0.11.2镜像内禁网执行`python -m pytest -q -p no:cacheprovider`，退出0，`247 passed, 13 warnings in 61.15s`；包括既有来源、缓存、互斥、重试、鉴权和迁移回归。
- 实际运行的scheduler容器为0.11.2、running、重启计数0；同镜像隔离构建的任务表只有tomica-incremental，source=tomica、mode=incremental、interval_seconds=172800、下次2026-11-13T03:00:00+08:00。
- systemd单元校验、日历解析、daemon-reload和timer重启成功，真实timer为active，下次Sun 2026-11-15 03:30:00 CST；Pokemon调度为空，旧每日/每周全量不再注册。
- 两套API均ready/0005_gunpla，原插件ID不变，迁移与导入均为false。当前未手动触发抓取；上述验证是实际调度配置与下次触发时间核对，不冒称未来任务已执行成功。

运行回执在本机与服务器私有artifacts/acceptance/sync-frequency.json；原图鉴页面、账号和缓存配置没有改动。
