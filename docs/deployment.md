# 部署与运行

生产使用现有 Ubuntu 24.04 / PostgreSQL 18；代码位于 `/opt/dual-catalog/app`，数据库配置在 `/opt/dual-catalog/.env`（0600）中，永不随包覆盖。应用角色不能建库，迁移只写本项目库。

运行三类进程：API、队列worker、scheduler。scheduler仅为多美卡按固定48小时间隔、北京时间03:00安排增量检查，不再安排每日或每周全量任务，也不再定时抓取宝可梦。高达由独立timer每周日北京时间03:30增量检查。生产API绑定127.0.0.1:8092；独立演示API绑定127.0.0.1:8093，仅供隔离验收。浏览器预览由本项目独立nginx容器监听80/443，HTTP跳转HTTPS，反向代理生产API8092，访问 https://117.72.11.77/preview/ 登录查看真实采集资料。微信正式域名另配。演示使用dual_catalog_demo库，不能拿它证明来源完整性。

服务器命令从项目路径运行，使用以下Compose参数：

```sh
docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog build
docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog run --rm api python -m backend.app.worker init-db
docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog up -d api worker scheduler
```

演示使用相同代码，替换env为`.env.demo`、项目名为`dual-catalog-demo`，配置数据库dual_catalog_demo、端口8093和API_BIND=127.0.0.1；仅启用演示API，测试scheduler和worker由验收器在隔离schema控制，避免合成数据混入真实采集。

备份使用PostgreSQL18的`/www/server/pgsql/bin/pg_dump`，对本项目库输出自定义格式到`/opt/dual-catalog/backups`；目录0700、文件0600。密码在服务器环境加载，不输出。记录当前镜像ID和版本；回退只恢复本项目镜像和容器，不降级表结构、不删除数据库、不停止原有插件。

真实来源访问按robots与2秒限速执行。单页失败保留旧数据；`worker report`核对运行状态；手动重试使用管理页。全量导入可能较长，limited/partial不得计为完整。

0.10.0使用可信IP证书提供HTTPS私有入口，登录接口允许POST，其他公开代理路径只允许GET/HEAD并禁止管理路径；未更改既有nginx配置。配置微信合法请求与图片域名、真实AppID，执行check_release和真实微信自动化后再发布。

镜像以10001用户运行，Compose从0600配置注入环境，不将秘密挂载进容器。仅本项目artifacts目录授予10001写权限。禁止输出docker compose config的展开秘密，检查使用`config --quiet`。

生产使用两路worker并按来源互斥；部署镜像dual-catalog:0.10.0。服务器不能下载依赖时，使用已测试的0.1.0基础镜像配合Dockerfile.release打包源码，不修改全局镜像源。

0.8.5补齐特注、套装、活动、角色和非卖品的独立款式，纠正混合编码与连续照片/基础车型引用的配对；重复的明确车型分组标题继续保留。API内存上限640MiB，worker及原图预热384MiB，scheduler96MiB；仅调整本项目进程。列表元数据批量读取，Redis之外每个图鉴仅保留一份已解码的修订快照，修订号或600秒过期时替换，分页使用排序副本。完整性核对在独立一次性worker中运行`python -m scripts.audit_tomica_coverage`，不要在API容器追加重型Python核对进程。报告在私有`artifacts/acceptance/tomica-coverage.json`；读run状态、run_items、problems及edition_covers_pending，不把运行中的首次预热或源站失效图片称为全部完成。初次补录与修正记录见同功能目录tomica-completeness-plan.md。

验收时生产16693条图鉴记录，其中14548个补充款式身份；全站1092个页面任务中1090成功、1个源站404、1个含无法确认SP模板而隔离。Dream页482张封面均已缓存；新增款封面6097张已落盘、8451张仍待预热，图片文件保留30天，Redis热点24小时，后台持续处理。此为验收时间点的进度，不是全量图片完成声明。`verify_tomica_snapshot`清理Redis键而不清理进程快照，其cold仅代表响应缓存未命中，不能用来证明重建整份图鉴的耗时。

预览原图缓存位于data/artifacts/reference-images，按来源URL+图片ID生成键，磁盘缓存30天，失败保留旧图；正式转存状态不变。图片专项回填使用python -m scripts.repair_images --section covers或forms，变更前后记录保存到artifacts/acceptance/image-repair-*.json。


Redis缓存：本项目独立systemd服务dual-catalog-redis，127.0.0.1:6382，原有6379不变。配置/etc/dual-catalog-redis.conf，数据/var/lib/dual-catalog-redis，独立账户dual-catalog-cache；256MiB上限、allkeys-lru与RDB快照。连接凭证只保留在服务器环境文件（0600），生产DB0、验收DB1。prepare_redis.py复用已有本机Redis8.0.5二进制的独立副本，不修改原进程。

列表/筛选缓存600秒、详情缓存24小时，并将业务修订号纳入key；原图字节缓存24小时，保留磁盘后备。Redis连接失败时短超时并降级。冷图片回源独立并发限制，先释放数据库连接；命中Redis/磁盘不执行源站DNS或限速排队。静态CSS/JS继续使用浏览器版本缓存，管理凭证和管理写操作不缓存。

部署使用锁定redis-py6.4.0与vendor中的通用wheel，Dockerfile.release离线安装该依赖。独立cache-warmer服务运行python -m scripts.warm_cache --watch，先预热全量详情、封面优先下载原图，再补详情原图，按源URL去重，完成后6小时再次扫描新增与过期，失败5分钟后重试；真实验证python -m scripts.verify_cache。核验命令在本项目api容器运行；预热进度见data/artifacts/acceptance/cache-warmup.json，status=running不表示全量完成。不要对已有6379执行清空或配置修改。

多美卡网页使用/api/tomica?page=N&limit=S，S可选20/40/60/100且默认20；原有cursor接口仍支持小程序。电脑宽度>=1024采用五列，手机自适应；分页搜索与筛选重置为第一页。

宝可梦扩展详情使用0003迁移创建独立pokemon_details表，不加入列表快照。常规采集会更新该表。历史补齐分两步：python -m scripts.cache_pokemon_pages（原站串行限速缓存HTML），python -m scripts.backfill_pokemon_details --watch（仅写扩展资料，不覆盖基础名称、图片或人工修正）。失败续补可加--missing-only；补齐后运行python -m scripts.audit_pokemon_details核对覆盖、种族值合计和异色图配对。一次性容器应设restart=no，结束后保留报告并移除。HTML在项目私有artifacts/pokemon-detail-html目录，不公开挂载。

2026-11-10多美卡展示与搜索已更新0.4.1：全幅卡片图片、主图/版本图查看器、图标居中及车型别名/全半角归一；Tomica列表缓存视图升级list-v3，避免旧空结果。无数据库迁移，详见tomica-display-search-fix.md。

新品月刊新增0004_tomica_news独立表，原图以摘要命名放backend/preview/news-assets，来源为用户提供。离线导入python -m scripts.seed_tomica_news，按slug与内容摘要幂等；新品修订号独立于旧图鉴，7图同时预热Redis。部署前备份本项目两库并停止自身cache-warmer，健康后恢复；python3 /opt/dual-catalog/deploy_tomica_news.py --check在独立一次性容器核验数据库与原图。现有公众号联网发现入口仍未接通，不把本地导入当成自动抓取。数据库升级0004后旧0.5.1健康检查仅接受0003，不自动降库；保留备份与旧镜像，按故障阶段修复版本。

0.6.1为纯前端年份筛选详情返回修复，无迁移/导入；按标签页恢复多美卡条件及位置。发布脚本/opt/dual-catalog/deploy_mobile_year_return.py停自身预热、替换本项目镜像、健康后恢复；接口/首页字节核对见mobile-year-return-deploy.json。

0.6.2补齐两类列表直接刷新、宝可梦详情返回：pagehide记录位置，按种类独立保存筛选，多美卡恢复页码与每页数量，宝可梦恢复已加载条数并从新游标继续。仅保留同一标签页的浏览上下文；显式重置清空筛选。发布脚本/opt/dual-catalog/deploy_catalog_refresh.py，无迁移/导入；两套API仍为0004，服务源文件摘要与本地一致。公网恢复27项、导航32项、分页17项、新品32项及图片搜索27项通过；详细证据见both-catalog-refresh-fix.md。

0.6.3补齐手机新品侧栏迟到造成的188像素位置推移：恢复已有上下文时先等待新品索引排版完成，再恢复位置。发布仍使用deploy_catalog_refresh.py，不迁移或导入；新增受控延迟回归，公网29项新回归及导航32项、月刊32项通过，旧手机返回35项本地回归通过。定位证据见late-news-layout-before.json。

0.7.0增加持久化访问IP、采集条目变更及发布操作日志，位于data/artifacts/logs。首次运行python3 /opt/dual-catalog/app/scripts/prepare_logging.py配置本项目代理和独立轮转；后续无迁移发布统一使用python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.7.0 --reason "更新说明"，记录开始、阶段、配置键、结果与回滚。原代理输出已备份到access-legacy-*.log。查询命令与留存规则见docs/logging.md；服务器实际11项、Linux日志单测8项及公网状态恢复29项通过。

0.7.1只更新月份索引：每月单列完整年月新品标题；同月多文章仍归一个入口，原图、详情及返回保留。月刊测试15项、本地/公网月刊33项、公网恢复29项通过。公众号自动采集仍待本次域名授权和账号归属确认，未启用任何新采集进程；当前月份内容仍来自用户提供材料。


2026-11-11发布0.9.0：双主题使用theme.css与本地矢量背景，现有图标/原图保留。宝可梦支持region组合筛选与滚动加载，按图鉴保存筛选、进度和位置。旧地区定义为各版本图鉴合并，已由以下0.9.1规则替代；原UI验收见spec/feature_20261111_F001_ui-regions/acceptance.md。

0.9.1按用户新确认的Wiki全国编号分段归类，全国1025种无重复、无遗漏；洗翠899–905与未确认808–809单列。离线分段表在backend/app/pokemon_regions.py，python -m backend.app.pokemon_regions --refresh仅重建该规则，核对新编号后需先更新分段表并重新测试发布；线上不访问外站。地区元数据/列表缓存和筛选游标继续绑定索引版本，无需清空其他Redis图片缓存。本轮不迁移数据库、重新导入资料或修改照片。修正及实际验收见spec/feature_20261111_F001_ui-regions/wiki-region-classification-fix.md。

0.10.0增加私有账户、首次强制改密、单会话替换及HTTPS。管理操作仅服务器CLI；持久鉴权数据库独立于0004图鉴库，无图鉴迁移/重导。发布脚本在实际镜像内执行禁网测试，失败维持503门禁；证书每12小时检查续签，账户与恢复命令见[鉴权运维](auth.md)。身份信息和会话不存Redis，缓存命中也须先鉴权。鉴权启用时浏览器资源统一private,no-store，服务器Redis与磁盘缓存继续有效。


0.11.1增加高达独立表与17种模型规格、39个作品索引。来源为万代中文官网，排除配件品牌与独立配件，四种售卖分类取官方筛选结果。模型列表不下发图库，详情才读取全部原图与详细图；价格缺项不估算。

升级命令（仅本项目，显式迁移模式）：

```sh
python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.11.2 --reason 'Gunpla model catalog with complete product galleries' --migrate --import-gunpla /opt/dual-catalog/data/artifacts/gunpla-source/catalog.json
```

发布器先对实际镜像禁网测试，停本项目写入并在backups/gunpla-时间目录冻结采集快照、备份两套PostgreSQL和SQLite鉴权库，随后两库升级0005、仅生产导入模型。已有账号指纹须一致。迁移失败保留maintenance关闭与备份，不自动回退0004镜像或降库；按日志修复后用0005镜像继续恢复，再运行prepare_auth.py gate --mode open检查后开放。

每周日上海03:30由dual-catalog-gunpla-sync.timer启动增量采集，镜像取当前APP_IMAGE。每来源串行2秒，HTML检查点与文件锁避免重复全量，7天重核详情，单项失败保留旧记录。覆盖报告在data/artifacts/gunpla-source/catalog.json，status=running/partial不代表完整。原始HTML仅私有目录保存。

发布只等待最多180秒的首屏封面、规格图标与样例图库预热；完整封面/图库由已有cache-warmer在后台继续。磁盘缓存30天、Redis热点24小时，不清空旧图片。通过systemctl list-timers dual-catalog-gunpla-sync.timer及docker logs --tail 2 dual-catalog-cache-warmer-1核对真实进度。公网入口/preview/gunpla.html沿用私有登录与可信HTTPS；微信正式发布仍待AppID和域名。

0.11.2采集频率：多美卡以2026-01-01 03:00为固定相位每48小时执行，跨月及重启均不重置间隔，2026-11-11部署时核对下次为2026-11-13 03:00（北京时间）。高达改为每周日03:30，当次核对下次为2026-11-15 03:30；systemd timer通过install_timer写入并重启生效，未来重装不会恢复为每日。宝可梦自动任务停用；当前无待执行/运行任务及待重试项。手动管理命令、历史资料与图片缓存预热保留。服务器独立执行，不依赖用户电脑或Codex后台在线。


公网防爬只修改本项目Nginx入口，不修改应用镜像、采集频率或图片缓存。以每个真实连接IP计算：普通图鉴API 8次/秒、突发24；图片30次/秒、突发240；登录6次/分钟、突发5；总入口60次/秒、突发400；同时处理最多40个请求。超限返回429并保留上游原有Retry-After，代理产生的429给出10秒重试提示。健康检查、robots和HTTP ACME校验不占上述入口额度；内部采集与cache-warmer直连8092，不经过公网限流。

已知搜索/批量爬虫标识返回403，robots.txt声明全站Disallow，响应增加X-Robots-Tag。标识拦截不能识别所有伪装客户端，实际数据继续依赖现有登录鉴权；不采用国家/地区封锁或固定IP白名单，保留手机及公司网络访问。拦截和限流行为进入原访问日志，新增request_limit、connection_limit、known_crawler字段，不记录Cookie或密码。

防爬配置先通过同版本真实Nginx的隔离端口测试（哑上游，不向正式接口发送压力请求），再备份并保持文件inode热加载；语法、健康、鉴权或爬虫检查失败会恢复原配置，仅操作dual-catalog-preview-proxy。

```sh
python3 /opt/dual-catalog/app/scripts/verify_crawler_defense.py
python3 /opt/dual-catalog/app/scripts/prepare_crawler_defense.py
```

隔离验证临时监听127.0.0.1:18080/18443，结束删除测试容器；真实证书只读挂载。发布回执在artifacts/acceptance/crawler-defense-deployment.json，限流验证在crawler-defense-shadow.json。已备份的原配置在backups/crawler-defense-*，无需重启应用、改数据库或停用缓存。
