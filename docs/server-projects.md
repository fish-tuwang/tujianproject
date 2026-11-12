# 服务器项目清理记录

## 2026-11-12：鱼鱼找鸡

已根据用户要求删除 `/opt/fish-find-chicken`：Compose 标签确认的 `fish-search`、`fish-napcat` 容器、代码、`.env`、状态与QQ登录数据、二维码、两个专用镜像及 `fish-find-chicken_default` 网络均移除。没有保留该项目源码或业务数据备份；图鉴私有目录只留操作元数据和验证回执。

删除前检查根目录解析结果、嵌套挂载、其他容器共享挂载和专用网络归属，图鉴 `/opt/dual-catalog` 在保护范围内。另按明确缓存ID清理23个鱼项目Node构建链及图鉴部署前未共享的旧构建快照，保留图鉴部署后缓存及正在使用的镜像共享缓存。依照 [Docker缓存筛选说明](https://docs.docker.com/reference/cli/docker/buildx/prune/) 使用ID定向清理，未执行全局镜像或数据卷清空。

清理前后图鉴全部容器ID及两个真实账号的非会话指纹相同，两套API均为ready/0005_gunpla。公网健康和登录页面200，匿名API401、图鉴页面303转登录；服务端实际读取三类图鉴及高达展示图成功。磁盘可用空间22,399,336,448→27,377,184,768字节，约释放4.64GiB，使用率降至55%。回执：服务器 `data/artifacts/acceptance/fish-project-removal.json`、`catalog-after-fish-removal.json`。

发布器 `plugins()` 改为仅检查实际存在的旧项目容器，已删除项目不再使后续图鉴发布失败；对于仍存在的独立容器，继续检查前后ID，Docker发现或查询失败仍报错。相关删除场景与已有发布回归23项通过，退出0；真实服务器验证发布器在缺少fish-search时正常。

## 2026-11-12：其余独立业务应用

用户进一步明确“也删除，只保留图鉴”后，已完成以下清理：

| 项目 | 已移除内容 |
| --- | --- |
| QQ群总结机器人 | `/opt/qq-summary-bot`、容器、专用镜像和网络，以及9条独立旧构建缓存 |
| 旧Nginx实例 | `nginx` 容器；保留图鉴代理正在使用的共享Nginx镜像 |
| OpenWebUI | `/opt/open-webui`、未使用的 `open-webui` 数据卷 |
| AstrBot | `/opt/astrbot` 及对应回收站副本 |
| Ollama及旧QQ客户端 | ollama.service、手工安装的Ollama/Napcat程序、模型、`/root/ollama`、`/root/Napcat`、`/root/.config/QQ` |
| AgentScope旧站点 | 整个 `/www/wwwroot/ai.tuwangwakuwaku.top`、旧站点配置、专用证书、访问日志和对应回收站副本 |

先以52个精确路径清单检查解析结果、文件身份、宿主挂载和图鉴容器挂载，再删除两个独立容器及其专用数据。末次检查发现宝塔统计服务重新创建旧站点配置，追溯到新版宝塔实际使用的 `data/db/site.db` 注册记录；现已仅删除该旧站点与域名记录、两条未共享证书记录、反向代理及文件历史条目、旧站点统计数据，并清除重新生成的配置。其他管理记录及审计日志保留。

服务器业务项目现只剩图鉴，运行中的7个业务容器均属于图鉴；旧的已停止图鉴代理容器仍属本项目。清理前后图鉴容器ID及两套真实账号非会话指纹相同，三类图鉴及高达展示图实际读取成功，两套API为ready/0005_gunpla，公网登录页和健康检查200，匿名访问按原规则返回401/303。图鉴所需PostgreSQL、独立Redis、Docker、证书、SSH及服务器管理设施继续保留，没有重启图鉴容器。

本轮额外释放约6.2GiB，完成时可用约31.6GiB。清理回执和验证结果位于服务器 `data/artifacts/acceptance/retired-apps-removal.json`、`catalog-after-retired-apps-removal.json`；操作事件写入图鉴 `deploy.jsonl`。仅保留清理工具与操作元数据，没有保留已删除项目源码或业务数据备份。发布器实际检查结果为无剩余独立旧项目容器，后续图鉴发布可继续执行。

## 2026-11-12：图鉴QQ接入组件

用户随后要求沿用原QQ账号接入图鉴，明确账号949494401及其已加入的全部QQ群。新增的 `dual-catalog-qq-bridge` 和 `dual-catalog-qq-account` 属于图鉴项目，代码和专用登录状态在 `/opt/dual-catalog` 内；没有恢复鱼鱼找鸡、QQ总结或其他旧业务。原有7个图鉴容器未重建。接入与扫码状态详见 `docs/qq-catalog.md`、对应实施计划及服务器 `qq/deployment.json`。
