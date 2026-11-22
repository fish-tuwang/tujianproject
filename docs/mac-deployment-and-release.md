# Mac mini 部署与公司发布流程

更新日期：2026-11-23。仓库 `fish-tuwang/tujianproject`，正式分支 `main`。公司 Codex 负责修改、检查和推送；家庭 Mac mini 负责运行和自动拉取。

**最新部署变更：** 普通 QQ 已按用户要求采用完整 FatFish 公开框架与原版控制台，Qwen 模型和原 NapCat 登录保留。新增独立上游更新任务；当前架构、实际生效的人设位置与官方 harness 插件变更，优先参见 [fatfish-mac.md](fatfish-mac.md)。本文后续旧 Qwen worker 描述用于原部署和回滚，不代表 FatFish 接管后的消息处理入口。

## 三个系统的区分

| 系统 | 本仓库代码 | 运行方式 |
| --- | --- | --- |
| 多美卡、宝可梦、高达图鉴 | backend/app、backend/preview 等 | Mac Docker：little-atlas-mac |
| 普通 QQ 群聊机器人 | qqbot/：NapCat + Qwen，含聊天、引用回复、表情和生图 | Mac Docker：little-atlas-mac-qq |
| QQ 官方机器人 | 独立的 DeepSeek harness 项目 | 不属于本仓库部署；必须使用官方 QQ 机器人 API |

`backend/app/qq_bot.py`、`docs/qq-catalog.md` 是历史图鉴查询桥接资料，不代表当前普通 QQ 聊天机器人的入口。迁移后京东服务器旧 QQ 两容器停止并保留备份，避免同账号重复登录。

## 公司 Codex 如何发布

1. 先阅读根目录 AGENTS.md，确认远端 main 与已有本地修改，不丢弃其他工作。
2. 修改目标模块并做相关检查。普通 QQ：人设/回复在 qqbot/qq_chat.py，群消息和引用在 qqbot/qq_bot.py，表情/生图在 qqbot/qq_images.py，表情索引和资源在 qqbot/qq_stickers/。
3. 对用户授权的修改完成提交，并推送 main。仅保存公司本地文件、推到其他分支或只创建 PR，不会触发正式部署；PR 需要合入 main。
4. 报告 SHA、检查结果与推送结果。如果无法访问家庭 Mac 的运行状态，明确写“已推送，等待 Mac 自动更新”。

用户无需再次给开发代理复述部署路径。开发代理应自行阅读本文件与 AGENTS.md，不要求用户在公司反复执行 Mac 安装命令。

## 两个 5 分钟更新任务

### 图鉴

- LaunchAgent：com.little-atlas.updater，StartInterval=300。
- 脚本：scripts/mac_auto_update.py；宿主安装副本在 `~/Library/Application Support/LittleAtlasUpdater/updater.py`。
- 读取 main 的 backend 变化，三方合并以保留 Mac 定制，备份后构建 API，健康检查和容器文件校验通过才记入发布 revision；失败恢复旧代码和镜像。
- 数据库迁移、Dockerfile、requirements.lock、pyproject.toml、compose.*、.env 等受阻止规则保护，需要单独处理；不能承诺这类推送自动生效。

### 普通 QQ

- LaunchAgent：com.little-atlas.qq-updater，StartInterval=300。
- 脚本：scripts/mac_qq_auto_update.py；宿主副本在 `~/Library/Application Support/LittleAtlasQQ/updater.py`。
- 发布包是 qqbot/。有包变更才构建桥接；其他提交只推进检查 revision。
- 使用固定的已验证依赖底座，校验包路径、文件类型、表情资源、Python 编译及模块导入。仅重建 bridge，不重启 account。
- 若更新前 QQ 在线，更新后还需在线；同时核对容器内源码哈希。失败回滚桥接镜像，不改账号和持久化数据。
- 账号容器不因普通代码更新要求重新扫码。腾讯会话失效仍可能要求手机验证，自动代码更新不能替代此验证。
- 新依赖、客户端版本、Compose、宿主更新器/守护脚本变化需在 Mac 单独安装，现有自动任务不会盲目执行仓库中的新安装脚本。

## Mac 私有目录和启动

- 图鉴：`~/Library/Application Support/LittleAtlas/runtime`；使用 compose.mac.yaml、.env.mac 与 Docker 持久卷。
- QQ：`~/Library/Application Support/LittleAtlasQQ`；runtime.env、compose.yaml、部署记录、QQ 配置与备份仅留本机。
- QQ 卷：little-atlas-mac-qq_account、config、state、logs。不得删除或复制进 Git。
- com.little-atlas.server 与 com.little-atlas.qq 登录启动，等待 Docker 后启动服务；容器 restart=unless-stopped。依赖既有 Mac 自动登录、联网和 Docker 正常启动。整机无人值守恢复不能仅凭配置宣称验收通过。
- OneBot 3002 与 bridge 8096 只在共享容器网络的 loopback 内监听；WebUI 6099 仅绑定 Mac 127.0.0.1 并启用认证。不新增公网管理端口。
- 图鉴保留原网页登录鉴权。外部京东地址仍可作为中转，Mac 路由入口与云端旧站点不可混淆。

## QQ 离线恢复

宿主 LaunchAgent com.little-atlas.qq-guard 每 30 秒执行 scripts/mac_qq_guard.py 的安装副本：

- 使用 WebUI 实际在线状态及账号身份确认在线，探测错误不当成掉线。
- 连续离线 60 秒且本账号有有效快速登录记录时限频重试，每小时最多 3 次。
- 长时间陈旧的“已登录但离线”状态、两次快速登录失败后，可限频重启账号，每小时最多一次。
- 需要安全验证/登录态失效时停止重试；扫描和初始化期间不打断登录。
- 保留 QQ 数据，已设置默认自动登录账号，并为未来账号容器重建固定现有 hostname/MAC。

目前在线检查和策略测试已验证；不能把策略测试描述成已证明数天不掉线。不要清用户目录、批量改版本、轮换 IP 或使用循环发送消息“保活”。

## 检查与排障（仅在 Mac 执行）

```sh
python3 scripts/mac_qq_status.py
python3 scripts/mac_qq_login.py --refresh
launchctl list | rg 'little-atlas\.(qq|updater)'
```

新二维码在 QQ 私有目录，短期有效。发送给用户扫码即可，不能提交 Git。验收需检查 ready、账号匹配及真实回复消息 ID；群内测试由用户 @ 机器人触发，不自行向群发送测试消息。

图鉴更新日志在 LittleAtlasUpdater/updates.log、errors.log。QQ 更新日志在 LittleAtlasQQ/updater.log、updater-errors.log；守护状态在 guard-state.json、guard.log。检查日志时只输出时间、事件与错误分类，不输出密钥、二维码 URL 或聊天正文。

## 回滚与验收用语

QQ 代码自动更新失败恢复旧桥接镜像；图鉴按原更新器恢复 API 和源文件。需要恢复服务器 QQ 时，先停 Mac QQ 服务与其启动/守护任务，再启原服务器实例，始终只运行一份。

区分“代码已修改”“已检查”“已推送 main”“Mac 已拉取”“运行检查通过”“用户真实收发验证”。没有证据不得跨级报告。

## 普通 QQ 互动节奏（2026-11-23）

用户已选择启用：群安静30分钟后冒泡，每群每日最多3次，北京时间22:00—09:00不主动发言。仅覆盖已授权且近24小时有过@互动的群，同一段无人回应的冷场不重复，两次主动发言至少间隔2小时。普通的夜间@回复不受主动发言安静时段限制。

新增 group_activity、image_history、idle_history 表保存限额和最近画面指纹，属于兼容旧代码的附加表；部署前已备份原会话库，旧镜像回滚无需删除新表。密钥和 QQ 登录容器不变。图库按画面而不是字幕去重，近期图片优先轮换，小图库至少不连续发同一张；不够合适就发文字或保持安静。
