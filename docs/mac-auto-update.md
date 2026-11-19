# Mac 自动更新

适用现有 `/Users/xiaotuwangjiang/Downloads/tujianproject`、`compose.mac.yaml`、`.env.mac`、Compose 项目 `little-atlas-mac`。无需将现有目录初始化为 Git 仓库。

安装（Mac 终端执行一次）：

```sh
curl -fL --retry 3 https://raw.githubusercontent.com/fish-tuwang/tujianproject/main/scripts/mac_auto_update.py -o /tmp/tujian-mac-updater.py && python3 /tmp/tujian-mac-updater.py --install "$HOME/Downloads/tujianproject"
```

首次按上游提交 `288b33d` 到 main 的差异检查现有代码。先做逐文件三方合并，不覆盖 Mac 定制文件；已确认的 2026-11-19 gunpla.py/theme.css 冲突只在上游旧/新文件哈希均匹配时，分别进行局部分类表达式替换和年份网格规则追加。其他冲突停止且不落盘；首次更新失败不启用定时服务。初次同步成功会输出 `UPDATE_OK` 与 `INSTALLED`。使用公开仓库，不要求提供 GitHub 密码。

Mac 用户登录、Docker 运行且联网时，LaunchAgent 每五分钟获取 main。自动同步范围为 `backend/`，不复制服务器部署模板、Mac 私有配置及缓存；遇到数据库迁移、依赖、Dockerfile 或 Compose 修改时暂停自动部署，等待专门适配。GitHub 推送后并非瞬间上线。

构建仍使用原 `.env.mac`、`compose.mac.yaml`。只重建和替换 `api`，`--no-deps` 保留 PostgreSQL；卷和数据库不做修改。更新成功需通过 readiness 和运行容器所有已更新 backend 文件的 SHA256 检查，以及已有 DX/FAZZ 记录的作品关联检查。构建或启动检查失败会恢复已备份源码与旧 API 镜像；不支持数据库迁移回滚，所以迁移不会自动执行。

状态、备份和日志保存在 `~/Library/Application Support/LittleAtlasUpdater`，不在 Git 仓库中。脚本并发加锁；日志按 5MB 轮转一份，源码备份暂不自动清理。

查看近期更新：

```sh
tail -n 40 "$HOME/Library/Application Support/LittleAtlasUpdater/updates.log"
tail -n 40 "$HOME/Library/Application Support/LittleAtlasUpdater/errors.log"
```

手动检查：

```sh
python3 "$HOME/Library/Application Support/LittleAtlasUpdater/updater.py"
```

停用自动检查（不停止图鉴）：

```sh
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.little-atlas.updater.plist"
```

本机 Windows 验证使用真实临时 Git 仓库和文件补丁，Docker/健康检查为模拟；macOS LaunchAgent 和 Mac 实际镜像构建需安装时验证，不能将 Windows 测试计为线上部署完成。


## 2026-11-20 修复定制代码导致更新卡住

日志停留 `c2462be` 且提示 `gunpla.py:153`、`theme.css:43` 不能应用时，运行上述安装命令一次以更新独立安装在 Application Support 中的更新器。仅推送仓库不会替换这个已安装的独立脚本。

新版更新器会保留 Dalong 相关方法和摘要扩展字段；分类修复仅作用于 summary_rows、filters、series_groups、cached 四个已核实入口，其余方法及主题定制保留。替换前完成所有文件的合并准备，无法识别的本地结构不强制覆盖。源码与镜像仍有备份和回退。

安装成功日志除 `UPDATE_OK`、`INSTALLED` 外，当前有记录的 Mac 应输出 `CLASSIFICATION_OK X=9 checked_DX=['1189', '875']`（实际总数可能随新采集增加）。当前测试覆盖模拟 Mac 定制，尚未取得该 Mac 的源文件或执行结果；不得把合并验证等同于 Mac 已上线。
