# 私有图鉴登录与单会话鉴权

2026-11-11。目标版本0.10.0。用户要求仅自己的账号登录、不允许同时登录、无注册入口、仅本人创建账号。已确认首个用户名`peyro-gogogo`，密码由系统生成，首次登录修改；新登录生效，旧会话立即失效。沿用本会话直接实现、验证、服务器部署和GitHub同步授权。

## 访问与会话

FastAPI统一保护两类图鉴、详情、图片与新品静态资源，不能只在浏览器隐藏页面。未登录访问页面跳转/login/，API与图片返回401；已认证但需改临时密码只允许账户相关操作，其余返回403 PASSWORD_CHANGE_REQUIRED。登录/改密/退出采用POST JSON和X-Catalog-Client请求头，校验跨站Origin；没有注册或远程创建账户接口。

认证默认开启，旧功能测试显式关闭认证；生产/演示均启用。仅/login/和公开登录静态资源、health、登录/退出处理公开。原/api/admin保留已有管理Bearer校验，公网仍由项目代理404隔离。缓存服务、采集与管理员命令属于服务器内部权限，不向网页提供内部服务令牌。

认证数据使用本项目持久化artifacts/auth/accounts.sqlite3，独立SQLite事务存储用户名、scrypt密码哈希、唯一当前session摘要、12小时绝对到期、首次改密标志及失败限流计数。不用可被Redis LRU淘汰的会话键，不变更现有0004图鉴数据库。scrypt参数N=32768/r=8/p=3、随机盐；存储随机256位session的SHA256摘要。事务替换session，所有后续请求实时校验；旧会话退出不得撤销新会话，改密/重置/停用立即撤销旧会话。失败消息不透露账户是否存在，IP及用户名限流、登录事件记入私有auth日志，不记录密码或token。

浏览器用HttpOnly、Secure、SameSite=Lax Cookie，不存localStorage token；12小时失效。页面提供用户名、修改密码和退出；401或首次改密跳转保留图鉴导航目标，10秒会话检查使旧页回到登录页。登录后延续原地区/搜索/年份/分页与位置恢复。私有页面、API及图片响应private/no-store，Redis/磁盘原图缓存继续工作。

小程序新增登录/首次改密页面，以同一会话规则使用Bearer；凭证保存本机存储，401清理页面缓存并回登录，触顶/详情行为继续。新增private-image组件包装原image，受保护图片通过wx.downloadFile携带鉴权头获得本地临时路径，统一限流并复用下载结果；原图查看器也先下载再previewImage。不把完整会话token放在图片URL，不向第三方图源发送凭证。头像/原图/版本与异色比较继续可用；没有AppID和正式合法域名，保持不宣称已在微信真机发布。

## 账号管理与内部预热

新增`python -m backend.app.auth_cli create-user USERNAME --generate --output-file PATH`、reset-password、disable-user及list-users。账号创建仅在SSH服务器命令中执行，无网页管理入口。生成的临时密码只写0600文件，下载至本地被Git忽略的私有artifacts目录并移除服务器明文副本，不写入源码、运行日志或GitHub。首个账号必须部署前创建，最终交付重新生成未登录的临时凭证，已测试旧会话全部撤销。

内部cache-warmer访问鉴权API使用随机AUTH_SERVICE_TOKEN，仅回环GET及指定图鉴/原图API认可；Nginx删除客户端传入的内部令牌头。服务令牌不允许登录、用户管理或POST操作。API和预热角色私有环境变量保持0600。auth.jsonl纳入已有轮转与view_logs查询。

## HTTPS与部署

现站仅HTTP，已实查项目专属代理占80、443空闲、UFW已允许443。使用Let's Encrypt正式IP证书（Certbot>=5.4、webroot、shortlived），仅修改本项目dual-catalog-preview-proxy：挂载本项目ACME与证书目录，80保留HTTP-01挑战，其余跳转https://117.72.11.77；443终止TLS并反代回环8092，仅/auth允许所需POST，原管理端口隔离不变。独立systemd timer每12小时续签并安全reload项目代理；先完成可核验HTTPS，再启用Secure Cookie鉴权，不接受关闭证书校验的公网验收。

新增项目部署准备脚本处理私有auth文件目录、服务令牌、账号、代理备份/配置测试/可回滚重建和证书定时器；保留既有采集、缓存与其他插件。首次不更改目录数据库、车型或照片。发布沿用带审计的deploy_release.py及0004健康回执。未得到有效证书不交付HTTP明文登录。

## 验收

完整Python与Node测试；新单测覆盖口令哈希、并发登录唯一有效、旧退出不影响新会话、到期/改密/停用、失败限流、CSRF、首次改密、所有入口与图片的未授权访问、内部预热权限及缓存不能绕鉴权。真实桌面与WebKit手机双浏览器登录交替测试，证明第二次登录后旧请求401；无注册入口、密码修改与退出可用。历史27/29/61项浏览器脚本通过私有storageState和服务鉴权适配运行，保留原断言。公网HTTPS链验证、HTTP跳转、证书续签dry-run、代理/日志、双API与预热健康。最终只留peyro-gogogo首账户，交付新临时密码私有文件、HTTPS链接、截图、测试原始结果与GitHub提交。

依据：OWASP Session Management与Password Storage Cheat Sheet；Let's Encrypt 2026-03-11 IP证书说明；微信官方api-typings DownloadFileOption.header。
