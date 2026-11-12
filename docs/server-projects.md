# 服务器项目清理记录

## 2026-11-12：鱼鱼找鸡

已根据用户要求删除 `/opt/fish-find-chicken`：Compose 标签确认的 `fish-search`、`fish-napcat` 容器、代码、`.env`、状态与QQ登录数据、二维码、两个专用镜像及 `fish-find-chicken_default` 网络均移除。没有保留该项目源码或业务数据备份；图鉴私有目录只留操作元数据和验证回执。

删除前检查根目录解析结果、嵌套挂载、其他容器共享挂载和专用网络归属，图鉴 `/opt/dual-catalog` 在保护范围内。另按明确缓存ID清理23个鱼项目Node构建链及图鉴部署前未共享的旧构建快照，保留图鉴部署后缓存及正在使用的镜像共享缓存。依照 [Docker缓存筛选说明](https://docs.docker.com/reference/cli/docker/buildx/prune/) 使用ID定向清理，未执行全局镜像或数据卷清空。

清理前后图鉴全部容器ID及两个真实账号的非会话指纹相同，两套API均为ready/0005_gunpla。公网健康和登录页面200，匿名API401、图鉴页面303转登录；服务端实际读取三类图鉴及高达展示图成功。磁盘可用空间22,399,336,448→27,377,184,768字节，约释放4.64GiB，使用率降至55%。回执：服务器 `data/artifacts/acceptance/fish-project-removal.json`、`catalog-after-fish-removal.json`。

发布器 `plugins()` 改为仅检查实际存在的旧项目容器，已删除项目不再使后续图鉴发布失败；对于仍存在的独立容器，继续检查前后ID，Docker发现或查询失败仍报错。相关删除场景与已有发布回归23项通过，退出0；真实服务器验证发布器在缺少fish-search时正常。

## 仍待用户确认的独立应用

以下应用与鱼项目不属于同一个Compose工程，各有自己的数据；已通过异步问题请求确认是否一并删除，尚未执行删除：

| 项目 | 当前目录或服务 |
| --- | --- |
| QQ群总结机器人 | `/opt/qq-summary-bot`、`qq-summary-bot` 容器 |
| 旧Nginx实例 | `nginx` 容器；图鉴使用独立 `dual-catalog-preview-proxy` |
| OpenWebUI | `/opt/open-webui`、未使用的 `open-webui` 数据卷 |
| AstrBot | `/opt/astrbot` |
| Ollama及旧QQ客户端 | 停用的ollama.service、`/root/ollama`、`/root/Napcat`、`/root/.config/QQ` |
| AgentScope旧站点 | `/www/wwwroot/ai.tuwangwakuwaku.top/agentscope` 及旧站点配置 |

当前仅“鱼鱼找鸡删除”部分完成，尚不称服务器业务项目已只剩图鉴。图鉴所需PostgreSQL、独立Redis、Docker、证书、SSH及服务器管理设施继续保留。
