# 私有图鉴登录与单会话鉴权执行计划

**目标：** 仅服务器创建的账户可用图鉴，每账户只有一个有效会话，无注册入口。

**技术栈：** FastAPI、标准库scrypt/SQLite、现有PostgreSQL与Redis、原生JS/微信小程序、项目Nginx、Certbot。

**设计文档：** D:/poke&Tomy/spec/feature_20261111_F002_private-auth/spec-design.md

## 改动总览

Task 1建立独立认证数据库、服务端会话边界和服务器CLI；Task 2复用其协议接入网页、小程序与私有图片；Task 3准备HTTPS、初始账户和失败时保持关闭的发布门禁。图鉴数据库继续0004，Redis继续缓存资料与原图；每次读私有数据前实时校验会话，不能以缓存命中绕开认证。临时凭证、会话文件和证书都不进入源码包或GitHub。用户名peyro-gogogo，新登录替换旧会话，无注册入口。

执行依赖固定为：Task 1/2/3源码与本地测试完成 → Task 3安装关闭的代理门禁/TLS、准备目录与环境、构建镜像和预置账户 → deploy_release在实际发布镜像内禁网跑完整测试并发布 → 匿名边界确认后开门禁 → Task 2公网认证E2E导出同一会话并运行27/29/61回归 → Task 3最终CLI重置并交付。Task 2公网检查与Task 3最终重置由Task 4统一编排，各只执行一轮，不按Task编号提前运行。

---

### Task 0: 环境准备

**背景:** 当前工作区干净，Node v25.9.0、Python3.10虚拟环境、Playwright与Chrome可用；服务端Python3.12、项目代理80、443空闲且已允许，Certbot5.9.0隔离环境已安装。本Task仅记录已完成的环境准备，不新增实现。

**执行步骤：**
- [x] 阅读主应用、API缓存、预热、小程序请求及现有测试，确认登录当前不存在；确认首账户和单会话策略。
- [x] 检查scrypt与SQLite能力、项目代理挂载、443和Certbot工具，保持既有插件配置。

**检查步骤：**
- [x] 验证密码算法及SQLite，实际执行scrypt(n=32768,r=8,p=3,maxmem=64MiB)输出64字节，SQLite3.40.1。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -c "import hashlib,sqlite3; print(len(hashlib.scrypt(b'test',salt=b'0123456789abcdef',n=32768,r=8,p=3,maxmem=67108864)),sqlite3.sqlite_version)"`
  - 预期：64字节与SQLite版本，退出0；实际等价探测已执行，耗时0.167秒。
- [x] 验证Node和服务器证书工具。
  - `node --version`；服务端`/opt/dual-catalog/certbot-venv/bin/certbot --version`。
  - 预期：分别Node25.9.0和Certbot5.9.0，退出0；IP参数已从实际help确认。

---

### Task 1: 鉴权服务与管理命令

**背景:**
现有`create_app()`直接挂载图鉴路由和StaticFiles，`public_cached()`及原图端点先读Redis，均未校验用户。`warm_once()`通过回环HTTP访问详情和原图；原`/api/admin`已有独立Bearer鉴权。新增独立认证存储和外层鉴权，保护缓存命中与静态图片，保留图鉴数据库0004及旧管理鉴权。Task 2依赖本Task的登录/改密/会话接口；Task 3负责私有目录所有者、服务令牌、账户预置和代理剥离内部请求头。

**涉及文件:**
- 新建：`D:/poke&Tomy/backend/app/auth_store.py`、`D:/poke&Tomy/backend/app/auth.py`、`D:/poke&Tomy/backend/app/auth_cli.py`、`D:/poke&Tomy/backend/tests/test_auth.py`。
- 修改：`D:/poke&Tomy/backend/app/config.py`、`D:/poke&Tomy/backend/app/main.py`、`D:/poke&Tomy/backend/app/audit.py`、`D:/poke&Tomy/scripts/warm_cache.py`、`D:/poke&Tomy/scripts/verify_cache.py`、`D:/poke&Tomy/scripts/verify_tomica_snapshot.py`、`D:/poke&Tomy/scripts/prepare_logging.py`、`D:/poke&Tomy/scripts/view_logs.py`、`D:/poke&Tomy/backend/tests/test_api.py`、`D:/poke&Tomy/backend/tests/test_warm_cache.py`、`D:/poke&Tomy/backend/tests/test_audit.py`、`D:/poke&Tomy/.env.example`。

**执行步骤:**
- [x] 增加认证配置并固定客户端接口契约，保持默认私有。
  - 位置：`D:/poke&Tomy/backend/app/config.py:Settings`中`cache_namespace`后增加`auth_enabled=True`、`auth_store_path='artifacts/auth/accounts.sqlite3'`、`auth_cookie_secure=True`、`auth_session_seconds=43200`、`auth_service_token: SecretStr=SecretStr('')`；验证会话时长为正且不超过7天。相对存储路径基于`ROOT`解析，不能取启动终端当前目录。`.env.example`只列非真实配置和空内部令牌。
  - 接口：`POST /api/auth/login`接收`username/password`；`GET /api/auth/me`返回`auth_enabled/username/must_change_password/expires_at`；`POST /api/auth/password`接收`current_password/new_password`；`POST /api/auth/logout`返回`{ok:true}`。登录与改密成功沿用上述用户字段；web仅设置Cookie、不返回原始token，小程序仅返回`access_token`、不设置Cookie。请求存在Authorization时只使用严格Bearer凭证，错误Bearer不得回退Cookie；没有注册、账户创建、找回密码或账户枚举HTTP端点。用户名统一strip/lower后按`[a-z0-9][a-z0-9_-]{2,63}`校验；密码原样处理。
- [x] 在独立SQLite中实现密码哈希和原子单会话存储。
  - 位置：新建`D:/poke&Tomy/backend/app/auth_store.py`的`AuthStore`与`hash_password()/verify_password()`，该模块只依赖标准库、无HTTP导入；`auth.py`负责HTTP适配。每次操作使用短连接、`sqlite3.Row`、外键、`busy_timeout=5000`及WAL；初始化`accounts`（username唯一、password_hash、active_session_hash唯一、session_expires_at、must_change_password、disabled）和`login_limits`表。目录0700、数据库及WAL/SHM文件0600；创建路径与账户操作不连接PostgreSQL。所有写事务用try/except/finally提交或回滚并关闭连接，锁超时返回通用503而非成功/匿名降级。
  - `hash_password()`使用16字节随机盐、`hashlib.scrypt(n=32768,r=8,p=3,maxmem=64*1024*1024)`，编码算法参数/盐/摘要；`verify_password()`严格解析受支持参数，以`hmac.compare_digest`比较摘要。新密码允许Unicode，不strip密码，长度15–128；生成密码使用`secrets.token_urlsafe(18)`。未知账户走同成本虚拟哈希，错误与停用账户使用相同响应。
  - `AuthStore.login(username,password,client_ip)`先原子预留限流额度、验证密码，再`BEGIN IMMEDIATE`复读密码哈希及disabled；复读哈希必须与已验证版本一致，防止重置密码与登录竞态。生成`secrets.token_urlsafe(32)`，仅存SHA256摘要及固定绝对到期，替换当前session。并发成功登录仅最后提交的token有效；不在Redis或进程内缓存会话授权。
  - `authenticate(token)`每次按摘要查询且检查disabled/绝对到期；`logout(token)`只清除摘要仍匹配的行，旧会话退出不影响新会话。`change_password(token,current,new)`在写事务内重新验证当前session及密码版本，更新哈希、清除首次改密标志并轮换session；重置/停用直接清除session。限流按IP连续5次/5分钟及用户名20次/15分钟持久化，成功登录清理对应计数；超限429带Retry-After，计数预留与检查不能分开提交。
- [x] 在路由和缓存之前统一拦截身份，并挂载认证接口。
  - 位置：`D:/poke&Tomy/backend/app/auth.py:install_auth(app,settings)`注册认证router和认证中间件；`D:/poke&Tomy/backend/app/main.py:create_app()`在现有路由装配完成、返回app前调用。把存储放`app.state.auth_store`，同步SQLite/KDF操作通过`anyio.to_thread.run_sync`执行；KDF使用独立CapacityLimiter(2)，避免并发口令校验耗尽640MiB API容器或阻塞原图通道。
  - 公开精确路径为`/login/`、Task 2使用的登录CSS/JS、`/health/live`、`/health/ready`、`/api/auth/login`和安全退出处理；`/api/auth/me`、改密和`/account/`校验会话。其余`/preview`、JSON列表/详情、`/api/reference-images`、`/api/tomica-news/images`、`/preview/news-assets/`、背景图片、openapi/docs及未知私有页面均先鉴权。匿名页面302至`/login/?next=...`，匿名API/图片及私有JS/CSS等子资源401 JSON；next只允许本地`/preview/`导航目标，不接受协议相对URL/外站URL/控制字符。
  - 首次改密账户仅可访问账户页面、认证静态资源、me/password/logout；私有数据API与图片返回403 PASSWORD_CHANGE_REQUIRED，图鉴HTML跳转账户页面。web会话Cookie使用`__Host-catalog_session`，固定HttpOnly/Secure/SameSite=Lax/Path=/、无Domain，Max-Age取会话时长（默认12小时）；删除Cookie使用同名及同Path/Secure属性。认证与私有成功/错误/重定向/304响应均覆写`Cache-Control: private, no-store`；授权必须在Redis/ETag/StaticFiles读取之前完成。`auth_enabled=False`的隔离测试跳过外层保护，`/api/auth/me`返回auth_enabled=false，不提供可登录的绕过凭证；新认证单测及E2E必须显式保持开启。
  - 认证POST要求JSON、受支持的`X-Catalog-Client: web|miniprogram`，拒绝跨站Origin与Sec-Fetch-Site=cross-site；存在Origin时精确匹配可信scheme/host，web Cookie写操作要求同源Origin，原生小程序Bearer请求允许缺省Origin；客户端头不能豁免已有Origin/跨站检查。不启用跨源CORS。公网代理只接受固定IP Host并覆盖可信转发头，API仅绑定回环；输入体在读入前及流式累计均限4KiB，通用错误文案。中间件自身捕获AuthError并产生JSON/重定向，不能依赖内层FastAPI异常处理器捕获外层错误。
  - `/api/admin/`从用户会话中间件分支委派给其现有`require_admin()`独立管理Bearer验证，不能额外要求用户Cookie；禁止把内部服务令牌或普通用户会话当作管理Bearer。`/admin`静态页面仍属私有页面，公网二者继续由Task 3代理404隔离，以免破坏原内部管理调用。
- [x] 给回环缓存预热配置最小服务权限，不形成公开旁路。
  - 位置：`D:/poke&Tomy/backend/app/auth.py`内部服务校验；`D:/poke&Tomy/scripts/warm_cache.py:warm_once()`创建httpx.Client处；`D:/poke&Tomy/scripts/verify_cache.py:main()`与`D:/poke&Tomy/scripts/verify_tomica_snapshot.py:main()`的回环Client处。
  - 只有非空`AUTH_SERVICE_TOKEN`恒时匹配、实际可信客户端为loopback、GET/HEAD且规范化路径精确属于`/api/tomica`、filters/UUID详情、`/api/pokemon`、regions/数字详情、`/api/reference-images/UUID`时认可`X-Catalog-Service`；不做宽泛`/api/`前缀匹配。不允许/auth、/admin、账户页面、任意POST或普通公网客户端，客户端自报X-Forwarded-For不改变回环判定。Task 3在项目Nginx反代中覆盖该头为空，并覆盖X-Forwarded-For为真实remote_addr；Uvicorn仅信任本机代理转发头。服务请求返回相同鉴权后的no-store响应，原Redis/磁盘预热流程保留。
  - warmer及两个回环诊断脚本从Settings读取SecretStr并放Client默认header，令牌不进URL、错误文本、进度JSON或报告；base校验scheme=http、host为127.0.0.1/localhost/::1且无userinfo/片段，关闭重定向跟随，禁止将内部令牌发送给自定义外站或跳转目标。保留原2秒源站间隔、并发与中断恢复。
- [x] 增加SSH专用账号管理CLI和不含凭证的私有审计。
  - 位置：新建`D:/poke&Tomy/backend/app/auth_cli.py:main()`，子命令create-user/reset-password/disable-user/list-users，统一使用Settings和AuthStore。create/reset接受用户名、`--generate`和必需的`--output-file`，生成密码只写独占新建0600文件；禁止密码命令行参数及覆盖已有文件。stdout只输出username/动作/文件路径，list-users仅输出账号和状态，不输出密码哈希/session摘要。create重复用户名失败；reset替换临时密码、恢复可用状态、要求首次改密并撤销旧会话；disable立即失效。部署时用Task 3预置的10001用户与持久卷运行CLI。
  - 位置：`D:/poke&Tomy/backend/app/audit.py:CHANNELS`加入auth；主应用认证初始化仅配置auth通道，事件包括账户创建/重置/停用、登录成功/失败/替换、限流、退出、改密。只记username/client_ip/UA/事件及时间，不写密码、请求体、Cookie、Authorization或token。Task 3预建auth.jsonl为10001:10001/0600；`configure_audit`新建auth文件亦用0600。
  - 位置：`D:/poke&Tomy/scripts/prepare_logging.py:rotation()`在现有三个通道后追加auth规则，日轮转/5MiB/30份/create 0600 10001 10001；提取`prepare_log_files()`统一预建auth日志并赋正确所有者，`main()`复用。Task 3只调用`prepare_log_files()/rotation()`，不得调用会重装HTTP代理的现有`main()/proxy_logging()`覆盖TLS/门禁挂载。`D:/poke&Tomy/scripts/view_logs.py:main()`的kind choices加入auth，保留现有日志过滤、压缩历史和access汇总行为。
- [x] 为鉴权、账号CLI、预热边界和日志编写单元测试。
  - 测试文件：`D:/poke&Tomy/backend/tests/test_auth.py`，扩展`D:/poke&Tomy/backend/tests/test_warm_cache.py`和`D:/poke&Tomy/backend/tests/test_audit.py`；`D:/poke&Tomy/backend/tests/test_api.py`中现有两处create_app Settings显式`auth_enabled=False`，保留旧断言且不修改既有查询/缓存/管理预期。
  - 场景：随机盐与错误密码；双线程/双AuthStore实例并发登录后只有一个token有效；旧logout不能撤销新登录；过期/改密/重置/停用和重启恢复；首次改密不允许取列表/原图/新品静态图；匿名/伪造/跨站请求401/403；预先命中Redis或If-None-Match仍不绕授权；Cookie属性、Bearer不回退Cookie、小程序不设置Cookie及所有错误响应no-store；创建失败不泄露密码或覆盖文件；CLI stdout/日志不含秘密；限流原子性与SQLite锁超时失败关闭；管理Bearer可独立使用而用户/服务token不能管理；服务头非回环/错token/POST/管理路径均拒绝、伪造转发头不获授权、真正回环查询通过、预热仍写原图缓存。认证测试使用tmp_path隔离存储并保持auth_enabled=True。
  - 运行命令：`& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_auth.py D:/poke&Tomy/backend/tests/test_warm_cache.py D:/poke&Tomy/backend/tests/test_audit.py D:/poke&Tomy/backend/tests/test_api.py -q`
  - 预期：所有目标用例通过；Windows只保留现有POSIX日志轮转跳过，认证竞态用例不得跳过或放宽断言。

**检查步骤:**
- [x] 验证认证与旧API/预热/日志的目标回归。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_auth.py D:/poke&Tomy/backend/tests/test_warm_cache.py D:/poke&Tomy/backend/tests/test_audit.py D:/poke&Tomy/backend/tests/test_api.py -q`
  - 预期：退出0，记录真实通过/跳过数；所有认证、并发、缓存门禁和旧API断言通过。
- [x] 检查新增模块和入口可编译，CLI不要求数据库连接。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m py_compile D:/poke&Tomy/backend/app/auth_store.py D:/poke&Tomy/backend/app/auth.py D:/poke&Tomy/backend/app/auth_cli.py D:/poke&Tomy/backend/app/main.py D:/poke&Tomy/backend/app/config.py`
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m backend.app.auth_cli --help`
  - 预期：两条均退出0；CLI仅列SSH管理子命令、不打印配置或密码。

---

### Task 2: 网页与小程序登录集成

**背景:**
现有浏览器`request()`直接GET图鉴，页面启动立即`route()`；小程序`createApi()`仅GET且无凭证，图片组件直接请求URL，`page-factory.js`的Map跨页面保存列表。Task 1已提供统一会话接口，本Task只为这些现有入口接入登录、退出与失效处理，不重写图鉴分页/地区/详情逻辑。Task 3负责可信HTTPS、首次凭证和最终撤销测试会话。

**涉及文件:**
- 新建：`D:/poke&Tomy/backend/auth/index.html`、`D:/poke&Tomy/backend/auth/auth.css`、`D:/poke&Tomy/backend/auth/auth.js`、`D:/poke&Tomy/backend/preview/auth-client.js`。
- 新建：`D:/poke&Tomy/miniprogram/services/session.js`、`D:/poke&Tomy/miniprogram/services/private-images.js`、`D:/poke&Tomy/miniprogram/components/private-image/index.js`、`D:/poke&Tomy/miniprogram/components/private-image/index.wxml`、`D:/poke&Tomy/miniprogram/components/private-image/index.wxss`、`D:/poke&Tomy/miniprogram/components/private-image/index.json`、`D:/poke&Tomy/miniprogram/pages/login/index.js`、`D:/poke&Tomy/miniprogram/pages/login/index.wxml`、`D:/poke&Tomy/miniprogram/pages/login/index.wxss`、`D:/poke&Tomy/miniprogram/pages/login/index.json`、`D:/poke&Tomy/miniprogram/tests/auth.test.js`。
- 修改：`D:/poke&Tomy/backend/preview/index.html`、`D:/poke&Tomy/backend/preview/app.js`、`D:/poke&Tomy/backend/preview/theme.css`、`D:/poke&Tomy/miniprogram/services/api.js`、`D:/poke&Tomy/miniprogram/lib/page-factory.js`、`D:/poke&Tomy/miniprogram/app.js`、`D:/poke&Tomy/miniprogram/app.json`、`D:/poke&Tomy/miniprogram/app.wxss`、`D:/poke&Tomy/miniprogram/pages/tomica-list/index.wxml`、`D:/poke&Tomy/miniprogram/pages/pokemon-list/index.wxml`、`D:/poke&Tomy/miniprogram/pages/tomica-detail/index.wxml`、`D:/poke&Tomy/miniprogram/pages/pokemon-detail/index.wxml`、`D:/poke&Tomy/miniprogram/pages/pokemon-detail/extra.wxml`、`D:/poke&Tomy/miniprogram/tests/api.test.js`、`D:/poke&Tomy/miniprogram/tests/pages.test.js`。
- 新建：`D:/poke&Tomy/scripts/browser-auth.cjs`、`D:/poke&Tomy/scripts/verify-private-auth.cjs`；修改`D:/poke&Tomy/scripts/verify-ui-regions.cjs`、`D:/poke&Tomy/scripts/verify-both-catalog-refresh.cjs`、`D:/poke&Tomy/scripts/verify-tomica-display.cjs`。

**执行步骤:**
- [x] 增加独立登录/改密界面，与Task 1共享明确路径。
  - 位置：`D:/poke&Tomy/backend/auth/index.html`放账号密码表单、改密表单和aria-live反馈；`auth.css`沿用Little Atlas圆角/渐变，`auth.js`处理提交，不添加注册、找回或创建账号入口。Task 1的`/login/`与受保护`/account/`返回该HTML；公开资源固定`/auth-assets/auth.css`和`/auth-assets/auth.js`，不可公开整个backend目录。
  - `auth.js`使用`fetch('/api/auth/login'|'password'|'logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Catalog-Client':'web'},body:JSON.stringify(...)})`。表单pending时禁用提交，密码不trim、不进入URL/console/storage；新密码15–128、确认一致。登录与me读取`auth_enabled/username/must_change_password/expires_at`；首次改密跳/account/，改密成功由HttpOnly Cookie自动接收新会话。next仅允许同源`/preview/`路径/query/hash，默认/preview/，拒绝协议相对地址、反斜杠、外站和控制字符。
- [x] 接入网页会话状态与退出，保留原导航恢复。
  - 位置：新增`D:/poke&Tomy/backend/preview/auth-client.js`，暴露`window.CatalogAuth`的`ready/check/expire/logout`；`index.html`在`app.js`之前加载该脚本，在原header增加用户名、修改密码及退出控件；仅补充控件样式，不更换现有图标/卡片布局。
  - `auth-client.js`启动GET /api/auth/me，每10秒检查一次，visibilitychange回到前台立即检查，pagehide停止定时器。401统一跳/login/，403 PASSWORD_CHANGE_REQUIRED跳/account/，保留当前pathname/search/hash为next；重复失效仅导航一次。auth_enabled=false只用于隔离开发环境，隐藏账户控件并停止心跳；生产无匿名前端开关。
  - 位置：`D:/poke&Tomy/backend/preview/app.js:request()`保留原status错误并增加code；401/首次改密调用CatalogAuth失效处理。末尾启动在CatalogAuth.ready之后运行原route()，不更改rememberCatalogList/readCatalogList、详情返回、地区筛选和哨兵逻辑。正常注销POST成功后离开私有页面；网络失败显示可重试状态，不能宣称服务器会话已退出。
- [x] 为小程序增加会话生命周期与认证接口，维护既有请求契约。
  - 位置：`D:/poke&Tomy/miniprogram/services/session.js`统一保存/读取/清除本机`dual-catalog:session:v1`（access_token/username/expires_at/must_change_password），维护内存generation和订阅通知；清理/更换session时递增generation。`app.js`在onShow立即me并启动10秒检查、onHide停止；无会话进入登录页，401清除会话后只reLaunch一次。
  - 位置：`D:/poke&Tomy/miniprogram/services/api.js:createApi()`保留get/list/detail/filters/regions、query编码和abort行为；新增POST login/changePassword/logout及GET me。每次请求动态取当前token，加Authorization:Bearer，仅认证POST加X-Catalog-Client:miniprogram和JSON；无token的请求不捏造凭证。401触发统一清理/导航，403 PASSWORD_CHANGE_REQUIRED进入登录页改密模式；409仍交给catalog-state原逻辑。原无存储测试mock继续由模拟HTTP响应决定结果，不把生产服务改成匿名。
  - 位置：新增`D:/poke&Tomy/miniprogram/pages/login`四文件，`app.json`将登录页加入pages首项。页面支持账号密码登录和首次/主动改密，使用Task 1字段，失败显示统一消息，成功保存新token并进入原图鉴tab；当前密码/新密码只留页面内存。既有列表页提供用户名/改密/退出入口，由共同page-factory方法调用认证API，不增加注册入口。
- [x] 将私有图片请求封装在组件中，不修改原资料映射。
  - 位置：`D:/poke&Tomy/miniprogram/services/private-images.js`实现`loadPrivateImage(wxApi,baseUrl,url)`：同源受保护URL经wx.downloadFile加Authorization，检查200后返回tempFilePath；第三方URL原样显示且绝不带凭证，本地临时路径直接返回。按会话generation+URL去重、全局最多3个在途下载；新会话/退出清空下载映射，迟到结果不得回填旧组件或变成新会话缓存，401走统一失效处理。token不写URL、日志或data属性。
  - 位置：新增private-image组件，以src/mode属性观察器触发下载，内部image使用本地路径；序列号隔离迟到结果，detached后不setData，错误triggerEvent('error')，点击保留原bindtap/dataset行为。`app.json:usingComponents`全局注册，四图鉴WXML及extra.wxml替换原image标签；`app.wxss`原image尺寸选择器增加private-image，组件host/内部图片宽高覆盖原固定图片容器，保持aspectFit与现有样式。
  - 位置：`D:/poke&Tomy/miniprogram/lib/page-factory.js:createDetailPage().previewImage()`先用共享下载器解析当前图片及去重图库本地路径，再wx.previewImage；异色/形态仍由原prepareExtra/imageUrl映射提供src。仅有效组件渲染的图下载，不在列表响应中等待所有原图下载。
- [x] 清除被撤销会话的列表与详情状态，避免旧缓存回填。
  - 位置：`D:/poke&Tomy/miniprogram/lib/page-factory.js`模块Map订阅session变更后clear；每页onLoad捕获generation，onHide/onUnload仅允许同generation保存快照。会话清除时dispose原CatalogState以递增请求sequence，迟到列表/详情/图片结果不写回。有效会话内仍使用原kind缓存、过滤/位置恢复、分页与详情打开方式；旧会话onHide不得把已清除快照重新塞回新会话。
- [x] 给真实浏览器验收接入同一私有会话，不削弱历史断言。
  - 位置：新建`D:/poke&Tomy/scripts/browser-auth.cjs`，从`CATALOG_AUTH_STATE`所指Git忽略的storageState JSON读取Cookie，为browser.newContext/browser.newPage选项提供storageState；给node fetch生成仅匹配PREVIEW_URL origin/path/secure/有效期的Cookie头。没有环境路径的现有本地无鉴权测试保持原行为；不把Cookie打印或写进普通报告。
  - 三个既有脚本默认生产入口改为https://117.72.11.77，使用该helper初始化上下文；verify-ui-regions.cjs逐地区node fetch也带同一Cookie，其余page.request由context共享Cookie。--local覆盖名单加入auth-client.js，保持原27/29/61项断言、3像素阈值及真实滚动动作，不给验收脚本开放服务器绕过后门。
  - 位置：新增`D:/poke&Tomy/scripts/verify-private-auth.cjs`，从`CATALOG_AUTH_CREDENTIALS`私有JSON读取username/password，不打印密码；真实桌面与WebKit手机覆盖无注册、匿名HTML/API/原图/新品图被挡、错误密码、首次改密、Cookie属性、登录成功、A/B新登录取代旧会话、A旧logout不影响B、改密/注销及返回目标。两个profile顺序执行且每次改密后即时更新同一私有凭证文件；过期使用后端可控时钟单测，公网验证绝对expires_at与重置撤销，不等待12小时或降低生产会话时长。退出验证完成后重新登录，最后导出最新有效B会话storageState供历史回归；报告只含检查名称/结果，截图只显示清空密码后的登录UI。
  - 验收顺序固定为auth E2E→共享同一token运行历史27/29/61→Task 3最终CLI重置新临时密码并撤销所有测试会话。不同测试上下文共享已导出的同一逻辑会话，不在每个脚本重新登录互相踢出；不关闭HTTPS证书校验。
- [x] 为客户端鉴权核心行为编写单元测试，并保留原测试断言。
  - 测试文件：`D:/poke&Tomy/miniprogram/tests/auth.test.js`，扩展`D:/poke&Tomy/miniprogram/tests/api.test.js`和`D:/poke&Tomy/miniprogram/tests/pages.test.js`。
  - 测试场景：Bearer动态注入与POST客户端头；401清理/单次跳转；首次改密与轮换token；同源图片头、第三方无凭证、并发3/去重/下载错误；旧generation的下载/列表/详情及onHide不能回填；退出网络失败不伪装成功；原图preview使用去重本地路径。原query编码、abort、409重取、地区/搜索/位置、原图/异色测试继续保留。
  - 运行命令：`node --test D:/poke&Tomy/miniprogram/tests/*.test.js`
  - 预期：新增与原20项用例均通过；不使用微信真机或mock数据冒充公网认证验收。

**检查步骤:**
- [x] 检查浏览器脚本语法与小程序核心逻辑。
  - `node --check D:/poke&Tomy/backend/auth/auth.js`
  - `node --check D:/poke&Tomy/backend/preview/auth-client.js`
  - `node --check D:/poke&Tomy/backend/preview/app.js`
  - `node --check D:/poke&Tomy/scripts/verify-private-auth.cjs`
  - `node --test D:/poke&Tomy/miniprogram/tests/*.test.js`
  - 预期：全部退出0；已有与新增Node测试通过。
- [x] 验证真实登录与单会话替换，输出私有回归会话。
  - 前置：Task 1/3已启动HTTPS服务并预置首账户，私有凭证JSON和storageState路径已通过环境变量CATALOG_AUTH_CREDENTIALS/CATALOG_AUTH_STATE指定。
  - `node D:/poke&Tomy/scripts/verify-private-auth.cjs`
  - 预期：退出0，桌面与手机模拟检查均pass；B登录后A接口401、A旧退出不影响B；强制改密/退出可用、无注册入口、输出报告不含密码/token。
- [x] 在已导出的同一会话下运行历史图鉴回归。
  - `node D:/poke&Tomy/scripts/verify-tomica-display.cjs`
  - `node D:/poke&Tomy/scripts/verify-both-catalog-refresh.cjs`
  - `node D:/poke&Tomy/scripts/verify-ui-regions.cjs`
  - 预期：各退出0，保留27/29/61项历史断言通过，分别保存报告；已授权图片放大、刷新/关闭恢复及全国分段无回归。

---

### Task 3: HTTPS与安全发布

**背景:**
项目代理只监听80，443已空闲且UFW允许；`/opt/dual-catalog/certbot-venv/bin/certbot`已安装5.9.0并支持IP证书。Task 1/2提供鉴权与客户端，本Task配置本项目HTTPS、私有运行数据和首账户。旧0.9.2无鉴权，首次发布失败回滚时必须保持私有入口关闭，不能重新匿名公开。

**涉及文件:**
- 新建：`D:/poke&Tomy/scripts/prepare_auth.py`、`D:/poke&Tomy/scripts/renew_tls.py`、`D:/poke&Tomy/backend/tests/test_auth_deploy.py`、`D:/poke&Tomy/docs/auth.md`。
- 修改：`D:/poke&Tomy/deploy/preview-nginx.conf`、`D:/poke&Tomy/Dockerfile.release`、`D:/poke&Tomy/scripts/deploy_release.py`、`D:/poke&Tomy/CHANGELOG.md`、`D:/poke&Tomy/docs/deployment.md`。

**执行步骤:**
- [x] 创建可重复执行的项目准备工具，先保存可回滚快照。
  - 位置：`D:/poke&Tomy/scripts/prepare_auth.py:main()`提供`tls`、`accounts`、`gate`、`finalize`子命令；根目录固定`/opt/dual-catalog`，记录原项目代理镜像/挂载、三插件容器ID、两份环境配置与代理文件的0600备份。仅操作`dual-catalog-preview-proxy`及本项目目录，所有命令用参数列表，输出不含配置值、密码或Cookie。`tls`先创建0755 gates目录和0644 maintenance flag，再安装第一份含门禁的挑战配置；一旦安装门禁，失败恢复只能恢复含门禁配置或停止项目代理，原始无门禁备份仅留作人工恢复材料。
- [x] 为项目代理配置ACME挑战并签发可信IP证书。
  - 位置：`prepare_auth.py:prepare_tls()`创建`/opt/dual-catalog/tls/{webroot,config,work,logs}`，仅把webroot、`config/live`、`config/archive`及gates子目录只读挂载项目代理；live/archive在容器内保持`/etc/letsencrypt/live`与`/etc/letsencrypt/archive`相对结构，证书软链接续签后仍有效。禁止挂载整个config或ACME accounts账户密钥。第一份HTTP挑战配置仅开放ACME和健康，其余返回503；离线测试候选配置及完整挂载后再重建项目代理。Certbot使用`certonly --webroot --webroot-path /opt/dual-catalog/tls/webroot --ip-address 117.72.11.77 --preferred-profile shortlived --cert-name 117.72.11.77 --config-dir /opt/dual-catalog/tls/config --work-dir /opt/dual-catalog/tls/work --logs-dir /opt/dual-catalog/tls/logs --non-interactive --agree-tos --register-unsafely-without-email`，先加`--dry-run`验证挑战，再执行正式签发；证书私钥及ACME账户不进入源码包。
- [x] 安装HTTPS代理和首轮发布门禁，防止旧镜像回滚公开数据。
  - 位置：`D:/poke&Tomy/deploy/preview-nginx.conf`中80只公开`/.well-known/acme-challenge/`，其他请求308至固定`https://117.72.11.77$request_uri`；443加载IP证书并反代127.0.0.1:8092。有效Host固定117.72.11.77，其他Host拒绝；`/api/auth/`只放行GET/HEAD/POST且限制请求体4KiB，其余继续GET/HEAD；精确/admin、/api/admin及其子路径均404，覆盖X-Forwarded-Proto/X-Forwarded-For并清空X-Catalog-Service。
  - `prepare_auth.py:set_gate()`由`gate --mode closed|open`创建/移除`/opt/dual-catalog/tls/gates/maintenance`，非敏感gates目录0755、flag0644，让nginx worker能够stat；只读挂载到代理`/var/run/dual-catalog-gates`。HTTPS默认location和/api/auth/以该文件存在时return503，health和ACME单独location保持可用。首次发布前closed；open先直连8092/8093确认匿名401 AUTH_REQUIRED、网页303至/login/、0004健康、实际监听仅回环及生产CLI唯一peyro-gogogo存在，再移除flag。发布失败维持flag，不能恢复无gate旧配置。
  - `prepare_tls()`写配置前先以临时候选文件及相同证书/gate/log挂载离线`nginx -t`；当前`/opt/dual-catalog/preview-nginx.conf`是单文件bind mount，最终必须对同一文件inode调用`write_text()`/flush/fsync，再容器内`nginx -t`和reload，禁止os.replace/rename覆盖该路径。失败用同inode写回上一份含门禁配置并测试/reload，防止容器继续读取旧inode；不以HTTP明文登录或关闭证书验证收尾。
- [x] 配置证书自动续签及安全reload。
  - 位置：`D:/poke&Tomy/scripts/renew_tls.py:main()`调用同一隔离Certbot与目录执行`renew`，`--dry-run`传给Certbot；成功后只对项目代理执行`nginx -t`和`nginx -s reload`，错误返回非零并保留旧证书。`prepare_tls()`写入独立`dual-catalog-cert-renew.service/timer`，每12小时运行、Persistent=true；不更改其他证书服务或插件。
- [x] 准备持久鉴权目录、内部令牌和唯一首账户，再发布0.10.0。
  - 位置：`prepare_auth.py:prepare_accounts()`为生产`data/artifacts/auth`、演示`demo/artifacts/auth`及auth.jsonl设置10001所有者、目录0700/日志0600（轮转create 0600继承原10001所有者）；两份.env仅追加AUTH_ENABLED=true、AUTH_COOKIE_SECURE=true、AUTH_STORE_PATH与各自随机AUTH_SERVICE_TOKEN，权限0600并保留其他键。运行Task 1日志轮转生成器，保留既有access/collection/deploy规则。
  - `Dockerfile.release`镜像label更新0.10.0，新增prepare_auth.py/renew_tls.py复制项；`deploy_release.py`的审计摘要加入auth模块并同步`backend/tests/test_audit.py`现有文件哈希夹具，0004健康约束不变。`deploy_release.main()`开始要求maintenance flag存在，失败/回滚始终维持closed且不自动open；在其真实build/check_image之后、修改APP_IMAGE和启动服务之前，用Task 4禁网命令测试该实际发布镜像，失败不发布。限定源码包排除.env、artifacts、依赖缓存、.git、证书和密钥；先以相同限定源码构建新镜像，再以10001用户及生产持久卷运行`python -m backend.app.auth_cli create-user peyro-gogogo --generate --output-file /app/artifacts/auth/login-bootstrap.json`，预置后再运行既有发布脚本；重复accounts不得重置已有账户。
  - CLI写私有username/password JSON，stdout只给路径；通过已授权SSH/SFTP下载到本地`D:/poke&Tomy/artifacts/private/catalog-login.json`，只比较两端SHA256及本地username/密码长度，不打印内容；完整下载并核对一致后删除服务器明文文件。下载失败保留服务器0600文件供重试，不提前删除。两份.env明确API_BIND=127.0.0.1、AUTH_STORE_PATH=/app/artifacts/auth/accounts.sqlite3；生产与demo分别持久化、使用不同服务令牌，demo无用户时保持拒绝访问。
  - 门禁closed后执行`python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.10.0 --reason '私有账号登录、单会话与HTTPS'`；双API与预热健康、匿名401检查通过后gate open。保存独立发布回执；无图鉴迁移/导入，三插件ID保持原值。
- [x] 在全部公网认证与历史回归后交付全新临时凭证。
  - 位置：`prepare_auth.py:finalize_account()`通过新镜像CLI reset-password为peyro-gogogo生成新私有JSON、强制首次改密并撤销测试session；服务器子命令只生成与报告文件路径，SSH调用方下载并比较SHA256、核对本地username/长度后再SSH删除服务器明文副本。用旧storageState验证401后删除测试storageState及独立测试密码副本，保留最终本地catalog-login.json，生产list-users仅含peyro-gogogo。最终密码不再登录验收，确保交付凭证尚未使用。文档`docs/auth.md`记录创建/重置/停用、单会话、12小时到期、证书续签/恢复及私有文件路径，CHANGELOG只写核心行为；交付HTTPS链接和未填密码的登录截图，不宣称微信真机发布。
- [x] 为部署安全边界编写不接触生产环境的单元测试。
  - 测试文件：`D:/poke&Tomy/backend/tests/test_auth_deploy.py`，扩展`D:/poke&Tomy/backend/tests/test_audit.py`发布夹具；以临时目录和模拟subprocess验证限定路径/容器、代理配置检查失败回滚、同inode写入、只mount live/archive而非accounts、gates0755/flag0644、证书未就绪不开放、旧镜像匿名200时门禁拒绝open、发布失败保持closed、私有文件0600且输出无秘密、下载摘要匹配后才删除明文、续签失败不reload、成功只reload项目代理及timer命令。
  - 运行命令：`& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_auth_deploy.py -q`；预期：退出0，全部安全边界通过，不连接服务器或申请证书。

**检查步骤:**
- [x] 验证脚本入口、部署单测及可信公网TLS。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_auth_deploy.py -q`；`python3 /opt/dual-catalog/app/scripts/prepare_auth.py tls`；`curl -fsS https://117.72.11.77/health/ready`。
  - 预期：分别退出0，正式证书链受信任、IP SAN正确、健康ready；HTTP GET跳转HTTPS，不使用-k或ignoreHTTPSErrors。
- [x] 验证续签、门禁与最终凭证交付边界。
  - `python3 /opt/dual-catalog/app/scripts/renew_tls.py --dry-run`；`systemctl is-active dual-catalog-cert-renew.timer`；`python3 /opt/dual-catalog/app/scripts/prepare_auth.py gate --mode open`。
  - 预期：退出0、timer active，匿名API仍401；Task 2认证E2E及27/29/61项回归完成后执行`prepare_auth.py finalize`，新临时密码可在私有文件读取、旧storageState请求401、无服务器明文凭证残留。

---

### Task 4: 整体验收与交付

**背景：** 完成三个功能Task后，先验证工作区完整套件，再在门禁关闭状态部署；认证E2E与历史回归使用相同有效session，最终重置临时密码。

**执行步骤：**
- [x] 记录完整测试、发布回执、TLS、真实认证及历史回归结果到`D:/poke&Tomy/spec/feature_20261111_F002_private-auth/acceptance.md`，记录真实退出码、边界和遗留，不打印或提交密码/token。
- [x] 向服务器上传限定源码，按Task 3先TLS/门禁、镜像/账户、发布/匿名拦截、开门禁、认证和历史回归、最后重置凭证的顺序执行；停止本轮测试进程与SSH会话后交付。

**检查步骤：**
- [x] 首先运行完整Python和Node测试。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest -q`
  - `node --test D:/poke&Tomy/miniprogram/tests/*.test.js`
  - 预期：各退出0，保留原有与新增鉴权用例；失败回对应Task1/2/3，不继续发布。
- [x] 在不可变发布镜像内运行禁网完整后端测试。
  - 服务端`docker run --rm --network none --memory 384m --pids-limit 128 -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python dual-catalog:0.10.0 -m pytest -q -p no:cacheprovider`；由Task 3发布脚本在真实构建后、首次启动前执行，记录镜像ID与退出码，本检查引用同一回执不另建或重跑镜像。
  - 预期：退出0，无生产库或外站连接，POSIX日志轮转通过；失败回Task1或镜像内容检查。
- [x] 执行真实TLS、认证和历史浏览器验收。
  - `node D:/poke&Tomy/scripts/verify-private-auth.cjs`
  - `node D:/poke&Tomy/scripts/verify-tomica-display.cjs`
  - `node D:/poke&Tomy/scripts/verify-both-catalog-refresh.cjs`
  - `node D:/poke&Tomy/scripts/verify-ui-regions.cjs`
  - 预期：各退出0；认证覆盖未登录、首次改密、A/B会话替换、旧退出、绝对到期字段、注销、静态原图及注册缺失；实际过期另由Task 1可控时钟单测证明。历史27/29/61分别通过，无证书验证绕过或弱化断言。
- [x] 重置最终临时凭证、核对运维与源码交付。
  - 服务端`python3 /opt/dual-catalog/app/scripts/prepare_auth.py finalize`；`systemctl is-active dual-catalog-cert-renew.timer dual-catalog-redis`。
  - 本地读取私有JSON只核对username=peyro-gogogo、密码长度≥15，不将密码打印；用旧storageState请求需401。
  - 预期：唯一首账户存在、最终会话已撤销、两API0004健康、预热正常、原插件不变、续签timer active，私有文件与HTTPS链接可交付；仅任务源码、规范和无秘密配置示例同步GitHub。
