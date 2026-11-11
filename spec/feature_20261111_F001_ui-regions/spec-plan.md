# 双图鉴圆角主题与宝可梦地区浏览实施计划

目标：保留图标及既有行为，改进主题、提供地区图鉴筛选、用滚动自动加载取代继续探索。

技术栈：FastAPI/SQLAlchemy/PostgreSQL/Redis、原生JavaScript/CSS、微信原生小程序。

设计文档：spec/feature_20261111_F001_ui-regions/spec-design.md

改动总览：Task 0复核现有工具链；Task 1仅修改地区索引、查询、仓储、API及对应后端测试六个文件，提供离线地区集合与过滤契约。
Task 2依赖Task 1的十地区元数据、region参数和total，实现浏览器主题、自动加载及小程序地区选择；单独theme.css与两份SVG保留既有布局、图标和原图。
Task 3依赖前两项检查通过，更新发布文档和镜像版本，再通过既有审计发布脚本部署0.9.0并执行公网回归；验收不重复编写Task 1/2测试。
全程不引入数据库迁移、重新采集照片或浏览时外站依赖；所有本地命令均从 `D:/poke&Tomy` 执行，服务器命令复用当前已授权的远程会话。

### Task 0: 环境准备

**背景:**
本轮沿用现有Python、Node和Playwright工具链，不安装新框架。
先复核状态恢复和部署约束，再以既有单元测试确认测试入口可运行；Task 1/2依赖本Task的可用环境。

**执行步骤:**
- [x] 阅读 `spec/feature_20261109_F001_dual-catalog/both-catalog-refresh-fix.md`、`docs/deployment.md` 与本功能设计，确认按图鉴独立恢复、缓存及发布范围。
- [x] 运行既有环境烟测，不为工具版本新增实现镜像测试。
  - 测试文件: `backend/tests/test_release.py`，验证现有隔离环境及发布配置校验入口；该Task不引入业务逻辑或新测试文件。
  - 运行命令: `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_release.py -q`
  - 预期: 全部通过；具体地区及交互单元测试分别由Task 1/2负责。

**检查步骤:**
- [x] 复核Python、Node与npm工具链。
  - `& '.venv/Scripts/python.exe' scripts/check_toolchain.py`
  - 预期: 退出码0，JSON包含Python版本且node/npm的exit_code均为0。
- [x] 验证Playwright可启动Chrome和WebKit。
  - `node -e "const {chromium,webkit}=require('playwright'); (async()=>{for(const [engine,options] of [[chromium,{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'}],[webkit,{headless:true}]]){const b=await engine.launch(options); console.log(b.version()); await b.close();}})().catch(e=>{console.error(e);process.exitCode=1})"`
  - 预期: 输出两个浏览器版本并退出0，后续真实浏览器检查无需另装测试框架。

---

### Task 1: 离线地区图鉴与筛选接口

**背景:**
用户选择的是地区图鉴收录范围，同一物种可以同时出现在多个地区，列表继续使用全国编号及原有52poke资料。
当前 `PokemonQuery` 只有属性筛选，`CatalogRepository.list_pokemon()` 只处理属性与搜索，游标签名包含原有 `{q,type}`，列表尚未返回总数。
本 Task 提供离线成员集合、地区元数据和组合筛选契约；Task 2 的浏览器、小程序及状态恢复共同依赖该契约，不增加数据库字段或迁移。

**涉及文件:**
- 新建: `backend/app/pokemon_regions.py`
- 新建: `backend/app/data/pokemon-regions.json`
- 新建: `backend/tests/test_pokemon_regions.py`
- 修改: `backend/app/schemas.py`
- 修改: `backend/app/repository.py`
- 修改: `backend/app/api.py`

**执行步骤:**
- [x] 定义地区白名单及可复现的离线索引生成入口 — 让地区范围来自实际图鉴成员，而不是首次登场世代或全国编号区间。
  - 位置: 新建 `backend/app/pokemon_regions.py`，定义 `SUPPORTED_REGIONS`、`build_region_index(client, collected_at)` 及显式 `main()` 的 `--refresh` 命令。
  - 固定键和顺序为 `kanto/关都`、`johto/城都`、`hoenn/丰缘`、`sinnoh/神奥`、`unova/合众`、`kalos/卡洛斯`、`alola/阿罗拉`、`galar/伽勒尔`、`hisui/洗翠`、`paldea/帕底亚`。排除索引中的其他地区，不向运行时开放任意键或外站URL。
  - 生成入口使用 `httpx.Client(timeout=30)` 读取 `https://pokeapi.co/api/v2/region/{key}/`，遍历每个响应的全部 `pokedexes` URL，再读取各图鉴的 `pokemon_entries`。从 `pokemon_species.url` 的末段取得全国编号，使用集合合并后升序保存；禁止使用地区 `entry_number`，禁止把已属于前一地区的物种从后一地区删除。
  - 已有 `artifacts/ui-regions/region-*.json` 记录当前关联：关都含 `kanto/letsgo-kanto`，城都含 `original-johto/updated-johto`，丰缘含 `hoenn/updated-hoenn`，神奥含 `original-sinnoh/extended-sinnoh`，合众含 `original-unova/updated-unova`，卡洛斯含 `kalos-central/kalos-coastal/kalos-mountain/lumiose-city/hyperspace`，阿罗拉含 original 与 updated 的 alola/melemele/akala/ulaula/poni 十份，伽勒尔含 `galar/isle-of-armor/crown-tundra`，洗翠含 `hisui`，帕底亚含 `paldea/kitakami/blueberry`。全部按关联收录，不能只取首份图鉴或排除扩展版本。
  - 采集时将 region 与 pokedex 原响应缓存到 `artifacts/ui-regions/region-{key}.json` 和 `artifacts/ui-regions/pokedex-{name}.json`；任一请求失败、物种URL非法或集合为空时生成命令失败，原发布JSON保留。全部成功后用临时文件原子替换正式JSON。
  - 定义依据: [PokéAPI Pokedex 文档](https://pokeapi.co/docs/v2#pokedexes)。仅显式生成命令访问外站；导入模块、校验参数、列表查询和元数据查询只读取随发布交付的本地JSON。
- [x] 生成带来源和内容版本的静态数据并提供只读访问函数 — 使发布与后续核查使用同一份集合。
  - 位置: `backend/app/pokemon_regions.py:build_region_index()` 的结果序列化处，以及同模块新增 `load_region_index()`、`region_dexes(key)`、`region_metadata()`。
  - 写入 `backend/app/data/pokemon-regions.json`，顶层包含 `schema_version:1`、`definition:'同地区各版本图鉴合并收录'`、`index_version`、`collected_at`、`regions`。每个地区保存 `key/name/source_url/collected_at/pokedexes/dexes`；`pokedexes` 每项保存实际 `name/url/version_groups`，版本组保留 `name/url`。采集日期使用实际UTC时间。
  - `index_version` 使用白名单顺序、图鉴来源/版本组及升序去重的成员内容计算稳定SHA-256；排除采集时间，同样成员和版本生成相同版本号。
  - `load_region_index()` 使用 `Path(__file__).with_name('data') / 'pokemon-regions.json'` 和单次缓存加载，校验十个键、非空正整数成员、地区内无重复及版本哈希；`region_dexes(key)` 返回 `frozenset[int]`，`region_metadata()` 返回新对象，避免调用方修改共享索引。
  - 元数据固定返回 `{definition,index_version,items}`；`items` 按白名单顺序排列，每项为 `{key,name,pokedexes,source_url,collected_at,species_count}`，`species_count` 是离线成员集合长度，不代表数据库已收录数量。响应不携带整份 `dexes`。
  - 在项目根执行 `& '.venv/Scripts/python.exe' -m backend.app.pokemon_regions --refresh`，生成正式数据；现有 `Dockerfile.release` 的 `COPY backend /app/backend` 会携带该JSON，无须新增数据库迁移或修改图片记录。
- [x] 在查询模型中增加有限地区参数 — 让空选择与旧请求完全一致，非法键沿用现有422错误响应。
  - 位置: `backend/app/schemas.py:PokemonQuery`，在 `type` 字段旁添加 `region: str | None = None`，在 `valid_type()` 后添加 `valid_region()`，导入 `SUPPORTED_REGIONS` 所对应的键集合。
  - `valid_region()` 使用 `mode='before'`，将非空文本 `strip().lower()`；`None`、空字符串和纯空白归一化为 `None`；其他值只允许十个地区键，未知键抛 `ValueError('unknown region')`。保留 `Query.strip_query()`、limit约束和属性白名单行为。
- [x] 将地区与属性、搜索按交集组合，并返回完整筛选总数 — 让前端总数和自动加载结束状态准确。
  - 位置: `backend/app/repository.py:CatalogRepository.list_pokemon()`，在 `rows = self.catalog_rows('pokemon')` 后、现有 `query.type` 处理前追加地区成员筛选，使用 `r['dex'] in region_dexes(query.region)`；保留现有全国编号精确匹配、三语言名称包含匹配和有效字段投影。
  - 完成地区、属性、搜索三层筛选后先记录 `total = len(rows)`，再调用既有 `_page(rows, query, 'pokemon', lambda r: (r['dex'],))`，返回 `{**page, 'total': total}`。每一批的total相同，空交集为0，末页 `next_cursor` 仍为 `None`。
  - 不按地区图鉴编号排序，不修改共享snapshot列表及其行对象，不把 `PokemonForm` 变成额外列表条目；不改变 `list_tomica()` 的品牌、年份、页码及20/40/60/100分页。
- [x] 将地区及索引内容绑定到宝可梦游标，同时保留未选地区的旧签名 — 防止跨地区续页及离线集合变动后错页。
  - 位置: `backend/app/repository.py:CatalogRepository._page()`，紧接 `filters = query.model_dump(exclude={'cursor', 'limit', 'page'})`，在计算SHA-256前处理 `source == 'pokemon'` 的签名载荷；使用 `pokemon_regions.region_index_version()` 读取离线索引内容版本。
  - 对空地区从 `filters` 中删除 `region`，保持原有 `{q,type}` 的字段、空值、排序、`json.dumps(..., sort_keys=True, ensure_ascii=False)` 和哈希算法；禁止对所有查询使用 `exclude_none=True`，禁止给空地区添加索引版本字段。
  - 对已选地区保留规范化的 `region`，在签名载荷加入 `region_index_version: region_index_version()`。保留现有revision检查、排序键、`INVALID_CURSOR` 400与 `CATALOG_CHANGED` 409响应；地区、属性、搜索或地区索引内容变化使原游标签名校验失败。
- [x] 公开离线元数据并隔离新版列表缓存 — 让两端复用契约，避免命中部署前缺少total的缓存。
  - 位置: `backend/app/api.py:list_pokemon()` 的 `public_cached()` 调用，将 view 从 `'list'` 改为 `'list-regions-' + region_index_version()`，params继续使用含规范化region的 `query.model_dump()`。
  - 在 `@router.get('/pokemon/{dex}')` 之前新增 `@router.get('/pokemon/regions')` 和 `pokemon_regions()`，调用 `public_cached(request, session, 'pokemon', 'regions-' + region_index_version(), {}, lambda repo: region_metadata())`；固定路由必须先注册，避免被动态dex路由当成非法整数。
  - list与regions缓存键同时包含索引内容版本，list参数签名同时包含region；关都与帕底亚缓存互相隔离。继续复用现有 `CatalogCache`、数据库revision和Redis不可用时回源机制，不改 `cache.py`、图片或详情缓存键。
- [x] 为离线合并、组合筛选、游标兼容和API缓存编写单元测试。
  - 位置: 新建 `backend/tests/test_pokemon_regions.py`；复用 `backend/tests/conftest.py:session` 的内存SQLite、`backend/tests/test_api.py:client` 的TestClient夹具及 `backend/tests/test_cache.py:MemoryRedis`。新文件通过明确导入取得client夹具，不修改全局测试初始化。
  - 测试场景:
    - 合并算法: 用 `httpx.MockTransport` 提供十地区响应及少量图鉴响应，同一地区两个版本包含重复物种，`entry_number` 与 `pokemon_species.url` 编号不同 → 成员按物种URL全国编号去重、升序；#25同时保留在两个地区；每份关联图鉴和version_groups均保留；成员不变而采集日期改变时index_version相同。
    - 静态快照: 正式JSON恰含十地区，成员是非空升序唯一正整数，`pokedexes`覆盖上述实际关联；#25属于关都与帕底亚，#1000属于帕底亚而不属于关都。将 `httpx.Client.send` 替换为抛错函数后，离线加载、地区查询与元数据端点仍成功。
    - 参数校验: `region=''/'  '/None` → `None`，`region=' KANTO '` → `kanto`，`region='national'/'orre'/'unknown'` → Pydantic校验失败；API未知地区为422及 `INVALID_PARAMETERS`，空地区与未提供地区的查询结果相同。
    - 组合筛选与总数: 逆序植入全国#1、#25、#133、#1000，分别设置草/电/一般/钢和中文/英文名 → 关都排除#1000，帕底亚保留#1000，`region=kanto&type=电&q=皮卡` 和 `q=#25` 只返回#25；空交集total为0；`limit=1`各批全国编号递增、不重复，total保持完整交集长度，末批无游标。
    - 旧游标兼容: 手工按旧载荷 `{q:None,type:None}`、旧JSON哈希及当前revision生成sort_key为 `[1]` 的base64游标 → 未选地区及空地区继续返回下一条，选关都拒绝为 `INVALID_CURSOR`；关都游标用于帕底亚、修改属性或搜索均拒绝；模拟 `pokemon_regions.region_index_version()` 返回新版本后地区游标拒绝，未选地区旧游标仍有效。
    - 元数据路由与缓存: `/api/pokemon/regions` 为200、十个中文名称顺序正确、包含definition/图鉴版本/来源/日期/species_count且不暴露dexes；同地区同参数第二次命中缓存，另一个地区首次为miss且结果正确；预置旧 `'list'` view缓存不会污染新响应的total。
    - 回归边界: `repo.catalog_rows('pokemon')` 的成员和顺序在地区查询前后相同；宝可梦详情和来源图片字段保持现有投影；Tomica旧游标及页码分页测试继续通过。
  - 运行命令: `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_pokemon_regions.py -q`
  - 预期: 所有核心测试通过，测试过程不访问外站，不依赖本地PostgreSQL或Redis服务。

**检查步骤:**
- [x] 检查离线数据、地区入口及元数据结构。
  - `& '.venv/Scripts/python.exe' -c "from backend.app.pokemon_regions import region_metadata, region_dexes; m=region_metadata(); assert len(m['items']) == 10; assert 25 in region_dexes('kanto') and 25 in region_dexes('paldea'); assert 1000 not in region_dexes('kanto') and 1000 in region_dexes('paldea'); print(m['definition'], m['index_version'], [r['key'] for r in m['items']])"`
  - 预期: 输出合并收录说明、稳定版本哈希和十地区键，无外网访问。
- [x] 验证地区核心行为与现有列表、详情、缓存回归。
  - `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_pokemon_regions.py backend/tests/test_repository.py backend/tests/test_api.py backend/tests/test_cache.py backend/tests/test_catalog_snapshot.py backend/tests/test_pokemon_details.py -q`
  - 预期: 全部通过，旧宝可梦游标、Tomica分页和共享snapshot行为保持兼容。
- [x] 验证新增模块与修改模块均可编译。
  - `& '.venv/Scripts/python.exe' -m compileall -q backend/app/pokemon_regions.py backend/app/schemas.py backend/app/repository.py backend/app/api.py backend/tests/test_pokemon_regions.py`
  - 预期: 退出码为0，没有语法或导入编译错误。

---

### Task 2: 圆润主题、地区选择与滚动浏览

**背景:**
浏览器当前通过 `#load-more` 手动续页，宝可梦状态只保存名称/属性，追加失败还会清空已显示卡片；小程序已有 `onReachBottom()` 和按图鉴缓存的列表状态。
本 Task 依赖 Task 1 的 `/api/pokemon/regions` 元数据与列表 `total`，提供地区组合筛选、滚动自动续页及独立恢复，同时保留原图、现有图标和多美卡页码分页。
主题采用单独CSS覆盖层和本地SVG装饰，沿用现有桌面分栏、卡片图片铺满、手机底栏及详情关闭按钮布局。

**涉及文件:**
- 新建: `backend/preview/theme.css`
- 新建: `backend/preview/backgrounds/tomica-track.svg`
- 新建: `backend/preview/backgrounds/pokemon-map.svg`
- 新建: `scripts/verify-ui-regions.cjs`
- 修改: `backend/preview/index.html`
- 修改: `backend/preview/app.js`
- 修改: `miniprogram/lib/page-factory.js`
- 修改: `miniprogram/services/api.js`
- 修改: `miniprogram/pages/pokemon-list/index.wxml`
- 修改: `miniprogram/app.wxss`
- 修改: `scripts/verify-both-catalog-refresh.cjs`
- 修改: `miniprogram/tests/pages.test.js`
- 修改: `miniprogram/tests/api.test.js`
- 修改: `miniprogram/tests/catalog-state.test.js`

**执行步骤:**
- [x] 添加圆润彩色主题与两套本地背景 — 用清晰的主题差异改善浏览体验。
  - 位置: `backend/preview/index.html` 的 `style.css` 后引入 `theme.css?v=0.9.0`；新建 `backend/preview/theme.css`，按 `body[data-catalog]` 覆盖颜色、圆角、边框与阴影，使用深色侧栏、圆角白卡、彩色属性标签、多美卡暖色横幅及宝可梦蓝绿横幅。资源查询版本统一为0.9.0。
  - 在 `backend/preview/backgrounds/tomica-track.svg` 绘制赛道/车库线条，在 `backend/preview/backgrounds/pokemon-map.svg` 绘制探索地图/路径；作为 `.feature` 背景装饰，保留 `.feature-illustration` 原始照片及现有全部SVG、字符图标和图片来源。覆盖层沿用 `style.css` 的宽度、网格、媒体断点、Tomica图片铺满和关闭按钮居中规则，手机底栏仍可用；装饰不覆盖文字或拦截点击。
- [x] 接入地区下拉和中文快捷标签 — 两种入口共享同一筛选状态。
  - 位置: `backend/preview/index.html` 的 `#type-wrap` 旁新增 `#region-wrap > #region`，工具栏后新增 `#region-tabs` 和地区定义说明；在 `backend/preview/app.js:selectKind()` 的属性控件切换处同步隐藏/显示地区控件，仅宝可梦请求 `request('pokemon/regions')`。
  - 新增 `populateRegions(metadata)`、`changeRegion(key)`、`syncRegionControls()`，使用 `items[].key/name` 构建“全部地区”与十地区选项/按钮，以 `textContent` 写名称，展示 `definition` 与 `pokedexes` 版本名。下拉和标签都写 `state.query.region`、保留 `type/q`、调用 `load(true)`；异步元数据回填检查当前kind及选择序列。`renderCards()` 使用 `state.total=response.total` 展示“地区名 · 已呈现 X / 共 Y”，全国选择显示全国图鉴，空结果为0。元数据失败显示重试入口并保留全国浏览。
- [x] 扩展列表保存和恢复并隔离旧请求 — 刷新、详情返回和切换图鉴后恢复同一浏览位置。
  - 位置: `backend/preview/app.js:readCatalogList()` 的宝可梦键白名单加入 `region`，按 Task 1 十地区键校验；`rememberCatalogList()` 继续分别写 `listKeys.tomica/pokemon`，保存地区/属性/搜索、`visibleCount/scrollY`，多美卡保存页码/每页数量。
  - 调整 `route()`、`selectKind()`、`restorePokemonList()`：切换前保存当前图鉴，切入后读取目标已存状态；显式重置以空query进入并覆盖该图鉴旧记录。恢复开始设置 `restoring` 与恢复令牌，逐批恢复到保存数量后恢复位置；每个await后校验kind/sequence/令牌，恢复失败停止且保留成功批次，finally只解除本次令牌的暂停。重置、地区/属性/搜索改变、图鉴切换立即使旧恢复失效并中止旧列表请求，旧响应不得覆盖新卡片或滚动位置。
- [x] 用哨兵和滚动额度替换手动续页 — 每次进入底部或新的滚动只推进一批。
  - 位置: `backend/preview/index.html` 删除 `#load-more`，在 `#feedback` 后放置 `#pokemon-sentinel`；`backend/preview/app.js` 删除该按钮的全部读取与事件，新增 `setupPokemonObserver()`、`tryLoadPokemonMore()` 与滚动监听，复用 `load(false)` 的游标和按dex去重，不改变Tomica `renderPagination()/changePage()`。
  - `IntersectionObserver` 使用底部预加载区，记录哨兵可见性、进入边沿和一次性滚动额度；请求前消耗额度，`loading`、无cursor、非宝可梦、`restoring`、详情或原图dialog打开时禁止触发。append完成/布局变化/关闭dialog/恢复结束都不得自行重置额度；用户在哨兵可见期间再次滚动可取得一批额度。首屏内容不足一屏时逐批补齐到可滚动或末页，填满后立即停止；静止页面不能循环拉完1025条。`showDetailDialog()/hideDetailDialog()/openImageViewer()/closeImageViewer()` 同步暂停状态，并在布局稳定后等待新的滚动或重新进入哨兵。
- [x] 保留失败批次之前的卡片并提供续页重试 — 网络波动不丢失浏览进度。
  - 位置: `backend/preview/app.js:load()` 的request捕获与finally处，捕获请求发起时的kind、sequence、query、cursor，提交响应前核验归属；宝可梦追加错误只更新 `#feedback` 并显示“重试下一批”，保留items/cursor/total和已有DOM，重试调用同一cursor的 `load(false)`。首批错误使用 `load(true)` 重试，409沿用重新获取首批行为。
  - 失败时消耗本次自动加载额度并暂停自动重试；成功后由新的滚动/进入动作继续。finally只释放当前请求的loading，过期请求不得改反馈、状态或持久化记录，末页明确提示结束并停止观察加载。
- [x] 为小程序增加地区选择并同步主题 — 复用既有状态对象和触底加载。
  - 位置: `miniprogram/services/api.js:createApi()` 返回值新增 `regions: () => get('/api/pokemon/regions')`；`miniprogram/lib/page-factory.js:createListPage()` 的data新增 `regions/regionIndex/regionDefinition`，宝可梦onLoad读取元数据，新增 `filterRegion(event)`，以元数据key合并当前filters后调用 `state.setFilters()`，保留type/q。
  - `onLoad()` 的状态回调与地区元数据完成后按 `value.filters.region/type` 同步picker索引，使现有kind缓存restore恢复控件；异步回填不清空已恢复筛选，onUnload后不再setData。`miniprogram/pages/pokemon-list/index.wxml` 的宝可梦筛选block加入地区picker与合并收录说明，保留属性picker、图片与状态提示；`miniprogram/app.wxss` 调整页面/横幅/卡片/标签圆角及两图鉴色彩。保留 `onReachBottom()`、`catalog-state.js` 的游标去重/竞态/滚动位置行为。
- [x] 新增真实浏览器验证并迁移旧刷新回归脚本 — 用实际滚动覆盖自动加载和视觉效果。
  - 位置: 新建 `scripts/verify-ui-regions.cjs`，沿用Playwright、`PREVIEW_URL`、本机Chrome与现有WebKit手机配置；支持 `--local` 本地静态资源覆盖，覆盖index/app/style/theme/pokemon-details和两份backgrounds SVG，报告与桌面/手机截图写入 `artifacts/acceptance/ui-regions-*`。先走真实地区API，再用明确路由延迟/失败注入验证竞态及异常；浏览动作使用 `mouse.wheel`/页面滚动，禁止直接调用 `load()` 冒充滚动。
  - 场景覆盖十地区控件互相同步、地区+属性+q与total、至少三批追加/去重/末页停止、首屏不足补齐、静置不连续加载、追加失败保留与原cursor重试、详情/大图打开暂停、返回位置、刷新及跨图鉴恢复、旧恢复期间显式重置。截图覆盖两主题1440px桌面与390px手机，断言无横向溢出、地区控件隔离、图标SVG及原图仍在、卡片图片铺满、关闭按钮中心、多美卡20/40/60/100分页。
  - 修改 `scripts/verify-both-catalog-refresh.cjs` 原 `#load-more` 三处点击，提取 `scrollNextBatch()`：真实滚到哨兵并发送新的滚动、等待指定新增数量和loading结束；保留原全部刷新、过滤、108条恢复、图片、独立进度、页码及显式重置竞态断言，`--local`覆盖同时包含theme和backgrounds资源。
- [x] 为地区筛选传参及恢复核心逻辑补充单元测试。
  - 位置: `miniprogram/tests/api.test.js` 增加regions端点与region/type/q组合编码；`miniprogram/tests/pages.test.js` 使用模拟地区元数据和列表响应验证 `filterRegion()` 保留type/q、key/name映射、缓存恢复picker和迟到元数据不清空筛选；`miniprogram/tests/catalog-state.test.js` 增加地区切换旧响应丢弃、地区/属性/搜索和scrollTop快照恢复、追加失败保留卡片并原cursor重试。现有主题样式由上一步真实浏览器验证，不编写CSS实现镜像测试。
  - 运行命令: `node --test miniprogram/tests/api.test.js miniprogram/tests/pages.test.js miniprogram/tests/catalog-state.test.js`
  - 预期: 新增核心测试与既有用例全部通过，无网络依赖。

**检查步骤:**
- [x] 验证前端语法与小程序核心行为。
  - `node --check backend/preview/app.js`
  - `node --check scripts/verify-ui-regions.cjs`
  - `node --check scripts/verify-both-catalog-refresh.cjs`
  - `node --test miniprogram/tests/api.test.js miniprogram/tests/pages.test.js miniprogram/tests/catalog-state.test.js`
  - 预期: 每条命令均为0，新旧测试全部通过。
- [x] 验证真实地区筛选、滚动加载与桌面/手机主题。
  - 前置: Task 1 数据/API就绪，在另一个终端执行 `& '.venv/Scripts/python.exe' -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8092`。
  - 设置环境: `$env:PREVIEW_URL='http://127.0.0.1:8092'`
  - `node scripts/verify-ui-regions.cjs --local`
  - 预期: 所有浏览器断言通过、无pageerror，输出pass报告及两主题桌面/手机截图，末批/静置/暂停期间无多余列表请求。
- [x] 验证已有双图鉴刷新与长列表恢复回归。
  - `node scripts/verify-both-catalog-refresh.cjs --local`
  - 预期: 保留的全部旧断言在桌面Chrome与WebKit手机均通过，超过100条恢复与显式重置竞态无回归。


---

### Task 3: 整体验收与发布（Acceptance）

**前置条件:**
Task 1/2的单项检查通过，地区JSON已生成，浏览器、小程序及浏览器验证脚本已完成。原服务为0.8.5，目标为0.9.0。
本Task的检查按顺序执行：本地完整测试通过后才能发布，再验证独立容器、正式/演示API和公网页面。服务器命令经已授权的 `scripts/remote_session.py` 会话执行，保留既有主机校验和私有审计，不打印凭证。

**涉及文件:**
- 修改: `CHANGELOG.md`、`Dockerfile.release`、`docs/deployment.md`、`docs/api-contract.md`
- 生成证据: `artifacts/deploy.tar.gz`、`artifacts/acceptance/ui-regions-*`、`spec/feature_20261111_F001_ui-regions/acceptance.md`

**执行步骤:**
- [x] 更新发布元数据与契约说明，确保用户和运维可核查本轮变化。
  - 位置: `CHANGELOG.md` 顶部新增0.9.0条目；`Dockerfile.release` 的 `org.opencontainers.image.version` 改为0.9.0；`docs/deployment.md` 更新当前镜像与地区索引离线交付、自动加载行为；`docs/api-contract.md` 补充地区元数据、region/total及旧游标兼容语义。浏览器资源版本由Task 2统一更新，本Task不重复修改前端。
- [x] 准备限定发布内容的源码包，保持服务器配置独立。
  - 位置: 项目根生成 `artifacts/ui-regions-0.9.0.tar.gz`，执行 `tar -czf artifacts/ui-regions-0.9.0.tar.gz --exclude=__pycache__ --exclude=*.pyc --exclude=.env* --exclude=node_modules backend scripts docs miniprogram vendor Dockerfile.release compose.production.yaml pyproject.toml package.json package-lock.json requirements.lock README.md CHANGELOG.md`。
  - 本地完整测试通过后，通过现有远程会话上传该包至 `/opt/dual-catalog/ui-regions-0.9.0.tar.gz`，解包到 `/opt/dual-catalog/app`；不覆盖 `/opt/dual-catalog/.env`、`.env.demo`、data或其他项目目录。`Dockerfile.release` 已复制完整backend，theme.css、背景SVG及离线JSON随包交付。

**检查步骤:**
- [x] 首先运行工作区完整测试并记录原始输出与各自退出码，作为发布前置。
  - `& '.venv/Scripts/python.exe' -m pytest -q`
  - `node --test miniprogram/tests/*.test.js`
  - 预期: 两条命令均退出0；地区数据/仓储/API失败回Task 1，小程序及状态恢复失败回Task 2，工具缺失回Task 0。不把未执行或中断记为通过。
- [x] 发布0.9.0并核对审计回执。
  - 远端解包: `tar -xzf /opt/dual-catalog/ui-regions-0.9.0.tar.gz -C /opt/dual-catalog/app`
  - 远端发布: `python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.9.0 --reason '地区图鉴筛选、圆角主题与滚动自动加载'`
  - 远端回执: `cat /opt/dual-catalog/data/artifacts/acceptance/logging-deployment.json`
  - 预期: 退出0，回执status=pass、image=dual-catalog:0.9.0、plugins_unchanged=true、database_migration=false、data_import=false；双API为ready且revision仍为0004_tomica_news，预热恢复。保存为本轮私有 `artifacts/acceptance/ui-regions-deployment.json`；发布失败检查本Task及脚本私有日志，沿用脚本回滚，不推进公网验收。
- [x] 在服务器独立禁网容器验证发布镜像内的完整后端测试。
  - 远端: `docker run --rm --network none --memory 640m --entrypoint python dual-catalog:0.9.0 -m pytest -q`
  - 预期: 退出0，发布镜像内单测通过且不连接生产数据库或外站；地区相关失败回Task 1，镜像内容缺失回本Task。
- [x] 验证公网真实地区筛选、自动滚动和桌面/手机效果。
  - 设置环境: `$env:PREVIEW_URL='http://117.72.11.77'`
  - `node scripts/verify-ui-regions.cjs`
  - 预期: 退出0，报告status=pass、无pageerror，保存两主题桌面和手机截图；覆盖地区/属性/搜索交集、total、至少三批与去重、末页停止、静置不连拉、首屏补齐、失败保留/原cursor重试、详情与大图暂停、返回/刷新/切换恢复、显式重置取消旧恢复及筛选控件隔离。此处不加--local，确保验证部署资源；失败回Task 2，API返回不符回Task 1。
- [x] 运行受影响的历史回归，检查原图、图标及多美卡分页。
  - `node scripts/verify-both-catalog-refresh.cjs`
  - `node scripts/verify-tomica-display.cjs`
  - `node scripts/verify-tomica-editions.cjs`
  - 预期: 每条均退出0且报告pass；长列表恢复、图片放大、居中关闭按钮、铺满卡片和20/40/60/100分页保持通过。原#load-more迁移由Task 2完成，此处只运行已有断言；交互失败回Task 2。
- [x] 核对正式/演示健康、地区缓存与进程状态。
  - 远端: `for port in 8092 8093; do curl -fsS "http://127.0.0.1:$port/health/ready"; curl -fsS "http://127.0.0.1:$port/api/pokemon/regions"; done`
  - 远端: `curl -fsS -D - -o /dev/null 'http://127.0.0.1:8092/api/pokemon?region=kanto&limit=1'`（连续执行两次）
  - 远端: `docker ps -aq --filter label=com.docker.compose.project=dual-catalog | xargs -r docker inspect --format '{{.Name}} {{.State.Running}} {{.State.OOMKilled}}'`
  - 远端: `systemctl is-active dual-catalog-redis`
  - 预期: 双端口健康及十地区元数据正确，同参数第二次含X-Catalog-Cache: hit；API与cache-warmer运行且OOMKilled=false，缓存守护进程active；原插件不变由发布回执证明。API/缓存契约失败回Task 1，进程或版本异常回本Task。
- [x] 整理证据与结束独立测试进程后交付。
  - 在Task 2本地uvicorn所属终端发送Ctrl+C，停止本轮独立服务；保留生产API与预热。在 `spec/feature_20261111_F001_ui-regions/acceptance.md` 记录真实命令、退出码、报告/截图路径、operation_id、来源语义与未验证边界。
  - `Get-Content -LiteralPath 'spec/feature_20261111_F001_ui-regions/acceptance.md'`
  - `Get-ChildItem -LiteralPath 'artifacts/acceptance' -Filter 'ui-regions-*'`
  - 预期: 记录可对应原始报告和截图，交付 `http://117.72.11.77/preview/?catalog=tomica` 与 `http://117.72.11.77/preview/?catalog=pokemon` 及两主题效果；明确手机结果来自WebKit模拟，不声称微信真机已验证。
  - 实际执行差异：发布包使用既有`artifacts/deploy.tar.gz`上传至`/opt/dual-catalog/deploy.tar.gz`，按目标目录包含性验证后解包；完整镜像测试使用384MiB、pids=128、禁网、无挂载及关闭pytest缓存，命令与结果详见acceptance.md。以上路径与参数差异不改变验收范围。
