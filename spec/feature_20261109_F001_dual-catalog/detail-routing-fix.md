# 详情回退与分类搜索隔离修复

用户报告：点击宝可梦/车型后返回主页；要求打开对应详情，且两类图鉴分别显示自身搜索筛选。按既有连续执行授权完成修复与部署。

## 根因与证据

- backend/preview/app.js的route在await selectKind前捕获id。分类列表已渲染但横幅/筛选请求未结束时，用户打开详情会启动新route；旧route完成后仍按无id的旧地址关闭弹窗。实际延迟pokemon/25复现：detail open true→false，而URL仍为#pokemon/1。证据artifacts/acceptance/detail-race-before.json。
- 启动固定先selectKind(tomica)，之后才按URL选分类，宝可梦初次打开会先显示并请求车型资料。
- 横幅“翻开图鉴”使用#catalog，被路由误判为默认tomica，宝可梦会跳回多美卡。
- 未对过期详情响应做身份校验；旧CSS/JS也无版本化请求。

## 修复范围

仅调整backend/preview/app.js、index.html、style.css及回归验证、发布版本和简短CHANGELOG。route与详情请求分别使用序号，异步返回时校验当前导航身份；初始分类从有效hash或catalog参数读取，入口分为catalog=tomica与catalog=pokemon；品牌/年份和属性按分类隐藏，待执行搜索计时器在切分类时清理。横幅只在当前分类滚动。原图、抓取、数据库与原有插件保持既有实现。

验证：受控延迟横幅/筛选，在请求完成前点击真实卡片，待旧请求完成后详情仍打开且名称/地址一致；两类直接进入/刷新详情、返回、快速切换、各自搜索及筛选互不串用；手机/桌面、图片及进化既有用例回归。修复前证据不把未复现的部分标为已复现。

## 实施记录

已部署镜像dual-catalog:0.1.9；仅静态预览与发布版本变动，未执行业务数据回填、数据库迁移或既有插件变更。首页HTML引用版本化CSS/JS，公网app.js、style.css与index.html逐字节对比均与本机修正版一致（HTTP200）。

修复候选在真实浏览器配合只读公网API执行verify-navigation --local：32项通过；它与实际公网部署验收分开记录。首次公网验收因验证器健康探针await拼写错误，0项断言后失败；已修正验证器，保留navigation-public-attempt1.json，未把它记作应用失败或成功。

验证文件scripts/verify-navigation.cjs包含延迟分类请求、完成后详情保持、直接入口/刷新、跨分类搜索控件隐藏、过期详情响应不覆盖当前条目等针对性回归。已有图片专项node scripts/verify-images.cjs也在0.1.9实际公网通过14项，浏览器错误0。

## 最终公网验收

实际命令：node scripts/verify-navigation.cjs

```text
{"status":"pass","mode":"deployed public frontend","assertions":32,"errors":[]}
exit_code=0
```

实际命令：node scripts/verify-images.cjs

```text
{"status":"pass","assertions":14,"errors":[],"base_url":"http://117.72.11.77"}
exit_code=0
```

32项与候选32项不重复累计。公开入口：/preview/?catalog=pokemon&v=0.1.9与/preview/?catalog=tomica&v=0.1.9。导航截图navigation-pokemon-detail/search.png、navigation-tomica-detail/search.png来自本次公网验收。浏览器自动化进程已正常退出；交付服务按用户要求保留运行。

复盘：之前仅验证“详情瞬间打开”，遗漏后台分类请求结束时关闭详情的问题；本次加入延迟请求完成后检查及过期详情响应检查。原图对应、形态、年份/品牌等既有数据处理未改，图片14项回归通过。
