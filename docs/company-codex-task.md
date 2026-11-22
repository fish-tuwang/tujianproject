# 发给公司 Codex 的任务

请在 `fish-tuwang/tujianproject` 中执行本次修改。先阅读根目录 AGENTS.md、docs/mac-deployment-and-release.md、docs/fatfish-mac.md 和 qqbot/README.md，检查远端 main 与已有本地修改，保留他人工作。

普通 QQ 已采用 FatFish 公开运行框架 + 本仓库 Mac 适配层：运行入口为 qqbot/fatfish_mac.py；qqbot/qq_bot.py 负责现有账号的认证 OneBot 事件/API 网关，qqbot/fatfish_gateway.py 处理适配传输；不要改成旧 backend/app/qq_bot.py，也不要在公司启动同一个 QQ 账号。

按我随后提供的需求完成实现、相关行为测试、提交并推送 main，不要只给方案。现有 Mac 每5分钟拉取 main，更新 qqbot/ 会切换聊天桥接，并同步安装过的 FatFish Mac 适配器；QQ 账号容器、登录、群范围、密钥和会话保持。上游 Vegra85/fatfish-bot 另有每5分钟更新任务，不要用上游代码覆盖我们的适配层或私有人设、数据。

官方 QQ 是 DeepSeek Harness 的 @tencent-connect/dsh-qqbot 插件，使用官方 API；official_qq/ 是无凭据工具模板，不是 NapCat 实例。不要把两个机器人的账号、凭据、协议或发布状态混在一起。

按改动运行检查；QQ 基础检查：`python -m compileall -q qqbot official_qq`，行为与部署检查：`python -m pytest tests/test_qq_engagement.py tests/test_fatfish_mac.py tests/test_mac_qq_update.py tests/test_mac_qq_guard.py -q`。宿主部署脚本、外部依赖、插件配置改动不因推送就自动生效，需评估并记录安装方式。

完成后报告提交 SHA、检查结果和真实发布证据。公司无法检查家庭 Mac 时，只报告“已推送，等待 Mac 自动更新”，不要声称已经本机上线或真实收发通过。凭据、聊天日志、数据库、二维码和私有 runtime.env 不得提交。

本次具体修改：〔在这里填写需求〕。
