# 手机年份筛选详情返回修复

本轮范围：按用户录屏修复多美卡选择年份后进入详情、关闭回到原筛选列表和位置；保留页码、每页数量及当前搜索/品牌组合。沿用用户连续修复和部署授权，不改采集、数据库或图片身份。

## 证据与边界

用户提供12.65秒iPhone录屏，2026年列表点入No.057化石運搬車，关闭后出现全部年份与1970年车型，滚动回首页。已用ffprobe核对视频并提取逐秒及关闭附近画面到artifacts/year-return-video。
Chrome手机触摸和WebKit手机模拟普通开关详情均保留年份，尚未从自动化中观察到录屏中浏览器的具体重载触发。WebKit真实加载公网0.6.0后进行“选2026→详情→刷新详情→关闭”，稳定出现query从{year:2026}变{}、滚动1293变0，证据mobile-year-return-before.json。此证据只证明重载路径会丢失，不冒充精确复现了录屏中的原生事件。

app.js中state.query仅内存保存，selectKind初始化无条件清空筛选；详情关闭不记录/恢复原列表滚动；route以!state.items.length判断初始化，列表加载/空结果也会被当成新入口。原有路由序号保护必须保留。

## 精准计划

1. app.js增加仅当前标签页、仅多美卡的轻量列表快照，保存query/page/pageSize/scrollY，不保存整份数据或图片。有效字段/页码校验、sessionStorage受限时正常降级；显式重置和切分类仍沿用当前行为。
2. 初次进入多美卡时从快照恢复并请求对应页，筛选选项返回后再恢复选中值。route用尚未发起初始加载的sequence===0判断初始化，避免暂时空列表导致重置。
3. 卡片点击前记下位置；复用同一详情显示/关闭函数处理车辆、宝可梦和月刊，关闭/遮罩/Escape/浏览器返回恢复列表位置，保留已有routeSequence/detailSequence失效保护。普通触摸不依赖触摸后按钮获得焦点。
4. 新增scripts/verify-mobile-year-return.cjs，Chrome触摸与WebKit手机引擎分别测试2026第6台、详情滚动、底层滚动偏移、刷新详情/列表、2025第2页、40款、品牌/搜索组合与重置；回归旧导航32、分页17、新品32和原图查看器27场景。实测引擎不等于iPhone实机。
5. 仅发布静态前端和版本0.6.1到本项目生产/演示，停自身预热→更新→健康→恢复；无迁移，无重写图鉴数据，原插件保持运行。

## 工具链

复用现有Playwright，通过本地CLI安装WebKit27.2浏览器运行时用于本次iPhone内核验证，未更新项目依赖/锁文件。首次npx受目录名&导致Windows命令封装失败，改用node node_modules/playwright/cli.js install webkit后完成；不归因为应用失败。


## 完成与实际验证

已部署dual-catalog:0.6.1，正式与演示均ready/0004_tomica_news，线上app.js和index.html字节SHA256与本地源文件一致。无数据库迁移、无数据导入，原插件容器ID保留，暂停的本项目图片预热已恢复。

真实公网执行node scripts/verify-mobile-year-return.cjs，status=pass / assertions=35 / errors=[]，exit_code=0；Chrome手机触摸、WebKit27.2手机模拟、Chrome桌面分别11项，加1项暂空列表导航竞态及1项错误检查。包括选择2026第6台、详情内部滚动、底层滚动移到0、刷新详情/列表、2025第2页、40款与搜索、显式重置、返回键、Escape。

本轮旧导航verify-navigation.cjs --local为32项通过；公网verify-page-size.cjs为17项、verify-tomica-display.cjs为27项、verify-tomica-news.cjs为32项均通过，exit_code=0。不同套件不累加重叠断言。后端业务和原生小程序本轮未改，未重复运行其完整套件；不把上轮110/15记作本轮重跑。

验收脚本首次复用上一次点击前的滚动基线，自动化重开卡片实际滚动后出现1290/1538差异；改为每次实际点击前重新定位目标并记录基线。另一次过滤对象键插入顺序不同导致JSON字符串比较失败，改为键排序后比较完整query/page/pageSize/IDs。断言内容未丢弃，最终35项通过，首次失败报告保留mobile-year-return-local-first-baseline.json。

证据：artifacts/acceptance/mobile-year-return-before.json（旧版重载路径损失）；mobile-year-return-local.json/public.json、year-return-webkit-touch-public.png、mobile-year-return-deploy.json。录屏和提取帧仅本地私有artifacts，不发布到服务器。未取得用户实机运行日志，浏览器原生重载触发仍属于未直接观测的部分，不把模拟测试称为iPhone实机验收。

列表快照限当前标签页，只保存查询/页码/数量/位置，不保存整页数据和图片；sessionStorage受限时普通页面浏览与本次会话详情关闭继续可用，跨重载恢复依赖存储可用。关闭标签页后不承诺跨新标签恢复。用户可用新版链接选择2026，进入任意车并关闭核对；进一步核对第二页和详情刷新后返回。

交付：http://117.72.11.77/preview/?catalog=tomica&v=0.6.1
