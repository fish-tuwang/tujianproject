# 双图鉴微信小程序执行计划

**目标:** 实现可按年份、品牌查找多美卡、按全国编号浏览宝可梦的微信小程序，并提供可恢复的定期同步与数据维护能力。

**技术栈:** Python 3.10+（容器 Python 3.12）、FastAPI、SQLAlchemy 2.x、psycopg 3、PostgreSQL 18、httpx、BeautifulSoup 4、APScheduler 3.x、pytest；微信原生 JavaScript/WXML/WXSS、Node 内置测试；Docker Compose；S3 兼容对象存储接口。

**设计文档:** D:/poke&Tomy/spec/feature_20261109_F001_dual-catalog/spec-design.md

## 改动总览

- 涉及文件列表去重后：新建84个文件，修改1个现有文件（CHANGELOG.md），共85个；Task3/4对Task1新建文件的后续修改不重复计数；共有Task0—7八个任务，Task7七个验收场景。
- 本次为从零新增后端数据层、双来源适配器、同步工作进程、管理页面与微信原生四页；原仓库无现有公共方法、调用点或测试可复用。
- Task 0 建工具链，Task 1 固定实体和契约，Task 2 实现离线可测解析，Task 3 消费候选并发布；Task 4 对外提供查询和管理，Task 5 消费 API，Task 6 打通部署与证据采集，Task 7 统一验收。
- 同号车型代次与宝可梦形态分开建模；待发布数据通过校验后提交，人工覆盖独立保存；每来源修订号保证分页变化可检测。
- API、队列 worker、定时入队 scheduler 使用独立进程；生产复用用户服务器上的 PostgreSQL 18 与已创建的 dual_catalog 库。本地 Compose 验证独立 PostgreSQL 18；生产仅部署本项目容器，不更改既有插件或数据库服务。
- 文件目标使用绝对路径；本机 PowerShell 命令工作目录均为 `D:/poke&Tomy`，命令内相对路径以此为根。服务器命令固定 `--project-directory /opt/dual-catalog/app`，镜像工作目录 `/app`；三者路径不可混用。单元测试、真实数据库/网络、开发者工具验收分别记录，缺失外部条件不能记为通过。

**当前阶段交付:** 后端服务与本地演示；用户已确认真实AppID和HTTPS域名暂未准备。微信正式发布属于后续发布验收，保留完整实现与验收路径，对应检查标blocked/待执行，不阻塞后端和演示实现，不将本阶段完成等同正式发布通过。

**当前核对依据与运行边界:**

- 2026-11-09 已读取本项目设计文档、本计划与服务器准备记录；`D:/poke&Tomy/spec/global` 不存在，未发现 AGENTS.md。
- Tomica HTTP 小样本可读，HTTPS 证书不匹配；52poke 主详情本机 HTTP 客户端返回 200，robots 返回 200。Tomica robots 返回 404，仅记录未知。
- 微信开发者工具常见安装路径和命令未在本次检查中发现，不据此断言未安装；执行前通过 WECHAT_CLI_PATH 指定实际路径。
- 运行模式明确为本地演示、真实采集验证、正式发布三阶段。演示数据不计入来源完整性；真实采集先完成访问规则核对；正式发布核对部署、合法域名、内容/图片复用证据及微信验收。
- 实施时参考官方文档：[FastAPI 容器部署](https://fastapi.tiangolo.com/deployment/docker/)、[SQLAlchemy PostgreSQL](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)、[APScheduler 3.x](https://apscheduler.readthedocs.io/en/3.x/userguide.html)、[微信自动化 SDK](https://www.npmjs.com/package/miniprogram-automator)。此处为计划编写时基线；执行后状态、真实测试输出及部署见 execution-summary.md 与 deployment-state.md。

---

### Task 0: 环境准备

**背景:**
项目目前只有设计与本计划，无公共代码、调用方、依赖清单、迁移或测试设施；全部业务文件均为新增。
已读取环境为 Python 3.10.11、Node 25.9.0、npm 11.12.1、Docker CLI 28.5.1；Docker 配置访问出现权限告警，未验证 daemon。先建立隔离工具链，供 Task 1—6 使用。

**涉及文件:**
- 新建: `D:/poke&Tomy/pyproject.toml`
- 新建: `D:/poke&Tomy/requirements.lock`
- 新建: `D:/poke&Tomy/package.json`
- 新建: `D:/poke&Tomy/package-lock.json`
- 新建: `D:/poke&Tomy/backend/__init__.py`
- 新建: `D:/poke&Tomy/backend/app/__init__.py`
- 新建: `D:/poke&Tomy/backend/app/config.py`
- 新建: `D:/poke&Tomy/backend/tests/conftest.py`
- 新建: `D:/poke&Tomy/backend/tests/test_config.py`
- 新建: `D:/poke&Tomy/scripts/check_toolchain.py`

**执行步骤:**
- [x] 创建依赖与隔离运行环境。
  - 位置: `D:/poke&Tomy/pyproject.toml` 文件顶层定义项目、setuptools 包发现及 pytest testpaths=`backend/tests`；Python requires-python 为 >=3.10。运行依赖限定 FastAPI >=0.115,<1、Pydantic >=2,<3、pydantic-settings >=2,<3、SQLAlchemy >=2.0,<2.1、psycopg[binary] >=3,<4、alembic >=1.13,<2、httpx >=0.27,<1、beautifulsoup4 >=4.12,<5、APScheduler >=3.11,<4、boto3 >=1.35,<2、uvicorn >=0.30,<1；dev extra 包含 pytest >=8,<9、pytest-cov >=5,<8、pip-tools >=7,<8。
  - 在项目根依次执行 `python -m venv .venv`、`& '.venv/Scripts/python.exe' -m pip install pip-tools`、`& '.venv/Scripts/python.exe' -m piptools compile --extra dev --output-file requirements.lock pyproject.toml`、`& '.venv/Scripts/python.exe' -m pip install -r requirements.lock`。执行阶段将解析后的精确版本写入锁文件，计划不声称已安装依赖。
  - 位置: `D:/poke&Tomy/package.json` 新建 scripts.test=`node --test miniprogram/tests/*.test.js`、scripts.smoke=`node scripts/miniprogram-smoke.js`；加入 devDependency `miniprogram-automator`，执行 `npm install --package-lock-only`、`npm ci` 生成并使用 `D:/poke&Tomy/package-lock.json`。使用 CommonJS，与微信原生 JS 模块一致。Task 5 才首次运行 npm test。
  - 原因: 使用本地虚拟环境与锁文件，避免污染全局包或依赖不可复现。
- [x] 新建配置加载与 pytest 数据库基础。
  - 位置: `D:/poke&Tomy/backend/app/config.py:Settings` 定义 `database_url,admin_token,source_interval_seconds,timezone,object_store_endpoint,object_store_bucket,object_store_access_key,object_store_secret_key,public_image_base_url`；database_url 默认指向本机 15432 的 dual_catalog_demo（postgresql+psycopg 驱动，不含真实密码），默认时区 Asia/Shanghai，节流不得低于 2 秒。秘密用 SecretStr，日志禁止 dump 全配置；缺失管理员 token 时管理写入接口不可用，公共图鉴可启动。env_file 读取项目根 .env，配置 extra='ignore'；PUBLIC_API_BASE_URL、WECHAT_APP_ID、WECHAT_CLI_PATH 等发布字段由 Task 6 发布校验器单独读取并验证，不以忽略额外字段代替发布校验。
  - 位置: `D:/poke&Tomy/backend/tests/conftest.py` 新建 `session` fixture：SQLAlchemy SQLite 内存引擎 + StaticPool，启用外键，逐测试事务隔离；在 fixture 函数内导入 Task 1 Base，令 Task 0 配置测试独立运行。生产专属 PostgreSQL 锁、NULL排序、迁移与 upsert 在 Task 6 用真实数据库补测。
  - 位置: `D:/poke&Tomy/backend/__init__.py`、`D:/poke&Tomy/backend/app/__init__.py` 建立无导入副作用的包；不在导入阶段访问数据库或公网。
  - 原因: 单元测试无需云账号，配置错误能够在应用边界明确报告。
- [x] 增加工具链诊断入口。
  - 位置: `D:/poke&Tomy/scripts/check_toolchain.py:main()` 读取当前解释器版本、执行 node --version 与 npm --version，输出 JSON 和退出码；`--containers` 执行 docker info 并单独报告 stderr，权限/daemon异常不得返回通过；`--wechat` 从 WECHAT_CLI_PATH 验证可执行文件，缺失退出非零。不自动安装软件、不修改 Docker 用户配置。
  - 原因: 将基础开发、容器集成和微信验收分别给出真实结果，后两项缺失不得冒充端到端通过。
- [x] 为配置约束编写单元测试。
  - 测试文件: `D:/poke&Tomy/backend/tests/test_config.py`。
  - 测试场景: 环境变量覆盖默认值；小于 2 秒间隔拒绝；非法数据库 URL 拒绝；秘密 repr 不暴露；缺 token 返回管理关闭配置。
  - 运行命令: `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_config.py -q`
  - 预期: 全部通过，不依赖 Task 1 的实体或真实凭证。

**检查步骤:**
- [x] 验证 Python、Node、npm 与依赖无冲突。
  - `& '.venv/Scripts/python.exe' scripts/check_toolchain.py`
  - `& '.venv/Scripts/python.exe' -m pip check`
  - 预期: 均退出 0，诊断版本真实可读。
- [x] 验证测试框架与配置逻辑。
  - `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_config.py -q`
  - 预期: 收集到测试且全部通过。
- [x] 验证配置模块语法。
  - `& '.venv/Scripts/python.exe' -m compileall -q backend/app/config.py scripts/check_toolchain.py`
  - 预期: 退出 0。Docker 与微信诊断在 Task 6 就绪后分别执行，不将基础检查当成部署验收。

---

### Task 1: 数据模型与共享契约

**背景:**
多美卡同号不同代次和宝可梦同号不同形态必须分别建模，避免采集覆盖已有条目。
当前没有业务代码、业务表或测试，服务器仅有独立空业务库；依赖 Task 0 的配置与 pytest 基础，产出的实体、适配器输入输出和接口契约供 Task 2—6 共用。

**涉及文件:**
- 新建: `D:/poke&Tomy/backend/app/models.py`
- 新建: `D:/poke&Tomy/backend/app/schemas.py`
- 新建: `D:/poke&Tomy/backend/app/repository.py`
- 新建: `D:/poke&Tomy/backend/alembic.ini`
- 新建: `D:/poke&Tomy/backend/migrations/env.py`
- 新建: `D:/poke&Tomy/backend/migrations/versions/0001_catalog.py`
- 新建: `D:/poke&Tomy/backend/tests/test_repository.py`
- 新建: `D:/poke&Tomy/docs/api-contract.md`

**执行步骤:**
- [x] 定义图鉴实体及数据库约束。
  - 位置: `D:/poke&Tomy/backend/app/models.py`，新建 `Base`、`TomicaModel`、`TomicaVariant`、`Pokemon`、`PokemonForm`、`Evolution` 类。
  - 多美卡使用 UUID 主键；`TomicaModel` 包含 `series,number,generation,name_original,name_display,brand,release_year,release_month,scale,source_url,source_locator,primary_image_id,checked_at,updated_at`，年月可空，月份限制 1—12；编号不设置单列唯一约束。`TomicaVariant` 外键关联车型，另存 `variant_code,description,special_orderer,country,release_year,release_month,image_id`，不继承基础车型发售日期。
  - `Pokemon.dex` 为正整数主键；包含 `name_zh,name_ja,name_en,types,height_m,weight_kg,abilities,source_url,checked_at,updated_at`；`PokemonForm` 以 `(dex,form_key)` 唯一，另存显示名、属性、图片和差异字段；`Evolution` 保存起止编号、起止形态和条件文本，唯一键覆盖完整关系，保留分支。
  - 原因: 将业务身份、版本差异与展示字段分离；宝可梦属性、特性等数组使用 SQLAlchemy 通用 JSON 类型，支持隔离单元测试。
- [x] 建立采集、身份、覆盖与发布记录。
  - 位置: `D:/poke&Tomy/backend/app/models.py`，图鉴实体之后新增 `SourcePage`、`SourceIdentity`、`SyncRun`、`SyncItem`、`FieldOverride`、`ImageAsset`、`CatalogRevision`。
  - `SourcePage` 以 `(source,url)` 唯一，存 `etag,last_modified,content_hash,checked_at,updated_at,last_success_at`；`SourceIdentity` 以 `(source,kind,source_key)` 唯一，映射内部实体 ID，另存原始证据和人工核对状态。
  - `SyncRun` 保存来源、模式、状态、开始结束时间和统计；`SyncItem` 以 `(run_id,url)` 唯一，存状态、尝试次数、下次重试时间、解析候选 JSON、问题 JSON 与进度；item状态固定 pending/processing/succeeded/failed/isolated，未到重试时间的failed不领取，重试入口把可重试项置pending。`FieldOverride` 以 `(kind,entity_key,field)` 唯一，存人工值、操作者与时间。
  - `ImageAsset` 保存来源 URL、内容摘要、对象键、授权记录引用、署名、状态和最近错误；`CatalogRevision` 每来源一行，事务发布成功后递增 `revision`。所有时间以带时区 UTC 存储，运行时转北京时间。
  - 原因: 让断点恢复、内容时间、人工覆盖及分页数据版本具有明确持久化落点。
- [x] 冻结来源适配器输入输出类型。
  - 位置: `D:/poke&Tomy/backend/app/schemas.py`，文件顶部新增 Pydantic 类型 `ParseIssue(code,message,url,locator,severity)`、`SourceCandidate(kind,source_key,fields,evidence)`、`ParsedPage(source,url,discovered_urls,candidates,issues,content_hash)`；`kind` 枚举为 `tomica_model,tomica_variant,pokemon,pokemon_form,evolution`。
  - `source_key` 可空，空值必须附身份待核对问题；`evidence` 保留页 URL、锚点、原始标识和图片路径，不接受行号/数组位置作为稳定身份。定义 HTTP 输出 `ErrorResponse(code,message)`、`PageResponse(items,next_cursor)` 及车型、版本、宝可梦、形态、进化、同步记录 DTO；公开 DTO 不含管理凭证或原始待发布内容。
  - 在 `schemas.py` 的 DTO 之后定义 `TomicaQuery(q: str | None = None, brand: str | None = None, year: int | Literal["unknown"] | None = None, limit: int = 30, cursor: str | None = None)` 与 `PokemonQuery(q: str | None = None, type: str | None = None, limit: int = 30, cursor: str | None = None)`；Pydantic field validators 去除 q 首尾空格、限制100字符，limit 1—100，year 正整数或 unknown，brand unknown 表示 NULL，type 仅允许标准十八属性，空筛选统一为 None；DTO 定义中明确 UUID/正整数标识、nullable字段与 ISO8601 时间。
  - 原因: Task 2 只产候选数据，Task 3 负责身份匹配与发布，Task 4 不直接返回 ORM 对象。
- [x] 实现事务内读写与稳定列表查询。
  - 位置: `D:/poke&Tomy/backend/app/repository.py`，新建 `CatalogRepository(session: Session)`；方法 `get_tomica(model_id: UUID)`, `get_pokemon(dex: int)`, `list_tomica(query: TomicaQuery)`, `list_pokemon(query: PokemonQuery)`, `get_tomica_filters()`, `get_revision(source: str)`, `stage_page(run_id: UUID,page: ParsedPage)`, `publish_candidates(run_id: UUID,candidates: list[SourceCandidate])`, `set_override(kind: str,entity_key: str,field: str,value: object,actor: str)`。
  - 方法由调用方显式传入 Session，不自行创建全局连接或提交事务；详情未知返回 `None`。发布按业务唯一键 upsert，字段变更才更新 `updated_at`，成功检查更新 `checked_at`；读取时合并允许字段的人工覆盖，保留来源值供管理页比较。`list_tomica()`、`list_pokemon()`、`get_tomica_filters()` 在 SQL 查询层先以 `(kind,entity_key,field)` 唯一覆盖记录构建有效值表达式，再统一筛选、排序和键集分页；覆盖存在且值为 JSON null 时必须映射 SQL NULL，不用 COALESCE 错误回退来源值。整表先分页再在Python覆盖/过滤禁止使用。
  - 车型按 `release_year ASC NULLS LAST,id ASC`，宝可梦按 `dex ASC`；关键字参数化匹配，品牌/年份 `unknown` 查询 SQL NULL。游标采用键集分页，包含 `sort_key,filter_hash,revision`，条件规范化后计算 SHA-256；过滤条件不符返回 400，修订号变化返回 409 `CATALOG_CHANGED`，客户端清空列表重查。
  - 原因: 保证分页稳定、未知字段语义一致，避免后续任务各自实现互不兼容的列表协议。
- [x] 创建初始迁移，完成接口契约文档。
  - 位置: `D:/poke&Tomy/backend/migrations/env.py:run_migrations_online()` 读取 Task 0 `Settings.database_url`，绑定 `Base.metadata`；`D:/poke&Tomy/backend/migrations/versions/0001_catalog.py:upgrade()` 创建上述实体、外键、唯一约束、来源索引与查询索引，`downgrade()` 按依赖逆序撤销；`D:/poke&Tomy/backend/alembic.ini` 固定脚本目录为 `backend/migrations`，不嵌入凭证。
  - 位置: `D:/poke&Tomy/docs/api-contract.md`，新增“DTO、查询、管理、错误、CLI”章节；逐字段记录上述 DTO、日期格式、可空性及游标协议；列表 `limit` 默认 30、范围 1—100，`q` 去空格后最多 100 字符，`brand/year/type` 为单选参数。
  - 冻结 `GET /api/tomica`、`GET /api/tomica/filters`、`GET /api/tomica/{id}`、`GET /api/pokemon`、`GET /api/pokemon/{dex}`；静态 `/filters` 路由先于动态 ID 注册。详情含来源和内容更新时间；不存在返回 404，参数错误 422，游标错误 400/409。
  - 冻结 `GET /api/admin/runs`、`GET /api/admin/issues`、`POST /api/admin/sync`（`source,mode`，返回 202 和 `run_id`）、`POST /api/admin/runs/{id}/retry`（返回 202）、`PATCH /api/admin/overrides`（`kind,entity_key,field,value`，返回更新后覆盖记录），均需 Bearer 凭证；来源正在执行返回 409。`GET /health/live` 返回进程状态，`GET /health/ready` 校验数据库及迁移版本。
  - 冻结 `python -m backend.app.worker` 子命令 `init-db`、`seed-demo`、`sync --source tomica|pokemon --mode incremental|full [--limit N]`、`work`、`schedule`、`probe`、`report`；Task 3 实现，Task 6 复用。进程成功为退出码 0，失败为非零，报告输出结构化 JSON；限制 N 仅用于采集样本，不可计入全量完整性通过。
  - 原因: 新建项目没有可复用公共方法或调用点，先固定新增接口再由后续任务消费。
- [x] 为模型约束、发布与分页核心逻辑编写单元测试。
  - 测试文件: `D:/poke&Tomy/backend/tests/test_repository.py`；复用 Task 0 Session fixture，以 SQLite 内存数据库执行通用 ORM 逻辑，PostgreSQL 专属并发锁和迁移由 Task 6 集成验收覆盖。
  - 测试场景: 编号 001 的不同代次保存为两个车型；重复来源身份拒绝重复；相同候选二次发布不增行且内容时间不变；基础车型年份不传播给版本；全国编号 2、10 按整数排序；多形态列表仍仅一个全国编号；未知品牌/年份过滤；不同筛选游标返回错误；修订变化返回 `CATALOG_CHANGED`；人工覆盖经重复采集后仍可见；品牌/年份覆盖参与 filters、组合筛选与跨页年份排序，显式 null 覆盖归入 unknown，宝可梦名称/属性覆盖参与搜索筛选，覆盖改变后旧游标失效。
  - 运行命令: `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_repository.py -q`
  - 预期: 全部测试通过，不访问公网与生产数据库。

**检查步骤:**
- [x] 验证实体、契约和迁移可导入。
  - `& '.venv/Scripts/python.exe' -m compileall -q backend/app/models.py backend/app/schemas.py backend/app/repository.py backend/migrations`
  - 预期: 退出码 0，没有语法错误。
- [x] 验证仓储业务约束与稳定查询。
  - `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_repository.py -q`
  - 预期: 全部测试通过，覆盖同号代次、重复同步、版本日期、整数排序及游标失效。
- [x] 验证 Alembic 发现唯一初始迁移。
  - `& '.venv/Scripts/python.exe' -m alembic -c backend/alembic.ini heads`
  - 预期: 仅输出 `0001_catalog (head)`，不连接生产数据库。

---

### Task 2: 来源访问与双图鉴解析

**背景:**
两类图鉴的数据结构不同，多美卡旧式嵌套表格和百科多章节内容都需要保持上下文，防止字段串到其他车型或形态。
当前没有来源访问或解析代码；依赖 Task 1 的候选契约，本 Task 只返回解析结果，Task 3 负责身份映射、存储及发布。

**涉及文件:**
- 新建: `D:/poke&Tomy/backend/app/sources/base.py`
- 新建: `D:/poke&Tomy/backend/app/sources/http.py`
- 新建: `D:/poke&Tomy/backend/app/sources/tomica.py`
- 新建: `D:/poke&Tomy/backend/app/sources/pokemon.py`
- 新建: `D:/poke&Tomy/backend/tests/test_sources.py`
- 新建: `D:/poke&Tomy/backend/tests/fixtures/tomica-number.html`
- 新建: `D:/poke&Tomy/backend/tests/fixtures/tomica-special.html`
- 新建: `D:/poke&Tomy/backend/tests/fixtures/pokemon-list.html`
- 新建: `D:/poke&Tomy/backend/tests/fixtures/pokemon-detail.html`
- 新建: `D:/poke&Tomy/backend/tests/fixtures/pokemon-forms.html`
- 新建: `D:/poke&Tomy/backend/tests/fixtures/pokemon-evolution.html`
- 新建: `D:/poke&Tomy/docs/source-policy.md`

**执行步骤:**
- [x] 建立来源适配协议和 HTTP 返回类型。
  - 位置: `D:/poke&Tomy/backend/app/sources/base.py`，文件顶部新增 `SourceAdapter` Protocol：`seed_urls() -> list[str]`、`discover(url: str, body: bytes) -> list[str]`、`parse(url: str, body: bytes) -> ParsedPage`；`discover()` 返回 `parse()` 结果中的规范化 `discovered_urls`，不另发网络请求。新增 `FetchResult(url,final_url,status,headers,body,etag,last_modified,content_hash,not_modified,checked_at,error)` 数据类，`body` 在 304 时为空，访问失败保存错误码与简明说明。
  - `parse()` 为不联网、不写库的纯解析入口，候选采用 Task 1 的 `SourceCandidate`；成功解析页面也保留非致命 `ParseIssue`，页面结构无法识别时抛出 `SourceParseError`。原因: 保证解析可离线验证，调度端能够区分无变化与解析失败。
- [x] 实现白名单访问、访问规则及缓存请求。
  - 位置: `D:/poke&Tomy/backend/app/sources/http.py`，新增 `normalize_url(base: str, href: str, source: str) -> str` 和 `SourceHttpClient.fetch(url: str, etag: str | None, last_modified: str | None, previous_hash: str | None) -> FetchResult`。
  - Tomica 仅允许 `http://tomica.minibird.jp/t-tomica/` 下 HTML 页面；宝可梦仅允许 `https://wiki.52poke.com/wiki/`、`/zh-hans/` 下列表、主详情及已关联的形态页面。保留原站确实采用的 Tomica HTTP，不关闭 HTTPS 校验；对路径逐段编码，保留锚点供身份证据，抓取 URL 去掉片段，去重 URL 不改写日文条目名。拒绝凭证、端口变更、跨域链接及非 HTTP(S) 地址，每次重定向重新校验，最多 3 跳。
  - 在 `http.py:fetch_robots(source)` 单独允许固定 `http://tomica.minibird.jp/robots.txt`、`https://wiki.52poke.com/robots.txt`，仅用于策略读取，不进入 HTML 发现/候选，不作为通用路径白名单例外。robots 重定向仅允许同协议同主机同 `/robots.txt`，其余拒绝。`fetch()` 先按来源 robots.txt 检查路径，使用带项目名称的 User-Agent；robots 404 记为 `unknown`，不阻断已授权的只读小样本验证，也不解释成内容复用授权；robots 请求超时或服务器错误将本轮来源任务标为可重试失败。52poke 明确禁用的 `/index.php` 等路径不得访问，也不引入未验证的隐藏 API；401/403 直接记录访问拒绝，不绕过限制。
  - 每来源使用共享注入的单调时钟与 sleep 函数，实现请求开始间隔至少 2 秒；HTTP 超时 20 秒，含首次请求最多 3 次。仅超时、连接错误、429、5xx 重试，退避 2/4 秒，429 的 Retry-After 等待值取与退避值的较大者；超过 300 秒的等待交给 Task 3 持久化重试。其他 4xx 直接返回明确访问错误，不循环请求。
  - 发送已有 ETag/Last-Modified；304 返回 `not_modified=True`，200 计算原始内容 SHA-256，摘要相同同样返回无变化状态，禁止把空 body 交给解析器。原因: 减少重复读取并让 Task 3 保留最后一次成功内容；图片下载不属于本 Task 的 HTML 客户端。
- [x] 实现多美卡发现、分段解析和品牌规范化。
  - 位置: `D:/poke&Tomy/backend/app/sources/tomica.py`，新增 `TomicaAdapter.seed_urls()` 返回 menu.html；`parse()` 按菜单、编号页、特注或套装页调用 `parse_menu()`、`parse_number_page()`、`parse_supplement_page()`，使用 BeautifulSoup 与 CP932 解码。
  - `parse_menu()` 只发现编号、特注、套装相关 HTML 链接；同 URL 不同锚点合并为一次抓取，锚点证据另存。1085 个菜单链接只表示导航数量，不能作为车型完整性指标。
  - `parse_number_page()` 以实际车型锚点及车型标题为边界，先读取车型号、代次、名称、年月、比例，再在该边界内读取版本单元格；嵌套表格按所属车型和最近版本标识关联。禁止对整页去标签后用正则拼装记录；正则仅校验已定位字段的编号、年月、比例格式。
  - 在同文件新增 `normalize_brand(name: str) -> str | None`，以明确别名映射和车型制造商名称匹配，不从特注栏目名称推定品牌；保留未知品牌。`1970.9～` 只写基础车型年月，版本年月仅从版本自己的日期字段读取；底盘批次、套装说明中的年份不能替代版本日期。
  - `source_key` 优先采用规范车型锚点与可靠版本编码；不完整、重复或冲突编码保留原文、所属车型、图片路径和链接作为 evidence，返回待核对问题，不用数组序号生成身份。WANTED、装饰图及无实际图片条目输出图片未知状态；特注页引用编号锚点只补充版本关系，不创建同名重复车型。原因: Task 3 必须依据证据作可恢复的匹配。
- [x] 实现全国图鉴与主详情字段解析。
  - 位置: `D:/poke&Tomy/backend/app/sources/pokemon.py`，新增 `PokemonAdapter.seed_urls()` 指向全国图鉴简单版；`parse()` 调用 `parse_national_list()` 或 `parse_detail()`，按 UTF-8 解码并读取页面主内容区域。
  - `parse_national_list()` 按表头定位全国编号与中日英名列，编号转正整数，发现对应主详情链接；同编号去重，名称证据冲突返回 issue，不写死全国总数。原 Pokémon GO 页面不用于发现全国完整清单。
  - `parse_detail()` 在主信息框读取全国编号、名称、属性、身高体重和特性，在游戏章节的进化与形态区域读取关系；新增 `parse_forms()`、`parse_evolutions()` 保留形态键、各形态差异、分支起止编号与条件。排除导航、动画、漫画和旁支系列表格，缺失值保留 null，未能可靠定位的关系产生 issue，不凭名称猜测编号。
  - 图片候选读取真实图像元素的 `src/data-src` 与来源署名，优先内容图而非导航图；仅在候选字段记录来源 URL 和授权状态，实际图片域名与下载策略交 Task 3。原因: 防止全国列表、动画条目和特殊形态混为同一份详情。
- [x] 保存真实样本和来源规则记录。
  - 位置: `D:/poke&Tomy/backend/tests/fixtures/`，建立涉及文件中六份固定 HTML。多美卡编号样本来自 `http://tomica.minibird.jp/t-tomica/number/tba000.html`，保留至少两个同号不同代次及多版本的完整祖先表格；特注样本来自 `http://tomica.minibird.jp/t-tomica/special/tto%20Honda.html`。
  - 宝可梦样本分别截取全国列表、妙蛙种子主信息框、具有地区形态的主详情及伊布分支进化区域，保留必要标题和祖先结构；每份 HTML 首部注释记录来源 URL、抓取日期、编码和人工核对的预期字段。测试断言根据人工校对填写，不用解析器输出反向生成期望值；异常结构变体在测试内派生，不能替代真实页面样本。
  - 位置: `D:/poke&Tomy/docs/source-policy.md`，记录两个来源的入口、robots 检查时间与结果、允许抓取路径、频率、文本复用和图片复用的确认状态、证据链接、署名要求与更新责任；当前无复用证据的项目明确记为待确认。Task 6 发布检查读取该记录并拒绝未确认内容或图片的正式发布；本地使用固定样本与占位图开发继续进行。
  - `source-policy.md` 顶部新增 fenced JSON 机器可读区：每来源包含 `access_status,robots_status,checked_at,allowed_paths,min_interval_seconds,text_rights_status,text_evidence_url,image_rights_status,image_evidence_url,attribution,delivery_mode`；状态取 approved/pending/rejected，robots 另允许 unknown，政策读取与内容/图片复用分别判断。Task 6只解析这一段，缺字段/证据不能视作approved。
  - 原因: 本机已证实 Tomica 样本和 52poke 主详情可读，仍需固定证据验证字段，不能把网页可读当成全量完整性或复用授权。
- [x] 为来源协议、访问限制和解析规则编写单元测试。
  - 测试文件: `D:/poke&Tomy/backend/tests/test_sources.py`；用 httpx MockTransport、注入时钟及六份固定样本，禁止单元测试访问公网。
  - 测试场景: CP932 名称和嵌套车型/版本正确；同号不同代次分开、基础年份不传播、特注方不作为品牌、WANTED 不成为实物图；全国编号数值解析、同号形态合并、分支进化条件保留、动画章节排除；缺锚点和冲突编码产生 issue；304 与摘要相同跳过解析；跨域及重定向越界拒绝；robots固定根路径例外只读策略、404保持unknown且不授予复用许可；robots 禁止路径不发请求；2 秒间隔、429 Retry-After、三次上限和失败恢复可确定断言。
  - 运行命令: `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_sources.py -q`
  - 预期: 全部测试通过，网络客户端无真实外网请求。

**检查步骤:**
- [x] 验证来源模块可编译。
  - `& '.venv/Scripts/python.exe' -m compileall -q backend/app/sources`
  - 预期: 退出码 0，无编码或语法错误。
- [x] 验证真实样本解析与受控访问行为。
  - `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_sources.py -q`
  - 预期: 全部测试通过，覆盖嵌套表格、形态、分支进化、缓存与重试，真实来源样本的预期字段逐项匹配。
- [x] 验证固定样本与来源记录齐备。
  - `& '.venv/Scripts/python.exe' -c "from pathlib import Path; p=Path('backend/tests/fixtures'); names=('tomica-number.html','tomica-special.html','pokemon-list.html','pokemon-detail.html','pokemon-forms.html','pokemon-evolution.html'); assert all((p/n).is_file() for n in names); assert Path('docs/source-policy.md').is_file(); print('source fixtures and policy ready')"`
  - 预期: 输出 `source fixtures and policy ready`，退出码 0。

---

### Task 3: 可恢复同步、图片与定时任务

**背景:**
用户需要持续更新图鉴，同时来源暂时失败、页面改版和任务重启不能破坏已发布数据。
依赖 Task 1 的仓储与 Task 2 的适配器，本 Task 负责身份判定、任务状态和发布事务；Task 4 只调用入队接口，Task 6 验证 PostgreSQL 并发与部署调度。

**涉及文件:**
- 新建: `D:/poke&Tomy/backend/app/sync/service.py`
- 新建: `D:/poke&Tomy/backend/app/sync/identity.py`
- 新建: `D:/poke&Tomy/backend/app/sync/images.py`
- 新建: `D:/poke&Tomy/backend/app/worker.py`
- 新建: `D:/poke&Tomy/backend/tests/test_sync.py`
- 新建: `D:/poke&Tomy/backend/tests/test_images.py`
- 新建: `D:/poke&Tomy/backend/tests/fixtures/demo.json`
- 新建: `D:/poke&Tomy/backend/migrations/versions/0002_sync_runtime.py`
- 修改: `D:/poke&Tomy/backend/app/models.py`
- 修改: `D:/poke&Tomy/docs/api-contract.md`

**执行步骤:**
- [x] 补齐任务恢复所需字段与数据库约束。
  - 位置: `D:/poke&Tomy/backend/app/models.py` 的 `SyncRun` 末尾增加 `limit,requested_at,replay_of,followup_mode,last_error`，状态固定 `queued,running,succeeded,partial,limited,failed`；`SourcePage` 增加 `discovered_urls,accepted_count`，保存上次成功清单与同页解析基线；`ImageAsset` 增加 `rights_status,next_retry_at,attempts,public_url`，默认授权状态 pending。时间与 JSON 约定沿用 Task 1。
  - 位置: `D:/poke&Tomy/backend/migrations/versions/0002_sync_runtime.py:upgrade()` 创建上述列，并建立 `(source)` 的部分唯一索引，限定状态为 queued/running；ORM索引同步定义postgresql_where与sqlite_where为相同谓词，避免SQLite错误变成source全表唯一；同一来源只能存在一个活跃任务。`downgrade()` 逆序撤销本迁移，旧迁移不重写。
  - 原因: 把重启、304清单复用、预算限制和图片重试落到持久化状态，而非进程内变量。
- [x] 实现稳定身份解析与歧义隔离。
  - 位置: `D:/poke&Tomy/backend/app/sync/identity.py` 文件顶部新增 `IdentityResolver.resolve(candidate: SourceCandidate, repository: CatalogRepository) -> ResolvedIdentity`；车型按来源锚点映射，版本按所属车型与可靠版本标识映射；宝可梦和形态使用全国编号及规范形态键，进化使用起止形态与完整条件。
  - 缺少 source_key 的候选，使用规范来源页、父车型标识、原始版本字段、规范图片路径构成证据摘要，查询已保存的 SourceIdentity；唯一明确匹配才复用，首次明确证据创建 UUID 映射，多个匹配或相同证据不同内容写 `IDENTITY_AMBIGUOUS` issue 并隔离候选。不使用 DOM 顺序、列表下标或可变显示名称作为永久身份。
  - 将解析后的稳定实体键加入候选 fields，交 Task 1 `publish_candidates()` 写入；不复制仓储 upsert 或人工覆盖逻辑。原因: 身份决策集中在一处，特注页和编号页能够引用同一实体。
- [x] 实现持久化入队、互斥认领和恢复。
  - 位置: `D:/poke&Tomy/backend/app/sync/service.py` 顶部新建 `SyncService(session: Session, settings: Settings, *, session_factory: Callable[[], Session] | None = None, http_client: SourceHttpClient | None = None, lock_provider: SourceLockProvider | None = None, image_service: ImageService | None = None, clock: Callable[[], datetime] | None = None)`。同文件定义 `SourceLockProvider.acquire(source: str) -> SourceLease | None` 与 lease 的 `assert_alive()/close()`；默认工厂使用 settings 创建生产 http客户端、专用PG锁连接、独立业务Session、UTC时钟与 ImageService，ImageService 构造接受注入的下载客户端/S3客户端/时钟，默认使用受限下载器及boto3。单测必须传假锁、MockTransport、假S3与假时钟，禁止默认生产依赖偷联网。
  - 同文件定义仅承载结果的dataclass：`RunResult(run_id: UUID,status: str,complete: bool,counts: dict[str,int])`；`identity.py`定义 `ResolvedIdentity(entity_key: str | None,issues: list[ParseIssue])`，`images.py`定义 `ImageResult(asset_id: UUID,status: str,public_url: str | None,error: str | None)`，不引入额外框架。新增 `SyncService.enqueue_run(source: str,mode: str,limit: int | None = None,replay_of: UUID | None = None) -> UUID`、`claim_next_run() -> UUID | None`、`run_once(run_id: UUID) -> RunResult`、`retry_run(run_id: UUID) -> UUID`。同源 queued/running 任务存在时，手动入队返回领域错误 `SOURCE_BUSY`，Task 4 映射 409；重试只复制失败/待重试页面，成功页不重复加入。
  - 采用专用 PostgreSQL 连接执行 `pg_try_advisory_lock()`；锁键由固定来源整数表 `{tomica: 71001,pokemon: 71002}` 提供。入队在调用方短事务中检查活跃任务并插入，部分唯一索引裁决竞争，使用嵌套savepoint将唯一冲突转 SOURCE_BUSY，不获取覆盖整个run的同源锁；只有worker认领/执行才获取专用锁。认领通过 `SELECT ... FOR UPDATE SKIP LOCKED` 查 queued/running 记录，再获取同源会话锁，锁连接覆盖 run 全周期；锁未取得跳过该来源。API 进程仅入库，不执行采集或 FastAPI BackgroundTasks。`enqueue_run/retry_run` 只flush、不commit、不自行begin；HTTP/CLI/调度调用方在首次SQL前开启短事务并提交。`claim_next_run/run_once` 不复用HTTP Session，必须通过 session_factory 逐检查点创建短业务事务。专用锁连接为AUTOCOMMIT且禁用透明重连，空闲锁不持有业务事务；网络抓取/退避在业务事务外执行。
  - 获取来源锁后将该 run 的旧 processing 项重置 pending，逐项从持久化进度继续；每项完成立即提交状态。锁连接断开立即终止当前 run，每次发布前在同一专用连接开启短事务、执行 SELECT 1 并通过绑定该连接的Session写入发布及checkpoint，提交后恢复AUTOCOMMIT，锁丢失会导致该事务失败，禁止在另一个连接上做“探活后发布”的竞态；不自动重连后继续旧任务；finally 释放锁并关闭连接。原因: 跨进程排他，并让崩溃后的 running 任务可恢复。
- [x] 实现增量发现、分批校验与事务发布。
  - 位置: `D:/poke&Tomy/backend/app/sync/service.py:run_once()` 在锁内先处理来源入口，再合并入口发现清单与数据库已知详情清单；入口 304 使用 SourcePage.discovered_urls，仍逐一条件请求已知详情，不能因入口没变跳过全部详情。full 模式重读所有已知及新发现页面，增量模式使用缓存头和内容摘要。
  - 每个页面经 fetch → parse → stage_page → resolve → validate → publish。304/摘要相同只更新检查时间；网络/解析失败记录 SyncItem 错误并保留旧正式页。有效结构、车型/全国编号、必填名称、来源定位、父子关联为发布必检；已发布同页候选数量下降超过 20%、空解析和严重模板错误阻断该页批次，入口发现清单下降超过 20% 阻断该轮新数据发布；首次导入无基线仍必须通过结构与必填校验。
  - 单页全部合法候选在一个事务中调用仓储发布，出现身份歧义时该页整体隔离；实际公开字段发生变化才递增对应 CatalogRevision、更新内容时间，人工覆盖读取规则沿用 Task 1。失败页与来源消失记录不删除；Run 统计新增/修改/不变/失败/隔离/待补详情数量，全部完成为 succeeded，失败页存在为 partial，预算未遍历完为 limited，禁止 limited 记录参与全量完整性通过。
  - `Retry-After >300秒` 保存 SyncItem.next_retry_at，下一轮 work 继续处理，当前 worker 不长时间阻塞；重试总尝试数沿用 Task 2 的三次上限，手动重试建立新 run 并保留 replay_of。原因: 浏览数据发布不受个别来源故障拖累，完整性报告保持真实。
- [x] 增加独立图片处理与失败恢复。
  - 位置: `D:/poke&Tomy/backend/app/sync/images.py` 新增 `ImageService.process_asset(asset_id: UUID) -> ImageResult`，只处理 rights_status=approved 且授权证据引用有效的记录；pending/rejected 均返回占位状态，不尝试下载。授权证据同时记录允许用途、来源、署名和确认时间，网页可访问不作为授权依据。
  - 允许的图片来源主机固定为 `tomica.minibird.jp,s1.52poke.com`；每跳重定向重新校验，禁止凭证、自定义端口、私网/回环/链路本地地址，DNS解析后的连接目标也需校验。超时20秒、最多3次总尝试，流式下载最大10MiB，检查 MIME 与 PNG/JPEG/GIF/WebP 文件签名；WANTED/装饰图候选从入口排除，不上传原始任意 HTML。
  - 按 SHA-256 内容摘要生成对象键，使用 boto3 的 S3兼容接口上传；只生成经过配置验证的自有 HTTPS public_image_base_url。失败保存错误、attempts和下次重试时间，成功只更新图片状态和受影响来源修订，不回滚已发布文本；重试由 work 空闲轮询处理，每来源保持串行及2秒节流。
  - 原因: 图片授权、下载或对象存储故障不阻断文字图鉴，并防止任意候选URL变成后端访问入口。
- [x] 创建独立 worker、调度器与可核对 CLI。
  - 位置: `D:/poke&Tomy/backend/app/worker.py:main()` 使用 argparse 定义 `init-db`（Alembic upgrade head）、`seed-demo --confirm-demo`（仅允许数据库名 dual_catalog_demo）、`sync --source tomica|pokemon --mode incremental|full [--limit N]`（正常入队后本进程执行；同源queued且模式相同的CLI维护窗口允许认领该已有run，不重复插入；running由work恢复，其他冲突仍返回SOURCE_BUSY）、`work`（持续认领队列）、`schedule`（独立常驻，仅入队）、`probe`（每来源各访问入口及一个详情，输出状态不发布）、`report`（输出最近运行、待补详情和调度下次时间JSON；报告文件写/app/artifacts/acceptance，本机用仓库artifacts/acceptance）。从 Settings 读取 DATABASE_URL/.env，日志不输出密码；成功退出0，partial/limited/failed报告明确 complete=false，采集失败退出非零。
  - `schedule` 使用 APScheduler 3 BlockingScheduler、Asia/Shanghai、coalesce=True、max_instances=1，固定任务ID；每日03:00增量、周日04:00全量。调度与worker分容器；活跃任务为 queued 时提升为 full，活跃任务为 running 时写 followup_mode=full，worker 完结当前任务后在同一短事务先将当前run转终态再插入后续full，使部分唯一索引不冲突，再释放同源锁，避免周任务被长日任务吞掉。手动请求仍返回 SOURCE_BUSY，不静默改写用户请求。
  - 位置: `D:/poke&Tomy/backend/tests/fixtures/demo.json` 新建明确标注 synthetic 的演示集：同号两代车型、未知品牌与年份、多版本独立日期、dex2与10、多形态和伊布分支关系、来源时间与占位图片；seed-demo 通过仓储发布，重复执行幂等，不下载来源图片。不得对生产库运行。
  - 位置: `D:/poke&Tomy/docs/api-contract.md` 的 CLI 与管理章节追加本Task方法签名、状态枚举、SOURCE_BUSY、followup语义及report完整性字段，供Task4—6直接复用。原因: 命令、后台与定时任务共享同一执行服务。
- [x] 为身份、任务恢复、校验发布和图片处理编写单元测试。
  - 测试文件: `D:/poke&Tomy/backend/tests/test_sync.py`、`D:/poke&Tomy/backend/tests/test_images.py`；使用注入锁接口、假时钟、MockTransport及模拟S3，不联网。PostgreSQL真实锁与进程断开由Task6集成测试补充。
  - 测试场景: 多代车型不覆盖、歧义页隔离；重复同步不改内容时间/修订、人工覆盖保留；入口304仍检查详情；页空/数量下降/429/超时不清空旧数据；预算limit报告不完整；持久化恢复跳过成功页；同源busy与不同来源独立；周全量followup不丢失；固定北京时间触发下一运行时间；pending授权不下载、越界/私网/超大文件拒绝、上传失败保留文本、摘要幂等与图片重试。
  - 运行命令: `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_sync.py backend/tests/test_images.py -q`
  - 预期: 全部测试通过，未调用公网、真实S3或生产数据库。

**检查步骤:**
- [x] 验证同步模块与CLI可导入。
  - `& '.venv/Scripts/python.exe' -m compileall -q backend/app/sync backend/app/worker.py backend/migrations`
  - `& '.venv/Scripts/python.exe' -m backend.app.worker --help`
  - 预期: 均退出0，帮助列出七个约定子命令。
- [x] 验证同步与图片的异常路径。
  - `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_sync.py backend/tests/test_images.py -q`
  - 预期: 全部通过，旧数据保留、恢复、followup、授权和图片独立性均有断言。
- [x] 验证迁移链完整。
  - `& '.venv/Scripts/python.exe' -m alembic -c backend/alembic.ini heads`
  - 预期: 仅输出 `0002_sync_runtime (head)`；真实数据库升级与并发锁在Task6验证。

---

### Task 4: 图鉴查询接口与数据管理

**背景:**
用户通过稳定 API 查找和查看图鉴，管理员需要了解更新状态、重试失败页面及纠正展示字段。
当前尚无 HTTP 或管理界面；依赖 Task 1 的查询/DTO 和 Task 3 的入队服务，输出供 Task 5 小程序及 Task 6 部署验收消费。

**涉及文件:**
- 新建: `D:/poke&Tomy/backend/app/main.py`
- 新建: `D:/poke&Tomy/backend/app/api.py`
- 新建: `D:/poke&Tomy/backend/app/admin.py`
- 新建: `D:/poke&Tomy/backend/admin/index.html`
- 新建: `D:/poke&Tomy/backend/admin/admin.js`
- 新建: `D:/poke&Tomy/backend/admin/admin.css`
- 新建: `D:/poke&Tomy/backend/tests/test_api.py`
- 修改: `D:/poke&Tomy/docs/api-contract.md`

**执行步骤:**
- [x] 创建应用工厂、请求级数据库依赖和健康检查。
  - 位置: `D:/poke&Tomy/backend/app/main.py` 顶部新增 `create_app(settings: Settings) -> FastAPI`、`get_session(request: Request) -> Iterator[Session]`；创建应用时保存 engine、`app.state.settings=settings`、`app.state.session_factory=sessionmaker(engine)`，lifespan 退出释放连接池；每请求创建独立 Session，结束关闭，异常回滚；该依赖不预先begin或SELECT，禁止导入模块时访问数据库或来源网站。
  - 工厂内部导入并按顺序注册公共 api router、管理 router，再挂载静态管理页面 `/admin/`；提供 `app = create_app(Settings())` 供 `uvicorn backend.app.main:app` 启动。公共查询只执行 SELECT，管理写入在明确的 `session.begin()` 事务内提交。
  - 新增 `live() -> dict` 对应 `/health/live`，不依赖数据库；`ready(session: Session) -> dict` 对应 `/health/ready`，校验 `SELECT 1` 与 Alembic 当前 revision 等于 ScriptDirectory 获取的 head，未就绪返回 503，不把连接串或异常堆栈放进响应。原因: 运行状态与迁移就绪分别供部署探针判断。
- [x] 暴露分页查询、筛选项与详情。
  - 位置: `D:/poke&Tomy/backend/app/api.py` 顶部创建 APIRouter，新增 `list_tomica(query: TomicaQuery,session: Session)`、`tomica_filters(session: Session)`、`tomica_detail(model_id: UUID,session: Session)`、`list_pokemon(query: PokemonQuery,session: Session)`、`pokemon_detail(dex: int,session: Session)`，直接调用 Task 1 CatalogRepository 对应方法，并通过共享 DTO 序列化。
  - 注册 `GET /api/tomica/filters` 先于 `/api/tomica/{id}`；列表沿用 `items,next_cursor`，limit 为 1—100、默认30，q 去空格且最长100；多美卡 brand/year 的 `unknown` 映射未知值，宝可梦名称/全国编号搜索与属性筛选保持单个全国编号一行。筛选项filters、列表筛选、排序与返回 DTO 均基于人工覆盖后的有效值，不只在详情上应用覆盖。
  - 车型按年份空值末尾及UUID排序、宝可梦按整数dex排序；游标错配400，数据修订变化409 `CATALOG_CHANGED`，不偷偷从另一页返回数据。详情未收录返回404，来源/时间/图片状态按契约输出，无图或未授权图片返回空 URL。原因: 小程序能够可靠恢复筛选与分页状态。
- [x] 实现管理员鉴权和持久化入队操作。
  - 位置: `D:/poke&Tomy/backend/app/admin.py` 顶部新增 `require_admin(request: Request) -> str`，只接收 Authorization Bearer，使用 `secrets.compare_digest` 比较配置凭证；缺失或错误返回401，服务未配置管理员凭证返回503 `ADMIN_DISABLED`，不把 token 写日志、URL或异常；认证结果返回固定操作者标识 `admin`。
  - 同文件新增可由测试替换的依赖 `get_sync_service(request: Request,session: Session) -> SyncService`，精确调用 `SyncService(session=session, settings=request.app.state.settings, session_factory=request.app.state.session_factory)` 创建服务；供入队与重试路由通过Depends注入，不使用模块级共享Session。
  - 新增 `enqueue_sync(body: SyncRequest,session: Session)` 和 `retry_sync(run_id: UUID,session: Session)`，对应 `POST /api/admin/sync`、`POST /api/admin/runs/{id}/retry`；验证 source 为 tomica/pokemon、mode 为 incremental/full，在路由首次SQL前进入 `with session.begin():` 调用 Task 3 `enqueue_run()`/`retry_run()`，退出事务成功后返回202及run_id；不得在依赖已经隐式开启的事务里二次begin。领域错误 SOURCE_BUSY 映射409，未知run返回404、不可重试状态返回409；API不运行采集、不启用BackgroundTasks。
  - 原因: 管理触发与定时触发共用数据库队列及互斥，不能靠HTTP请求内的长任务实现同步。
- [x] 提供任务问题查询与受限人工纠错。
  - 位置: `D:/poke&Tomy/backend/app/admin.py` 在写入路由前新增 `list_runs(session: Session,source: Literal["tomica","pokemon"] | None = None,status: Literal["queued","running","succeeded","partial","limited","failed"] | None = None,limit: int = 30,cursor: str | None = None)` 与 `list_issues(session: Session,source: Literal["tomica","pokemon"] | None = None,run_id: UUID | None = None,status: Literal["pending","processing","succeeded","failed","isolated"] | None = None,limit: int = 30,cursor: str | None = None)`，对应已约定GET管理路由；按 `requested_at DESC,id DESC` 与 `run_id,id` 稳定分页，使用 items/next_cursor，limit限制1—100；issues为SyncItem.issues展开项，以issue在该已持久化JSON内的序号作为仅本次查询分页tie-breaker，cursor存run_id/item_id/issue_index及filter_hash，来源与status筛选针对SyncItem，禁止将列表下标用作业务身份。runs cursor存requested_at/id/filter_hash。未知枚举/非法UUID返回422，错配游标400。issues DTO 包含来源、页面、run_id、错误码、重试时间、待补详情或身份歧义类型，不返回原始凭证；支持 source/run_id/status 过滤。
  - 同文件新增 `set_override(body: OverrideRequest,session: Session)`，对应PATCH管理路由。白名单：tomica_model 为 name_display/brand/release_year/release_month/scale；tomica_variant 为 description/country/release_year/release_month；pokemon 为 name_zh/name_ja/name_en/types/height_m/weight_kg/abilities；pokemon_form 为 display_name/types。所有 ID、dex、外键、来源定位、图片授权和同步状态均禁止修改；字段值按共享DTO类型与年月/非负尺寸约束验证。
  - 事务内调用 Task 1 `set_override()` 保留原始采集值；读取覆盖前后有效值，有效值确实变化才递增该来源 CatalogRevision，并记录修改时间；相同值重复请求不递增。返回 `kind,entity_key,field,source_value,override_value,effective_value,actor,updated_at`；列表读取基于同一有效值投影。原因: 人工纠错持续生效，旧分页能检测筛选值变化。
- [x] 完成轻量同源管理页面和错误协议。
  - 位置: `D:/poke&Tomy/backend/admin/index.html` 新建凭证输入、来源/模式选择、手动同步、运行列表、问题列表、重试按钮、字段纠错表单和结果区；`D:/poke&Tomy/backend/admin/admin.css` 定义简洁响应式布局、状态及禁用样式。
  - 位置: `D:/poke&Tomy/backend/admin/admin.js` 新增 `adminRequest(path,options)`、`loadRuns()`、`loadIssues()`、`enqueueSync()`、`retryRun(runId)`、`saveOverride()`；token只存模块内存，刷新后清空，不使用localStorage/sessionStorage或嵌入HTML。所有来源文本用textContent/创建DOM节点呈现，禁止innerHTML；运行中按钮禁用，HTTP409展示已有冲突状态，认证失败清空内存token；纠错结果同时显示来源值、人工值与最终值。
  - 位置: `D:/poke&Tomy/backend/app/main.py:create_app()` 内注册 RequestValidationError、领域错误与未处理异常的响应处理器；统一 `ErrorResponse(code,message)`，422参数错误、404不存在、409冲突各自保留HTTP语义，500只返回通用错误与服务端脱敏日志。公开静态管理页面不包含数据和凭证，全部数据请求重新鉴权。
  - 位置: `D:/poke&Tomy/docs/api-contract.md` 的“管理、DTO、错误”章节补齐上述问题查询参数、管理员关闭状态、覆盖字段白名单和返回字段，明确人工覆盖参与列表筛选/排序与revision变化。原因: Task 5、Task 6使用同一可验证协议。
- [x] 为API、管理权限和纠错一致性编写单元测试。
  - 测试文件: `D:/poke&Tomy/backend/tests/test_api.py`；FastAPI TestClient 覆盖 get_session 与同步服务依赖，使用Task 0 SQLite事务fixture及假入队服务，并覆盖工厂的session_factory/http/锁/S3依赖，禁止公网、真实worker和生产数据库访问。
  - 测试场景: 同号不同代次详情；年份/品牌组合及unknown、按有效覆盖值筛选；全国编号2/10排序、多形态仍一行、详情来源时间；filters未被UUID路由拦截；游标错误400/409；参数422与未知详情404；管理缺token/错token401、未配置503；合法请求202且只入队、同源busy409；重试保留run映射；纠错类型验证及结构字段拒绝、原值保留、同值幂等、有效值变化使旧游标失效；HTML不嵌入token；数据库未迁移时ready503而live200。
  - 运行命令: `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_api.py -q`
  - 预期: 全部测试通过，任何图鉴GET和管理入队请求均未调用来源HTTP客户端。

**检查步骤:**
- [x] 验证后端和管理脚本语法。
  - `& '.venv/Scripts/python.exe' -m compileall -q backend/app/main.py backend/app/api.py backend/app/admin.py`
  - `node --check backend/admin/admin.js`
  - 预期: 均退出0，无Python或JavaScript语法错误。
- [x] 验证查询、权限、入队与覆盖行为。
  - `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_api.py -q`
  - 预期: 所有API测试通过，管理写入被保护，来源请求未发生。
- [x] 验证路由已生成公开协议且不泄露配置。
  - `& '.venv/Scripts/python.exe' -c "from backend.app.main import app; paths=app.openapi()['paths']; required=('/api/tomica','/api/tomica/filters','/api/pokemon','/api/admin/sync','/api/admin/overrides','/health/live','/health/ready'); assert all(p in paths for p in required); print('API routes ready')"`
  - 预期: 输出 `API routes ready`，退出0；应用导入不连接来源或数据库。

---

### Task 5: 微信双图鉴页面与交互

执行补充：按用户最新授权增加 `D:/poke&Tomy/backend/preview/index.html`、`D:/poke&Tomy/backend/preview/app.js`、`D:/poke&Tomy/backend/preview/style.css`，以相同查询 API 提供可点击的浏览器页面效果；Task 6 保留演示服务并提供链接和截图。该预览不替代微信编译验收。页面使用车型与宝可梦资料及图片状态，不能把合成演示数据当成完整真实图鉴。Task 6 增加浏览器交互截图验收，与微信正式发布的待办分开记录。

**背景:**
用户通过微信中的两个图鉴入口查找并打开条目，筛选与浏览位置在返回详情后保留。
当前没有小程序页面；本 Task 依赖 Task 1、Task 4 的查询契约，不调用来源站点或管理接口；Task 6 验证真实开发者工具中的编译、页面交互及截图。

**涉及文件:**
- 新建: `D:/poke&Tomy/miniprogram/app.js`
- 新建: `D:/poke&Tomy/miniprogram/app.json`
- 新建: `D:/poke&Tomy/miniprogram/app.wxss`
- 新建: `D:/poke&Tomy/miniprogram/project.config.json`
- 新建: `D:/poke&Tomy/miniprogram/sitemap.json`
- 新建: `D:/poke&Tomy/miniprogram/config.js`
- 新建: `D:/poke&Tomy/miniprogram/services/api.js`
- 新建: `D:/poke&Tomy/miniprogram/lib/catalog-state.js`
- 新建: `D:/poke&Tomy/miniprogram/pages/tomica-list/index.js`
- 新建: `D:/poke&Tomy/miniprogram/pages/tomica-list/index.json`
- 新建: `D:/poke&Tomy/miniprogram/pages/tomica-list/index.wxml`
- 新建: `D:/poke&Tomy/miniprogram/pages/tomica-list/index.wxss`
- 新建: `D:/poke&Tomy/miniprogram/pages/tomica-detail/index.js`
- 新建: `D:/poke&Tomy/miniprogram/pages/tomica-detail/index.json`
- 新建: `D:/poke&Tomy/miniprogram/pages/tomica-detail/index.wxml`
- 新建: `D:/poke&Tomy/miniprogram/pages/tomica-detail/index.wxss`
- 新建: `D:/poke&Tomy/miniprogram/pages/pokemon-list/index.js`
- 新建: `D:/poke&Tomy/miniprogram/pages/pokemon-list/index.json`
- 新建: `D:/poke&Tomy/miniprogram/pages/pokemon-list/index.wxml`
- 新建: `D:/poke&Tomy/miniprogram/pages/pokemon-list/index.wxss`
- 新建: `D:/poke&Tomy/miniprogram/pages/pokemon-detail/index.js`
- 新建: `D:/poke&Tomy/miniprogram/pages/pokemon-detail/index.json`
- 新建: `D:/poke&Tomy/miniprogram/pages/pokemon-detail/index.wxml`
- 新建: `D:/poke&Tomy/miniprogram/pages/pokemon-detail/index.wxss`
- 新建: `D:/poke&Tomy/miniprogram/tests/api.test.js`
- 新建: `D:/poke&Tomy/miniprogram/tests/catalog-state.test.js`
- 新建: `D:/poke&Tomy/miniprogram/tests/pages.test.js`

**执行步骤:**
- [x] 建立小程序入口、配置与共用视觉样式。
  - 位置: `D:/poke&Tomy/miniprogram/app.json` 顶层注册四个完整页面路径；tabBar 只包含多美卡列表与宝可梦列表，详情通过 navigateTo 打开；window 使用中文标题、浅色背景与深色文字。`D:/poke&Tomy/miniprogram/app.js` 新建 `onLaunch()`，初始化两个目录各自的内存浏览缓存，不存管理员凭证。
  - 位置: `D:/poke&Tomy/miniprogram/project.config.json` 顶层设置 miniprogramRoot 为 `./`、编译类型为 miniprogram、本地 appid 为 `touristappid`；`D:/poke&Tomy/miniprogram/sitemap.json` 明确页面索引规则。正式包 AppID 由 Task 6 发布配置生成流程写入并验证，测试号不计入正式发布通过。
  - 位置: `D:/poke&Tomy/miniprogram/config.js` 新建 `getConfig(envVersion)`，开发配置默认 `http://127.0.0.1:8092`，trial/release 要求构建时注入真实 HTTPS API 域名；禁止发布包回退到 localhost、HTTP 或服务器裸 IP。Node 测试显式传配置，不引用 wx 全局。
  - 位置: `D:/poke&Tomy/miniprogram/app.wxss` 顶层定义间距、字体、按钮、标签、两列卡片和空态共用样式；图片不存在时用 WXSS 图形与“暂无图片”文字，不新增来源不明的占位素材。原因: 首版形成一致、可读的图鉴界面，并隔离开发连接配置与正式域名。
- [x] 实现可取消的只读 API 客户端。
  - 位置: `D:/poke&Tomy/miniprogram/services/api.js` 新建 `createApi({baseUrl,request})`，导出 `listTomica(params)`、`getTomicaFilters()`、`getTomica(id)`、`listPokemon(params)`、`getPokemon(dex)`；每个方法返回 `{promise,abort}`，以注入的 wx.request 发 GET 请求，设置 15 秒超时，按 Task 1 的字段编码查询参数并读取 items/next_cursor。
  - 在请求完成回调内区分 HTTP 错误与网络错误，归一为 `{status,code,message}`；保留 409 CATALOG_CHANGED 供状态层处理，其余错误显示中文通用提示，不向用户展示服务器堆栈或内部日志。详情 ID 做 URI 编码，全国编号只接受正整数；客户端不提供管理 API 或 Bearer token 注入入口。原因: 让页面取消过期请求，并保持 API 与界面状态可独立测试。
- [x] 实现筛选、分页与生命周期状态管理。
  - 位置: `D:/poke&Tomy/miniprogram/lib/catalog-state.js` 新建 `createCatalogState({fetchPage,keyOf,onChange})`，导出 `setQuery(query)`、`loadMore()`、`retry()`、`suspend()`、`resume(snapshot)`、`snapshot()`；维护 query/items/nextCursor/loading/error/scrollTop/requestSequence，使用请求序号丢弃旧结果，同页加载互斥并按车型 UUID 或全国编号去重。
  - `setQuery()` 清空旧分页并开始首屏；loadMore 保持服务端排序，不按编号字符串再排序；409 CATALOG_CHANGED 取消当前页并从首屏重新查询，同一请求链仅自动重置一次，持续冲突进入可重试错误状态；普通失败保留已加载内容与重试游标。
  - 在同文件新增 `formatDex(dex)`、`displayValue(value)` 与 `formatBeijingTime(iso)`：编号至少四位、null/undefined/空文本显示“暂无资料”、数值 0 保留，时间标明北京时间。suspend 增加请求序号、取消当前请求并清理 loading；snapshot 保留条件、数据与位置，不包含请求句柄或凭证。原因: 避免快速筛选、返回页面和连续触底造成旧结果混入。
- [x] 完成两个列表页面与搜索筛选交互。
  - 位置: `D:/poke&Tomy/miniprogram/pages/tomica-list/index.js` 与 `D:/poke&Tomy/miniprogram/pages/pokemon-list/index.js` 文件顶层各导出 `createPage({api,cache,navigate,scrollTo})` 页面定义；真实微信环境通过 `typeof Page === 'function'` 守卫注册，Node 测试仅调用工厂，不设置全局 Page/App/wx。
  - 各页面新增 `onLoad/onShow/onHide/onUnload/onPageScroll/onReachBottom/onSearchInput/onFilterChange/onRetry/onCardTap`；搜索使用 300 毫秒防抖，修改条件重置分页，onHide/onUnload 清理定时器并 suspend，onShow 从独立缓存恢复条件与内容并恢复滚动位置。初次加载与未完成首屏恢复时执行首屏请求，不将空缓存误判为已加载。
  - 多美卡页先读取 filters 的有效品牌/年份选项，允许“全部”“未知”和品牌年份组合；年份标签使用“基础车型发售年份”。宝可梦页使用全国编号/名称搜索与标准属性单选。卡片打开对应详情 ID；宝可梦展示 #0001 格式，列表顺序直接使用服务端结果。
  - 位置: 两个列表的 `index.wxml/index.wxss/index.json` 顶层分别编写搜索框、筛选控件、两列卡片、首屏加载、加载更多、无结果、重试与图片失败占位，配置各自中文标题。卡片展示设计规定字段，image 的 binderror 只标记对应项失败，不能清空列表。原因: 实现用户要求的可组合查找与稳定浏览。
- [x] 完成车型及宝可梦详情页面。
  - 位置: `D:/poke&Tomy/miniprogram/pages/tomica-detail/index.js`、`D:/poke&Tomy/miniprogram/pages/pokemon-detail/index.js` 顶层导出 `createPage({api,navigate,copyText})`；在 onLoad 校验参数并读取详情，onUnload 取消请求，onRetry 重试，onImageError 切换对应图像占位，迟到回调不对已卸载页面 setData。
  - 多美卡新增 `selectVariant(event)`，展示车型名称、汽车品牌、编号代次、比例、基础发售年月、版本说明、独立版本年月和产地；版本日期未知明确显示“暂无资料”，不得用基础年份补齐。宝可梦新增 `selectForm(event)` 与 `openEvolution(event)`，显示中日英名、属性、身高体重、特性，切换形态只更新该形态的差异字段；进化按分支呈现并保留条件，仅已收录目标可跳转。
  - 位置: 两个详情的 `index.wxml/index.wxss/index.json` 顶层编写主图、字段区、版本/形态选择、进化区、来源和北京时间更新时间；onCopySource 仅按用户点击复制来源链接，不新增未配置外部 web-view。字段缺失、404 与接口失败各有明确状态，不渲染空白页。原因: 将不同版本和形态的资料留在正确业务上下文中。
- [x] 为请求、状态机和页面核心行为编写单元测试。
  - 测试文件: `D:/poke&Tomy/miniprogram/tests/api.test.js`、`D:/poke&Tomy/miniprogram/tests/catalog-state.test.js`、`D:/poke&Tomy/miniprogram/tests/pages.test.js`，使用 node:test、node:assert/strict；注入 request 替身、可控 Promise、伪时钟、setData 与导航适配器，不发公网请求，不伪装真实微信渲染。
  - 测试场景: 查询编码、取消请求、404/409/超时；组合条件重置游标、重复触底仅一请求、乱序响应忽略、409仅一次自动重置、失败保留旧数据；两个tab缓存独立、详情返回保留滚动、隐藏页不受旧回调修改；全国编号2/10展示与顺序；基础年份不补版本日期；形态切换与分支跳转、未知字段及图片错误占位；trial/release拒绝开发API地址、客户端没有管理token。
  - 运行命令: `node --test miniprogram/tests/api.test.js miniprogram/tests/catalog-state.test.js miniprogram/tests/pages.test.js`
  - 预期: 全部测试通过。Node结果仅证明JS逻辑，WXML/WXSS真实编译和页面截图由Task 6执行。

**检查步骤:**
- [x] 验证四页注册、双tab和配置JSON结构。
  - `node -e "const fs=require('node:fs'); const a=JSON.parse(fs.readFileSync('miniprogram/app.json','utf8')); const p=JSON.parse(fs.readFileSync('miniprogram/project.config.json','utf8')); JSON.parse(fs.readFileSync('miniprogram/sitemap.json','utf8')); const pages=['pages/tomica-list/index','pages/tomica-detail/index','pages/pokemon-list/index','pages/pokemon-detail/index']; require('node:assert/strict').deepEqual(a.pages,pages); require('node:assert/strict').deepEqual(a.tabBar.list.map(x=>x.pagePath),[pages[0],pages[2]]); for(const x of pages){for(const ext of ['js','json','wxml','wxss']) require('node:assert/strict').ok(fs.existsSync('miniprogram/'+x+'.'+ext)); JSON.parse(fs.readFileSync('miniprogram/'+x+'.json','utf8'));} require('node:assert/strict').equal(p.miniprogramRoot,'./'); console.log('four pages and two tabs ready');"`
  - 预期: 输出 `four pages and two tabs ready`，退出码0；这项是静态结构检查，不是微信编译结果。
- [x] 验证请求、列表状态与页面行为。
  - `npm test`
  - 预期: node内置测试实际收集上述三个测试文件，全部通过且无真实网络请求。
- [x] 验证全部小程序JS语法。
  - `Get-ChildItem -LiteralPath 'D:/poke&Tomy/miniprogram' -Recurse -Filter '*.js' | ForEach-Object { node --check $_.FullName; if ($LASTEXITCODE -ne 0) { throw ('JS syntax failed: ' + $_.FullName) } }`
  - 预期: 全部退出0；Task 6继续运行真实开发者工具smoke，不能用本项替代。

---

### Task 6: 服务器部署与验收工具

**背景:**
用户已提供现有服务器并授权数据库准备及部署；专用库和账号已创建，应用、表结构与客户端尚未部署，真实状态见同目录 deployment-state.md。
本 Task 消费 Task 1—5 的迁移、worker、API 和页面，补齐隔离部署及可执行证据工具，供 Task 7 区分离线、集成与正式发布结果；现有插件和其他服务保持原状。

**涉及文件:**
- 新建: `D:/poke&Tomy/Dockerfile`
- 新建: `D:/poke&Tomy/compose.yaml`
- 新建: `D:/poke&Tomy/compose.production.yaml`
- 新建: `D:/poke&Tomy/.dockerignore`
- 新建: `D:/poke&Tomy/.env.example`
- 新建: `D:/poke&Tomy/scripts/acceptance.py`
- 新建: `D:/poke&Tomy/scripts/check_release.py`
- 新建: `D:/poke&Tomy/scripts/miniprogram-smoke.js`
- 新建: `D:/poke&Tomy/backend/tests/test_release.py`
- 新建: `D:/poke&Tomy/docs/deployment.md`
- 新建: `D:/poke&Tomy/docs/human-verification.md`
- 新建: `D:/poke&Tomy/README.md`
- 修改: `D:/poke&Tomy/CHANGELOG.md`

**执行步骤:**
- [x] 建立本地与现有服务器分别使用的容器拓扑。
  - 位置: `D:/poke&Tomy/Dockerfile` 顶部建立 Python 3.12 slim 基础，按 requirements.lock 安装；定义 runtime、test 两个构建目标；requirements.lock来自dev extra，runtime也安装其全部锁定依赖（含pytest/pip-tools），不声称依赖精简；test只额外复制完整测试代码。runtime 包含应用、迁移、管理静态文件、来源政策、运行脚本及演示验收使用的固定HTML与synthetic demo.json，不包含来源下载图片；以非 root UID/GID 10001 运行，暴露应用健康检查；镜像标签由 APP_IMAGE 指定，禁止用漂移 latest 作为回滚依据。
  - 位置: `D:/poke&Tomy/compose.yaml` 新建 postgres、api、worker、scheduler 服务，本地 PostgreSQL 18、数据库 dual_catalog_demo，API 仅映射 `127.0.0.1:8092:8092`，worker 执行 `python -m backend.app.worker work`，scheduler 执行 `python -m backend.app.worker schedule`；容器DATABASE_URL显式指向 postgres:5432/dual_catalog_demo；postgres仅发布 `127.0.0.1:15432:5432`，供Task 0宿主机Python访问，不绑定公网5432。设置演示用户名/密码环境变量（仅本机演示值），宿主.env中的DATABASE_URL使用127.0.0.1:15432，服务environment覆盖为postgres:5432；不将生产连接秘密复制本地。
  - 位置: `D:/poke&Tomy/compose.production.yaml` 新建 api、worker、scheduler 三服务，全部使用 Linux host 网络及 `${APP_ENV_FILE:-.env}` 的env_file，。Compose由宿主root读取0600的env_file并将环境注入非root容器，禁止bindmount秘密文件。API 用 `uvicorn backend.app.main:app --host 127.0.0.1 --port ${API_PORT:-8092}`，复用回环地址既有 PostgreSQL 18；不定义 postgres 服务，不映射现有8080/8081端口。worker、scheduler 常驻且 restart=unless-stopped，分别限制进程/内存并保留总计至少1GB余量，日志轮转；三服务read_only=true、tmpfs=/tmp。`/app/artifacts` 与 `/app/logs` 分别bindmount `${PROJECT_DATA_DIR}/artifacts`、`${PROJECT_DATA_DIR}/logs`，生产PROJECT_DATA_DIR=/opt/dual-catalog，demo=/opt/dual-catalog/demo；宿主预建目录chown10001:10001、0700，备份和.env仍root专属。应用轮转日志写/app/logs，各进程独立文件；验收/worker报告写/app/artifacts/acceptance，镜像和来源政策只读。Docker stdout继续启用json-file轮转；禁止写入其他项目目录。禁止在API进程内启动调度器。
  - 位置: `D:/poke&Tomy/.dockerignore` 排除 .env、.env.demo、.git、.venv、node_modules、SSH材料、产物和本地秘密；`D:/poke&Tomy/.env.example` 仅列无秘密示例与必填字段 DATABASE_URL、ADMIN_TOKEN、APP_IMAGE、APP_ENV_FILE、PROJECT_DATA_DIR、API_PORT、PUBLIC_API_BASE_URL、WECHAT_APP_ID、WECHAT_CLI_PATH、ACCEPTANCE_BASE_URL 及 Task 0 对象存储字段。`.env.example`给出完整本地示例：APP_IMAGE=dual-catalog:dev、APP_ENV_FILE=.env、PROJECT_DATA_DIR=./artifacts/local-runtime、API_PORT=8092、ACCEPTANCE_BASE_URL=http://127.0.0.1:8092、DATABASE_URL=postgresql+psycopg://dual_catalog_demo:local-demo-only@127.0.0.1:15432/dual_catalog_demo、ADMIN_TOKEN=local-demo-admin-only、SOURCE_INTERVAL_SECONDS=2、TIMEZONE=Asia/Shanghai，其余发布/存储字段为空且标明正式必填；本地样例不适用于生产。原因: 生产连接既有实例，本地测试拥有可丢弃的数据环境。
- [x] 固定服务器部署、演示库和回滚步骤。
  - 位置: `D:/poke&Tomy/docs/deployment.md` 新增“服务器现状、构建传输、迁移启动、演示验收、备份回滚”章节；读取 `D:/poke&Tomy/spec/feature_20261109_F001_dual-catalog/deployment-state.md`，生产目录固定 `/opt/dual-catalog`。部署前通过交互式SSH执行 `ss -lntp` 和 `docker ps`，确认8092可用并记录既有服务状态，不读取插件业务数据或更改其配置。
  - 从已测试工作区按白名单构建镜像和传输部署文件，包含生产Compose、发布脚本、镜像及版本清单；排除全部.env、SSH材料、未获准图片、开发依赖目录和插件文件。服务器现有 `/opt/dual-catalog/.env` 保留，缺少配置逐项追加并保持0600，秘密仅服务器生成，不输出连接串。记录镜像摘要与主机校验信息，上传流程不能覆盖该.env。
  - 在服务器使用 `/www/server/pgsql/bin/psql` 经 runuser postgres 查询目录后创建独立 dual_catalog_demo 库并归 dual_catalog_app 所有；生产dual_catalog已存在，不重建、不清空。生成权限0600的 `/opt/dual-catalog/.env.demo`，只将数据库名切换dual_catalog_demo，设置 APP_ENV_FILE=.env.demo、PROJECT_DATA_DIR=/opt/dual-catalog/demo、APP_IMAGE为已加载版本标签、API_PORT=8093、ACCEPTANCE_BASE_URL=http://127.0.0.1:8093；生产.env追加APP_ENV_FILE=.env、PROJECT_DATA_DIR=/opt/dual-catalog、APP_IMAGE为同一已验证标签、API_PORT=8092、ACCEPTANCE_BASE_URL=http://127.0.0.1:8092；原DATABASE_URL保留。生产与演示分别使用Compose项目名 dual-catalog、dual-catalog-demo。演示验收期间常驻scheduler停止，worker停止；普通演示运行才启动三服务。演示启动命令为 `docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo up -d api`，API只绑定127.0.0.1:8093；demo验收必须使用.env.demo及8093，不对8092发送写请求。
  - 生产先执行 `docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog run --rm api python -m backend.app.worker init-db`，确认迁移至0002_sync_runtime；再执行同组参数的 `up -d api worker scheduler`。演示使用 `--env-file /opt/dual-catalog/.env.demo -p dual-catalog-demo`，init-db后运行 `seed-demo --confirm-demo`，禁止向生产库导入synthetic数据。所有命令失败均保留非零退出码。
  - 备份使用匹配版本 `/www/server/pgsql/bin/pg_dump -h 127.0.0.1 -U dual_catalog_app -d dual_catalog -Fc -f /opt/dual-catalog/backups/dual_catalog.dump`，备份目录0700、文件0600，不打印密码；部署前保存旧镜像标签。回滚只将本项目APP_IMAGE切回已记录标签并重建本项目三服务，不自动downgrade、不drop数据库、不执行全主机Compose清理。原因: 新服务能独立撤回且不会覆盖现有业务。
- [x] 建立真实数据库与运行链路验收器。
  - 位置: `D:/poke&Tomy/scripts/acceptance.py` 顶部新增 `main()`、`load_environment(path: Path | None)`、`assert_demo_database(url)`、`run_suite(name,context)`；参数固定为 `--env-file`（可选；本机显式文件路径，容器完全省略，直接读取已注入的进程环境；缺失显式文件必须失败，不静默回退）、`--mode demo|production-readonly`、`--suite postgres|api|sync|images|schedule|sources|coverage|all`、`--base-url`（默认ACCEPTANCE_BASE_URL，再默认http://127.0.0.1:8092）。从脚本父目录定位仓库，环境变量优先于可选文件，加载配置不输出秘密；每suite输出pass/fail/blocked、断言数量、原始结果摘要及退出码，JSON证据存 `D:/poke&Tomy/artifacts/acceptance/`，容器中对应 `/app/artifacts/acceptance/`，通过上述bindmount持久化到生产 `/opt/dual-catalog/artifacts/acceptance/` 或demo `/opt/dual-catalog/demo/artifacts/acceptance/`；报告记录运行环境与构建摘要。服务器证据下载仅从上述脱敏目录复制到本机artifacts/acceptance/server，不复制.env；check_release支持 `--evidence-dir` 读取该本机证据目录，服务器不执行微信工具。
  - demo 模式在任何写入前严格验证数据库名为dual_catalog_demo；production-readonly模式只允许 api、sources、coverage，不运行迁移、seed、锁破坏、重启或模拟数据。`all` 在demo只展开postgres/api/sync/images/schedule，生产只展开api/sources/coverage；sources与coverage缺真实数据不得被demo自动套件冒充。失败退出1，外部前提不足退出2并标blocked，零断言、全部跳过不得退出0。
  - postgres suite 使用真实PostgreSQL验证Alembic head、唯一键、NULL排序、有效覆盖查询及upsert；sync suite用固定网页样本和真实PG两条独立连接测试同源advisory锁竞争、连接断开释放、活跃run唯一约束、worker中断恢复、304入口继续详情、重复发布不改内容时间、异常页保留旧值。仅demo允许注入MockTransport和受控故障，报告必须标明“真实数据库、模拟来源”。
  - api suite实际请求健康、组合筛选、整数编号排序、详情形态与进化、未知值、图片状态及无凭证管理401；demo另验游标409（获取游标后执行有效覆盖修改）、管理202只入队、重试和人工覆盖。production-readonly只发GET，409仅在自然修订变化时验证，不制造写入；无自然409记录not-applicable，409必测证据来自demo，不能因该项跳过使零有效断言通过。生产非空图鉴和两来源成功全量run为必需前提，空库返回blocked。images suite在demo用测试生成图和模拟对象存储断言文本独立、重试与占位；真实存储交付由发布检查另验，模拟不能计作真实图片验收。
  - demo的postgres/api/sync/images套件前停止常驻worker/scheduler防止它们抢走测试任务；suite在finally清理仅本次run，恢复演示种子，验收窗口后才恢复常驻服务。schedule suite在demo先以固定北京时间计算两类Cron触发；启动本次专用worker子进程（同一生产work循环、注入固定来源，不访问公网），专用scheduler使用生产每日incremental和周full两个回调各登记30秒内的DateTrigger，分别确认mode、持久化run、worker领取及结束日志。两个短触发依次运行，周full另覆盖queued提升和running followup；finally停本次子进程/移除验收job，不修改真实日/周任务。sources suite经Task 2受限客户端真实访问每来源入口和一个详情并核对字段，不发布、不清库；coverage suite比对最新无限制全量run清单、来源列表与已发布条目，逐项输出缺失、歧义和失败，limited/partial或未跑全量均complete=false。原因: 每一层验证有真实边界与可复核证据。
- [x] 生成客户端发布配置并实现正式发布检查。
  - 位置: `D:/poke&Tomy/scripts/check_release.py` 新增 `main()`、`validate_release(config,evidence)`、`prepare_client(config)`，支持 `--env-file`、`--mode local|production`、`--prepare-client`。读取 Task 2来源政策中的机器可读状态区，明确文本/图片复用证据、署名、实际交付方式；仅approved证据允许对应正式内容，pending项目按blocked报告，不将来源HTTP200当授权。
  - `prepare_client()` 将Task 5小程序白名单文件复制到 `D:/poke&Tomy/artifacts/miniprogram/`，排除tests与任何.env；在产物 `project.config.json` 写真实WECHAT_APP_ID，在产物 `config.js` 生成保留 `getConfig(envVersion)` 导出的trial/release配置并注入PUBLIC_API_BASE_URL，源开发文件不覆盖；`--prepare-client` 仅校验配置和静态前提后生成产物，不要求尚未生成的微信证据，随后无该参数的检查再核对完整发布证据。production校验AppID非touristappid、API/图片域名为实际HTTPS且非localhost或裸IP、TLS有效、公开字段不含秘密、对象存储配置与真实图片可访问，未配置真实图片时不能将图片交付项记为通过。
  - 生产检查读取PostgreSQL coverage与开发者工具证据并校验其构建摘要、AppID、API域名及时间，旧产物截图不可用于新构建；缺域名/AppID/工具或真实证据输出blocked和非零码。当前未提供域名，不修改现有nginx、不占用其站点；部署文档给出项目API反向代理到127.0.0.1:8092的配置字段及证书/微信合法域名设置前提，实际域名齐备后按专属站点落地。原因: 服务器运行后端与微信客户端正式发布分别验收。
- [x] 增加真实微信自动化与使用文档。
  - 位置: `D:/poke&Tomy/scripts/miniprogram-smoke.js` 新增 `main()`，用miniprogram-automator通过环境WECHAT_CLI_PATH启动工具，`--mode demo|production` 分别打开源开发目录或 `D:/poke&Tomy/artifacts/miniprogram/`；要求开发者工具CLI/HTTP服务端口已开启。逐页验证四页实际编译、双tab、组合筛选、详情返回缓存、形态切换与分支跳转、空态/图片失败，保存截图、断言与构建摘要至 `D:/poke&Tomy/artifacts/acceptance/`。
  - 脚本捕获工具启动、编译和断言错误并设置非零process.exitCode，finally关闭本次自动化会话；工具缺失标blocked，禁止返回Node逻辑测试结果代替微信截图。生产模式仅操作读接口，演示模式使用明确synthetic数据，不在真实客户端输入管理凭证。
  - 位置: `D:/poke&Tomy/README.md` 写本地安装、测试、API和worker启动、服务器部署与状态边界；`D:/poke&Tomy/docs/human-verification.md` 记录真机布局、滚动、图片、交互和微信发布后台需核对项，保留未执行状态，不在本计划检查中插入HUMAN标记。`D:/poke&Tomy/CHANGELOG.md` 在本次应用实际实现后追加一条核心功能记录，数据库准备记录保留，不提前声称应用已上线。
- [x] 为发布配置与验收保护核心逻辑编写单元测试。
  - 测试文件: `D:/poke&Tomy/backend/tests/test_release.py`；通过临时目录、假环境和子进程替身验证，不连接生产或真正启动工具。
  - 测试场景: demo拒绝dual_catalog及其他库；production-readonly拒绝写入suite；缺AppID/HTTPS/授权/工具证据标blocked；开发包与正式配置分离、产物无凭证、现有.env不覆盖且0600；依赖锁缺失拒绝构建；suite失败与全部跳过保留非零码；报告不泄露URL密码；构建摘要变化使旧微信证据失效；容器无.env文件仍可通过注入环境加载、显式缺失env文件拒绝、只读模式不制造409、报告目录可写而代码目录不可写。
  - 运行命令: `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_release.py -q`
  - 预期: 全部测试通过，真实数据库/容器/工具仍按独立suite验证。

**检查步骤:**
- [x] 验证部署脚本、容器结构与发布保护。
  - `& '.venv/Scripts/python.exe' -m compileall -q scripts/acceptance.py scripts/check_release.py`
  - `node --check scripts/miniprogram-smoke.js`
  - `& '.venv/Scripts/python.exe' -m pytest backend/tests/test_release.py -q`
  - 预期: 均退出0；脚本测试不访问生产。
- [x] 验证容器构建及本地集成环境。
  - `& '.venv/Scripts/python.exe' scripts/check_toolchain.py --containers`
  - `& '.venv/Scripts/python.exe' -c "from pathlib import Path; p=Path('.env'); p.exists() or p.write_bytes(Path('.env.example').read_bytes()); print('local environment retained or initialized')"`（保留已存在文件，核对本地演示字段）
  - `docker compose -f compose.yaml -p dual-catalog-local config --quiet`
  - `docker compose -f compose.yaml -p dual-catalog-local build`
  - `docker compose -f compose.yaml -p dual-catalog-local up -d postgres`
  - `docker compose -f compose.yaml -p dual-catalog-local run --rm api python -m backend.app.worker init-db`
  - `docker compose -f compose.yaml -p dual-catalog-local run --rm api python -m backend.app.worker seed-demo --confirm-demo`
  - `docker compose -f compose.yaml -p dual-catalog-local up -d api`
  - 预期: 工具链、Compose解析和镜像构建均成功，容器经postgres:5432与宿主经127.0.0.1:15432连接同一演示库；Docker权限/daemon缺失按真实错误报告。
- [x] 验证服务器演示数据库、API和恢复机制。
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo stop worker scheduler'`
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo run --rm api python scripts/acceptance.py --mode demo --suite all --base-url http://127.0.0.1:8093'`
  - 预期: 五个demo suite实际执行并通过，报告明确模拟来源范围；生产及现有插件数据未改。
- [ ] 验证真实客户端与正式发布条件（后续发布阶段，当前前提未具备时记录blocked）。
  - `& '.venv/Scripts/python.exe' scripts/check_release.py --mode production --prepare-client`
  - `node scripts/miniprogram-smoke.js --mode production`
  - `& '.venv/Scripts/python.exe' scripts/check_release.py --mode production`
  - 预期: 条件齐备后产物、真实微信编译截图和发布证据均通过；用户当前未准备真实AppID/HTTPS域名，正式发布部分返回blocked/待执行，不影响后端与本地演示交付；不得标正式发布通过。

---

### Task 7: 双图鉴小程序验收

**前置条件:**
- Task 0—6 完成，依赖锁已生成，当前代码与镜像构建摘要一致；当前仅数据库准备完成的状态不得勾选为本 Task 通过。
- 根目录安装环境使用 `D:/poke&Tomy/.venv/Scripts/python.exe`；本机无法使用容器时，真实 PostgreSQL 集成验收在用户服务器的独立演示库执行，离线测试仍在本机执行。
- 服务器先按 Task 6 生成 `/opt/dual-catalog/.env.demo`，库名 dual_catalog_demo、API_PORT=8093；生产 `/opt/dual-catalog/.env` 原样保留并逐项补齐必填值。SSH 使用交互式凭证，不写入项目。
- 服务器演示迁移命令：`ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo run --rm api python -m backend.app.worker init-db'`。
- 演示种子命令：`ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo run --rm api python -m backend.app.worker seed-demo --confirm-demo'`。
- 演示API启动命令：`ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo up -d api'`。
- 演示验收窗口先停止后台任务：`ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo stop worker scheduler'`；schedule suite自行启动受控进程，验收后按Task6恢复演示常驻服务。
- 真实来源验收前完成访问规则核对；正式客户端验收前提供真实 AppID、有效 HTTPS 域名、微信合法域名配置和可用开发者工具。外部前提缺失时仅记录对应项目 blocked，不影响已完成的离线与演示验收。
- 下列序号为场景分组，实际验证项仍使用复选框；每项保存退出码与脱敏原始输出，不把全部跳过记为成功。Task 6的服务器证据先下载到本机artifacts/acceptance/server，再执行场景6发布校验。

**端到端验证:**

- [x] 场景 1：运行完整测试套件，验证全部模块无回归。
  - `& '.venv/Scripts/python.exe' -m pytest backend/tests -q`
  - `npm test`
  - 预期: 两条命令均收集到测试且全部通过，离线单元测试不访问公网或生产；分别报告两套结果，不累加重试次数。
  - 失败排查: 按测试文件回到 Task 0—6 对应模块；不得删除失败断言或将未执行测试记作通过。
- [x] 场景 2：验证真实数据库结构、隔离、重复发布与并发恢复。
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo run --rm api python scripts/acceptance.py --mode demo --suite postgres --base-url http://127.0.0.1:8093'`
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo run --rm api python scripts/acceptance.py --mode demo --suite sync --base-url http://127.0.0.1:8093'`
  - 预期: PostgreSQL 18 迁移到唯一 head，真连接互斥与断开释放、崩溃恢复、304后详情更新、重复同步和异常页保留旧值均通过；报告注明模拟来源。
  - 失败排查: Task 1 唯一键与仓储、Task 3 锁和恢复、Task 6 数据库指向与脚本保护。
- [x] 场景 3：验证多美卡筛选、宝可梦排序和管理隔离。
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo run --rm api python scripts/acceptance.py --mode demo --suite api --base-url http://127.0.0.1:8093'`
  - 预期: 同号不同代次分开；年份/品牌组合与未知项正确；dex按整数排序且形态不重复；详情与分支关系可读；游标冲突可检测；管理员鉴权、只入队与人工覆盖有效，生产库不写入。
  - 失败排查: Task 1 有效值查询与分页、Task 4 HTTP/管理接口、Task 5 客户端参数。
- [x] 场景 4：验证图片独立失败与真实调度触发链路。
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo run --rm api python scripts/acceptance.py --mode demo --suite images --base-url http://127.0.0.1:8093'`
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env.demo -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog-demo run --rm api python scripts/acceptance.py --mode demo --suite schedule --base-url http://127.0.0.1:8093'`
  - 预期: 图片失败不影响文字，待确认图片保持占位；调度北京时间计算正确，一次性短期触发真实入队并由 worker 完成，保留日志，日/周原任务未被改写。模拟存储通过不算真实图片交付通过。
  - 失败排查: Task 3 图片与时区、Task 6 调度进程/证据采集。
- [ ] 场景 5：验证真实来源与全量覆盖结果。
  - 前提: Task2来源访问规则已核对，Task3代表样本已人工对照并通过；本场景开始先执行下列stop worker命令再运行样本，全程由CLI领取本场景任务；先在生产执行受限样本且核对结果：`ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog run --rm api python -m backend.app.worker sync --source tomica --mode full --limit 5'`；宝可梦使用同组参数 `sync --source pokemon --mode full --limit 5`。样本报告limited/complete=false属预期，只证明样本，不用于覆盖通过。
  - 停止生产worker防止与CLI争抢（scheduler仍只入队，同源锁/唯一索引有效）：`ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog stop worker'`；确认没有未结束同源run后顺序执行以下全量命令，已有queued任务由CLI认领同源同模式任务，running任务必须恢复完成，不删除任务来绕过busy。
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog run --rm api python -m backend.app.worker sync --source tomica --mode full'`
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog run --rm api python -m backend.app.worker sync --source pokemon --mode full'`
  - 完成或失败均恢复生产worker：`ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog up -d worker'`；只有两来源无限制full实际完成且非空才继续coverage，不以只读报告代替导入。

  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog run --rm api python scripts/acceptance.py --mode production-readonly --suite sources --base-url http://127.0.0.1:8092'`
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog run --rm api python scripts/acceptance.py --mode production-readonly --suite coverage --base-url http://127.0.0.1:8092'`
  - 预期: 来源入口/详情真实字段可读；全量清单逐项核对，缺失、失败和歧义均报告。只有无限制全量成功且清单一致才完整通过；小样本、limited、partial或尚未导入不得通过完整性项目。
  - 失败排查: Task 2 来源模板与访问规则、Task 3 全量发现和状态统计、Task 6 部署网络；不可根据菜单链接数判断车型总数。
- [ ] 场景 6：验证容器构建和正式客户端发布条件（容器构建属当前阶段，正式发布检查属后续阶段）。
  - `docker compose -f compose.yaml -p dual-catalog-local build`
  - `& '.venv/Scripts/python.exe' scripts/check_release.py --mode production --prepare-client`
  - `node scripts/miniprogram-smoke.js --mode production`
  - `& '.venv/Scripts/python.exe' scripts/check_release.py --mode production`
  - 预期: 构建成功；真实 AppID/HTTPS 配置生效；开发者工具实际编译四页并通过交互断言，截图与当前构建匹配；图片、来源复用和全量证据就绪。Node 逻辑测试或本地 HTTP 地址不代替微信端验证。用户尚无真实AppID/HTTPS域名，当前只要求构建与演示证据，正式发布命令保持待执行/blocked，后续前提齐备再执行，不阻塞当前阶段。
  - 失败排查: Task 5 页面、Task 6 工具、域名、配置与镜像；本机容器权限告警保持为真实未完成项，不宣称已验证。
- [x] 场景 7：核对服务器上线状态与已有服务边界。
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog ps'`
  - `ssh root@117.72.11.77 'docker ps'`
  - `ssh root@117.72.11.77 'docker compose --project-directory /opt/dual-catalog/app --env-file /opt/dual-catalog/.env -f /opt/dual-catalog/app/compose.production.yaml -p dual-catalog run --rm api python scripts/acceptance.py --mode production-readonly --suite api --base-url http://127.0.0.1:8092'`
  - 预期: 本项目三个进程健康；既有 qq-summary-bot、fish-search、nginx 等容器保持原状；正式健康与只读API通过，未进行管理写入验收。报告分开列数据库准备、后端运行、客户端编译及微信发布状态，更新服务器准备记录。
  - 失败排查: Task 4 readiness、Task 6 资源限制与迁移。真机视觉与微信后台审核继续按 `D:/poke&Tomy/docs/human-verification.md` 记录，不在CLI报告中勾选未执行项目。



## 当前执行记录

2026-11-09 已实现并部署后端、双路worker、scheduler、四个原生页面及浏览器预览。Task0—6当前阶段开发检查完成；正式发布检查实际返回blocked，保持未勾选。全量来源与真实微信完整性分别记录，不因其他项目通过而代勾。实时效果地址 http://117.72.11.77/preview/ 。Task7场景2—4由服务器同一次demo all的47项断言覆盖（真实PostgreSQL，来源/对象存储模拟）；未额外累计。
