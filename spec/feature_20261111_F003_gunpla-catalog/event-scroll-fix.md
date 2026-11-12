# 活动预览打开后页面跳顶

2026-11-12。仅修复高达模型左侧活动预览的弹窗定位；保留活动内容、原图查看、筛选、分页以及已有商品详情关闭逻辑。QQ接入继续保持用户要求的暂停状态。

## 根因与基线

活动弹窗 `.gunpla-event-dialog` 设置 `position:relative`，覆盖原生模态dialog的固定定位。进入浏览器顶层后实际计算为absolute，自动聚焦弹窗时把窗口滚回页面上方。线上Chrome复现滚动824→68px，手机WebKit为7566→75px；关闭、Escape及随后刷新也未保留原位置。账号验收使用独立临时账号，真实账号未用于自动登录。

## 精确修复

该活动弹窗的定位改为fixed，依靠原生dialog视口居中及焦点恢复。仅修改原有这一条属性，不添加滚动补偿或修改共享样式。CSS资源版本及应用镜像更新为0.11.5，无数据库迁移或数据导入。

## 验证

`node scripts/verify-gunpla-event.cjs`在桌面Chrome与手机WebKit上，选择高达基地限定、每页40及第二页后滚到活动，核对打开、X关闭、Escape、活动原图查看、关闭图片、刷新后的位置、侧栏滚动以及筛选/记录/URL。候选模式明确标记为拦截本地CSS配合真实HTTPS API；最终部署模式不拦截线上资源。保留并运行已有`verify-gunpla.cjs`的64项商品/图片/详情/鉴权回归。

候选样式两端22项通过；正式发布0.11.5，operation_id为a782f200b12a4aa4854e06f54e8b3fde。实际发布镜像在禁网环境执行完整后端测试：289 passed, 13 warnings in 63.07s，退出0；警告为已有依赖弃用提示。两套数据库均ready/0005_gunpla，无迁移或导入。

最终公网运行`node scripts/verify-gunpla-event.cjs`，未拦截或替换线上资源，输出`GUNPLA_EVENT_SCROLL: 22 passed; desktop Chrome and mobile WebKit`，退出0。桌面824→824→824px、手机7566→7566→7566px（打开前/打开后/关闭后）。活动原图查看、Escape、刷新、侧栏位置和限定/40条/第二页等状态均保持。另运行`node scripts/verify-gunpla.cjs`，原有64项全部通过，退出0，JavaScript错误及429均为空；原图与封面对应、图库完整、商品详情滚动及X/遮罩关闭等历史修复保留。

最终镜像为sha256:e2d4f2adfed02488b2bf7389f1a962cf883378e21ee113247850ef05192d6d4b，服务器实际CSS/HTML与验收源码字节摘要相同。六个应用服务运行中、无OOM和自动重启，私有门禁已打开，独立Redis及证书续期/高达采集/日志轮转timer为active。

临时验收账号已停用并按精确用户名删除，旧验收会话访问auth/me和gunpla均实测401；两个真实账号的非会话指纹与验收前相同。临时凭证与会话已清理，用户原有私有凭证保留。暂停中的两个QQ组件，其容器ID和停止状态与发布前一致。服务器回执`data/artifacts/acceptance/gunpla-event-deployment.json`输出`GUNPLA_EVENT_DEPLOYMENT_VERIFIED: activity=22; history=64; accounts=2; QQ remains paused`，退出0。
