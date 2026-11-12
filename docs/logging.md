# 服务器日志

本项目私有日志位于 `/opt/dual-catalog/data/artifacts/logs/`，通过SSH查询，不提供公开网页下载。生产与演示采集隔离，演示日志在 `/opt/dual-catalog/demo/artifacts/logs/`。以下命令在服务器执行。

| 文件 | 记录内容 |
| --- | --- |
| access.jsonl | 访问时间、连接IP、请求ID、路径、状态码、耗时、响应字节和User-Agent |
| deploy.jsonl | 项目发布/配置更新的操作者、SSH来源IP、旧/新版本、原因、阶段、源码摘要、健康检查、失败与回滚 |
| collection.jsonl | 采集来源/任务、逐页结果、实际新增/修改条目、变更字段、隔离/错误及结束统计；月刊导入另标local_import |

```sh
# 查看访问过的IP及各IP请求次数（含图片和接口请求，不等于人数）
python3 /opt/dual-catalog/app/scripts/view_logs.py access --summary --limit 30

# 查询北京时间当天起的访问
python3 /opt/dual-catalog/app/scripts/view_logs.py access --since 2026-11-10 --summary

# 查看单个IP；替换成实际IP
python3 /opt/dual-catalog/app/scripts/view_logs.py access --ip 203.0.113.1

# 发布操作、最近采集，以及实际新增条目
python3 /opt/dual-catalog/app/scripts/view_logs.py deploy --limit 20
python3 /opt/dual-catalog/app/scripts/view_logs.py collection --limit 20
python3 /opt/dual-catalog/app/scripts/view_logs.py collection --event record_created
python3 /opt/dual-catalog/app/scripts/view_logs.py collection --event record_updated

# 实时跟踪；-F会跟随轮转后的新文件
tail -F /opt/dual-catalog/data/artifacts/logs/collection.jsonl
```

事件中的 `created/updated` 指成功提交的业务条目数，可能包括车型版本、形态和扩展资料；不是全新的独立车型/宝可梦种类数。`page_checked.not_modified=true` 表示页面未变，`page_failed` 表示失败或隔离，均不会冒充新品。按 `run_id` 关联同一任务。新品月刊目前来自用户材料导入，`news_created/news_updated` 不代表自动访问公众号。

访问汇总中的 `errors` 为HTTP状态码≥400的请求数，具体原因需要结合路径与状态查看；汇总也会包含本次自动验收请求和服务器自身的回环请求。

新日志从启用后开始；原代理输出已保留为 `access-legacy-*.log`（旧格式，不纳入JSON查询）。既有采集历史仍在SyncRun/SyncItem数据库和旧容器输出；不能补造未记录的过去操作。发布日志针对本项目统一脚本的操作，不是任意root终端命令的审计。

后续完成代码上传和验证后，用统一命令发布（当前脚本用于无迁移版本）：

```sh
python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.7.0 --reason "更新说明"
```

日志时间使用带时区的ISO格式；查询 `--since` 未写时区时按北京时间解释。访问IP取自nginx实际连接地址，客户端伪造转发头不会替换它；IP代表网络出口，不能直接等同于个人。访问日志不保存查询参数、Cookie或Authorization；部署日志只记变更配置键，不记凭证内容。

独立 `dual-catalog-logrotate.timer` 每小时检查：访问/采集各20MiB阈值、14份历史，部署5MiB阈值、30份历史，按日或大小轮转并压缩。大流量时保留时间可能短于14/30天。Python自动重开文件，nginx收到reopen；轮转配置 `/opt/dual-catalog/logrotate.conf`，状态文件独立，不改系统其它日志规则。查看 `systemctl status dual-catalog-logrotate.timer`。日志属于本项目私有卷，文件权限为访问/采集0640、发布0600。

公网防爬已加入request_limit、connection_limit和known_crawler字段：REJECTED表示代理限流或并发拒绝，known_crawler=1表示命中已知爬虫标识；结合client_ip、path及403/429状态查询。该日志继续轮转，不记录认证Cookie和口令。

## PostgreSQL 诊断日志

2026-11-12 已核实 `/www/server/pgsql/data` 集群的业务库仅有 `dual_catalog`、`dual_catalog_demo`。原 `log_statement=all` 累积约23GiB SQL日志，磁盘可用空间归零，导致独立SQLite鉴权库无法写入会话。此问题发生时PostgreSQL只读健康检查仍可能返回200，应结合实际登录结果和 `df -h /` 判断。

该集群通过 `ALTER SYSTEM` 持久设置并热加载：`log_statement=ddl`、`log_parameter_max_length=256`、`log_filename=postgresql-%a.log`、`log_rotation_age=1440`（分钟）、`log_rotation_size=0`、`log_truncate_on_rotation=on`。保留数据库结构操作、错误及原有超过5秒的慢SQL诊断；每天使用一个星期文件并循环覆盖上周文件。配置不要求重启数据库，应用访问、鉴权、发布和采集日志仍按前文的独立规则保存。轮转方式依据 [PostgreSQL 官方七天循环示例](https://www.postgresql.org/docs/current/runtime-config-logging.html#GUC-LOG-TRUNCATE-ON-ROTATION)。

```sh
# 磁盘余量及数据库当前日志
df -h /
runuser -u postgres -- /www/server/pgsql/bin/psql -d postgres -At -c "SELECT pg_current_logfile();"

# 核对实际生效值，setting 的单位与 SHOW 展示格式可能不同
runuser -u postgres -- /www/server/pgsql/bin/psql -d postgres -At -c "SELECT name,setting,pending_restart FROM pg_settings WHERE name IN ('log_statement','log_filename','log_rotation_age','log_rotation_size','log_truncate_on_rotation','log_parameter_max_length');"

# 历史 SQL 日志压缩后仍可查询；替换为实际日志日期
zgrep -n 'ERROR' /www/server/pgsql/logs/postgresql-2026-11-11.log.gz | tail -20
```

原配置备份与逐文件压缩校验回执保存在 `/opt/dual-catalog/backups/pg-logging-*/` 私有目录。旧大文件在数据库日志切换后压缩，只有完整解压SHA256与原始内容一致、原文件未再变化时才替换为 `.log.gz`；不清空历史日志、图鉴、图片缓存或账号。原图缓存预热在恢复后继续运行。
