# 两类图鉴普通刷新与详情返回

用户补充：电脑端选择其他年份后直接刷新，也要停留原筛选位置；宝可梦详情关闭、刷新也必须同样保留上下文。本轮扩展0.6.1的前端修复，不改数据库、抓取和图片关联。

## 实际根因

0.6.1只在多美卡列表加载/打开关闭详情时保存位置，普通浏览后刷新未更新当前位置；宝可梦完全没有列表恢复入口。公网Chrome桌面实测：多美卡2025筛选仍在，但scrollY1181→0；宝可梦水属性24条/scrollY2459刷新后变为空筛选12条/scrollY457。证据both-catalog-refresh-before.json。

0.6.2公网测试还暴露出手机端排版竞态：恢复位置后，新品侧栏才加载完成，侧栏高度133→321，列表顶点633.78→822.27，浏览器滚动锚定使2571变为2759。单独延迟真实新品索引请求可确定复现，证据late-news-layout-before.json。0.6.3在恢复已存上下文时等待现有新品索引请求完成，再执行原定位；普通初次加载仍并行执行，不修改内容、样式和来源图片。

## 方案与范围

将现有小型快照函数扩展为两个独立键，沿用旧tomica-list:v1键，宝可梦单独pokemon-list:v1。按来源只读q/brand/year或q/type，两个种类不互相覆盖。pagehide保存最新位置，详情打开时仍保存原列表位置。多美卡恢复页码与每页数量；宝可梦按已呈现条数重新请求当前数据，单次不超过100，超过100按当前游标继续到原进度，恢复后下一批仍从正确编号接续；不缓存旧行或旧游标。

恢复中用户重置/换筛选或换分类会使请求序号失效，停止旧恢复，旧响应不能恢复旧筛选/滚动。显式重置仍清空当前条件，页面内主动切分类沿用原行为；同一标签页重新进入各独立URL分别恢复最后有效状态。只修改app.js、版本和相关回归/部署记录。

## 验收

Chrome桌面与WebKit手机模拟覆盖多美卡独立刷新（从未进入详情）、年份+页码/数量、宝可梦属性与已加载36条、详情刷新返回、继续加载无重复、属性+搜索、显式重置、两种类独立URL恢复及新品侧栏延迟；桌面额外覆盖宝可梦108条跨100分批恢复，以及恢复请求未完成时重置的竞态。运行旧手机35项、分页17、月刊32、原图查看器27等受影响回归。最终前端发布0.6.3，无迁移/导入。

## 实施与实际验证

2026-11-10已完成。app.js沿用原请求序号与路由保护，只扩展快照恢复；index.html及发布镜像最终版本0.6.3。普通分页开始即记录请求页，避免请求进行中刷新恢复旧页；长列表恢复期间重置会使旧恢复失效，避免旧位置再次滚回。多美卡恢复先等新品侧栏排版，避免迟到内容推移位置。

在D:/poke&Tomy真实终端运行以下命令，各项独立计数，不合并为测试用例总数：

| 命令 | 实际最终结果 | 环境 |
| --- | --- | --- |
| node --check backend/preview/app.js | exit 0 | 静态语法检查 |
| node --check scripts/verify-both-catalog-refresh.cjs | exit 0 | 静态语法检查 |
| node scripts/verify-both-catalog-refresh.cjs --local | pass，assertions=29，errors=[]，exit 0 | 0.6.3本地前端覆盖、真实只读API；Chrome桌面+WebKit手机模拟 |
| node scripts/verify-mobile-year-return.cjs --local | pass，assertions=35，exit 0 | 0.6.3本地前端覆盖、真实只读API；Chrome触屏+WebKit触屏+Chrome桌面 |
| node scripts/verify-pokemon-details.cjs --local | pass，assertions=20，exit 0 | 0.6.2本地前端覆盖、真实只读API；补充侧栏修复前执行 |
| node scripts/verify-both-catalog-refresh.cjs | pass，assertions=29，errors=[]，exit 0 | 0.6.3部署后真实公网；Chrome桌面+WebKit手机模拟 |
| node scripts/verify-navigation.cjs | pass，assertions=32，errors=[]，exit 0 | 0.6.3部署后真实公网 |
| node scripts/verify-page-size.cjs | pass，assertions=17，errors=[]，exit 0 | 0.6.2部署后真实公网；补充侧栏修复前执行 |
| node scripts/verify-tomica-news.cjs | pass，assertions=32，errors=[]，exit 0 | 0.6.3部署后真实公网、7张原图字节核对 |
| node scripts/verify-tomica-display.cjs | pass，assertions=27，errors=[]，exit 0 | 0.6.2部署后真实公网；补充侧栏修复前执行 |

0.6.2首次公网新回归在15项后手机第二页位置等待10000ms超时，exit 1；一次重跑27项通过后仍继续追查，补充逐次滚动日志与独立受控延迟实验，确认上述侧栏排版竞态，没有把失败归为环境。0.6.3保留原精确位置/条目断言，新增电脑及手机各一项“新品侧栏延迟完成不能推移恢复列表”，共29项。相关日志记录在both-catalog-refresh-local-terminal.log与both-catalog-refresh-public-terminal.log。

历史修复影响：导航异步竞态与详情深链、搜索隔离、手机年份返回、每页数量、Mark X搜索、图片查看器、新品月刊及宝可梦扩展详情均按上表验证。后端与原生小程序本轮无代码变更，未重跑其测试，不引用此前数量作为本次证据。手机验证为触屏/内核模拟，没有真实iPhone连接。

## 部署结果与边界

python3 /opt/dual-catalog/deploy_catalog_refresh.py最终实际输出DEPLOYED dual-catalog:0.6.3，REMOTE_EXIT=0；生产8092与演示8093返回ready/0004_tomica_news。部署报告both-catalog-refresh-deploy.json记录plugins_unchanged=true、database_migration=false、data_import=false，服务器app.js/index.html字节摘要与打包源码一致。仅本项目容器更新；fish-search、qq-summary-bot、原nginx保持原容器。两套API与cache-warmer均为0.6.3、重启计数0、OOM=false；预热仍后台进行，不表示19844张原图已全量缓存。

浏览上下文使用sessionStorage，同一标签页刷新与详情返回有效，关闭标签页后不承诺保留。用户主动重置或页面内切换类别沿用现有交互语义。恢复请求真实数据，不保存旧图片、旧条目或旧游标；来源数据更新导致结果变化时以当前列表为准。真实手机尚未验证，使用Chrome触屏和WebKit手机模拟；首次公网失败已定位并有新增回归。
