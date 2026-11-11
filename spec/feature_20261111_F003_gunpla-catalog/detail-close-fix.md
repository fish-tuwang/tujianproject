# 高达详情关闭修复

用户反馈：长图库滚动后关闭按钮应保持可见，点击详情外部应关闭详情。

根因：高达详情直接滚动整个 dialog，绝对定位的关闭按钮随内容滚出；高达独立页面未绑定已有两类图鉴使用的遮罩点击关闭事件。

修复范围：仅高达页面 CSS 与事件处理。外层 dialog 裁切，内层 detail-root 独立滚动；X 相对外层定位，覆盖手机端共享的 fixed 规则。遮罩点击复用 closeDetail，保留请求取消、图片查看器关闭、URL 清理、列表筛选分页及双帧滚动恢复。共享 CSS、宝可梦和多美卡页面不改。

历史场景：完整商品图库、缩略图切换、放大与 Escape 分层、刷新详情后关闭恢复原列表位置。保留原有 verify-gunpla 断言并补充电脑 Chrome / 手机 WebKit 长图库滚动、内部点击、X 关闭、重开归顶、遮罩关闭与精确位置恢复实测。

发布：0.11.3，无数据库迁移、数据导入或采集计划变更。原账号保持不变，验收使用临时账号。

旧版实测：桌面详情实际滚动 1936px 后，X 从 y=69.5px 移到 -1866.5px；手机原按钮位置不随滚动改变，但两端点击遮罩均未关闭。独立旧版复现记录为 artifacts/acceptance/gunpla-close-baseline.json。

发布前候选页面：仅本地拦截候选 JS/CSS，仍使用真实线上 HTTPS API 和图片，两端 58 项通过。该结果不代替最终线上验收。

新镜像 sha256:84e9c9c578750da370a6652caa7e1417015b64f1257061894de3cf51c7b95141，实际发布流程在禁网镜像内执行 python -m pytest -q -p no:cacheprovider：247 passed, 13 warnings in 65.00s，退出0；警告来自依赖弃用提示。两套服务均 ready / 0005_gunpla，原三个插件容器 ID 一致。生产五个应用服务无 OOM/重启，演示接口健康；独立证书续期和高达采集 timer 均 active，公网防爬配置 SHA256 与发布前相同。


最终公网实测：运行 node scripts/verify-gunpla.cjs，未拦截或替换任何线上资源，电脑 Chrome 与手机 WebKit 共 58 项通过，退出0；包含原有46项与新增12项，JavaScript errors=[]、rateLimited=[]。长图库验证逐张滚动并等待真实图片解码，滚至实际底部后检查 X 的角落位置及点击关闭；遮罩关闭和刷新返回均保持原查询、记录、页码、每页数量及不超过3px的列表滚动差。截图：artifacts/acceptance/gunpla-detail-scrolled-desktop.png、gunpla-detail-scrolled-mobile.png。认证独立回归 node scripts/verify-private-auth.cjs 共34项通过，退出0。

收尾：临时验收账号按精确用户名停用并删除，原会话实际请求返回401；两个真实账号非会话指纹与验收前相同。服务器临时明文凭证及本机验收凭证/会话删除，保留用户原私有凭证文件。修复代码、回归脚本及本记录同步 GitHub main。
