# 多美卡按月新品推送执行计划

**目标:** 将用户提供的7张原图正确分组入库，在多美卡右侧按月份提供可跳转、可放大的新品展示。

**技术栈:** FastAPI、SQLAlchemy、Alembic、PostgreSQL、Redis、原生HTML/CSS/JavaScript、Playwright。

**设计文档:** D:/poke&Tomy/spec/feature_20261110_F002_tomica-news/spec-design.md


## 改动总览

独立新品表/0004迁移与离线幂等导入承载7张用户原图，复用现有修订号缓存；不改旧图鉴身份或远程图片白名单。
Task 1提供真实月份与原图API，Task 2基于该契约扩展现有页面路由/查看器；车型下方列表宽度保持不变。
本地独立SQLite API使用真实公开图鉴数据只读副本验收；Acceptance备份本项目库后迁移和导入，再验证公网。
公众号未启用联网采集，本轮素材来源明确为用户上传；线上后台图鉴缓存会在部署后继续运行。

---

### Task 0: 环境准备

**背景:**
沿用现有Python/Node/Chrome工具链，确认既有迁移测试可运行，为后续新品实现提供环境与旧数据基线。
本Task不创建业务代码；Task 1完成后，由Task 2的独立脚本准备SQLite与真实本地API验收资料。

**执行步骤:**
- [x] 检查Python、Node和Chrome可用。
  - `& .venv/Scripts/python.exe --version`、`node --version`、`Test-Path 'C:/Program Files/Google/Chrome/Application/chrome.exe'`
- [x] 核对并运行既有迁移单元测试作为环境与旧数据基线。
  - `& .venv/Scripts/python.exe -m pytest backend/tests/test_migrations.py -q`
  - 预期：既有迁移测试通过；不把尚未建立的新品API当作通过。

**检查步骤:**
- [x] Python、Node、Playwright与Chrome均可用。
  - `& .venv/Scripts/python.exe --version`
  - `node --version`
  - `node -e "require('playwright'); require('node:assert/strict').ok(require('node:fs').existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe'))"`
  - 预期：版本命令成功，Playwright可加载，Chrome文件存在，全部退出码0；此Task不创建或访问尚未实现的新品API。
- [x] 工具链命令与迁移基线实际执行成功。
  - `& .venv/Scripts/python.exe -m pytest backend/tests/test_migrations.py -q`
  - 预期：实际收集并通过迁移测试，退出码0。

---

### Task 1: 新品存储、幂等导入与按月原图接口

**背景:**
当前数据库没有新品月刊，现有图片代理只处理图鉴登记的远程来源；本次7张用户原图需要独立保存，避免串入旧车型或触发公众号联网。
此任务依赖Task 0工具链，为Task 2提供月索引、月刊详情和本地原图，并复用现有修订号缓存、错误响应和模型时间字段。

**涉及文件:**
- 修改：`D:/poke&Tomy/backend/app/models.py`、`D:/poke&Tomy/backend/app/main.py`、`D:/poke&Tomy/backend/migrations/versions/0001_catalog.py`、`D:/poke&Tomy/backend/tests/test_migrations.py`
- 新建：`D:/poke&Tomy/backend/migrations/versions/0004_tomica_news.py`、`D:/poke&Tomy/backend/app/news.py`、`D:/poke&Tomy/scripts/seed_tomica_news.py`
- 新建：`D:/poke&Tomy/backend/data/tomica-news/2026-11.json`、`D:/poke&Tomy/backend/preview/news-assets/`内7个摘要命名的JPG
- 新建：`D:/poke&Tomy/backend/tests/test_tomica_news.py`

**执行步骤:**
- [x] 在`models.py`的多美卡模型区域新增`TomicaNews(Record, Base)`，表名`tomica_news`。
  - 字段：`slug`唯一索引、`archive_month`月份索引、`title`、`source_name`、`source_url`、`content_hash`（64位）、`data`（JSON）；沿用Record的id/checked_at/updated_at，不修改TomicaModel、TomicaVariant或Pokemon字段。
  - 新增`0004_tomica_news.py`，`revision='0004_tomica_news'`、`down_revision='0003_pokemon_details'`；upgrade只创建新品表及索引，downgrade只删除新品表及其索引。
  - 在`D:/poke&Tomy/backend/migrations/versions/0001_catalog.py:upgrade()`的Base.metadata.sorted_tables遍历内，把后续表排除集合从`{'pokemon_details'}`扩为`{'pokemon_details', 'tomica_news'}`，保留既有列/索引排除逻辑。0001从当前ORM动态复制元数据，新表必须排除，否则空库升级会提前创建tomica_news并在0004重复建表；已上线0001不会被重跑。
  - 原因：独立月刊实体承载编辑整理的新品资料，不污染现有图鉴身份和图片关联。
- [x] 按原始字节准备7张素材和唯一的2026-11月刊数据文件。
  - 素材已准备于`D:/poke&Tomy/artifacts/news-source/`；以其中`manifest.json`的附件顺序/原路径/SHA256/大小为核对基准，将7个摘要命名JPG原样复制到`D:/poke&Tomy/backend/preview/news-assets/`，保留水印，不重编码、裁剪或生成替代图。测试编写时将manifest的7个附件序号/摘要/大小固化为独立预期常量，运行测试不依赖Windows附件目录，不以JSON自身作为附件身份的唯一证据。
  - 将`D:/poke&Tomy/artifacts/news-source/2026-11.json`原样复制到`D:/poke&Tomy/backend/data/tomica-news/2026-11.json`作为输入契约：头部为slug/archive_month/title/source_name/source_url，`data={origin:'user-upload',summary,products:[...]}`。固定slug=`2026-11-tomica`，来源名=`多美卡TOMY新品情報`，来源链接=`https://mp.weixin.qq.com/s/QX8hnHK6WcNHEGEqq9U4rQ`；不联网获取文章。
  - 产品字段固定为`id`、`name`、`name_zh`、`number`、`cover_digest`、`summary`、`observations`、`photos`；每张照片保存`digest`和`caption`，cover_digest必须属于本产品photos集合，API根据摘要生成image_url。No.114排首位，id固定`no-114-gardener-truck`，name为`No.114 植木屋さんトラック`，仅关联附件2—6；另两产品id固定`red-rescue-vehicles`和`suv-first-edition`，分别仅关联附件1和7，名称使用设计文档中的中性图片描述。No.114封面沿用JSON的附件3，不强制改为photos首张或附件2。
  - No.114的`observations`仅写可见的白色车体、佐藤造園字样、梯子/木纹板/绿色植栽外观及多视角装载状态；另两组保留JSON中各自可见的救援字样和SUV配色观察。月份是文章归档月，不写精确发布日期、售价或未经提供的车型编号。来源方式记录为用户上传。
- [x] 在`news.py`新增`news_index(session)`、`news_month(session, month)`与本地图片读取辅助函数。
  - `news_index()`按`archive_month`倒序聚合真实存在的月份，同月文章按slug稳定排序，返回`items`；每项含`month`、`title`（首篇标题）、`product_count`（同月所有产品数）、`cover_image_url`和`products`缩略入口（id/name/name_zh/image_url），各产品图片使用自己的cover_digest，月份封面取首篇首产品cover_digest，不返回完整observations与photos。产品ID在同月文章间必须唯一，避免三段深链歧义。
  - `news_month()`返回`month`、`title`和`articles`；每篇含slug/title/source_name/source_url/origin/summary/products，products保留输入字段并为cover_digest与photos生成image_url。No.114完整详情保持5张照片，其余各1张。无记录的有效月份返回None，由public_cached转404；不构造空白历史月刊。
  - 图片读取只使用`ROOT / 'backend/preview/news-assets' / (digest+'.jpg')`；严格校验64位小写十六进制摘要、实际文件存在、SHA256与文件名一致及现有image_type字节签名。路径无用户文件名拼接，不执行HTTP请求。Redis命中的字节也校验签名和SHA256，损坏缓存按未命中处理并用本地原图覆盖。
- [x] 在`news.py`声明`APIRouter(prefix='/api/tomica-news')`，在`main.py:create_app()`注册于已有API路由之后。
  - `GET /api/tomica-news`调用`public_cached(request, session, 'tomica-news', 'index', {}, ...)`，TTL600秒。
  - `public_cached`的loader实参是CatalogRepository，索引用`lambda repo: news_index(repo.session)`，月刊用`lambda repo: news_month(repo.session, month)`；不能直接把news_index/news_month传作loader，否则把repo误当成Session。
  - `GET /api/tomica-news/{month}`使用FastAPI路径参数约束校验YYYY-MM和01—12月份，调用public_cached的独立tomica-news修订号，TTL86400秒；不存在月刊返回404，格式无效返回422。
  - 在月刊动态路由之前定义`GET /api/tomica-news/images/{digest}`。此路由不创建数据库会话，先读`news-image:`加摘要的Redis字节，未命中时读本地原图并set TTL86400；返回实际图片MIME、`ETag`（带引号的摘要）、`Cache-Control: public, max-age=86400`、nosniff及X-Catalog-Cache（redis/disk）。匹配If-None-Match返回304，合法摘要无文件返回404，非法摘要返回422。Redis故障沿用CatalogCache短超时/冷却后备，不影响本地原图交付。
  - 原因：接口与图片都命中本项目缓存，用户浏览新品不再依赖微信或其他源站。
- [x] 在`seed_tomica_news.py`新增`load_articles(directory)`、`import_articles(session, articles)`和`main()`，作为离线月刊导入入口。
  - `load_articles()`先读取全部JSON并完成月份、跨文件slug唯一性、同月产品ID唯一性、头部/data/product必填字段、origin=`user-upload`、cover_digest属于本产品photos、照片摘要/签名和本地文件校验；整批校验结束后才进入数据库写事务。本次月刊照片只引用已复制的7张本地原图。
  - `import_articles()`按slug查询，使用头部元数据及data的`json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(',', ':'))`计算内容摘要，排除数据库id/时间和content_hash本身；首次插入、内容变更更新对应新品行及Record时间，无变化保持updated_at和checked_at。每批有变化仅调用一次`CatalogRepository(session).bump_revision('tomica-news')`；不触碰tomica/pokemon修订号及旧业务表，禁止跨会话单独提交修订号。
  - `main()`读取Settings并用Session.begin事务提交整批导入，随后用当前环境CatalogCache预热所有唯一照片，打印新增/更新/未变化与预热数量；同批再次执行应无新增和更新。使用`python -m scripts.seed_tomica_news`从仓库根目录执行，避免直接脚本运行时找不到backend包。生产/演示连接由服务器各自环境注入，不把凭证写入JSON或日志；本地环境redis_url为空时报告disk-only，不能把未写入Redis的set调用计作成功预热。
- [x] 为新品导入、查询、原图交付与迁移编写单元测试。
  - 测试文件：`backend/tests/test_tomica_news.py`，复用既有SQLite session、TestClient依赖覆盖和内存Redis测试替身。
  - 场景：同一月刊导入两次只生成一行、第二次时间/修订号不变；内容更新仅变新品修订号；坏月份/重复产品ID/缺图或错误摘要在数据库写入前失败；No.114恰好5图，三产品图片集合互斥且总计7图；真实月份倒序索引、未知月404、非法月份422；原图响应与上传附件逐字节一致，首次disk/再次redis、ETag条件304、非法摘要/路径无法读任意文件、Redis不可用仍从本地返回图片；入口不产生远程HTTP调用。
  - `test_original_assets_and_product_groups`使用从`D:/poke&Tomy/artifacts/news-source/manifest.json`固化的独立常量验证附件顺序和哈希；另覆盖name_zh/data.origin/summary保留、封面属于对应photos、重复slug/同月重复产品ID/不属于photos的cover在写入前失败、批次第二条出错整批零写入、多篇同月聚合稳定、Redis坏字节回退磁盘、旧图鉴记录与修订号不变，保证`-k original`能实际收集原图测试。
  - 扩充`test_migrations.py`原有迁移场景：从空库到0003断言tomica_news尚不存在，升级0004后新品表存在且原有Pokemon/Tomica数据保留；降回0003仅移除新品表，再升级恢复结构，保留已有0002往返断言。此项同时覆盖0001动态元数据排除修正，避免只在已有生产库上验证而漏掉全新安装。
  - 运行命令：`& .venv/Scripts/python.exe -m pytest backend/tests/test_tomica_news.py backend/tests/test_migrations.py -q`
  - 预期：新增核心行为与原有迁移回归全部通过。

**检查步骤:**
- [x] 验证模型、迁移、导入及新品接口行为。
  - `& .venv/Scripts/python.exe -m pytest backend/tests/test_tomica_news.py backend/tests/test_migrations.py -q`
  - 预期：全部通过；No.114五图与另外两组互不串位，幂等不更新旧数据，迁移保留已有记录。
- [x] 验证新模块语法和路由注册。
  - `& .venv/Scripts/python.exe -m compileall -q backend/app/news.py backend/migrations/versions/0004_tomica_news.py scripts/seed_tomica_news.py`
  - 预期：退出码0，无语法错误；路由注册由TestClient行为测试实际覆盖。
- [x] 核对7张素材均为不重复的原始文件。
  - `& .venv/Scripts/python.exe -m pytest backend/tests/test_tomica_news.py -q -k original`
  - 预期：原图摘要、字节保留与图片关联相关测试实际执行并全部通过，无全跳过或未收集测试。


---

### Task 2: 右侧月份索引与独立新品详情图册

**背景:**
现有介绍和横幅占满主内容宽度，详情路由仅识别tomica/pokemon；新品需要在介绍区右侧展示月刊入口，复用现有弹窗及放大查看器。
Task 1提供真实月刊与原图API，本Task负责准备独立SQLite/API验收数据与浏览器脚本，保持旧车型列表宽度、五列分页、名称搜索及两个图鉴的隔离契约。Task 0只验证已有工具链，不依赖本Task的准备脚本。

**涉及文件:**
- 修改：`D:/poke&Tomy/backend/preview/index.html`、`D:/poke&Tomy/backend/preview/app.js`、`D:/poke&Tomy/backend/preview/style.css`
- 新建：`D:/poke&Tomy/scripts/prepare_news_demo.py`、`D:/poke&Tomy/scripts/verify-tomica-news.cjs`

**执行步骤:**
- [x] 在`D:/poke&Tomy/scripts/prepare_news_demo.py`新增`copy_fields()`、`prepare()`与`main()`，在页面验收前准备真实本地API所需资料。
  - `prepare()`只对http://117.72.11.77执行GET：读取/api/tomica?page=1&limit=100与page=2，以及/api/pokemon/25和37；不访问管理接口或写入服务器。200条薄资料用于列表/关闭月刊返回与基本旧车详情，Pokemon25/37用于横幅及分类隔离，不复制旧版本/招式大表。
  - `copy_fields()`按TomicaModel/Pokemon实际表列白名单复制公开字段与ID，ISO时间转换datetime；prepare()只建立对应primary ImageAsset记录，source_image_url沿用公开来源，忽略嵌套variants/forms/extra。相关完整旧功能由部署后的公网历史回归验证。
  - `prepare()`唯一写入artifacts/news-demo/catalog.db，显式使用本地SQLite Settings初始化Alembic head，再事务导入薄资料与本月JSON；不使用.env里的数据库/Redis。相同ID不重复插入，保留原图缓存。只预热5个旧封面；其余旧图不作为新品图册验收依据。
  - 用前5条Tomica记录的公开preview_image_url执行GET，将字节按`reference_path(asset_id, source_image_url, directory)`写入上述本地reference-images目录并校验image_type；只预热这5张旧封面，不遍历下载200条全部原图。7张新品原图直接使用Task 1的本地文件；设置空Redis地址，不连接服务器缓存。
  - `main()`默认执行准备并打印本地数据库路径、Tomica=200、Pokemon=2、news=1、news_photos=7与旧封面预热数；`--serve`模式只启动已准备的库，不再次抓取：以`Settings(_env_file=None, database_url=本地SQLite, redis_url='', admin_token='', artifact_dir='D:/poke&Tomy/artifacts/news-demo/acceptance')`创建真实FastAPI实例，用uvicorn仅绑定127.0.0.1:8094。通过后台exec会话运行并记录会话ID，结束验收时只终止此会话。
  - 准备命令：`& .venv/Scripts/python.exe -m scripts.prepare_news_demo`
  - 启动命令：`& .venv/Scripts/python.exe -m scripts.prepare_news_demo --serve`
  - 原因：上线前在独立数据库上验证真实路由/SQL/图片交付，公开服务器仅提供只读资料。
- [x] 在`index.html`的`main`内，仅将现有intro和feature包进`.journal-layout > .journal-main`，并在其后增加`aside#news-sidebar`。
  - `#news-sidebar`包含新品情报标题、`#news-months`月份索引及`#news-highlights`本月产品缩略入口，初始hidden；`section#catalog`和footer继续位于journal-layout之外，原有ID、筛选、每页数量和按钮绑定不变。
  - 静态CSS/JS版本参数更新到0.6.0；不新增第三个图鉴分类、通知权限或微信公众号登录流程。
- [x] 在`style.css`尾部新增只作用于新品布局的规则。
  - `body[data-catalog="tomica"] .journal-layout`在宽屏使用`grid-template-columns:minmax(0,1fr) 280px`、24px间距；新品栏在intro/feature右侧。中小屏改为单列，侧栏排到横幅后、车型列表前。
  - `body[data-catalog="pokemon"] #news-sidebar`强制隐藏，journal-layout保持原单列布局；catalog/cards不放入右栏网格，原有>=1024五列规则保持。
  - 新品弹窗使用`.news-detail-dialog`限定样式，图册采用contain保留全图及水印，移动端单列和可换行产品导航；不覆盖已有image-canvas、close-detail图标居中和图片填满车型卡片的规则。
- [x] 在`app.js`中增加`loadNewsIndex()`（包含索引渲染），接入`selectKind()`。
  - `loadNewsIndex()`请求`request('tomica-news')`，依据Task 1的items（月、product_count、cover_image_url、products缩略信息）渲染真实月份倒序按钮和3组新品入口。月份链接为`#tomica-news/2026-11`，产品链接为相同路径加product.id；标题、来源和说明均经escapeHTML，路由段经encodeURIComponent。
  - 新品标题优先显示保留编号的name，name_zh只作副标题；缩略图使用API从cover_digest生成的image_url，不用photos首张代替封面，不把中文说明替换掉No.114正式名称。
  - `selectKind('tomica')`只启动独立异步新品索引请求，不await它，不复用或中止现有catalog controller；单独的索引sequence在每次分类切换递增，响应仅在序号有效且state.kind为tomica时更新侧栏。
  - `selectKind('pokemon')`立即隐藏新品栏，不发起新品API请求；迟到的索引响应只被丢弃，不能操作detail-dialog或触发路由跳转。新品请求失败只作用于其侧栏，保留车型列表与详情的可操作性。
- [x] 在`app.js`的`openDetail()`之前新增`openNews(month, productId)`（包含月刊详情渲染）。
  - `openNews()`内部渲染按月刊articles读取产品，未指定productId默认No.114，指定ID只选择对应产品；未知ID显示未找到该新品，不静默换成其他车辆。展示月刊标题、产品导航、所选名称/summary、明确标为“图中细节”的observations、对应photos图册和原文来源链接。
  - 原文链接只接受http/https并设置`target='_blank' rel='noopener noreferrer'`；来源说明显示用户上传与图片观察，不显示自动订阅、抓取成功或已联通公众号。
  - 每张图包在`.news-photo`容器中，使用既有imageMarkup与bindImages；No.114恰好5图，红色救援车辆和SUV各1图，不把7图全部挂在No.114。保留caption、原图水印和完整长宽比例，未知售价/发售日不生成事实字段。
  - `openNews()`在请求前递增detailSequence，清空旧弹窗内容并showModal，调用`request('tomica-news/'+encodeURIComponent(month))`；成功和失败均检查捕获的detailSequence以及state.kind===tomica。仅有效响应渲染新品，取消pokemon-detail-dialog样式并添加news-detail-dialog；`renderDetail()`反向移除news-detail-dialog，避免两类详情串样式。
  - 扩展`bindDetailZoom(root)`原选择器，追加`.news-photo img`，保留Enter/空格、100%适配、放大/缩小、Escape只关大图等既有行为。
- [x] 扩展`app.js`的入口分类识别和`route()`，保留全部竞态与返回保护。
  - 初始hash以`tomica-news`开头时initialKind直接为tomica，优先于query中的catalog，避免新品深链先加载宝可梦。
  - `route()`读取`kind/month/productId`三段，tomica-news的next固定tomica；沿用routeSequence、必要的selectKind与await后的有效性检查，再分支调用openNews。tomica/pokemon旧路由仍调用openDetail；`#catalog`保留既有行为。
  - 月份/产品路径段解码用捕获URIError的辅助函数；非法编码显示路由错误并使detailSequence失效。进入openNews或openDetail、切换分类、关闭详情均更新同一个detailSequence，不能各建互不失效的序号。
  - 同分类打开月刊或切换产品不调用selectKind，不清空state.query/page/pageSize；现有close-detail按钮、cancel和backdrop逻辑保持序号失效并回`#tomica`，仅关闭弹窗，不重置筛选或跳回其他分类。浏览器hash历史负责月刊/产品的前进后退与刷新复原。
- [x] 编写真正运行浏览器的新品功能验收脚本，不添加镜像实现的纯函数测试。
  - 文件：`scripts/verify-tomica-news.cjs`；沿用既有Playwright、Chrome路径、assert、pageerror收集、finally关闭浏览器及artifacts/acceptance JSON和PNG输出。
  - `base=process.env.PREVIEW_URL || 'http://117.72.11.77'`；`--local`仅按文件名覆盖本地preview index.html/app.js/pokemon-details.js/style.css，所有API和原图继续请求base对应真实服务。本地API和资料导入由本Task首步准备，PREVIEW_URL设为`http://127.0.0.1:8094`；不以mock新品响应替代真实API验证。race测试只延迟真实请求后route.continue，不伪造响应。
  - 检查：宽屏右栏位于介绍/横幅右侧，目录区域仍独立且20张卡片为五列四行；索引只列实际2026-11；点击月刊默认No.114五图、名称正确，另外两入口各自一图，三组原图摘要分别匹配用户附件2—6/1/7。
  - 检查：月刊与产品深链直接访问和刷新、前进/后退、未知产品不显示其他车型、图片可解码且放大保持同一URL与字节身份，关闭大图不关闭详情；手机390px无横向溢出。
  - 检查：从本地实际filters选择一个有记录的品牌并搜索当前结果中的真实名称，打开新品再关闭后query和控件值不变；另在不限制品牌/搜索的200条本地资料上设置40款、第2页，打开新品再关闭后query/page/pageSize及当前40个ID完全不变。拆开两场景，避免凭空要求前200条中某品牌至少有41款。
  - 检查：宝可梦独立新页面使用25/37真实资料，不显示新品栏且网络记录无tomica-news请求。阻塞新品月刊/索引响应后切换宝可梦或打开旧车型详情，再释放响应，旧数据不能覆盖新详情、关闭弹窗或跳回首页；旧车型详情迟到也不能覆盖已打开的新品。每个page/context均注册本地静态覆盖与pageerror监听，finally释放所有race门闩并关闭浏览器，失败也输出报告。
  - 运行命令：先执行`$env:PREVIEW_URL="http://127.0.0.1:8094"`，再执行`node scripts/verify-tomica-news.cjs --local`；公网验收由Acceptance在独立终端的默认公网base下执行`node scripts/verify-tomica-news.cjs`。
  - 预期：实际浏览器断言全部通过，errors为空，脚本成功退出；原图缓存命中不能被误算为公众号自动采集成功。

**检查步骤:**
- [x] 独立SQLite/API准备完成，健康和公开详情均返回真实资料。
  - 准备命令：`& .venv/Scripts/python.exe -m scripts.prepare_news_demo`
  - 独立后台会话启动命令：`& .venv/Scripts/python.exe -m scripts.prepare_news_demo --serve`
  - 健康命令：`Invoke-RestMethod http://127.0.0.1:8094/health/ready`
  - 资料命令：`Invoke-RestMethod 'http://127.0.0.1:8094/api/tomica?page=1&limit=20'`、`Invoke-RestMethod http://127.0.0.1:8094/api/pokemon/25`、`Invoke-RestMethod http://127.0.0.1:8094/api/pokemon/37`
  - 预期：准备统计Tomica=200、Pokemon=2、新品1篇/7图；健康revision=`0004_tomica_news`，Tomica total=200，宝可梦分别为25/37；所有写入只发生在本地独立目录。
- [x] 验证前端和验收脚本JavaScript语法。
  - `node --check backend/preview/app.js`
  - 预期：退出码0，无语法错误。
- [x] 验证新品浏览器脚本语法。
  - `node --check scripts/verify-tomica-news.cjs`
  - 预期：退出码0，无语法错误。
- [x] 对本Task准备的127.0.0.1:8094真实测试API运行本地前端交互检查。
  - 环境命令：`$env:PREVIEW_URL="http://127.0.0.1:8094"`
  - 测试命令：`node scripts/verify-tomica-news.cjs --local`
  - 预期：右侧月刊、5+1+1原图归属、深链刷新/历史、图片放大、返回保留查询、宝可梦隔离和迟到响应保护全部通过；输出实际JSON与截图，finally结束浏览器进程。


---

### Task 3: 新品推送上线验收

**前置条件:** Task 1/2本地检查通过；服务器现有0.5.1、数据库0003与缓存服务可用；此前用户已授权实现后部署。

**涉及文件:**
- 修改：`D:/poke&Tomy/Dockerfile.release`、`D:/poke&Tomy/CHANGELOG.md`、`D:/poke&Tomy/docs/deployment.md`、`D:/poke&Tomy/spec/feature_20261109_F001_dual-catalog/deployment-state.md`
- 新建：`D:/poke&Tomy/artifacts/deploy_tomica_news.py`（服务器部署/只读核验脚本）、`D:/poke&Tomy/spec/feature_20261110_F002_tomica-news/execution-summary.md`（实际验证与交付证据）

**执行步骤:**
- [x] 先执行本Task第一项端到端验证中的完整本地Python与原生逻辑套件，保存真实输出；全部通过后才执行服务器升级。
  - 本地命令：`& .venv/Scripts/python.exe -m pytest backend/tests -q`、`npm test`；不增加镜像UI实现的纯函数测试。失败回到Task 1/2定位修复，再运行受影响检查。
- [x] 修改`D:/poke&Tomy/Dockerfile.release`的COPY scripts列表加入`seed_tomica_news.py`，LABEL版本改为0.6.0，backend目录整体复制会带入0004、JSON和7张本地JPG。
  - Task 2已统一首页静态资源版本为0.6.0，此处只核对不重复编辑；`D:/poke&Tomy/CHANGELOG.md`追加月刊、正确分组原图与离线导入说明，部署文档更新迁移版本/导入命令/回滚方式。原因：版本和镜像实际内容一致。
- [x] 新建`D:/poke&Tomy/artifacts/deploy_tomica_news.py`，沿用`D:/poke&Tomy/artifacts/deploy_pokemon_details.py`的runuser备份与Compose参数，但把部署顺序固定为停预热→构建→备份→迁移导入→健康→恢复预热。
  - 脚本在服务器`/opt/dual-catalog/app`运行，根目录固定`/opt/dual-catalog`；先保存本项目与已有插件容器的ID/状态、旧镜像ID/版本，执行`docker compose --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog stop cache-warmer`，不删除原图/Redis/缓存目录。
  - 上传包仅含本项目源码、锁文件及vendor wheel，不含.env、数据库、node_modules、.venv或私有缓存；通过既有已认证远程会话传输到`/opt/dual-catalog`并解包到app。脚本调用`docker build --no-cache -f /opt/dual-catalog/app/Dockerfile.release --build-arg BASE_IMAGE=dual-catalog:0.1.0 -t dual-catalog:0.6.0 /opt/dual-catalog/app`；核对镜像LABEL=0.6.0。
  - 为`dual_catalog`和`dual_catalog_demo`分别执行参数数组`['runuser','-u','postgres','--','/www/server/pgsql/bin/pg_dump','-d',database,'-Fc']`，capture_output保存至`/opt/dual-catalog/backups/before-tomica-news-<database>-<本次时间戳>.dump`；备份目录0700、文件0600，使用pg_restore --list验证可读。只输出路径/大小，两个备份均有效后才执行数据库写操作。
  - 对`.env.demo/dual-catalog-demo`和`.env/dual-catalog`两组更新APP_IMAGE为0.6.0并保持0600；各以既有Compose基本参数加`run --rm --no-deps api python -m backend.app.worker init-db`升级0004，再用`run --rm --no-deps api python -m scripts.seed_tomica_news`导入两次。第二次必须新增0/更新0/未变化1，断言新品行时间与tomica-news修订号不变；导入前后旧表ID均保留。禁止在192MiB常驻api容器内额外启动验证Python进程，迁移、导入和SQL核验都用独立一次性容器。
  - 演示项目仅`up -d api`；生产先`up -d --scale worker=2 api worker scheduler`，轮询8092/8093的health/ready均为0004后再`up -d cache-warmer`。保持独立Redis6382、原6379、插件和已有队列，记录预热进度文件而不把running记为全量完成。
  - 增加`--check`只读核验模式，借助一次性容器查询两个库的alembic版本、新品篇数/产品数/原图数、原图本地文件SHA256及Redis的7张新品字节，检查生产/演示健康、cache-warmer运行、插件容器ID与部署前相同；输出机器可读`/opt/dual-catalog/data/artifacts/acceptance/tomica-news-deploy.json`。构建/迁移前失败恢复旧APP_IMAGE并重启原预热；数据库已升级0004时保留新配置与备份并修复当前版本，不自动降库或用仅识别0003的旧健康检查冒充健康，不回滚其他插件。
  - 服务器部署命令：`python3 /opt/dual-catalog/deploy_tomica_news.py`；服务器只读检查命令：`python3 /opt/dual-catalog/deploy_tomica_news.py --check`。通过既有远程会话执行，不再次请求已授予的部署许可。
- [x] 在`D:/poke&Tomy/spec/feature_20261110_F002_tomica-news/execution-summary.md`保存实际命令/退出码/测试数量、原图来源核对、生产与演示迁移/幂等结果、截图/JSON路径、版本和回滚镜像；同步部署状态文档。
  - 最后只终止Task 2记录的8094本地API会话，不按端口批量杀其他进程；公网生产/演示及全量缓存后台继续运行，交付月刊及No.114深链。

**端到端验证:**
- [x] 完整测试套件。
  - `& .venv/Scripts/python.exe -m pytest backend/tests -q` 与 `npm test`
  - 预期：全部通过，数量取实际输出；这是部署前门槛，已留存同一源码版本的通过证据后不重复执行；失败定位Task 1/2。
- [x] 新品公网真实验收及对应图片字节。
  - 环境命令：`Remove-Item Env:PREVIEW_URL -ErrorAction SilentlyContinue`
  - `node scripts/verify-tomica-news.cjs`
  - 预期：真实月索引、三组7图、5图No.114、深链/刷新/历史、原图放大、返回筛选/分页及隔离通过；原图HTTP字节摘要等于附件。
  - 失败排查：API/图片/摘要定位Task 1，页面/路由/返回/竞态定位Task 2，版本或服务连接定位本Task部署步骤。
- [x] 历史回归。
  - `node scripts/verify-navigation.cjs`、`node scripts/verify-page-size.cjs`、`node scripts/verify-tomica-display.cjs`、`node scripts/verify-pokemon-details.cjs`。
  - 预期：各套件通过，无新增运行时错误，原有详情不被新品路由关闭。
  - 失败排查：详情/导航/分页定位Task 2，旧接口或缓存异常定位Task 1及本Task部署步骤；不得将测试失败改写为通过。
- [x] 线上部署与缓存运行检查。
  - 服务器命令：`python3 /opt/dual-catalog/deploy_tomica_news.py --check`
  - 服务器健康命令：`curl -fsS http://127.0.0.1:8092/health/ready`、`curl -fsS http://127.0.0.1:8093/health/ready`
  - 预期：检查报告status=pass；正式/演示healthy且revision=0004_tomica_news；两库各1篇、3组、7图，重复导入unchanged，7张新品Redis字节及本地摘要一致；旧表保留，本项目预热运行，原有插件ID未变。缓存任务启动不等于原图全量完成。
  - 失败排查：迁移/导入/图片定位Task 1，服务/Redis/插件状态定位本Task，失败后按已记录旧镜像恢复本项目服务。
- [x] 保存真实网页截图、验收JSON与执行摘要，清理8094临时服务并保留用户要求的公网交付；交付公网月刊/No.114深链。
  - `Get-Content artifacts/acceptance/tomica-news-public.json -TotalCount 8`
  - 预期：status=pass，并给出实际已执行断言数；截图与最终版本一致。
  - 失败排查：报告缺失、失败或截图过期回到Task 2的report/finally输出与本Task公网版本核对；最终回复明确公众号未接通自动采集。
