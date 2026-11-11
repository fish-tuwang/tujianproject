# 宝可梦详情补充（2026-11-09）

本轮范围：仅补充宝可梦详情的种族值、获得方式、属性相性、可学招式、招式学习器、普通与异色原图对比，以及必要的采集、存储、展示和验证。

1. 从神奇宝贝百科详情页抽取结构化事实，保留游戏版本、形态、对战规则；不混用不同版本招式，不程序改色。
2. 新建独立 pokemon_details 表和 0003 迁移，大字段仅在单条详情接口读取，保持列表和 Redis 缓存性能。
3. 同步采集加入该详情候选类型；已有 1025 条通过限速串行抓取原页补齐。异色图按同表同列配对，使用本地原图代理及 Redis 缓存。
4. 浏览器和小程序详情增加六个区域，招式与获得方式支持筛选，形态及游戏上下文明确。
5. 运行真实源站快照解析测试、数据库迁移与详情接口测试、浏览器交互和图片解码验证，并回归详情跳转、分类隔离、多美卡分页。
6. 备份后部署公网，记录数据覆盖和实际验证结果，交付可直接访问的详情链接。

不具备小程序 AppID/HTTPS 域名，保留此前已确认的原生发布限制；公网浏览器效果可直接验收。

实现检查：后端78项通过（5条依赖弃用警告），小程序JS14项通过；公网详情18项、导航32项、分页14项、原图14项已实际通过。首次详情浏览器验证在10项后因六尾尚未入库而中断，之后重新运行通过，原始中断记录保留在artifacts/acceptance/pokemon-details-public-first-run.json。皮卡丘和未知图腾多行形态图片的解析缺项已修正，并加入真实快照回归。微信开发者工具编译未执行。

覆盖检查修订：最初核对只检查缺行和已解析记录的结构，曾放行6条相性为空的记录；现已加强为五类资料均需覆盖全部现有编号。6个源页使用繁体章节ID“屬性相性”，已兼容并以0723真实快照回归。初次宽松报告保留为pokemon-details-audit-first-pass.json，不作为最终覆盖证据。

## 最终交付（2026-11-10）

- 部署镜像dual-catalog:0.3.5，迁移0003_pokemon_details，生产和演示服务已升级；项目库迁移前已备份。
- 现有1025条扩展详情全部入库，种族值、获得方式、属性相性、招式表、异色对比各覆盖1025条；1015条有源站所列学习器记录，1532组普通/异色形态配对。
- 首轮1023页成功、286及836号页面连接中断；第二轮仅补抓2页，均成功。原始失败报告保留，未删除成功资料或覆盖基础名称。
- 严格覆盖核对先拒绝6条相性缺项（退出1），兼容繁体章节标题并仅补填6条后，通过逐项1025覆盖核对（退出0，无空项和配对错误）。
- 后端78 passed、5 warnings（依赖弃用）；小程序JS pass14/fail0；公网详情20项、历史导航32项、分页14项、原图14项均通过，退出0。
- 浏览器实测包含第1025号详情、皮卡丘11组、未知图腾28组、阿罗拉、超级进化及繁体章节相性。微信原生编译未执行，仍需AppID和HTTPS配置。

证据：artifacts/acceptance/pokemon-details-public.json、pokemon-details-audit.json、pokemon-details-coverage-rejected.json、pokemon-details-audit-first-pass.json，及pokemon-stats.png、pokemon-shiny-alola.png、pokemon-details-mobile.png。后续源站定时采集沿用同一扩展解析器；只在单条详情读取大字段。

### 终端结果原文节选

工作区D:/poke&Tomy；完整后端命令`.venv/Scripts/python.exe -m pytest backend/tests -q`：`78 passed, 5 warnings in 14.98s`，退出0。`npm test`：`tests 14 / pass 14 / fail 0`，退出0。

`node scripts/verify-pokemon-details.cjs`最终公网结果：`{"status":"pass","mode":"deployed public frontend","assertions":20}`，退出0。历史导航/分页/原图脚本分别32/14/14项，均退出0。

生产API容器执行`python -m scripts.audit_pokemon_details`：五项覆盖各1025、records1025、missing[]、errors[]，status pass，退出0；此前严格检查对6条空相性返回fail并退出1，补填后再次通过。`python -m scripts.verify_cache`：status pass、assertions19，退出0。故意连接无监听端口的降级用例会打印ConnectionError；本项目Redis6382实测正常。

最终健康检查：生产和演示API均healthy；自有Redisactive；原有fish-search、qq-summary-bot、nginx均保持Up6days。一次性抓取和回填容器已清理。
