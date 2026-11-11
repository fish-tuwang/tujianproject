# 私有登录与账号管理

生产入口为 https://117.72.11.77/preview/ 。未登录只显示登录页；图鉴接口、详情、原图、月刊和预览脚本均先鉴权。网页没有注册入口或注册接口。首账户为 `peyro-gogogo`，临时密码仅交付到本地私有文件，首次登录必须修改。

每个账号只保留一个有效会话：新设备登录立即撤销旧会话，旧设备的下一次请求会被拒绝；已打开页面每10秒及恢复前台时检查。退出、重置密码、停用立即撤销会话。会话最长12小时，浏览不会续期。密码使用带随机盐的scrypt摘要，服务端只存会话摘要。浏览器使用Secure、HttpOnly、SameSite=Lax Cookie；小程序使用独立Bearer凭证。Redis仍缓存图鉴与图片，每个请求在读取缓存前验证当前会话。

## 服务器管理命令

仅服务器管理员可以运行以下命令；网页和公开接口无法创建账户。新增账号也会获得相同图鉴权限，只有明确需要时才创建。发布检查保留主账号启用的要求，允许管理员创建的其他账号存在；单会话限制按每个账号分别执行。

```sh
docker compose --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog exec -T api python -m backend.app.auth_cli list-users
docker compose --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog exec -T api python -m backend.app.auth_cli create-user USERNAME --generate --output-file /app/artifacts/auth/new-login.json
docker compose --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog exec -T api python -m backend.app.auth_cli reset-password USERNAME --generate --output-file /app/artifacts/auth/new-login.json
docker compose --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog exec -T api python -m backend.app.auth_cli disable-user USERNAME
```

生成文件不可预先存在，权限0600。通过SSH下载并核对SHA256后删除服务器明文文件，不将密码写进命令参数、日志或Git。鉴权数据库在 `/opt/dual-catalog/data/artifacts/auth/accounts.sqlite3`，目录0700，随项目持久卷保存；备份时应使用SQLite备份API或停写后一并处理WAL。演示环境使用独立目录且不预置账户。登录、退出和账号操作写入私有 `logs/auth.jsonl`，轮转30天；日志不含密码、Cookie或会话令牌。

## HTTPS与发布

项目独立代理监听80/443，HTTP跳转HTTPS。IP证书由隔离Certbot及shortlived profile签发，`dual-catalog-cert-renew.timer`每12小时检查；成功后验证并重载本项目代理。检查：

```sh
systemctl is-active dual-catalog-cert-renew.timer
python3 /opt/dual-catalog/app/scripts/renew_tls.py --dry-run
curl --fail https://117.72.11.77/health/ready
```

证书和ACME账户仅保留服务器 `tls/`，代理只挂载live/archive，不挂载账户私钥。禁止把证书和环境配置加入源码包。首次部署使用 `prepare_auth.py tls`、构建镜像、`accounts --username peyro-gogogo`、`deploy_release.py`；后续发布继续使用版本化发布脚本。发布期间maintenance文件让私有入口503，健康和ACME保持可用；实际镜像禁网测试、双环境鉴权与唯一首账户检查通过后才开放。失败回退旧镜像仍保持maintenance关闭，避免旧版匿名公开。修复后执行 `prepare_auth.py gate --mode open`重新检查，不直接删除门禁文件。

公网代理拒绝管理路径，内部管理Bearer与缓存预热服务令牌各自独立；服务令牌仅用于回环读接口，公开代理会清除传入服务头。原有插件与6379 Redis不变。

微信原生页面已接入登录与私有图片下载，但正式小程序仍需要真实AppID、HTTPS域名和微信真机验收；IP证书用于当前网页交付。
