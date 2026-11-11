# 多美卡详情移除资料来源入口

2026-11-11，目标0.9.2。用户要求去掉每款车可点击的来源功能。

仅修改车型详情展示：浏览器不渲染多美卡“查看资料来源”链接，小程序多美卡详情不显示来源URL；更新时间继续展示。宝可梦详情和新品月刊来源入口保留，后台source_url继续用于采集和图片缓存，不删除数据。

验证范围：真实车型详情中没有来源链接、更新时间存在、宝可梦来源入口仍可用；既有图片放大/名称搜索/详情关闭和刷新位置回归。无后端逻辑变更，不新增静态样式的镜像单测。

## 实际结果

- `node --check backend/preview/app.js`退出0；发布前`node scripts/verify-tomica-display.cjs --local`为pass、17项、退出0，使用本地前端与只读真实API。
- 发布`dual-catalog:0.9.2`成功，operation_id=`b8ebaec129b1476192b40bbbc0a59689`；正式8092和演示8093均ready、revision=0004_tomica_news，原插件不变，无迁移/导入。回执`artifacts/acceptance/tomica-source-removal-deployment.json`。
- 终端直接运行Playwright公网检查，桌面Chrome和手机WebKit各打开两款真实Mark X：没有来源链接、更新时间存在；宝可梦来源链接仍存在、无JS错误。`tomica-source-removal-public.json`为pass、8项，退出0。未覆盖前端资源；手机是WebKit模拟，不是微信真机。
- `node scripts/verify-tomica-display.cjs`公网27项pass，退出0；`node scripts/verify-both-catalog-refresh.cjs`公网29项pass，退出0。证据副本`tomica-source-removal-display.json`、`tomica-source-removal-refresh.json`。
- API与cache-warmer均0.9.2、running、restarts=0、OOM=false，Redis服务active。小程序模板确认已去掉来源URL；后台与数据库未改，不重复运行无关的完整后端测试。

交付：http://117.72.11.77/preview/?catalog=tomica&v=0.9.2 。历史修复影响：原图放大、搜索Mark X、五列分页、关闭按钮居中及双图鉴详情返回/刷新位置均通过对应回归。复盘：按用户要求移除车型详情的来源入口，保留更新时间与后台采集依据，变更范围仅展示层；本轮无相关遗留。
