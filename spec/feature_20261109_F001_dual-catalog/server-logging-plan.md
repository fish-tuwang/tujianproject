# 服务器访问、发布与采集日志

本轮只补本项目三类日志与必要的部署、轮转、查询工具，不改图鉴页面、来源规则、定时周期或既有插件。

访问日志由本项目80端口nginx记录连接IP、时间、请求ID、方法、路径、状态、耗时、字节数和客户端类型；不信任客户端传入的X-Forwarded-For/X-Real-IP，不记录查询参数、Cookie或Authorization。日志留在私有卷，不提供公开HTTP下载。

采集沿用现有SyncRun/SyncItem事务和统计；仓储可选收集实际created/updated条目，检查点成功提交后才输出名称、身份、变更字段名及来源URL。保留未变更、失败、隔离、开始和结束事件；不能把扫描数当新增数。月刊本地导入独立记录，不当作公众号自动抓取。

发布采用仓库内统一脚本，记录操作者、SSH来源IP、旧/新镜像、操作阶段、源码摘要、健康检查、成功、失败及回滚；不输出环境文件内容或凭证。历史只保留已有真实日志和报告，不倒造操作记录。

路径统一为/opt/dual-catalog/data/artifacts/logs/{access,collection,deploy}.jsonl，演示采集在demo/artifacts/logs。Python使用WatchedFileHandler，主机独立logrotate小时检查并按日/大小轮转；访问和采集各保留14份（20MiB阈值），发布30份（5MiB阈值）。部署前保留原有代理输出与配置，代理变更仅作用于dual-catalog-preview-proxy。查询CLI支持类别、时间、IP、事件和访问IP汇总。

验证：真实事务新增/更新/无变化/回滚与日志轮转测试，相关仓储和同步回归；服务器nginx配置检查、带伪造转发头的真实公网请求及请求ID关联、轮转前后可继续写入；本项目发布实际成功/旧插件不变、采集真实任务事件。新日志从启用时开始，不声称覆盖未记录的历史操作。

## 实施与验收结果（2026-11-10）

已发布dual-catalog:0.7.0，无迁移或手动导入。旧插件fish-search、qq-summary-bot、原nginx的容器身份未变，均持续运行；本项目代理增加日志卷和受限Docker输出留存，项目两套API、采集worker/scheduler与cache-warmer更新。API健康0004_tomica_news，API/演示API/预热进程重启0次、OOM=false。发布operation_id在私有logging-deployment.json及deploy.jsonl中对应。

| 实际命令/检查 | 最终原始摘要 | 范围 |
| --- | --- | --- |
| .venv/Scripts/python.exe -m pytest -q | 117 passed, 1 skipped, 9 warnings in 16.75s；exit 0 | Windows本地全后端，SQLite及HTTP样本；POSIX轮转按平台跳过 |
| docker run --rm --network none --memory 256m --pids-limit 128 -e PYTHONDONTWRITEBYTECODE=1 -v /opt/dual-catalog/app:/src:ro -w /src --entrypoint python dual-catalog:0.6.3 -m pytest backend/tests/test_audit.py -q -p no:cacheprovider | 8 passed in 3.69s；REMOTE_EXIT=0 | Linux基础容器挂载本次0.7.0源码；包含打开文件重命名后自动重开的真实POSIX测试，其余为事务/查询及发布失败回滚单测 |
| python3 /opt/dual-catalog/app/scripts/prepare_logging.py | status=pass；REMOTE_EXIT=0 | 实际nginx -t、代理日志卷、logrotate配置检查和独立timer启用 |
| python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.7.0 --reason 'persistent access IP, release and source change logging' | status=pass，image=dual-catalog:0.7.0，plugins_unchanged=true；REMOTE_EXIT=0 | 实际发布记录与两套服务健康检查 |
| python3 /opt/dual-catalog/app/scripts/verify_logging.py --public-request-id [本次真实ID] --secret-marker [诊断标记] | status=pass，assertions=11，real_page_events=63；REMOTE_EXIT=0 | 公网真实连接IP；两种伪造转发头无效；查询参数/Cookie/Authorization诊断标记未写入；真实轮转后nginx及worker重开；历史与发布记录保留；私有权限与HTTP404；timer active；实际定时采集事件 |
| node scripts/verify-both-catalog-refresh.cjs | status=pass，assertions=29，errors=[]；TEST_EXIT=0 | 发布后真实公网，Chrome桌面/WebKit手机模拟，包含详情/刷新状态恢复、两类隔离、108条及侧栏延迟竞态 |

数字分别对应各项独立执行，不相加（Linux单测与本地单测重叠）。63表示验收时实际处理页面事件，不是发现63条新品；真实示例有page_checked.not_modified=true和业务created/updated=0，实际新增时才写record_created。没有制造生产新条目验证日志；新/改/无变化与回滚的分支由事务单测验证。发布回滚通过故障注入单测验证，没有故意破坏线上版本。

首次本地轮转测试遭Windows打开文件重命名WinError32，保留编码检查并拆出仅POSIX轮转测试，后者已在Linux实跑通过。首次服务器logrotate配置把10001当用户名称而检查失败；已改为继承现有collection文件的UID/GID（create 0640），配置检查及真实强制轮转均通过。首次失败与第二次成功的logging_setup事件均已留存，不掩盖首轮结果。

历史修复影响：全后端历史查询、采集、图片和月刊测试通过；公网29项确认筛选、详情返回、刷新、加载进度及侧栏延迟修复保留。前端和原生小程序本轮无业务改动。新文件不放进公共静态目录；访问IP为网络出口地址。遗留：不提供公开日志界面；未覆盖未经统一发布脚本执行的任意root命令，也无法还原启用前未记录的详细操作。
