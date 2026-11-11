# 高达模型图鉴实施计划

**目标：** 增加私有高达模型图鉴，官网完整模型规格、四类售卖、年代作品、全图库和左右预览。

**技术栈：** FastAPI/SQLAlchemy/Alembic、PostgreSQL、Redis、原生JS/微信小程序、受限HTTP采集。

**设计文档：** D:/poke&Tomy/spec/feature_20261111_F003_gunpla-catalog/spec-design.md


---

## 改动总览

新增独立官方解析/断点采集、GunplaEntry单表与0005迁移、私有API与复用图片缓存、独立网页和微信两页。依赖为Task1→Task2→Task3→Task4；Task1的同一受限真实爬虫在Task2/3编码期间持续运行，运行中快照可先导入，Task5必须读取其终态并导入最终快照。旧二类页面状态机、账号、图片身份和插件保留；高达新API/图片仍鉴权。Task 5第一项完整本地套件由Task 4发布前执行并记入同一检查项；Task 5其余终态/公网检查在发布后执行。所有全套回归、爬虫终态与公网实测由Task 5统一汇总，不重复完整抓取、同代码的全套测试或镜像测试。

### Task 0: 环境准备

**背景:**
现有工具与既有图鉴均已运行，本Task只核对范围、来源和回归基线，不新增业务逻辑；后续Task据此实施与部署。

**执行步骤:**
- [x] 确认源码与既有说明、用户两次范围修正以及年代选择；spec/global目录不存在，不引入新的全局规范。
- [x] 核对官网robots允许、21品牌排除4配件类得17模型品牌、39作品、官方四类筛选、3425四图及3027十图；核对服务器可访问官网/CDN且应用角色有public CREATE权限。
- [x] 核对当前分支main、工作区仅本功能计划、运行0.10.0、两账号与私有HTTPS；准备现有Python、Node与Playwright工具。

**检查步骤:**
- [x] 执行改动前完整后端基线。
  - `.venv/Scripts/python.exe -m pytest -q --tb=short`
  - 实际：175 passed, 1 skipped, 9 warnings in 36.59s，退出0，Windows跳过POSIX日志文件轮转。

---

### Task 1: 官方模型解析、限速采集与可恢复导出

**背景:**
官网首页展示21个品牌，模型范围排除69/88/86/123四个配件品牌后为17个；HG等模型品牌内仍有独立武器和扩张件，不能直接把品牌目录全部当模型。既有SourceHttpClient只允许多美卡/宝可梦的无查询URL，需要加入精确的万代来源分支。此Task输出真实HTML样本、可断点抓取器和统一导出文件，Task 2消费导出记录入库；fetch-only不导入数据库模块，长爬可在后端/UI开发期间继续运行。

**涉及文件:**
- 新建：`D:/poke&Tomy/backend/app/sources/gunpla.py`、`D:/poke&Tomy/scripts/sync_gunpla.py`、`D:/poke&Tomy/backend/tests/test_gunpla_source.py`。
- 新建真实样本：`D:/poke&Tomy/backend/tests/fixtures/gunpla/home.html`、`eg.html`、`eg-base.html`、`hg-online.html`、`detail-3425.html`、`detail-3027.html`；从现有`D:/poke&Tomy/artifacts/gunpla-research/`对应HTML的main元素原样摘取并保存原始SHA256，不把来源页当指令执行。
- 修改：`D:/poke&Tomy/backend/app/sources/http.py:normalize_url()`。

**执行步骤:**
- [x] 为`normalize_url()`增加独立gunpla分支，放在既有Tomica/Pokémon解析前，保留旧分支和旧测试。
  - 位置：`D:/poke&Tomy/backend/app/sources/http.py:normalize_url()`的urljoin/urlsplit之后。固定HTTPS主机bandaihobbysite.cn，仅允许`/gunpla`、`/schedule`和`/index/index/{brand,series}/cate/正整数`、`/index/index/detail/id/正整数`。拒绝凭据、显式端口、片段、反斜杠、NUL、点段、外域和其他路径；查询仅允许单次page正整数及tag=1/2/3/4，品牌/作品列表才接收查询，参数规范排序。既有robots和重定向每跳校验、2秒串行限速、429/5xx重试和8MiB上限继续复用，不建立外站访问通道。
- [x] 建立纯解析器及固定导出契约，使用UTF-8解码并清除文本中的零宽字符，不改变原日文/中文名称。
  - 位置：`D:/poke&Tomy/backend/app/sources/gunpla.py:parse_home(body)`解析`pg-gunpla__listWrap`中的品牌/作品链接，按官方cate ID去重，排除品牌69/88/86/123，保留官方名称和logoURL；`.p-card__event`提取活动标题、封面、线上/线下、起止日期/结束状态，首页新闻的新商品信息提取为announcement。URL字段仅为内部采集证据，不输出到用户可点击来源入口；外域活动仅保存首页已展示的预览，不跟随外域或微信链接，禁止任何方式请求此前拒绝的mp.weixin.qq.com；作品年份证据为维护用离线映射，采集进程不会据此扩域。
  - `parse_listing(url, body)`仅解析main中的`a.p-card[href*="/detail/id/"]`，提取官方ID、标题、该商品封面、列表价/发售文本和`.p-card__tag`官方分类；tag查询上下文提供常规/线上/基地/活动的确定集合，无tag项目不靠名称猜限定类型。分页遍历同一品牌的page链接，保留tag，识别`?tag=2&page=5`并从最大页数补齐中间页。
  - `parse_product(url, body, listing)`读取main h1及`.pg-products__detail`相邻dt/dd；只提取人民币价格原文、日元价格原文、发售原文与排序字段/精度。价格未刊登为null，月级日期保留年月，不换算、不补造日。主图库取`.js-swiper__main a.swiper-slide[data-fancybox="gallery"]`的href并按顺序去重；正文详细图仅取`.pg-products__instruction img`。排除缩略重复、相关推荐、品牌/作品logo、页脚和二维码，封面继续采用该ID列表卡片的cover_url，不替换成其他角度。
  - 导出顶层固定`schema_version=1, entries, coverage, errors`；entry固定`kind, source_key, name, data`。product的data至少包含`official_id, brand_ids, series_ids, sale_types, cover_url, gallery_urls, detail_image_urls, price_cny_text, price_jpy_text, release_text, release_precision, release_sort, scale, source_url`，URL仅作内部资料；品牌/作品保留官方ID、名称、logoURL，作品年代由Task 2核实映射，不能从商品日期推导。Task 2负责将这些URL注册ImageAsset并返回受保护图片地址。
- [x] 为模型本体建立独立排除函数，记录排除原因并保留可复核清单。
  - 位置：`D:/poke&Tomy/backend/app/sources/gunpla.py:is_model_product(product, allowed_series_ids)`。先排除四类配件品牌，再用官方作品关系排除非高达作品；独立水贴/底座/支架/骨架/LED/武器套组/扩张零件包根据明确商品名与品牌关系排除。配件关键词只匹配“独立配件商品”的完整模式，不对名称中任意“武器/附属品”子串一刀切；模型本体含武装、模型与配件组合、MGSD/SDCS/BB战士等完整模型继续保留。排除结果写coverage.excluded并注明官方ID/名称/reason，未识别条目进入errors，不伪装成成功模型。
- [x] 创建可恢复的受限采集CLI，先导出后入库，并将所有持久文件限定项目artifacts。
  - 位置：`D:/poke&Tomy/scripts/sync_gunpla.py:main()`提供`--fetch-only`、`--import-file FILE`、`--output FILE`、`--directory DIR`、`--mode full|incremental`和用于样本检查的`--limit N`。默认原始HTML/manifest/导出位于Settings.artifact_dir的同级gunpla目录；fetch-only与解析模块只用来源HTTP/标准库，不提前导入Task 2的模型和Repository。import-file在分支内延迟导入Task 2入库入口；普通同步完成抓取后使用同一入库入口。
  - 抓取次序：gunpla首页→17品牌未筛选目录与四类tag目录的完整页集合→按官方ID去重的商品详情。来源URL通过normalize_url校验，robots实测允许，所有网络仍交给SourceHttpClient；不沿“相关商品”扩散。未筛选目录与四类目录ID的差集写覆盖报告，未知销售类型保留为未确认，不强行归常规；同一ID的品牌和分类合并，详情只抓一次。
  - 以规范URL摘要命名原始HTML及元信息；保存ETag/Last-Modified/content_hash、列表语义摘要、详情成功时间和任务状态。增量重用7天内且列表信息未变化的成功详情，全量刷新详情；304使用已保存body，不用空body覆盖。每个成功页面后原子写manifest和导出快照，重启读取已成功任务；失败记可重试错误并保留旧详情/导出，不清空已发布资料。正式运行互斥仅限本项目gunpla同步，重复启动不产生第二个写入者。
  - 通过现有audit写collection的开始/页面失败/条目变化/完成事件，参数包含source=gunpla、官方ID、计数和变更字段，禁止写凭证/图片字节或全文正文。coverage至少给17品牌、每品牌计划/成功页、未筛选/分类ID数、模型/排除/未确认数、详情/图库图数、失败清单、limited和complete；limited或errors不计完整。输出进度和文件路径，Windows终端UTF-8，不输出整份HTML。
- [x] 为解析、过滤、URL边界及断点采集编写单元测试。
  - 测试文件：`D:/poke&Tomy/backend/tests/test_gunpla_source.py`，复用真实fixtures与httpx.MockTransport/临时时钟/临时目录，测试不联网。
  - 场景：首页21品牌→17模型品牌，重复8品牌不重复；配件品牌/独立武器/LED/骨架被排除，含武装或附加部件的完整模型保留；非高达作品不混入。
  - 场景：官方tag=1/2/3/4与卡片badge一致、同ID跨品牌/分类去重合并，tag分页2至末页不丢；出域/乱序/重复page/tag、端口、编码点段和跨域重定向被拒绝，既有Tomica/Pokémon仍按旧规则。
  - 场景：3425恰好4张图库、3027恰好10张图库，顺序与官方一致；列表封面与主图库不同URL仍分别保留，正文图去重且相关推荐不混入；3425人民币价格null，3027为60元/1,100日元(含税)，2025年10月不生成可见1日。
  - 场景：断点重跑不重抓成功任务、304复用body、列表变更使详情重查、7天详情过期、失败保留旧数据、limited/失败报告不标complete、并行第二个同步被拒绝；fetch-only在未创建GunplaEntry模型前仍可执行。
  - 运行命令：`& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_gunpla_source.py D:/poke&Tomy/backend/tests/test_sources.py -q`；预期：退出0，当前解析与既有来源边界全部通过。

**检查步骤:**
- [x] 验证源码可编译且采集CLI独立启动。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m py_compile D:/poke&Tomy/backend/app/sources/gunpla.py D:/poke&Tomy/backend/app/sources/http.py D:/poke&Tomy/scripts/sync_gunpla.py`
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' D:/poke&Tomy/scripts/sync_gunpla.py --help`
  - 预期：各退出0，CLI列出上述入口，不要求数据库连接或Task 2表已存在。
- [x] 运行来源及断点行为回归。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_gunpla_source.py D:/poke&Tomy/backend/tests/test_sources.py -q`
  - 预期：退出0，17品牌、四类分类、正反配件、图库/价格日期与HTTP边界断言全部通过。
- [x] 启动唯一真实全量采集并核验运行状态，终态覆盖检查仅由Task 5承担。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' D:/poke&Tomy/scripts/sync_gunpla.py --fetch-only --mode full --directory D:/poke&Tomy/artifacts/gunpla-source --output D:/poke&Tomy/artifacts/gunpla-source/catalog.json`
  - 预期：使用终端工具启动长命令并保留会话/PID，取得该进程的非空运行中manifest/进度、源=gunpla及预期目录后，本项仅标记“启动验证”完成，进入Task 2/3继续开发。17品牌最终逐页成功/失败、命令退出码与complete由Task 5等待同一进程核验；启动不等于采集完整，不另起一轮全量、不取消或以limited冒充完整。服务端旧镜像挂载新sources/sync脚本的等价启动由主执行者选定后记录实际命令，不同时启动本机与服务端两个爬虫。


---

### Task 2: 高达资料持久化、独立查询与私有图片缓存

**背景:**
Task 1导出真实的品牌、作品、商品、活动与公告；现有CatalogRepository.catalog_rows()只支持多美卡和宝可梦，不能把第三类传给该二选一分支。新增独立GunplaRepository和JSON资料表，复用现有业务修订、响应缓存和私有图片端点，供Task 3两端展示以及Task 4导入/预热；0005仅增加新表，既有图鉴与认证库不改写。

**涉及文件:**
- 新建：`D:/poke&Tomy/backend/app/gunpla.py`、`D:/poke&Tomy/backend/migrations/versions/0005_gunpla.py`、`D:/poke&Tomy/backend/data/gunpla-series-years.json`、`D:/poke&Tomy/backend/tests/test_gunpla.py`。
- 修改：`D:/poke&Tomy/backend/app/models.py`、`D:/poke&Tomy/backend/app/main.py`、`D:/poke&Tomy/backend/app/repository.py`、`D:/poke&Tomy/backend/app/sync/images.py`、`D:/poke&Tomy/backend/app/reference_images.py`、`D:/poke&Tomy/backend/app/auth.py`、`D:/poke&Tomy/scripts/sync_gunpla.py`、`D:/poke&Tomy/scripts/warm_cache.py`。
- 扩展既有测试：`D:/poke&Tomy/backend/tests/test_migrations.py`、`D:/poke&Tomy/backend/tests/test_reference_images.py`、`D:/poke&Tomy/backend/tests/test_images.py`、`D:/poke&Tomy/backend/tests/test_warm_cache.py`、`D:/poke&Tomy/backend/tests/test_auth.py`。

**执行步骤:**
- [x] 新增独立GunplaEntry模型与仅建表的迁移，避免改动旧图鉴实体映射。
  - 位置：`D:/poke&Tomy/backend/app/models.py`的TomicaNews之后增加继承Record/Base的GunplaEntry，表名`gunpla_entries`；字段`kind`（String(20)、索引）、`source_key`（String(120)）、`name`（Text）、`data`（JSON、默认dict）、`content_hash`（String(64)），UniqueConstraint(kind, source_key)。Record沿用id/checked_at/updated_at，不在旧ENTITIES、FieldOverride或Tomica/Pokémon快照中添加高达分支。
  - `D:/poke&Tomy/backend/migrations/versions/0005_gunpla.py`：revision=`0005_gunpla`、down_revision=`0004_tomica_news`，upgrade只建立同列/约束/索引，downgrade只删除gunpla_entries；CatalogRevision的gunpla行由首次导入创建。既有head迁移测试继续执行完整链。
- [x] 明确作品公开年与用户选择的年代分组，未知年份保留独立分组。
  - 位置：`D:/poke&Tomy/backend/data/gunpla-series-years.json`以官网作品cate ID为键，保存已核实的首次播出/公开year及官方证据URL；覆盖首页39作品的映射键；现有核实资料在D:/poke&Tomy/artifacts/gunpla-research/series-year-evidence.json，38项有依据，Crossbone暂归other，不编造年份。官方seriesResponse列表提供影视公开时间；SD三国创杰传用首次海外公开2019，不误用日版2021。未来企划保留计划年份/状态，不把尚未首播说成已首播。证据URL只用于维护，不进入用户API，运行时采集不访问这些额外域名。
  - `D:/poke&Tomy/backend/app/gunpla.py:series_groups()`按year整十年生成1970/1980/1990/2000/2010/2020年代，未知项归`other`、名称“其他企划 / 年代未确认”，组内按已知年份、官网顺序稳定排列。日期来源是作品公开信息，不是模型发售年月；未来首页新增ID落入other，不因缺映射拒绝整个索引。
- [x] 实现导出验证与幂等入库，保护原记录和图片身份。
  - 位置：`D:/poke&Tomy/backend/app/gunpla.py:import_catalog(session, document, changes=None)`接收Task 1的schema_version=1及entries/coverage/errors，只接收kind=`product|brand|series|event|announcement`，保留所有内部source_url、原图URL及coverage证据。product source_key为官网正整数ID，名称非空，brand_ids/series_ids/sale_types取官方导出，sale_types只接受1/2/3/4。拒绝同一kind/key的冲突副本，精确副本不重复创建。
  - 入库前对每条记录做结构与模型范围校验；不合格条目记import_errors且保留该key原记录，导出errors、limited或缺少记录不触发删除旧资料。对有效记录采用保存点隔离写入失败，收集created/updated/unchanged/failed，事务提交后才写record_created/record_updated审计；日志只含ID、名称、变更字段、source=gunpla。
  - `register_image(session, url)`结构校验只允许HTTPS staticcdn.bandaihobbysite.cn、无凭据/端口/片段/查询及正常uploads/assets路径；不在每次登记进行DNS请求。按source_url先复用ImageAsset，新增id用uuid5(NAMESPACE_URL,url)，保持status/rights_status为既有pending默认，不修改已登记图片的授权/转存状态。product data增加cover_image_id、gallery_image_ids、detail_image_ids，保持Task 1原始顺序与封面独立；brand/series/event封面及logo同样登记。图片下载仍由既有DNS/IP校验执行，不能把外部活动地址登记成图片。
  - 语义hash基于规范的kind/key/name/data，不纳入抓取时间；相同hash计unchanged，变更才更新updated_at。单次有效批次有新增/更新时仅调用CatalogRepository(session).bump_revision('gunpla')，不更改tomica/pokemon/tomica-news修订。
  - `D:/poke&Tomy/scripts/sync_gunpla.py:main()`的import-file及普通同步入库分支延迟导入import_catalog；使用Settings.database_url、事务和既有collection审计，持久化入库统计/失败清单，输出不含完整JSON、凭证或图片字节。fetch-only仍不加载数据库模型。
- [x] 实现独立摘要快照、组合筛选和四个只读接口，不复用二分类的catalog_rows()。
  - 位置：`D:/poke&Tomy/backend/app/gunpla.py:GunplaRepository(session, cache=None)`提供`summary_rows()`、`filters()`、`list_products(query)`、`product(official_id)`、`home(today=None)`；修订读取复用CatalogRepository.get_revision('gunpla')。
  - summary_rows仅投影product的公开摘要：`id/name/brand_ids/series_ids/sale_types/scale/release_text/release_sort/release_precision/price_cny_text/price_jpy_text/preview_image_url`；图片地址由cover_image_id构造`/api/reference-images/{uuid}`。原图URL、source_url、gallery数组、detail_image数组及正文不进入摘要或列表。用CatalogCache.snapshot('gunpla',revision,loader,ttl=600)保留一份摘要，多搜索/页码不积累解码副本，不改旧两个source快照。
  - 新增Pydantic GunplaQuery：mode=`grade|series`默认grade、grade/series为官网正整数ID字符串、sale_type为1/2/3/4或空、scale为metadata中比例或空、q长度最多100、page>=1、limit限定20/40/60/100默认20。非法类型返回既有INVALID_PARAMETERS/422。grade模式应用grade/sale_type/scale/q；series模式应用series/scale/q并显式忽略grade和sale_type，使该作品普通/各种限定统一展示。名称搜索统一大小写/全半角/连续空格，匹配中文、日文及英文名称，不改原名称。
  - 按release_sort倒序、官方ID稳定排序；复制/生成结果列表后排序，不能原地改共享快照。返回`items,total,page,page_size,total_pages,next_cursor:null`，空结果total=0/total_pages=1，超出页码夹到最后有效页，每页无重复。filters返回17品牌、比例、四个固定官方销售类型及series_groups；品牌/作品用保护后的logo图片地址，不返回维护证据URL。
  - product只查kind=product/source_key=id，缺项404；固定公开字段id/name/price_cny_text/price_jpy_text/release_text，cover为受保护地址或null，gallery和detail_images各为有序地址数组，并携带必要分类标签；不把内部source_url、source_image_url或抓取描述展开到JSON。gallery和detail_images分别按原顺序去重，缺价null、月级日期保持原文。
  - home返回首页活动预览与发售预告：活动标题、受保护封面、线上/线下、原起止日期、结束状态；发售预告从模型摘要选择上海时区当月及之后的release_sort，按年月分组，项携带本站product id及封面，保留官网新商品公告标题。月级日期只表示本月计划，不能声称具体日已发售；响应不生成外站链接。
  - 使用APIRouter(prefix='/api/gunpla')与既有get_session/public_cached挂载`GET ''`、`/filters`、`/products/{official_id}`、`/home`；public_cached loader用GunplaRepository(repo.session,repo.cache)，响应/详情缓存分别600秒/86400秒，home缓存参数含上海当前年月以避免跨月旧预告。`D:/poke&Tomy/backend/app/main.py:create_app()`在news_router相邻位置导入并include gunpla.router；保持默认私有中间件和旧路由顺序。
- [x] 仅扩展官方CDN图源及回环读取边界，保持既有图片和鉴权契约。
  - 位置：`D:/poke&Tomy/backend/app/sync/images.py:ALLOWED_HOSTS/validate_image_url()`增加精确staticcdn.bandaihobbysite.cn，新主机只接受HTTPS，继续拒绝端口、凭据、非公网DNS结果和非图像响应；不添加子域通配或外站CDN。
  - `D:/poke&Tomy/backend/app/repository.py:CatalogRepository._image_metadata()`在现有两站之外增加该精确HTTPS CDN引用分支及Bandai署名，继续保留无query/凭据/端口的检查。只让已登记CDN图片获得preview_image_url，旧Tomica路径归一、Pokémon地址与署名逻辑保留。Gunpla公开投影固定使用受保护preview地址，不公开object-store或source地址。
  - `D:/poke&Tomy/backend/app/reference_images.py:LOCKS`添加新主机独立锁，cached_reference()为其使用Referer=`https://bandaihobbysite.cn/gunpla`；复用现有2秒每源间隔、10MiB上限、格式校验、30天磁盘/24小时Redis和失败旧图保留，不增加SVG/HTML交付。
  - `D:/poke&Tomy/backend/app/auth.py:SERVICE_ROOTS`仅追加`/api/gunpla`，保留loopback+GET/HEAD+constant-time服务令牌要求；PUBLIC、注册、管理API、密码和Cookie规则完全不变。同文件document_request()的固定HTML路径集合增加/preview/gunpla.html，使不带Sec-Fetch-Dest的直接访问也303到/login/?next=原路径；该页面绝不加入PUBLIC，JS/CSS和API仍返回401。匿名/旧会话访问新接口、CDN映射原图及高达静态页仍在缓存前被拦截。
- [x] 将新模型详情和封面加入现有预热，复用原图字节与凭证限制。
  - 位置：`D:/poke&Tomy/scripts/warm_cache.py:build_manifest()`读取GunplaEntry中kind=product的官方ID/cover_image_id，将封面纳入covers和稳定order，详情端点追加`/api/gunpla/products/{official_id}`。所有登记的图库/正文图/活动/品牌logo继续经现有ImageAsset遍历、规范source_image_url去重和分源队列纳入；不复制照片或建立第二份图像缓存。
  - 保留旧Tomica/Pokémon详情次序、优先封面规则、每host分组、失败重试/报告及仅loopback发送服务头；不要清空原Redis或重置已有图片。报告仍实际记录ready/failed/running，Task 4在导入结束后恢复/重启本项目warmer让其发现新增登记。
- [x] 为持久化、公开投影、筛选、迁移和安全缓存编写行为单元测试。
  - 测试文件：`D:/poke&Tomy/backend/tests/test_gunpla.py`。复用SQLite session、test_api.client及MemoryRedis；用Task 1真实解析结果导入3425/3027，加少量明确标为合成的分类/分页边界记录。覆盖重复导入不新增/不改修订；字段或图库变更只更新gunpla修订；同URL复用已有ImageAsset ID、顺序保留且rights_status不被批准；坏entry/失败采集不抹掉旧记录，旧Tomica/Pokémon/新闻与认证不改写。
  - 验证17模型品牌、39官网作品metadata、核实年代/unknown组、4分类、普通+多种限定的作品联合查询、grade/scale/q交叉、各页20/40/60/100边界及无重复、并发查询不原地改变快照。用SQL事件计数证明翻页/换筛选复用一份摘要；列表/filters/home不含来源/主图库URL，详情4/10图正确且原图均是受保护地址，null价格与月日期不造数据，跨月home缓存键不同。
  - 扩展`D:/poke&Tomy/backend/tests/test_migrations.py`：从0004保留既有Tomica/Pokémon/新闻记录→upgrade head得到gunpla_entries及0005→只downgrade至0004后旧记录仍在→再次upgrade可用，不修改历史断言。
  - 扩展`D:/poke&Tomy/backend/tests/test_images.py`及`test_reference_images.py`：新CDN允许HTTPS公网地址、缓存保持原字节/正确Referer且重读不联网，拒绝HTTP新CDN、伪子域、端口/私网解析/HTML/SVG，旧两站用例继续通过。
  - 扩展`D:/poke&Tomy/backend/tests/test_warm_cache.py`：高达封面先于高达正文图、重复URL只取一次、完整model详情路径纳入、只有旧资料时既有顺序/计数断言保持。扩展`D:/poke&Tomy/backend/tests/test_auth.py`：匿名/旧会话不能读新接口或命中图片缓存，不带Sec-Fetch-Dest直读/preview/gunpla.html为303且next保留，而gunpla.js/gunpla.css为401；正确服务令牌仅loopback GET读高达，非loopback/错误令牌/POST/auth/admin均拒绝。
  - 运行命令：`& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_gunpla.py D:/poke&Tomy/backend/tests/test_migrations.py D:/poke&Tomy/backend/tests/test_reference_images.py D:/poke&Tomy/backend/tests/test_images.py D:/poke&Tomy/backend/tests/test_warm_cache.py D:/poke&Tomy/backend/tests/test_auth.py -q`；预期：退出0，新核心逻辑和对应历史安全/图片用例通过，不联网或读取生产库。

**检查步骤:**
- [x] 验证新增模型、接口与入库入口可编译。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m py_compile D:/poke&Tomy/backend/app/models.py D:/poke&Tomy/backend/app/gunpla.py D:/poke&Tomy/backend/migrations/versions/0005_gunpla.py D:/poke&Tomy/scripts/sync_gunpla.py D:/poke&Tomy/scripts/warm_cache.py`
  - 预期：退出0，入口完整，fetch-only与入库分支依赖分离。
- [x] 运行资料、迁移、缓存与认证的目标行为回归。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_gunpla.py D:/poke&Tomy/backend/tests/test_migrations.py D:/poke&Tomy/backend/tests/test_reference_images.py D:/poke&Tomy/backend/tests/test_images.py D:/poke&Tomy/backend/tests/test_warm_cache.py D:/poke&Tomy/backend/tests/test_auth.py -q`
  - 预期：退出0，图库与无来源投影正确，独立修订/分页/年代组合正确，0005升级和回退只影响新表，旧图片/鉴权无回归。
- [x] 验证独立品牌源不会流入旧二分类仓储。
  - `rg -n "catalog_rows|snapshot|gunpla|SERVICE_ROOTS" D:/poke&Tomy/backend/app/gunpla.py D:/poke&Tomy/backend/app/auth.py D:/poke&Tomy/scripts/warm_cache.py`
  - 预期：gunpla使用自身summary_rows及snapshot('gunpla',...)，warmer旧两类仍调用原catalog_rows，内部边界仅增加精确/api/gunpla；结构检查不替代上项行为测试。


---

### Task 3: 独立高达网页与微信原生入口

**背景:**
Task 2已约定品牌/作品/比例/销售类型索引、分页摘要、全图库详情及左右预览。旧app.js只识别两个kind且包含已验证的位置恢复状态机，本Task只追加第三导航链接并建立独立高达页面，防止高达条件污染旧图鉴。网页和微信均继续通过现有会话及受保护图片读取；真实微信发布不在无AppID条件下伪装完成。

**涉及文件:**
- 新建：`D:/poke&Tomy/backend/preview/gunpla.html`、`D:/poke&Tomy/backend/preview/gunpla.js`、`D:/poke&Tomy/backend/preview/gunpla.css`、`D:/poke&Tomy/scripts/verify-gunpla.cjs`。
- 新建：`D:/poke&Tomy/miniprogram/lib/gunpla-pages.js`、`D:/poke&Tomy/miniprogram/tests/gunpla.test.js`，以及`D:/poke&Tomy/miniprogram/pages/gunpla-list/index.js`、`index.json`、`index.wxml`、`index.wxss`和`D:/poke&Tomy/miniprogram/pages/gunpla-detail/index.js`、`index.json`、`index.wxml`、`index.wxss`。
- 修改：`D:/poke&Tomy/backend/preview/index.html`、`D:/poke&Tomy/miniprogram/app.json`。旧`D:/poke&Tomy/backend/preview/app.js`、两类列表/详情、`miniprogram/lib/page-factory.js`及既有图标不修改。

**执行步骤:**
- [x] 在独立高达HTML中复用既有壳、会话控件与圆角视觉，并只给旧网页增加第三入口。
  - 位置：`D:/poke&Tomy/backend/preview/index.html`的侧栏nav中，在宝可梦按钮后追加`<a class="nav-item" href="gunpla.html">高达模型</a>`，保留所有原id、图标路径和data-kind按钮。新`gunpla.html`侧栏三项分别链接`index.html?catalog=tomica`、`index.html?catalog=pokemon`及自身，避免把gunpla传给旧route/selectKind。
  - 新页加载现有style.css/theme.css、自己的gunpla.css及auth-client.js/gunpla.js；保留`account-controls/auth-status/session-user/change-password/logout`五个鉴权ID。新脚本启动等待CatalogAuth.ready（恢复顺序在本页手动控制），API请求使用same-origin Cookie，401及PASSWORD_CHANGE_REQUIRED调用CatalogAuth.expire，禁止在URL、storage或控制台保存密码/Cookie。
  - `gunpla.css`只作用于新页专属body/class；蓝/青主题、柔和圆角与机械网格背景使用CSS完成，保留旧图标和官方原图。桌面产品卡片5列，默认20条；封面容器固定比例、overflow hidden、图片width/height 100%、object-fit:cover，无内边距或空白背景框。手机自适应列数、工具栏折行，所有控件和弹层不产生横向溢出。
- [x] 实现规格/作品互斥筛选、同页分类和独立分页状态。
  - 位置：`D:/poke&Tomy/backend/preview/gunpla.js`维护mode/grade/series/sale_type/scale/q/page/limit/items/loading/sequence；GET `/api/gunpla/filters`消费Task 2的brands、scales、sale_types、series_groups，ID统一作为字符串使用；列表只消费`id/name/preview_image_url`及摘要分类字段，不请求每款详情来画卡片。
  - 规格模式固定显示官网四类标签：常规商品1、线上售卖2、高达基地限定3、活动限定4；默认sale_type=1。品牌选择取全部17个模型品牌，比例独立选择，点击品牌/分类/比例/名称重置page=1并原地刷新卡片，不执行location跳转；换页不重置筛选。每页20/40/60/100，页码夹到API实际返回page，空结果有可重试/重置反馈。
  - 作品模式打开本站dialog作品选择器，用series_groups渲染1970年代至2020年代及“其他企划 / 年代未确认”分组和官方logo；不从商品年份推算。点作品关闭选择器并设置mode=series、series=id、grade=''、sale_type=''，保留名称/比例以组合查询；本模式隐藏四销售标签，明确由API合并普通与各限定。切回规格清除series并恢复常规标签，保留互斥规则，不把旧作品条件藏在请求里。
  - 每次筛选和列表请求递增sequence、abort旧请求，只有当前sequence可更新items/反馈/页码。新页独立sessionStorage key=`dual-catalog:gunpla-list:v1`保存query/page/limit/scrollY，不写图片字节或登录凭证；pagehide/筛选前及开详情前保存。新页设置history.scrollRestoration=manual，初始恢复等filters/home排版和卡片完成后再按保存位置scrollTo；监听过时响应不得覆盖新选择或新的滚动位置。旧两个图鉴的storage key不读取、不清除。
- [x] 实现完整商品图库详情及独立放大查看器，不加入来源和额外字段。
  - 位置：`D:/poke&Tomy/backend/preview/gunpla.js:openProduct(id)`请求`/api/gunpla/products/{id}`，固定使用Task 2字段`id/name/cover/gallery/detail_images/price_cny_text/price_jpy_text/release_text`，其中cover为受保护地址或null，gallery与detail_images为按官方顺序排列的地址数组。卡片封面与gallery第一张不同仍各自保留，详情不以列表封面替代商品主图库。
  - 商品dialog显示名称、当前大图、全部gallery缩略图及正文detail_images；点击缩略图切换同一产品大图，点击大图/正文图进入contain全图查看器并支持缩放/复位/Escape/居中关闭按钮。保留官方水印，图片错误显示缺图状态，不换成其他模型照片；所有DOM文本escape，不插入官方HTML正文。
  - 仅显示“官方价格（人民币）”“日本地区建议零售价”“发售日期”三项资料，null价显示“未公布”，按原文保留月级日期。不渲染source_url/source_image_url、外站链接、年龄、长描述、相关推荐或额外资料页。两个真实样本3425/3027分别显示4/10个gallery项，detail_images另列且与gallery去重。
  - 用`#product/官方ID`支持详情直达/刷新。打开记录detailReturnY与当前列表快照，关闭只移除当前详情hash并恢复同一筛选/页码/位置；直接详情刷新先恢复列表和侧栏再打开对应商品。放大查看器关闭只关大图，不关闭商品详情或跳首页。作品选择器与活动预览使用各自dialog，不修改商品返回状态。
- [x] 在高达主页面左右展示活动和发售预告，避免迟到内容推移已恢复位置。
  - 位置：`D:/poke&Tomy/backend/preview/gunpla.html`采用左活动预览/中间主内容与目录/右发售预告的专属布局；`gunpla.js:loadHome()`只调用`/api/gunpla/home`，图片尺寸事先占位，初次位置恢复等待该请求完成或明确失败反馈，后续筛选不销毁再建侧栏。
  - 左侧使用API活动title、封面、线上/线下、原日期和已结束状态，全部/线上/线下仅过滤已加载预览；点击打开本站预览dialog展示同一张活动图及已展示资料，不生成官网或公众号跳转。右侧按年月分组显示本月及未来模型计划，项携带官方产品ID，点击走openProduct；公告标题按API提供展示，不虚构尚无模型条目的商品详情。移动端把两预览区折为可展开块并保持固定占位规则，不挤占首屏全部高度或横向溢出。
- [x] 增加两个独立微信页面和第三个tab，保持既有认证与图片下载行为。
  - 位置：`D:/poke&Tomy/miniprogram/app.json`pages追加gunpla-list/index和gunpla-detail/index，tabBar.list第三项指向高达列表；login仍为首page，旧tab顺序/页面/全局private-image配置保留。
  - `D:/poke&Tomy/miniprogram/lib/gunpla-pages.js`导出createGunplaListPage(wxApi)与createGunplaDetailPage(wxApi)，页面index.js只Page(工厂)。通过现有getConfig/createApi.get调用Task 2四接口，不把gunpla传入旧page-factory或旧detail(kind,id)拼接规则。列表具备规格/作品模式、四类标签、年代作品选择、比例/名称、页码与每页数量，原生作品模式同样清空sale_type/grade。
  - WXML所有封面/logo/图库使用private-image，列表mode=aspectFill，详情mode=aspectFit；相对preview图片地址通过当前apiBaseUrl解析成受保护本站地址。详情放大先用api.downloadImage下载同一商品的gallery/detail_images到临时本地路径再wx.previewImage，不裸传远程私有URL，不向外域发送Bearer。
  - 列表onHide只保存当前会话generation的筛选/页码/位置；onLoad读取后重新鉴权加载，详情返回沿现有页面栈保持列表。请求附带sequence和session generation，旧响应/onHide不得恢复已退出会话的资料；onUnload取消任务并取消session订阅，session变化清空当前items/detail。账号名/改密/退出继续复用session/API，退出失败保留会话且提示重试。活动与预告在列表用可折叠区域和本站弹层/商品详情体现，禁止navigateTo外站。
- [x] 为客户端状态、鉴权图片及真实网页验收编写单元与浏览器检查。
  - 测试文件：`D:/poke&Tomy/miniprogram/tests/gunpla.test.js`，使用现有node:test与wx mock调用gunpla-pages工厂。核心场景：规格四类原地切换请求正确；规格→作品清掉grade/sale_type并合并类别，作品→规格清作品；名称/比例联合、页码20/40/60/100与恢复；旧请求/旧会话不回填；详情只消费完整gallery/detail_images且采用受认证本地下载；旧页工厂及API测试原断言保留。
  - 运行命令：`node --test D:/poke&Tomy/miniprogram/tests/gunpla.test.js D:/poke&Tomy/miniprogram/tests/auth.test.js`；预期：退出0，筛选/分页/撤销/图库行为通过，不联网、不假称微信编译。
  - 新建`D:/poke&Tomy/scripts/verify-gunpla.cjs`，参照现有Playwright脚本使用PREVIEW_URL和scripts/browser-auth.cjs的CATALOG_AUTH_STATE。临时验收账户由Task 4服务器运维创建并仅在私有文件内保存随机凭证，浏览器脚本不使用或更改用户两个已有账号；所有新旧浏览器检查共用同一导出session，不各自再次登录造成互踢，Task 5结束撤销并删除此临时账户，不能仅停用后宣称账户不存在。
  - Chrome桌面/WebKit手机检查：17品牌/无四配件品牌、年代选择器、四类原地切换及URL不变、作品模式合并普通限定、名称/比例/分页、封面只有一张并占满固定框、3425四图/3027十图及真实图加载、三资料字段/null价/月日期、无来源链接、左右活动/未来预告、图片viewer/Escape、详情直达/刷新/关闭恢复条件和3像素内位置、侧栏受控延迟、无横向溢出和JS错误。截图保存artifacts/acceptance/gunpla-{desktop,mobile,detail}.png，JSON只存检查名/状态，不输出Cookie/密码或图片字节。
  - 同一脚本检查匿名新页面/新API/已缓存原图受保护，旧token失效由现有认证用例验证；不修改旧27/29/61脚本的断言或3像素阈值，Task 5用同一session分别运行并记录退出码。

**检查步骤:**
- [x] 验证网页/原生控制器及验收脚本JS语法。
  - `node --check D:/poke&Tomy/backend/preview/gunpla.js`
  - `node --check D:/poke&Tomy/miniprogram/lib/gunpla-pages.js`
  - `node --check D:/poke&Tomy/scripts/verify-gunpla.cjs`
  - 预期：各退出0；静态语法通过不等同微信真机验证。
- [x] 执行新增客户端行为与原鉴权回归。
  - `node --test D:/poke&Tomy/miniprogram/tests/gunpla.test.js D:/poke&Tomy/miniprogram/tests/auth.test.js`
  - 预期：退出0，新模式互斥/分页/图片与旧会话保护均通过；不读取真实凭证。
- [x] 在Task 4迁移/导入/开门禁完成后执行真实HTTPS高达验收，并交由Task 5统筹最终旧图鉴回归。
  - 设置PREVIEW_URL=https://117.72.11.77、CATALOG_AUTH_STATE为本机artifacts/private内临时验收会话文件，运行`node D:/poke&Tomy/scripts/verify-gunpla.cjs`。
  - 预期：退出0，桌面/手机各场景和原图真实加载通过，得到非空检查JSON与实际页面截图，不用ignoreHTTPSErrors、不把fixture代替公网图鉴；此项在Task 5统一执行一次，不在服务器尚未发布时空跑或勾完成。


---

### Task 4: 安全迁移、持续采集与私有部署

**背景:**
既有发布器只切镜像，固定0004健康并自动回退旧镜像；高达新增0005，旧0.10.0镜像的健康头不接受0005，迁移后不得自动回退。生产角色dual_catalog_app已实测具有public CREATE权限，两套数据库与持久卷、可信IP HTTPS、两个现有账号及原三个插件均已存在。本Task在Task 1真实原子快照和Task 2/3源码完成后，以显式迁移模式发布0.11.0；完整公网及历史浏览器验收由Task 5统一执行一次。

**涉及文件:**
- 修改：`D:/poke&Tomy/scripts/deploy_release.py`、`D:/poke&Tomy/scripts/prepare_auth.py`、`D:/poke&Tomy/Dockerfile.release`、`D:/poke&Tomy/docs/deployment.md`、`D:/poke&Tomy/docs/auth.md`、`D:/poke&Tomy/README.md`、`D:/poke&Tomy/CHANGELOG.md`。
- 新建：`D:/poke&Tomy/backend/tests/test_gunpla_deploy.py`。
- 扩展：`D:/poke&Tomy/backend/tests/test_audit.py`、`D:/poke&Tomy/backend/tests/test_auth_deploy.py`。

**执行步骤:**
- [x] 扩展既有发布器的显式迁移入口，保留无迁移发布的旧回滚路径。
  - 位置：`D:/poke&Tomy/scripts/deploy_release.py:main()`添加`--migrate`布尔参数和`--import-gunpla`路径参数，导入参数要求同时启用迁移。`validate_import_path()`将指定文件resolve，限定在`/opt/dual-catalog/data/artifacts/gunpla-source`，一次性读取并校验Task 1 schema_version=1、entries/coverage/errors与product记录结构后才进入停机流程；将本次验证的字节/摘要保留在内存，稍后写入本次备份目录的不可变catalog-import.json（0600、10001所有者），作为此次唯一导入输入。拒绝目录穿越、符号链接逃逸及无效JSON，不执行文件内容，不在导入阶段重新读取正由爬虫原子替换的活动快照。
  - `health()`健康头改为0005_gunpla；`D:/poke&Tomy/scripts/prepare_auth.py:verify_private_backend()`同样要求0005，保留双API匿名401、页面到login、原owner仍启用、可信HTTPS检查，不恢复账号数量必须为1的旧限制。不得运行accounts/finalize重置现有两个账号。
  - 保留build/check_image/test_private_image的实际顺序和原禁网完整pytest命令，镜像label必须为0.11.0，测试失败不迁移或导入。显式迁移分支放在真实镜像测试之后、APP_IMAGE更新之前；普通发布分支仍执行既有镜像更新/健康/回滚，不重复构建或跑同一镜像测试。
  - exception分支对args.migrate直接记录migration_release_failed、失败阶段与备份目录，确保maintenance flag存在并抛出非零，不进入旧镜像rollback，不恢复旧APP_IMAGE覆盖已经迁移的数据库；尚未发生迁移的失败也保留门禁及现场供主执行者修复。禁止自动降库、删除新旧表或重新匿名开放。无迁移参数时保留原有deployment_failed/rollback_started/rollback_finished语义及测试断言。
- [x] 为迁移模式增加私有备份、停止写入、迁移及安全导入阶段。
  - 位置：`deploy_release.py:backup_databases()`读取服务器`.env/.env.demo`，复用`prepare_auth.values()/artifacts()`及标准库urlsplit/unquote解析DATABASE_URL。为本次operation_id创建`/opt/dual-catalog/backups/gunpla-<operation_id>`0700目录，备份两份环境配置及当前代理配置0600，记录原APP_IMAGE、原插件container ID与阶段清单，不打印配置值。
  - 在保持maintenance closed的状态停止生产worker/scheduler/cache-warmer及两套API；仅操作Compose项目dual-catalog、dual-catalog-demo。对两个DB分别运行`/www/server/pgsql/bin/pg_dump --format=custom --host <解析值> --port <解析值> --username <解析值> --dbname <解析值>`，命令由参数列表构造，口令仅放子进程env的PGPASSWORD，stdout写0600独占创建的dump文件；使用同目录`pg_restore --list`检验有效性。解析值来自私有配置，不在终端展开或示例硬编码凭证；备份失败立即停止后续阶段。
  - 生产/演示SQLite鉴权库在上述服务停写后，由新镜像的--network none、--user 10001:10001一次性容器运行sqlite3.Connection.backup，源卷分别挂载各artifacts到/app/artifacts，目的为本次备份目录下单独0700且10001所有者的auth子目录并bind到/app/auth-backup。数据库目标文件0600；容器用同UID读取源库并计算账号名/disabled/must_change_password/密码摘要的整体指纹，只输出计数与整体指纹，不输出密码摘要/会话。禁止宿主root直接sqlite连接原库，以免生成root所有者的WAL/SHM；禁止改变原库/目录所有者或权限。迁移与导入不调用任何真实账号增删改命令，重新启动前再用同UID容器比对非会话指纹，核对源库/WAL/SHM权限仍可供10001读取。
  - `migrate_databases(image)`按.env.demo再.env，在新镜像的独立一次性容器使用对应env-file、host网络、10001用户、384MiB及对应artifacts卷执行`python -m backend.app.worker init-db`；两库均须到0005，不向旧图鉴表写入合成数据。仅生产把本次已冻结的catalog-import.json以文件只读bind挂载至/app/gunpla-import.json，再执行`python -m scripts.sync_gunpla --import-file /app/gunpla-import.json`，复用Task 2入库验证；演示只迁移，保留原演示资料。导出缺项/失败不会删除旧记录，回执如实记完整/部分覆盖与导入计数，不以可启动代替完整采集。
  - 完成迁移和生产导入后，沿原发布器仅更新两份.env的APP_IMAGE并保持0600，启动两套API、生产两worker/scheduler，双环境健康0005后恢复warmer，调用bounded_prewarm()，以内部回环GET和现有服务令牌预热当前首屏20个模型封面、17品牌logo、已导入集合与{3425,3027}交集的样本图库，目标URL按源去重，总时限180秒。保留原图片每源2秒规则，失败/超时/尚未导入样本分别写failed/deferred，不伪造命中；该有限预热结束后不等待全站图片缓存终态。检查原插件ID不变及API仅回环8092/8093，再经set_gate('open')检查并开放；回执database_migration=true、data_import=true，附backup目录、冻结导入文件SHA256/coverage摘要与实际image ID，日志仅保留操作元信息。
- [x] 配置高达独立定时增量与保留旧预热行为。
  - 位置：`deploy_release.py:install_gunpla_schedule()`仅在成功的高达迁移发布后创建`/etc/systemd/system/dual-catalog-gunpla-sync.service`和同名.timer，模式0644。service使用Type=oneshot、EnvironmentFile=/opt/dual-catalog/.env、TimeoutStartSec=3h，以`${APP_IMAGE}`读取当前发布镜像，避免将0.11.0固定在未来任务中。
  - service的ExecStart固定为`/usr/bin/docker run --rm --name dual-catalog-gunpla-sync --network host --memory 384m --pids-limit 128 --user 10001:10001 --env-file /opt/dual-catalog/.env -v /opt/dual-catalog/data/artifacts:/app/artifacts --entrypoint python ${APP_IMAGE} -m scripts.sync_gunpla --mode incremental --directory /app/artifacts/gunpla-source --output /app/artifacts/gunpla-source/catalog.json`。仅使用本项目容器名/目录，Task 1文件锁和容器名限制避免重叠抓取；不另建常驻worker、不修改旧scheduler任务或6379/6382 Redis配置。
  - timer使用`OnCalendar=*-*-* 03:30:00 Asia/Shanghai`、Persistent=true，启用前运行systemd-analyze verify及calendar检查；daemon-reload后enable --now该timer，不在本轮额外启动第二轮全量。每日增量复用Task 1的列表变化/7天详情重查、robots、2秒限速、collection日志和失败保留。
  - 首次fetch-only进程在Task 1阶段以旧镜像挂载新source及sync脚本启动；Task 4接收同一进程已完成商品的原子导出快照供首版上线，不重抓。快照coverage保持running/partial真实状态；Task 5等待同一进程终态后再次仅执行import-file增量导入终态文件、重启本项目warmer发现新增，最终完整性只引用该终态报告。Task 2的warmer在导入后启动以主动发现高达封面/图库，使用已有回环服务令牌并保留旧缓存，不清空Redis或reference-images。私有报告仍区分running/partial/ready与源图失败；全站图库预热持续后台执行，不作为首版开门禁的数小时等待条件。
- [x] 更新镜像打包、运维说明与临时验收账户的安全流程。
  - 位置：`D:/poke&Tomy/Dockerfile.release`在现有scripts COPY中加入sync_gunpla.py，label改0.11.0；backend整目录COPY已包含新parser/model/JSON/迁移/测试。源码归档只允许项目源码、vendor、配置样例和文档，排除.env、artifacts、.git、.venv、node_modules、pyc、证书/私钥及凭证，解包先验证路径留在`/opt/dual-catalog/app`且无链接成员；服务器.env永不随包覆盖。
  - `D:/poke&Tomy/docs/deployment.md`补齐显式迁移命令、备份位置、失败门禁恢复及每日timer；`docs/auth.md`仅更新0005与保持原owner规则，不改变两个已有账号；README新增独立HTTPS高达入口与真实范围；CHANGELOG用一条记录新增模型图鉴及采集/分类/全图库，不把采集中写成完整。具体发布命令为`python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.11.0 --reason 'Gunpla model catalog with complete product galleries' --migrate --import-gunpla /opt/dual-catalog/data/artifacts/gunpla-source/catalog.json`。
  - Task 5公网认证使用带本次operation_id随机后缀的独立临时账号，前缀qa-gunpla-acceptance-；创建前记录两个真实账号的非会话指纹并确认新用户名不存在，存在时拒绝覆盖。通过既有服务器CLI create-user --generate写`/app/artifacts/auth/qa-gunpla.json`，下载至本机artifacts/private/gunpla-qa-login.json、比对SHA256后删除服务器明文；不登录或修改两个用户账号。Task 5运行原认证E2E导出同一会话给新旧UI检查后，先用旧storageState保存的Cookie准备撤销校验，再由服务器CLI停用该临时账号、参数化SQL删除私有创建回执中同一精确用户名及其会话，审计记录验收账号清理；真实请求确认旧会话401且临时账号不存在、两个原账号非会话指纹不变后，删除本次私有测试凭证/会话。保留用户原凭证与账号，不按模糊前缀批量删除账号。
- [x] 为迁移门禁、命令范围、定时与旧发布兼容编写单元测试。
  - 测试文件：`D:/poke&Tomy/backend/tests/test_gunpla_deploy.py`，使用临时ROOT和模拟subprocess/文件，不连接生产、不真实迁移。验证build→image test→停止写入/backup→两库迁移→生产导入→切镜像→health005→warmer→open的顺序；镜像测试/备份/迁移/导入各失败不执行后续阶段、flag保留且迁移模式不调用旧镜像回退或降库；无迁移模式保持旧回滚行为。
  - 验证导入路径逃逸/坏JSON拒绝、PGPASSWORD只在子进程env且不进argv/日志、备份0600/目录0700、SQLite备份由10001容器执行且不改变源库/WAL/SHM权限，保留两个账号且不重置；验证活动导出在校验后被替换时仍导入已冻结文件、--import-gunpla参数不会被硬编码catalog.json忽略；有限预热目标/180秒预算/失败和未处理计数真实、保留每源2秒且不等待全图库；演示不导入真实图鉴、仅六个项目进程与独立timer命令；timer读取动态APP_IMAGE、明确上海03:30、无第二次全量与无其他插件操作。
  - `D:/poke&Tomy/backend/tests/test_auth_deploy.py`将受测健康夹具更新0005，新增旧004不能开门禁，保留原owner缺失/停用、管理员多账号、匿名旁路及证书最小挂载断言。`backend/tests/test_audit.py`保留原无迁移发布失败回滚断言，仅同步新增源摘要文件夹具；不得用删除旧用例掩盖回归。
  - 运行命令：`& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_gunpla_deploy.py D:/poke&Tomy/backend/tests/test_auth_deploy.py D:/poke&Tomy/backend/tests/test_audit.py -q`；预期：退出0，所有新发布失败边界与旧回滚/日志/鉴权回归通过。

**检查步骤:**
- [x] 验证发布源码可编译及安全单元回归。
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m py_compile D:/poke&Tomy/scripts/deploy_release.py D:/poke&Tomy/scripts/prepare_auth.py D:/poke&Tomy/scripts/sync_gunpla.py`
  - `& 'D:/poke&Tomy/.venv/Scripts/python.exe' -m pytest D:/poke&Tomy/backend/tests/test_gunpla_deploy.py D:/poke&Tomy/backend/tests/test_auth_deploy.py D:/poke&Tomy/backend/tests/test_audit.py -q`
  - 预期：各退出0，迁移异常保持私有关闭、旧无迁移回滚及两个账号策略均保留。
- [x] 执行Task 5的完整本地套件作为发布前唯一全套门槛，再用实际镜像完成一次迁移发布并取回回执。
  - `python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.11.0 --reason 'Gunpla model catalog with complete product galleries' --migrate --import-gunpla /opt/dual-catalog/data/artifacts/gunpla-source/catalog.json`
  - 预期：REMOTE_EXIT=0，真实构建镜像的禁网完整pytest通过后才迁移，备份有效、两库0005、生产模型可查询、原账号/插件不变；Task 5引用同一发布镜像测试与回执，不重复执行该命令。
- [x] 验证持续采集、预热及可信私有访问的真实运行状态。
  - `systemctl is-active dual-catalog-gunpla-sync.timer dual-catalog-cert-renew.timer dual-catalog-redis`
  - `systemctl list-timers dual-catalog-gunpla-sync.timer --no-pager`
  - `curl --fail https://117.72.11.77/health/ready`
  - `docker logs --tail 2 dual-catalog-cache-warmer-1`
  - 预期：三个服务active、下次任务为上海03:30、健康revision=0005_gunpla且TLS可信；warmer报告真实高达详情/原图进度，未完成/失败不计全部完成。匿名新接口/页面/图片、图库精确映射及最终临时账号撤销由Task 5统一检查。

---

### Task 5: 整体验收与交付

**执行步骤:**
- [x] 阅读同一真实爬虫终态、导入最终快照并刷新高达预热，保存逐品牌/四类/排除项/失败覆盖报告。运行中快照不代表完整；来源错误如实报告，不用取消/limited冒充完成。
- [ ] 在同一临时QA会话执行公网高达及历史27/29/61回归，截图检查桌面与手机；最终撤销并删除本次创建的精确测试账户、校验旧会话401及两个真实账号指纹不变后清理私有测试文件，不改两个真实账号密码或会话。
- [ ] 完成中文acceptance.md、CHANGELOG与部署说明、真实数据/缓存/任务状态，提交并同步已授权GitHub，只包含任务源码及无秘密材料。

**检查步骤:**
- [x] 运行最终完整后端与Node。
  - `.venv/Scripts/python.exe -m pytest -q --tb=short`；`node --test miniprogram/tests/*.test.js`
  - 预期：退出0，保留全部既有断言，报告真实数量及跳过。
- [x] 等待Task 1唯一真实采集进程结束并核对终态覆盖及最终导入。
  - 用原终端会话读取最终退出码；对同一输出文件运行`.venv/Scripts/python.exe -c "import json; p='artifacts/gunpla-source/catalog.json'; d=json.load(open(p,encoding='utf-8')); print(d['coverage']); print(d['errors'])"`；服务端采集时通过SSH读取其同一路径JSON并保存本地回执，禁止额外启动全量。
  - 预期：记录17品牌的计划/成功页、模型/排除/未确认数、所有errors与complete/limited；仅终态无缺口可称完整，源站未完成项如实披露且保留可重试状态。最终使用一次import-file导入该终态快照，并重启本项目warmer发现新增资料，不重复采集。
- [x] 在实际发布镜像内验证完整后端。
  - 由Task4发布器实际build之后、服务启动之前执行`docker run --rm --network none --memory 384m --pids-limit 128 -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python dual-catalog:0.11.0 -m pytest -q -p no:cacheprovider`。
  - 预期：退出0，记录真实镜像ID与终端原始摘要，不再重跑另一镜像充当发布验证。
- [x] 验证真实数据与页面可用性及历史契约。
  - `node scripts/verify-gunpla.cjs`；`node scripts/verify-tomica-display.cjs`；`node scripts/verify-both-catalog-refresh.cjs`；`node scripts/verify-ui-regions.cjs`
  - 预期：可信HTTPS无验证绕过、各退出0，四类原地切换/作品跨类/年代/全图/价格日期/无来源/原图放大/两侧模块/搜索及刷新返回通过；历史27/29/61断言和3px位置标准保持。
- [ ] 核对服务器最终0005、鉴权、持续同步、图片预热及原插件。
  - `curl --fail https://117.72.11.77/health/ready`；`systemctl is-active dual-catalog-gunpla-sync.timer dual-catalog-cert-renew.timer dual-catalog-redis`
  - 预期：ready revision=0005_gunpla，timer/Redis active，匿名高达API和图片401，两个真实账号保留、临时QA不存在、三原插件ID不变、无OOM或异常重启；公开交付页面与真实截图。
