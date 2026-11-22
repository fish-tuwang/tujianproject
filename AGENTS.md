# 项目协作与发布约定

2026-11-23 最新：用户已授权部署完整 FatFish 公开框架。普通 QQ 当前还需先读 [FatFish Mac 部署说明](docs/fatfish-mac.md)：`qqbot/fatfish_mac.py` 是宿主适配入口，`qqbot/qq_bot.py` 在 QQ_ENGINE=fatfish 下仅作原账号认证网关。官方 QQ 仍为独立 harness 插件，`official_qq/` 为本次新增的无凭据工具/提示词模板，不是 NapCat 服务。不要将下文旧 Qwen worker 的入口及提示词生效方式误套到当前 FatFish 实例。

开始修改前阅读 [部署与发布说明](docs/mac-deployment-and-release.md)；修改普通 QQ 机器人还需阅读 [qqbot/README.md](qqbot/README.md)。本文是本仓库长期约定，用户最新明确指令优先。

## 项目与部署位置

- 仓库：`fish-tuwang/tujianproject`，发布分支 `main`。
- 图鉴与普通 QQ 机器人的正式服务运行在家里的 Mac mini，公司环境负责开发、验证和推送代码。
- 普通 QQ 机器人是 `qqbot/` 的 NapCat + Qwen 聊天机器人。`backend/app/qq_bot.py` 是旧图鉴查询桥接，不能当成当前聊天机器人修改入口。
- 用户另有 QQ **官方**机器人，接 DeepSeek harness；这是独立项目。其官方 API、凭据、部署及限制不能套用 NapCat/OneBot，本仓库不负责发布它。

## 开发与发布

1. 核对当前分支、远端 main 和本地未提交修改，保留用户已有工作。
2. 对用户已授权的功能修改、修复，默认完成实现、相关检查、提交并推送 main；用户要求只分析、只评审或暂不发布时按其要求执行。不得用强制推送覆盖他人提交。
3. 提交只包含本次任务文件。QQ 逻辑主要改 `qqbot/qq_chat.py`、`qqbot/qq_bot.py`、`qqbot/qq_images.py`、`qqbot/qq_stickers/`。
4. 运行适合改动的检查；更新器/守护器检查为 `python -m pytest tests/test_mac_qq_update.py tests/test_mac_qq_guard.py -q`。QQ 包语法检查可用 `python -m compileall -q qqbot`，涉及消息逻辑还需相应行为测试。
5. 推送后报告提交 SHA、检查结果及发布状态。Mac 每 5 分钟检查 GitHub main；没有本机运行证据时只能说“已推送，等待 Mac 自动更新”，不能声称“本机已上线/验收通过”。
6. 改性格提示词时，权威来源是 `qqbot/qq_chat.py` 的 `PERSONALITY`；同时更新文档快照并注明其为源码快照，不能将它误当独立生效配置。

## 运行与数据边界

- 保留 QQ 账号、群范围、密钥、会话和 QQ 登录数据，不在公司再启动同一 QQ 账号的实例。
- 密钥、密码、二维码、QQ 用户目录、数据库、runtime.env、私有备份和聊天日志不得提交或复制到文档。
- 普通代码/表情更新只切换 QQ 聊天桥接；不能借更新强制重建 QQ 账号容器或清空登录数据。
- 新依赖、数据库结构、QQ/NapCat 版本、Compose/构建配置、更新器或宿主守护器修改，需要独立部署评估。GitHub 推送不代表这些宿主设置已应用。
- 不以探测失败判定 QQ 掉线，不循环重启、频繁重新登录、切 IP 或重置设备标识。明确需要安全验证时保留状态并由用户确认。
