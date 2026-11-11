# 公众号新品自动归档执行计划

设计：spec-design.md。以真实来源可用为接通验收条件，不将配置入口当成功采集。

### Task 1: 每月单一索引标题

- [x] 复用现有月份归并，将索引展示为年月新品情报，月份各占一行，手机可读。
- [x] 验证同月两篇文章只有一个索引、新旧月份独立排序。

检查：`.venv/Scripts/python.exe -m pytest backend/tests/test_tomica_news.py -q`，预期同月归并和原图归属通过；`node scripts/verify-tomica-news.cjs --local`，预期完整历史浏览检查通过。

### Task 2: 验证公众号入口

- [x] 明确账号归属：用户确认是第三方公众号，只需读取最新公开消息。
- [ ] 通过有效的来源联网批准流程解除既有工具限制，再使用正常浏览器访问真实来源。
- [ ] 核对文章正文、作者身份、最新文章列表入口及图片链接。验证页/权限拒绝视为未接通，不绕过。

检查：保存实际来源访问结果、正文/列表是否存在及账号核对证据，预期能正常取得真实内容；不能取得则如实记录具体阻碍，不发布虚假的成功状态。

### Task 3: 自动采集、归档与日志

- [ ] 依据Task 2已证实的入口实施采集，稳定身份去重、按文章主题月份归档、原图按实际归属缓存。
- [ ] 接入周期运行与既有采集日志；失败不改旧图，成功提交后记录新增/更新及归档月。

检查：真实文章首次采集成功、重复采集不重复索引/文章、下一月份独立标题、失败保留数据；运行相关事务与图片回归，禁止把样本或用户上传当成真实自动采集。

### Task 4: 端到端验收与发布

- [ ] 完整后端与新品回归，公网年份/详情返回历史回归。
- [ ] 用统一审计发布脚本部署，核对原插件、日志、原图、按月索引和真实定时入口。

检查：`.venv/Scripts/python.exe -m pytest -q`、`node scripts/verify-tomica-news.cjs`、`node scripts/verify-both-catalog-refresh.cjs`；预期均通过。公众号成功接通必须另有真实来源/实际采集证据，前置未解决时分开报告已完成的月份展示与未完成的自动采集。

## 当前进度

2026-11-10：Task 1已部署0.7.1。Task 2等待异步问题的域名访问授权与账号归属答复；本轮没有重试被拒绝的公众号域名，也没有实现/启用公众号采集进程。Task 3和自动采集端到端验收未完成，不能把本次展示更新当成接通。

后续澄清：用户确认《多美卡TOMY新品情報》属于他人，目标为读取最新公开消息。账号归属前置已完成，既有origin egress拒绝仍未解除；未发起新的公众号访问，也未更换客户端、SSH服务器或代理重试。需要有效的来源访问批准，或由账号方提供且独立获准接入的订阅数据；不能用转发服务绕过原有拒绝。本次只更新接入状态记录，未改运行代码或部署。

实际执行：`.venv/Scripts/python.exe -m pytest backend/tests/test_tomica_news.py -q`输出15 passed, 1 warning in 1.10s，exit 0。`node scripts/verify-tomica-news.cjs --local`与部署后同命令无--local，均status=pass/assertions=33/errors=[]，TEST_EXIT=0；原有7张图字节、No.114五图、跳转、月份标题、返回、手机宽度与异步保护均通过。`node scripts/verify-both-catalog-refresh.cjs`公网status=pass/assertions=29/errors=[]，TEST_EXIT=0。各组不相加；没有将测试的十月素材写入生产。

部署使用统一deploy_release.py，实际image=dual-catalog:0.7.1、status=pass、plugins_unchanged=true、REMOTE_EXIT=0，无迁移或导入，两套API健康0004_tomica_news；API/演示API/预热进程restart=0、OOM=false。操作记录明确写“no WeChat collection enabled”。证据news-month-title-deployment.json、news-month-title-public-terminal.log、month-title-refresh-regression-terminal.log及新版桌面截图。
