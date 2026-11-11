# 公网防爬限制

2026-11-11：仅调整本项目Nginx外部入口，应用仍为0.11.2，不重启应用、不迁移或重新导入图鉴，不修改两个真实账号。原多美卡每48小时、高达每周日、宝可梦停用的自动采集安排保留。

## 已启用

- 已知搜索/批量爬虫标识直接403；正常Chrome、Safari、微信和搜狗浏览器保留。搜狗只匹配spider标识。
- robots.txt声明全站禁止抓取，HTTPS响应增加noindex/nofollow/noarchive。
- 使用真实连接IP分桶，忽略外部伪造的X-Forwarded-For：图鉴接口8次/秒、突发24；图片30次/秒、突发240；登录6次/分钟、突发5；总入口60次/秒、突发400；同时处理最多40个请求，超出返回429。
- 代理429提供10秒重试提示；上游已有Retry-After保持原值，避免重复或覆盖原登录保护。
- 健康检查/robots不占额度，HTTP ACME校验保留。内部采集及缓存预热直连8092，不经过这些公网规则，不做国家/地区封锁或固定IP白名单。
- 访问日志新增request_limit、connection_limit、known_crawler，保留IP、路径、状态及UA；不记录Cookie和密码。

标识和频率限制不能百分之百识别持有效账号、伪装成正常浏览器的低频采集。数据与缓存原图继续由现有登录鉴权保护，不将robots声明当成访问控制。

## 实际验证

`python3 /opt/dual-catalog/app/scripts/verify_crawler_defense.py`：退出0，终端节选`{"status": "pass", "checks": 17}`。使用实际同一Nginx镜像，临时仅监听127.0.0.1:18080/18443，哑上游承接全部压力请求，不向正式应用发送压力流量；5个限流/并发区均真实触发429，允许请求仍成功，伪造转发IP不能绕过，拒绝记录进入结构化日志。验证结束删除测试容器、关闭哑上游。首轮脚本因HTTPConnection不支持with语法退出，改用contextlib.closing后重新执行通过。

`python3 /opt/dual-catalog/app/scripts/prepare_crawler_defense.py`：先使用同镜像nginx -t，再备份、保留bind挂载inode热加载，语法/健康/权限/机器人检查失败恢复原配置。实际退出0，proxy_id_unchanged=true、plugins_unchanged=true、application_restart=false，配置SHA256为435388c2dd306f47c5c23a51996da3f2793aac9f9dd072132a6a231ee0648e73；备份为服务器backups/crawler-defense-20261111T135726/preview-nginx.conf。

使用独立临时QA账号，在真实可信HTTPS上依次运行：

- `node scripts/verify-private-auth.cjs`：34项通过，退出0，匿名/API/原图保护、登录改密、旧会话失效均保留。
- `node scripts/verify-gunpla.cjs`：原45项加正常浏览不被限流的检查，共46项通过，退出0，rateLimited=[]。
- `node scripts/verify-ui-regions.cjs`：原61项加正常地区浏览不被限流的检查，共62项通过，退出0，rateLimited=[]；多美卡与宝可梦的搜索/地区/滚动/刷新/详情返回及3像素位置标准保留。

临时账号已停用并精确删除，旧会话请求实际401；两个真实账号非会话指纹一致，临时明文凭证和会话文件删除，原用户私有凭证文件保留。后台应用与定时器未重启、缓存继续运行。

规则和验证边界参考官方[Nginx请求限流](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html)、[并发限制](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html)及[map](https://nginx.org/en/docs/http/ngx_http_map_module.html)。运行回执在私有artifacts/acceptance/crawler-defense-{shadow,deployment}.json，浏览器记录在同目录，不含账号口令。
