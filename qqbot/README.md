# Mac mini QQ 群聊机器人

这里是当前 Mac mini 运行的 Qwen 聊天、图片与表情机器人源码。与 `backend/app/qq_bot.py` 中的旧图鉴查询桥接分开。

在公司用 Codex 修改本目录，提交并推送到 `fish-tuwang/tujianproject` 的 `main` 分支后，Mac 每 300 秒检查一次，有本目录变更时自动构建并更新聊天桥接。

- 人设、回复策略：`qqbot/qq_chat.py`
- 群消息处理、去重、连续消息：`qqbot/qq_bot.py`
- 表情与生图：`qqbot/qq_images.py`
- 表情目录和图片：`qqbot/qq_stickers/`

密钥、账号、群范围、会话数据库、QQ 登录数据只保存在 Mac 私有目录及 Docker volumes，不进仓库。代码更新不会重启账号容器，也不修改这些配置。新增依赖、QQ/NapCat 版本或数据库破坏性变更需单独部署；普通 Python 代码与表情资源变更可自动更新。

自动更新器：`scripts/mac_qq_auto_update.py`。启动项：`com.little-atlas.qq-updater`。安装完成后无需在公司或 Mac 上反复执行安装命令。失败时保留旧服务或回滚旧桥接镜像，详细日志位于 `~/Library/Application Support/LittleAtlasQQ/updater.log`。

验证更新器：`.venv/bin/python -m pytest tests/test_mac_qq_update.py -q`。更新器使用固定、已验证的运行依赖镜像，GitHub 修改构建配置不会自动执行。
