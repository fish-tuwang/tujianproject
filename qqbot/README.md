# Mac mini QQ 群聊机器人

**2026-11-23 更新：** 普通 QQ 已切到完整 FatFish 公开框架。当前入口是 `fatfish_mac.py`，`qq_bot.py` 提供保留登录的认证传输网关；旧 Qwen worker 在 QQ_ENGINE=fatfish 下不接收群消息。请先阅读 [FatFish Mac 部署说明](../docs/fatfish-mac.md)。下文的 Qwen 聊天实现作为兼容回滚入口保留，不能误当当前唯一聊天引擎。

记忆/情绪/关系/日记实现位于 `fatfish_extensions/`，由本仓库独立维护并随 qqbot 发布，不能直接改本机 upstream/current 中的空壳。控制面板原页与新增 `/local-core` 同用这些实现；异地只读入口保留图鉴所有者鉴权。阅读 [功能与数据说明](../docs/fatfish-memory-and-emotion.md)。

这里是当前 Mac mini 运行的 Qwen 聊天、图片与表情机器人源码。与 `backend/app/qq_bot.py` 中的旧图鉴查询桥接分开。

在公司用 Codex 修改本目录，提交并推送到 `fish-tuwang/tujianproject` 的 `main` 分支后，Mac 每 300 秒检查一次，有本目录变更时自动构建并更新聊天桥接。

- 人设、回复策略：`qqbot/qq_chat.py`
- 群消息处理、去重、连续消息：`qqbot/qq_bot.py`
- 表情与生图：`qqbot/qq_images.py`
- 表情目录和图片：`qqbot/qq_stickers/`

密钥、账号、群范围、会话数据库、QQ 登录数据只保存在 Mac 私有目录及 Docker volumes，不进仓库。代码更新不会重启账号容器，也不修改这些配置。新增依赖、QQ/NapCat 版本或数据库破坏性变更需单独部署；普通 Python 代码与表情资源变更可自动更新。

自动更新器：`scripts/mac_qq_auto_update.py`。启动项：`com.little-atlas.qq-updater`。安装完成后无需在公司或 Mac 上反复执行安装命令。失败时保留旧服务或回滚旧桥接镜像，详细日志位于 `~/Library/Application Support/LittleAtlasQQ/updater.log`。

验证更新器：`.venv/bin/python -m pytest tests/test_mac_qq_update.py -q`。更新器使用固定、已验证的运行依赖镜像，GitHub 修改构建配置不会自动执行。

## 冷场冒泡与表情（2026-11-23）

`QQ_IDLE_ENABLED=true` 开启冷场冒泡，`QQ_IDLE_MINUTES=30`、`QQ_IDLE_DAILY_LIMIT=3`。仅对已授权且过去24小时有人 @ 过机器人的群生效；群里无人发言30分钟才考虑冒泡，北京时间22:00—09:00不主动说话。两次主动冒泡至少间隔2小时，同一段无人回应的冷场只发一次。队列执行前及模型生成后都会重查群活动，已有人说话就取消，不补发夜间积压。

文字、图文、纯表情为三种回复模式。纯表情不附带空引用或额外文字。图片按解码后的画面指纹记录每群发送历史，优先避开最近3张；同类图库不足时至少不重复上一张，不靠字幕去重。历史与每日额度存在本机 SQLite，更新/重启后保留。模型每次得到真实北京时间，夜间被 @ 仍可正常回复。

实现参考仅用于设计比较，未运行第三方机器人：
- https://github.com/Vegra85/fatfish-bot ：冷场试探、排队、表情词典的说明。
- https://docs.maibot.chat/manual/configuration/bot-config ：按群/时段调节参与频率及模型选表情。
