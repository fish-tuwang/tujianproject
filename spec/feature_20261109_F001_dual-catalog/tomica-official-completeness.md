# 多美卡官方商品图库全量补采

2026-11-24。用户要求补齐官网商品详情的全部图片，核实同款包装盒并优先作为卡片封面，保留车身图并预热缓存。

## 已执行的线上盘点

通过京东入口现有反向隧道读取 Mac 真实 API，逐页读取 167 页，共 16,698 条车型；其中 150 条关联官方商品。150 个详情请求全部成功，按条码去重后为 150 个商品、232 张图片：35 个商品的来源为官方商城详情，115 个仍为官方产品列表页；21 个商品有已标记包装盒，129 个包装盒状态为 unverified。此盘点不是补采成功报告，也不代表其余历史车型在当前商城必然有售。

No.132（JAN 4904810950509）线上仅一张列表图；官方商城公开详情可查到多张图片，证实详情采集有缺口。官网商城 Tomica 根分类显示 1,108 件相关商品，包含玩具、场景和周边，不能直接视作应新增的车模数量。公司与京东直接请求商城 HTML 分别出现超时/403，公开检索可以读取该详情；部分已知原图 URL 可以正常读取。不能把请求失败记为无图或成功，也不绕过验证。

## 完成标准

1. 复用 Mac 实际已安装的采集器与存储，发现官网车型分类及全部分页，逐项进入商品详情，不局限于既有关联的 150 个商品。
2. 按商品条码与可信车型/版本关联补齐图库；不同代次、初回和通常版不互换盒图。未能匹配的商品单独记录，不能仅按编号覆盖历史车型。
3. 收集详情大图、懒加载图和完整图库，去重；只有核实为同一商品包装盒的图片才选为封面。保留旧车身图与已有详情，不猜盒图文件名或默认最后一张就是盒图。
4. 可恢复的限速任务记录发现、成功、缺图、失败与待处理数量，逐项缓存并验证图片；不能以任务启动或样本成功宣称全量完成。
5. 核对 Mac 实际部署版本、数据库/图库覆盖与缓存结果，再报告新增及失败清单。

## 本轮采集与缓存证据

- 已读取官网 22 个分类、32 个列表分页：按条码去重 1,111 个商品，各分类逐项数量与页面标示一致。根分类聚合计数存在差异，不据其宣称车型应有数量。
- 列表实际包含完整懒加载图库，5,392 个已记录图片地址全部下载成功，失败 0；并另核对详情首图，记录 1,068 个缩略图与原图映射。42 个首图原图暂不可读，明确 deferred，不把请求失败当作无车或成功。
- 复核 1,111 张初始候选图及 1,953 张其余图库照片，确认清单中 468 个商品有包装图；记录具体图片，不按图库最后一张自动推断。商品含周边、场景、文具和组合销售，仍按实际车辆/明确含车内容区分，未确认的保留核对状态。
- 京东中转已存入 6,185 个校验后独立图片文件，对应 6,452 个来源地址，合计约 449.9 MiB。应用读取必须符合已提交 SHA-256；不能将此数量视为 Mac 数据库已成功导入数量。
- 优先发布可读取的真实原图库；只有官方列表小图可读的单图车型保留该真实小图并标记 thumbnail，原图缺口保留在进度记录，不拼图、不放大伪造。

## 运行与发布状态

Mac 已确认成功更新 9b0b5bd，并实际运行后续全量清单版本。线上抽查 H2 列表封面使用已核实包装图，详情照片保留；仍需核实全量导入。

真实任务随后暴露旧 `/app/artifacts/tomica-official-media` 目录不可写。新增媒体保存到应用可写的 `artifact_dir/tomica-mall-backfill/published`，图片服务同时读取此目录及旧图库；不依赖修改旧目录权限。列表、详情及缓存命中响应统一映射到受原鉴权保护的媒体接口。此修复需在 Mac 自动更新后验证，不能仅凭推送报告成功。

维护接口仅保留覆盖计数与补采进度，已移除本轮临时源码/文件结构诊断。`/api/tomica-maintenance/progress` 记录真实成功、排除、待核对、失败、原图缺口及仅有小图的数量。所有旧官方照片与已核实车型/版本关联保留，补采前存档原证据。

京东只有 18092 HTTP 反向隧道，没有可用的 Mac 文件或 SSH 管理通道。用户先前提供的 UPDATE_OK 已证实更新恢复，后续部署以真实 API 指纹和进度为准；若自动更新再次停滞，需宿主 updates.log 定位，不用云端旧数据库代替。

## 2026-11-24 22:53 线上验收记录

- Mac 实际已完成上一轮全量遍历：1,111 项，865 个官方商品关联入库、4,365 张图库图片、345 个已核实包装封面，失败 0；另有185个排除项和61个待核对项。
- 本轮已逐一核对这61项：39项纯配件排除，22项含车商品或精确车型关联可发布；并纠正生日套装本体实际含车的分类。新增核实91个包装封面。代码/清单推送2d581bd，Mac尚未显示新清单指纹，已请求宿主更新日志定位，不将推送当上线。
- 相关测试实际输出 `64 passed, 1 warning in 7.78s`，退出0。真实H2列表盒图、详情图片、SHA一致性及未登录401验证通过。新增91个盒图的线上抽查仍待Mac部署。
- 42个记录首图的原图缺口保留；不能把官网不可读原图说成已补齐，也不删除旧车型或已有关联版本。已有图片缓存校验完成。

## 2026-11-25 Mac 发布验收

用户提供 revision=6b9498d，连续 FETCH_DONE/UP_TO_DATE。重新认证只读检查后，Mac 清单指纹确认为 aaa8d2c930a85592393c7fa843ede82a5b628ee81eff1ecb36e1dcc7c65bf527。实际官方商品887、图库4513、已核实盒图封面437。完整1111项遍历：created21、supplemented等具体动作以保存进度为准，失败0；仅余JAN4904810089131 Cars Advent Calendar 2026关联待核对，两条历史候选分别是套装内McQueen与Mater的单车，不把整套图库随意附到其中一辆。

实际执行 /tmp/tomica-live-verify.py 及 /tmp/tomica-live-extra-verify.py，退出0；H2封面SHA一致、未登录401，JAN4904810950813/4904810228035/4904810228844新盒图与全部详情照片均HTTP200且字节SHA一致。同步阻碍已解除；468是完整来源清单含非车型商品的盒图数，437才是当前已发布官方商品的盒图数。

## 2026-11-25 未知发售年份补录验收

用户授权“能补就补年份”。从当前未知记录的官方条码候选核对官网发售日，记录700条明确发售年月事实；结合原图鉴已保存的同页、同图片身份年月分组，只补空缺 release_year，不修改已有年份、发售月份、名称、图片及版本关联，保留手工设置，日期冲突跳过。基础车型与明确版本分开处理，不用当前再版日期覆盖历史基础车型，不解析工厂批次码或原型汽车年式为发售年份。

代码0cd411d已由Mac自动加载。实际 /api/tomica-maintenance/years 返回 changed_models=1148、changed_variants=1、conflicts=0、status=completed；页面未知年份总量由16607降为15458。逐一验证999号列车2024、MR2 2023、Cars GRC 2025以及原图鉴迪士尼特注2025：详情年份与按年搜索均正确。未确认记录继续保留未知。

执行 python -m pytest backend/tests/test_tomica_release_years.py backend/tests/test_tomica_mall_backfill.py backend/tests/test_tomica_mall_inventory.py backend/tests/test_tomica_mall_media.py backend/tests/test_tomica_maintenance.py backend/tests/test_api.py backend/tests/test_tomica_editions.py backend/tests/test_tomica_repair.py backend/tests/test_sources.py -q；原始摘要106 passed, 1 warning in 13.17s，退出0。线上 /tmp/tomica-year-live-verify.py 返回LIVE_YEAR_VERIFICATION_OK，退出0。日期来源及原空值备份写入Mac图鉴 artifacts/tomica-mall-backfill/release-years-*.json，聚合日志记录 tomica_release_years_completed。

## 2026-11-25 中国官网包装补图

按用户提供 https://www.tomy.cn/tomica 检查中国官网多美卡与TLV：34个分类/分页列表、558个详情，详情请求失败0，记录2970个图库图片地址。242项可与既有日本官方清单按唯一货号后六位对应，其中70项此前无已核实盒图；逐张检查相关图库，最终目视确认64项同款包装。两项采用官方包装正面图，其余为盒体照片。记录完整中国商品页、图库地址、货号、对应完整JAN、日文商品名及原图SHA，不按相同编号猜测代次或版本；合并多货号及无法确认项不自动关联。

64张原始图片约21.8MB已预缓存京东现有图片目录并逐一校验SHA；Mac通过已有鉴权图片服务读取。只为缺盒图的商品追加包装图片，保留原车身图库、旧盒图及版本关联，来源边界限于中国官网公开上传目录。源码a4c2f3c已在Mac运行完成：实际新增64个包装封面，官方商品仍887项，图库4513增至4577张，已核实包装商品431增至495，写入失败0。标准图库遍历1111项完成，另1个原有Cars套装关联待核对未强行处理。未知年份仍15458，补年结果保留。

执行 python -m pytest backend/tests/test_tomica_cn_packaging.py backend/tests/test_tomica_mall_backfill.py backend/tests/test_tomica_mall_inventory.py backend/tests/test_tomica_mall_media.py backend/tests/test_tomica_maintenance.py backend/tests/test_tomica_release_years.py backend/tests/test_api.py backend/tests/test_tomica_editions.py backend/tests/test_tomica_repair.py backend/tests/test_sources.py -q；终端原始摘要119 passed, 1 warning in 13.32s，退出0。线上 /tmp/tomica-cn-live-verify.py 输出LIVE_CN_VERIFICATION_OK，退出0；银河铁道999与F-35A的列表盒图、详情包装图和原图SHA一致，未登录访问401。

仍缺包装图的历史车型及本次TLV、停车场等无可靠包装照片的条目保留现有图片，不把车身、内饰、活动图或其他版本包装冒充盒图。

## 2026-11-25 中国官网定时新品检查

按用户要求接通中国官网新品增量检查，沿用每48小时、北京时间03:00的固定相位，独立于原图鉴的车型采集，覆盖中国官网多美卡及TLV分类分页。558条已采集记录作为初始基线，不能把既有全站商品算作首次新增。列表全量发现链接，仅对新增、列表变化和首页最新商品读取详情比较，按真实article:published_time上架月份进入原新品月刊；article:modified_time参与变化识别，不把文件上传年月或官网上架时间写入车型首次发售年份。

Mac运行源码10d6cca，已通过POST /api/tomica-maintenance/china/run手动触发，run_id=8826f7d2-05c4-4776-9016-e8b85b8dbacf。实际2026-11-25 20:25:23开始、20:29:40完成；34个列表页、558条商品、9个最新/变化详情复核，新增0、变更0，status=completed、error=null。初次接入官网本月17组商品资料及完整图库，不将这17组记成网站本轮新增。下次2026-11-27T03:00:00+08:00，enabled=true、interval_hours=48，API进程重启保留固定相位并补查错过的周期。

状态入口GET /api/tomica-maintenance/china；手动入口仅允许已登录、同源JSON空对象，不能指定任意抓取地址；重复触发复用当前任务。状态、基线及图片持久化在settings.artifact_dir/tomica-cn-sync，collection日志事件tomica_cn_sync_started / tomica_cn_sync_finished / tomica_cn_sync_failed。网络失败不会推进基线或报告无新增；图片下载验证、落盘并预热现有缓存，来源图不重新编码。

实际执行相关pytest，原始结果158 passed, 1 warning in 15.23s，退出0。服务器验证LIVE_CN_SCHEDULE_AND_MANUAL_CHECK_OK 0 0 2026-11-27T03:00:00+08:00，退出0；17组封面逐一HTTP200且字节SHA一致，原有用户月刊完整保留。官方商品盒图仍495、未知年份仍15458。使用Mac实际已部署JS与真实月刊数据，桌面1280/手机390宽度均通过官网资料标签、完整商品图片数量及图片放大验证；用户上传文章原标签和图片放大保留。No.63详情图库置于12条版本记录之前的布局亦通过两种宽度复核。
