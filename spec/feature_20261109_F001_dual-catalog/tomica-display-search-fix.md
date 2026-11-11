# 多美卡图片、对齐和名称搜索修正（2026-11-10）

范围：卡片图片填满边框、详情主图和版本图点击放大、关闭按钮和品牌图标居中、车型名称搜索。沿用用户此前一次完成并部署的授权，不追加确认步骤。

复现：公网 q=Mark x / MARK 返回0；q=マーク 返回9，内有064、060个人出租车和SP-286覆面巡逻车等Mark X记录；q=丰田返回0。repository.list_tomica只做原名/显示名/品牌/编号的字面casefold子串匹配，没有日英别名及全半角、空格归一。

视觉根因：卡片img限制85%尺寸，外圈仍显示底色和装饰；close-detail默认padding为1px 6px，文字×依赖字形基线，品牌◈同样依赖字体基线。

修改：新增小型名称别名与归一化搜索模块，保留数据库原名；Tomica列表缓存视图更新，避免旧的空搜索结果；preview的Tomica卡片使用cover全幅，详情新增独立大图查看器；关闭和品牌图标使用SVG；原生Tomica缩略图aspectFill、详情调用wx.previewImage。其余分类、分页、原图引用及源站数据不修改。

验证：真实Mark X名称回归、全半角/空格/连字符、品牌组合、Mark II隔离；卡片边缘、两图标几何居中、主图/版本图放大和关闭后仍在详情、手机端；回归原有导航32、分页14、原图14和宝可梦详情20项。微信原生仅运行JS测试，编译仍受既有AppID/HTTPS准备状态限制。

别名核对：[丰田Mark X日文车型资料](https://toyota.jp/ucar/catalog/brand-TOYOTA/car-MARK_X/)、[丰田Mark X英文资料](https://global.toyota/en/detail/308555)。补充别名仅用于查询，不能当作来源站原始名称或替换已有人工显示名。

## 实施及验收

已部署dual-catalog:0.4.1，未变更数据库结构或原始车型名称。公网Mark x现返回4条：060个人出租车、064、SP-286覆面巡逻车、072（原名含全角空格“マーク　X”）。常见品牌/车型别名仅补充查询，不是全车型的自动翻译；未收录的别名仍可用原始名称查找并按需补充。

终端结果（D:/poke&Tomy）：`.venv/Scripts/python.exe -m pytest backend/tests -q` → `90 passed, 5 warnings in 14.89s`，退出0；`npm test` → tests15/pass15/fail0，退出0。小程序真实编译未执行。

`node scripts/verify-tomica-display.cjs` → status pass、deployed public frontend、assertions27、errors[]，退出0；覆盖7种Mark X写法、品牌组合、原名空格、图片贴边、SVG中心、完整原图适配、200%缩放、主图/版本图、Escape和手机端。导航32、分页14、原图14、宝可梦详情20、基础浏览8项均通过，各退出0；生产容器真实Redis19项通过，退出0。各组有重叠，不累加计数。

首次本地大图检查在5项后因测试把相对URL与绝对URL直接比较而中断；已改为比较解析后的同一绝对原图地址并重跑通过，原始记录保留tomica-display-local-first-run.json。人工复查发现Grid自动最小尺寸使大图首次适配时溢出，改为明确尺寸的block容器并增加整图必须位于视口内的断言，通过后部署。

截图：artifacts/acceptance/tomica-filled-cards.png、tomica-mark-x-search.png、tomica-image-viewer.png、tomica-image-viewer-mobile.png；最终报告tomica-display-public.json。因增加独立图片dialog，原有浏览器回归定位由泛化dialog改为明确的#detail-dialog，保留原断言含义。

运行核对：生产与演示API healthy，独立Redis active；原有fish-search、qq-summary-bot、nginx仍Up6days。

搜索回归补充：新增别名时只保留归一名称会使日文部分词（如トヨ、シビ）漏查；新增用例先复现0!=6（退出1），随后同时保留原文归一值和别名归一值，完整后端90项通过，退出0。缓存视图升级list-v3，使此前缓存的部分词空结果失效。

最终0.4.1公网验证：tomica-display-public.json为status pass、assertions27、errors[]，退出0；包含原文部分词回归。导航32、分页14、原图14、宝可梦详情20及真实Redis19在0.4.1再次通过，退出0。0.4.0阶段基础浏览8项通过，前端代码一致。
