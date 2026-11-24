# FatFish：Mac 运行与自动发布

**当前人格：** 用户已授权按 FatFish 公开行为说明复刻群友性格，保留“哦鲸鲸”身份与温和边界。源码及运行渲染快照见 [qq-personality-current.md](qq-personality-current.md)；这是本项目复刻，不是作者未公开的私有人设。本次只更新普通 QQ，不修改腾讯官方 QQ harness 插件。

**远程管理更新：** 用户已授权在公司操作全部已实现的普通 QQ 控制面板管理功能，原只读限制已取消，仍仅所有者可管理；删除/退出/进程控制需界面确认。见 [远程管理说明](qq-panel-remote-management.md)。

2026-11-23。普通 QQ 现采用 Vegra85/fatfish-bot 的完整公开 Python 运行框架与原版网页控制台，当前上游版本 v1.18.2、提交 fe3b52438fcba5798609baae2d32c33f51305bff。上游地址：<https://github.com/Vegra85/fatfish-bot>，MIT；上游 LICENSE 保留在每个本机版本内。表情资源分别保留原来源/署名与许可，不因此变成 MIT。

## 实际架构

- 原 QQ 账号仍在 little-atlas-mac-qq-account-1，未重新登录或重建。NapCat、设备标识、持久卷和守护器保留。
- qqbot/qq_bot.py 的 QQ_ENGINE=fatfish 模式负责原有认证 HTTP 事件入口与 OneBot 网关，不再把群消息交给旧 Qwen 聊天 worker，因此不会双份回复。
- qqbot/fatfish_mac.py 在 Mac 原生 Python 环境运行上游 bot.main()；把其 OneBot WebSocket 调用适配到认证本机网关，避免为了换聊天框架而重启 QQ。模型沿用现有 Qwen 凭据，官方机器人继续独立使用 DeepSeek。
- 完整公开控制台由同一适配器的 --panel 模式运行，地址 http://127.0.0.1:8765；重启按钮只重启聊天服务。管理页面只绑定本机且校验 Host / X-Panel，不新增公网管理端口。
- 私有根目录：~/Library/Application Support/LittleAtlasQQ/fatfish。current 指向 releases/<SHA>；config.json、persona.md、data/、stickers/ 独立保存并链接到版本。账号凭据、私有配置、聊天/记忆、日志绝不提交。

## 两条独立更新线

1. 公司修改本仓库 main：com.little-atlas.qq-updater 每300秒检查。qqbot/ 改动构建桥接；部署成功后同步已安装的 fatfish_mac.py 到私有 adapter.py 并重启聊天/面板。QQ 账号容器保持。
2. 上游 FatFish main：com.little-atlas.fatfish-updater 每300秒检查，脚本 scripts/mac_fatfish_update.py。下载完整上游代码到独立新版本，检查归档路径/链接、必要文件、依赖、全部 Python 编译、bot/panel 导入，再切换并检查面板、QQ 在线。代码与虚拟环境一起切换，失败回到旧版本；不覆盖本机适配器、人设、密钥、数据或表情。

上游新增未适配依赖、接口变化或检查失败会保留当前版本，日志记录失败，不能承诺任意破坏性更新也强制上线。首次安装/修改宿主更新器需在 Mac 单独应用，不由任意 GitHub 脚本自动执行。

## 行为保留与公开版边界

保留温和诚实的人设、真实北京时间、纯表情、不同 DeepSleep 画面轮换。画面按解码 RGBA 指纹记历史，跨进程重启避免连续相同图片；纯表情去掉空引用/空文本。冷场冒泡仍由原 SQLite 群活动守门：安静30分钟、每群每日最多3次、两次至少2小时、22:00—09:00静默、同一轮无人回应不连发、近24小时有@互动、有人说话即取消。

公开工具模块已随完整运行框架部署：网页检索、网页读取、文件制作/上传、表情词典、歌曲/语音相关、日历和群聊控制等。工具仍受其依赖与服务配置约束；没有语音/生图/音乐等外部服务凭据的项目不能凭空可用，控制台可检查配置。不会借迁移自动添加好友、入群、拉黑删好友、恶作剧或操作 QQ 空间；这些不能用“启用全部工具”推定为具体外部操作授权。

Mac 已额外安装 python-pptx、imageio-ffmpeg 和 yt-dlp，并把 Chrome 的实际 Mac 路径配置给 PDF 工具；ffmpeg/yt-dlp 包装命令在私有 bin/，启动项 PATH 包含该目录。各次上游更新的新虚拟环境也安装这些依赖，避免更新后丢失 PPT/视频能力。实际 QQ 发文件仍经过原账号容器，Mac 生成文件先复制到该容器临时目录，不重建账号。

作者未公开的记忆提炼、情绪、关系等模块在公开仓库里是空壳。现已由本项目在 qqbot/fatfish_extensions/ 自行补全，机器人和控制台共同加载，详情见 [记忆与情绪说明](fatfish-memory-and-emotion.md)。这些是本项目实现，不能称为作者私人内核。

人设基础模板仍来自 qqbot/qq_chat.py 的 PERSONALITY，安装时转换为 FatFish 原生文字/[[表情:名字]] 协议。正在生效的 FatFish 人设是私有 persona.md，可在控制台“人设”查看/修改。上游更新保留此文件。公司修改基础模板时必须明确评估如何更新本机私有覆盖，不能误报只改旧 Qwen 提示词就已改变当前 FatFish 人设。

## 官方 QQ 插件

本机是 DeepSeek Harness + @tencent-connect/dsh-qqbot 0.5.5，并无独立机器人仓库。已通过插件支持的本机 config API 设置 groupPrompt/directPrompt，保留原绑定、provider/model、访问范围；模板在 official_qq/personality.md。官方工具在 ~/.dsh-qqbot/workspace/whale，使用现有 qqbot_send_file 发送真实文件，whale_tools.py 提供北京时间与持久化的画面轮换。

官方插件不使用 NapCat。当前工具未暴露原生引用参数时使用短文字引用，不能声称出现原生引用卡片；不照搬普通 QQ 主动冒泡到官方消息窗口之外。官方的配置及运行独立于普通 QQ 自动发布；模板变更需使用该插件支持的配置入口应用并验证，不把 main 推送当成官方已更新。

## 模型消耗统计

千问等模型的实际 usage 与费用统计见 [qq-model-usage.md](qq-model-usage.md)，不再将千问套用 DeepSeek 的计价与缓存规则。

## 验证与公司任务

`python3 scripts/mac_qq_status.py` 检查 QQ 网关；面板总览检查机器人在线和 QQ 在线。LaunchAgent：com.little-atlas.fatfish、com.little-atlas.fatfish-panel、com.little-atlas.fatfish-updater，均保留登录启动与进程恢复。日志只留本机，排障只输出状态/分类，不公开聊天和密钥。

测试：`python -m pytest tests/test_fatfish_mac.py tests/test_qq_engagement.py tests/test_mac_qq_update.py tests/test_mac_qq_guard.py -q`。另有本机隔离测试直接调用上游 FatFish.handle 和真实 Qwen 模型，拦截所有 QQ 发出动作；测试不等于用户群真实收发。

可直接发送给公司 Codex 的任务见 [company-codex-task.md](company-codex-task.md)。公司仅开发并推送，不启动同一账号的 QQ 实例。

## 2026-11-23 冒泡节奏调整

按用户最新要求，取消近期被@及无人回应只发一次的条件。已授权且已有活动记录的群，安静至少一小时后可冒泡，每群两次至少间隔一小时、每天最多三次；22:00—09:00仍静默，生成期间有人说话仍取消。既有较长的冷场配置保留，不更改私有群范围。二维码在返回前校验完整PNG，网页转为Blob加载并等待成功，失败不会继续展示破图。二维码真实远程加载仍需Mac更新后验证。

## 2026-11-24 按最后一次被@计时

最新规则覆盖旧冷场条件：最后一次被@满一小时后可冒泡，普通群消息不推迟计时；12:23被@则13:23到期，有新的@即重新计时。没有新的@时，后续两次发送仍至少相隔一小时，每群每日最多三次，22:00—09:00静默，不补发夜间积压。生成或分段发送期间出现新的@会取消待发内容，普通聊天不取消。首次记录群活动作为从未被@群的计时起点；旧记录缺少@时间时暂用已有最后活动时间。计时存储沿用SQLite，不改账号或群范围。FatFish每10秒检查，到期后模型生成及QQ发送仍有实际耗时，不承诺秒级送达。

## 主动冒泡禁链接（2026-11-24）

统一人设提示不能保证拦截；在冒泡上下文的发送入口过滤明文网址、Markdown链接目标、CQ链接与富卡片，纯链接过滤后不发送。保留图片/语音的传输地址，普通被@回复不经过此过滤。不修改Mac私有人设，也不新增控制面板设置页。
