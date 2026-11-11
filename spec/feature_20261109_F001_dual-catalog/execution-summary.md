# 实施与验收结果

当前阶段：后端、浏览器效果与小程序源代码已实现；真实微信正式发布未完成。效果地址：http://117.72.11.77/preview/ 。生产运行镜像dual-catalog:0.1.5。

## 功能

多美卡年份/品牌及组合筛选、名称/编号搜索、多版本详情；宝可梦全国编号排序、名称/编号和属性筛选、通常与地区形态、分支进化详情。四个原生页面使用同一API，桌面/手机浏览器预览用于本轮样式查看。两路worker、同源互斥、断点恢复、管理员重试/人工覆盖和北京时间日周调度均实现。

## 真实终端结果

工作目录D:/poke&Tomy。测试不是微信端编译；单元测试离线，浏览器使用真实服务器API。

```text
.venv/Scripts/python.exe -m pytest backend/tests -q
49 passed, 1 warning in 7.21s
exit_code=0

npm test
tests 11
pass 11
fail 0
exit_code=0

PREVIEW_URL=http://117.72.11.77 node scripts/browser-smoke.js
{"status":"pass","assertions":8,"base_url":"http://117.72.11.77","errors":[]}
exit_code=0
```

警告为Starlette TestClient对httpx的弃用提示。compileall、JavaScript语法、Compose配置校验通过；npm audit输出found 0 vulnerabilities。服务器独立演示库运行scripts/acceptance.py --mode demo --suite all：47项通过，真实PostgreSQL18连接/事务/锁/恢复和真实短期调度，来源/对象存储部分使用模拟传输，不等于生产图片交付。

真实生产API只读14项通过；来源入口与详情实时访问8项通过。各项不累加成一个“总测试数”，原始结构化报告下载到artifacts/acceptance/server。

## 未通过的正式发布前提

check_release.py --mode production实际返回blocked：真实AppID、HTTPS接口域名、来源内容复用证据、自有HTTPS图片、微信工具及对应新鲜证据、完整来源证据。miniprogram-smoke.js --mode production为blocked，0项断言，WeChat developer tool CLI not configured。PowerShell工具返回非零，脚本定义阻塞退出码2；不得视为已编译。

本地客户端构建配置生成通过，touristappid与127.0.0.1仅供开发；未冒充体验版、真机或正式发布。浏览器图片可引用源站，慢/失败显示原创插画，正式image_url仍要求确认后的自有HTTPS交付。

## 文件与服务

核心新增位于backend/app、backend/migrations、backend/tests、backend/admin、backend/preview、miniprogram、scripts及docs；新增Dockerfile与Compose配置、Python/Node锁文件。具体文件由spec-plan.md逐Task列出，后续真实来源样本和原创PNG素材已补充；根目录CHANGELOG.md记录本轮变更。

交付服务应保持运行，按照用户明确要求保留生产API、worker、scheduler和预览代理；临时run验收容器自动删除。原有fish-search、qq-summary-bot及nginx保持运行。未提交Git、未改全局镜像源、未覆盖其他数据库。

## 修复回归

旧站错位锚点/重复编号、全角特别版标识、CP932路径、图片慢加载和默认形态顺序均已修复并验证；没有删除既有断言。剩余来源歧义进入问题记录并保留旧数据，避免猜测身份或误标完整。

## 首轮全量实测

2026-11-09 14:37 UTC数据库只读查询：tomica_models=1997、tomica_variants=15515、pokemon=1025，1025条宝可梦均有身高字段。宝可梦full运行succeeded：1026页全部succeeded（列表+1025详情）。多美卡full运行partial：1086页succeeded、1页failed、1页isolated，当前没有pending/processing。

失败为源站链接http://tomica.minibird.jp/t-tomica/special/tto%20begarutasendai.html返回HTTP404；隔离页为number/tbas01.html，其中无编号且无图片身份依据的记录保留待核对，已确认部分仍成功发布。不猜测新地址、不填造身份。该来源将在后续日/周任务继续核对。

实际执行coverage检查返回：

```text
{"mode":"production-readonly","suite":"coverage","status":"blocked","assertions":0,"error":"tomica unrestricted full sync has not succeeded"}
REMOTE_EXIT=2
```

因此Task7场景5保持未完成，绝不把1997款车型、15515版本数当成全站100%完整证明。Task7场景6正式微信发布亦保持未完成，其余5个验收场景有对应已执行证据。Task0—6当前阶段实现及可执行验证完成，后续发布检查单独阻塞。

生产run.stats中的pages/changed是最后一次工作进程恢复后的处理计数；本记录使用SyncItem持久化状态核对整个运行，不把进程局部计数当成全量总数。

歧义项SQL实际计数为4条。完整交付文件清单见file-manifest.md；临时本机API/PostgreSQL容器已停止并保留数据卷，服务器交付服务保持运行。

## 图片专项修复（后续更新）

用户指出图片与源站不符后，已定位并修复403外链、隐藏懒加载、随机版本封面和形态未关联图片。当前部署0.1.8，58个后端测试、12个原生逻辑测试、14个真实网页图片断言通过，7张抽查图片与源站字节一致；具体证据、范围与完整回填结果见image-fix.md。本节取代早期以原创插画后备为交付方式的记录，正式微信发布状态不变。

## 详情与分类隔离修复

现运行0.1.9。修复旧路由等待分类加载后关闭新详情、初始错用多美卡搜索及翻开图鉴锚点误切分类的问题。公网真实浏览器导航32项、图片14项通过，见detail-routing-fix.md及artifacts/acceptance/navigation-public.json，未改业务数据或原图抓取。

## Redis与页码分页更新

当前镜像0.2.2：独立Redis6382缓存原图与公共读取，235张既有图片导入、51张预热；多美卡20条分页、桌面5列4行。65个后端单测、12个原生逻辑测试、真实Redis19项、分页14项、详情32项及图片14项通过，分别报告不重复累计。详见redis-pagination-plan.md。

## 2026-11-10 宝可梦详情扩充

六项详情已上线0.3.5，独立表0003已覆盖现有1025条，1532组同形态普通/异色原图配对。逐项覆盖和图片配对严格审计通过；后端78、小程序JS14、公网详情20项通过，历史导航/分页/原图回归保留。源站两条连接中断已补抓成功，繁体标题造成的6条相性缺项已补齐。详见pokemon-details-plan.md。

2026-11-10新增0.5.1：多美卡每页20/40/60/100可选，默认20；独立cache-warmer主动预热3022条详情与19844张原图，封面优先、磁盘30天、Redis热缓存。详情已全部预热，图片仍后台逐步处理；详见page-size-cache-plan.md及私有cache-warmup.json实时进度。

2026-11-10新品展示0.6.0已发布：右侧月索引、No.114五图与另两组分离、原图Redis交付，新增0004独立表，真实公网32项通过；来源为用户上传，不代表公众号自动采集接通。完整记录见../feature_20261110_F002_tomica-news/execution-summary.md。
