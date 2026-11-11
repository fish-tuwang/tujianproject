# 私有登录验收（0.10.0）

本轮范围：用户指定的唯一首账户 `peyro-gogogo`、无注册入口、服务器管理账户、新登录替换旧会话、首次强制改密，以及与其配套的HTTPS、图片鉴权和发布。图鉴库维持0004，不迁移或重新导入；已有地区编号、原图映射、搜索、分页和返回位置契约保留。

## 已执行终端证据

- 工作区 `D:/poke&Tomy`，`.venv/Scripts/python.exe -m pytest -q --tb=short`：`172 passed, 1 skipped, 9 warnings in 33.62s`，退出0。Windows跳过POSIX打开文件重命名的日志轮转用例；9项为Starlette/Alembic弃用提示。
- `node --test miniprogram/tests/*.test.js`：`tests 28 / pass 28 / fail 0`，退出0；包含旧分页、详情、地区、原图及新增会话和私有下载行为。
- 修改轮转配置后，`.venv/Scripts/python.exe -m pytest backend/tests/test_auth_deploy.py backend/tests/test_audit.py -q --tb=short`：`14 passed, 1 skipped in 1.83s`，退出0。
- 35个新增/修改Python与JS文件实际执行py_compile或node --check，`SYNTAX_CHECK_PASS 35`，退出0。
- 隔离本地SQLite与1张合成图片运行 `node scripts/verify-private-auth.cjs`：桌面Chrome、手机WebKit共34项通过，退出0。只证明认证交互，不用于证明真实图鉴或公网；结果保留本地 `artifacts/acceptance/private-auth-local.json`。
- 发布脚本在其真实构建的0.10.0镜像内执行 `docker run --rm --network none --memory 384m --pids-limit 128 -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python dual-catalog:0.10.0 -m pytest -q -p no:cacheprovider`：`173 passed, 9 warnings in 62.62s (0:01:02)`。镜像内Linux轮转用例通过，无生产数据卷或环境配置注入测试。

## 定位并修正的验证问题

- 发布哈希新增认证模块后，旧发布失败测试夹具缺文件；补齐相同模块文件，原回滚断言保留。
- WebKit本地HTTP的Cookie枚举将SameSite显示为None；验收改为读取真实Set-Cookie的SameSite=Lax，同时检查浏览器Cookie的HttpOnly和公网Secure，不放宽传输保护。
- 服务器logrotate把裸数字10001当用户名，拒绝轮转配置；改成create 0600继承日志原有所有者，未创建额外系统账户，服务器四类日志配置检查通过。依据[logrotate官方手册](https://github.com/logrotate/logrotate/blob/main/logrotate.8.in)的create属性继承规则。

## 公网与交付

HTTPS正式IP证书已签发（到期2026-11-18），HTTP返回308，可信HTTPS健康ready；发布期间私有路径503门禁实际生效。证书检查不使用-k或ignoreHTTPSErrors。`python3 /opt/dual-catalog/app/scripts/renew_tls.py --dry-run`实际输出`Congratulations, all simulated renewals succeeded`，随后nginx配置检查及本项目reload成功，REMOTE_EXIT=0。Certbot演练包含约445秒默认随机延迟，未跳过挑战。

真实发布命令为 `python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.10.0 --reason 'Private owner login, one active session, HTTPS'`，REMOTE_EXIT=0。operation_id为`a9e667eb60194fe0a54b0be24a6685b0`；实际发布镜像`sha256:f7801d96cf91aeb211632d52b06fafda899d337d835d6989ca32a21316e94e8b`。两套API保持0004健康，无图鉴迁移/导入，原三个插件容器ID不变。

使用可信公网HTTPS、真实资料和同一个导出的会话分别执行：

- `node scripts/verify-private-auth.cjs`：`{"status":"pass","checks":34,"profiles":[{"name":"desktop","status":"pass"},{"name":"mobile","status":"pass"}]}`，退出0。
- `node scripts/verify-tomica-display.cjs`：`status=pass, assertions=27, errors=[]`，退出0；Mark X多种名称、原图、放大、5列20条、图标与关闭按钮居中保留。
- `node scripts/verify-both-catalog-refresh.cjs`：最终完整运行`status=pass, assertions=29, errors=[]`，退出0；年份、40条/第二页、月刊迟到、两图鉴筛选隔离、108条进度及详情刷新返回保留。
- `node scripts/verify-ui-regions.cjs`：`status=pass, checks=61`，退出0；11个Wiki全国编号分类覆盖1025种且每种一次、自动续页、地区/属性/搜索组合及主题保留。

首次三组并行运行时，WebKit在40条页面刷新出现一次3524→907的滚动偏移，归因尚未确认，未将其声称为旧缺陷或已修复。保留3像素阈值后，单独手机14项及完整29项重跑均通过；额外将认证状态请求延迟750毫秒，5轮手机刷新均3524→3524。没有修改旧滚动逻辑、反转断言或隐去首次失败。探测原始结果保留于私有artifacts/acceptance/auth-scroll-probe.json。

服务器执行独立运维脚本最终18项通过、REMOTE_EXIT=0：可信证书IP SAN、HTTP跳转、双API匿名401、内部预热可用/公网服务头无旁路、管理路径404、三个定时/缓存服务active、六个项目进程0.10.0且重启0/OOM=false、原插件ID不变、账户及日志0600/UID10001、独立真实logrotate保留所有者与权限、唯一owner及首次改密、测试会话为空、服务器明文凭证不存在。回执为私有artifacts/acceptance/private-auth-operations.json。预热已恢复，17718条详情就绪、30674/30723张原图就绪；49张未成功，不将其计为全部图片完成，本轮未改变图源映射。

账户数据库独立持久化，密码仅为scrypt摘要、会话仅为SHA256摘要；Redis缓存不代替鉴权。初次及最终私有凭证均SFTP下载并比对SHA256后删除服务器明文。最终执行`prepare_auth.py finalize`成功；旧会话分别请求me、Tomica、Pokémon均401，最终凭证未再用于登录。交付文件`D:/poke&Tomy/artifacts/private/catalog-login.json`仅本机当前用户拥有ACL权限，Git忽略。实际auth日志13条生命周期事件存在，扫描未含最终密码、测试会话或密码/令牌字段。测试会话、临时日志副本和本地测试凭证已删除，本地测试服务已停止；保留隔离的合成数据库与日志供复核。

执行相对计划的调整：三插件ID在发布器与最终运维核对，不在环境快照中重复保存；轮转以create 0600继承10001所有者，独立真实轮转已验证。HTTPS/门禁绑定文件使用同inode写入，保留现有项目代理原镜像与停止的回退容器；回退不重新公开匿名入口。

微信AppID和正式HTTPS域名尚未提供，原生小程序验证限Node逻辑测试与源代码；未进行微信真机或正式发布。

## 2026-11-11 管理员增设账号

按用户后续指令增设固定密码且无需首次改密的账号。该次管理员操作通过SSH加密stdin向独立一次性容器传入带随机盐的scrypt摘要，参数及格式与现有认证相同；仅写入新账号并设置must_change_password=0。密码仅在内存和HTTPS登录请求中使用，没有写入源码、命令参数或凭证文件。原主账号不变，网页改密长度规则及公开注册禁用保持原设置。

实际运行 `python artifacts/create-requested-account.py`：输出 `status=created, must_change_password=false`，随后9项可信公网检查通过，最终 `ACCOUNT_CREATE_AND_LIVE_LOGIN_VERIFICATION_PASS`，退出0。检查包含指定凭证登录、直接进入图鉴、两类列表、受保护原图、后登录撤销前会话、旧退出不影响新会话及验证会话退出；单会话按每个账号执行。

同时移除发布自检中的账号总数必须等于1的限制，仍要求原主账号存在且启用，避免新增账号后无法通过后续发布门禁。`.venv/Scripts/python.exe -m pytest backend/tests/test_auth_deploy.py -q --tb=short`：`10 passed in 0.12s`，退出0；新增回归覆盖多账号可正常开放、主账号停用/缺失仍保持关闭，旧匿名旁路与代理回滚测试保留。仅更新服务器宿主发布脚本及文档，不重启服务或重建运行中的0.10.0镜像。
