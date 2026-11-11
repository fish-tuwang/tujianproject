# 小小藏家 · Little Atlas

Tomica 多美卡、宝可梦全国图鉴与高达模型图鉴：微信原生页面、可点击浏览器预览、FastAPI查询与管理、PostgreSQL、独立采集和定时队列。

高达模型独立入口：[浏览高达模型](https://117.72.11.77/preview/gunpla.html)。按万代官网完整品牌目录中的17类模型规格、四类售卖属性或39部作品查询，作品按首次公开年代分组；独立配件不收录。列表仅展示封面，详情保留商品全部图库、详细图、人民币/日元价格与发售日期，缺失价格不推算。采集与原图缓存均在后台执行，覆盖和缓存状态以[实际验收](spec/feature_20261111_F003_gunpla-catalog/acceptance.md)为准。

宝可梦地区按Wiki全国编号分段展示，每种只属于一个分类；洗翠和未确认单列，全国1025种均保留。支持地区、属性、名称联合查询和滚动加载。规则与验收见[地区分类修正](spec/feature_20261111_F001_ui-regions/wiki-region-classification-fix.md)。

当前站点采用私有登录，仅服务器命令可创建账户；新登录撤销旧会话，首次登录须修改临时密码。登录、账号管理与证书续签见[鉴权说明](docs/auth.md)。

## 开发

在项目根创建Python虚拟环境，安装requirements.lock；`npm ci`安装客户端验证依赖。复制.env.example为本地.env并调整本地配置。

```powershell
& '.venv/Scripts/python.exe' -m pytest backend/tests -q
npm test
docker compose up -d postgres
& '.venv/Scripts/python.exe' -m backend.app.worker init-db
& '.venv/Scripts/python.exe' -m backend.app.worker seed-demo --confirm-demo
& '.venv/Scripts/python.exe' -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8092
```

本地开发先用`python -m backend.app.auth_cli create-user USERNAME --generate --output-file artifacts/local-login.json`创建账户，再打开`http://127.0.0.1:8092/preview/`登录查看效果；`/admin/`提供任务管理与人工纠错，凭证仅在当前页面内存保留。source fixtures为真实网页样本；demo.json明确为合成演示数据。

## 采集

`python -m backend.app.worker sync --source tomica --mode full --limit 5`验证样本；去掉limit执行完整采集。另一来源为pokemon。日常worker执行work，独立scheduler执行schedule。使用report查看进度，probe核对来源可访问性。采集失败不会清空已发布数据；正式图片转存保留复用确认要求，预览原图通过限定来源缓存交付。

部署见docs/deployment.md；设计与计划见spec/feature_20261109_F001_dual-catalog。当前微信正式发布仍需真实AppID与HTTPS域名，check_release会明确报告未满足项，不将网页演示当成正式小程序。

服务器访问IP、项目发布操作及采集条目变更已写入私有日志，支持自动轮转和按IP/时间/事件查询，使用方式见[日志说明](docs/logging.md)。

当前服务器预览：[查看页面](https://117.72.11.77/preview/)；真实交付与未完成项见spec/feature_20261109_F001_dual-catalog/execution-summary.md。

独立入口：[宝可梦](https://117.72.11.77/preview/?catalog=pokemon&v=0.3.5)、[多美卡](https://117.72.11.77/preview/?catalog=tomica&v=0.3.5)。详情导航与分类隔离修复见spec/feature_20261109_F001_dual-catalog/detail-routing-fix.md。

Redis缓存及20条分页已上线：[多美卡](https://117.72.11.77/preview/?catalog=tomica&v=0.2.2)、[宝可梦](https://117.72.11.77/preview/?catalog=pokemon&v=0.2.2)。缓存部署与验证见docs/deployment.md及spec/feature_20261109_F001_dual-catalog/redis-pagination-plan.md。

宝可梦详情包含种族值、按游戏版本区分的获得方式和招式、招式学习器、属性相性与同形态异色原图对比。可从[六尾详情](https://117.72.11.77/preview/?catalog=pokemon&v=0.3.5#pokemon/37)查看；招式支持按名称、属性或学习器编号搜索。

多美卡页面支持图片铺满卡片、详情原图点击放大及常见车型名称别名搜索，例如Mark x / MARKX / 丰田 Mark-X均能找到对应4条记录。预览：https://117.72.11.77/preview/?catalog=tomica&v=0.4.1 。

每页数量与主动缓存：[多美卡预览](https://117.72.11.77/preview/?catalog=tomica&v=0.5.1)，默认20款，可选40/60/100；后台独立cache-warmer主动准备图鉴详情与原图，原图磁盘保留30天，Redis作为热缓存。实现与实际进度见spec/feature_20261109_F001_dual-catalog/page-size-cache-plan.md。

多美卡新品月刊已上线：[2026年11月](https://117.72.11.77/preview/?catalog=tomica&v=0.6.0#tomica-news/2026-11)，右侧按月索引，用户提供的7张原图按5/1/1分组展示并支持放大。公众号自动抓取尚未接通。实现和验证见spec/feature_20261110_F002_tomica-news。

自动检查频率：多美卡每48小时北京时间03:00，高达每周日北京时间03:30；宝可梦暂不自动采集。任务由服务器持续执行，采集与发布日志沿用现有私有日志。
