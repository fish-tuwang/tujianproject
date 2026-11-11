# 每页数量与主动缓存（2026-11-10）

本轮范围：多美卡网页允许选择每页20/40/60/100款，首次默认20，保留筛选后重置页码、详情路由与桌面五列；主动缓存双图鉴原图与详情，不再要求用户逐条点击。

实施：沿用现有API的注册原图代理、来源白名单、原图字节校验和每来源2秒限速。独立cache-warmer服务先预热全部详情JSON，再按列表封面优先、详情图片随后处理；按来源URL去重并给对应图片ID写入原图缓存。每个来源一个队列，两个来源可同时推进，实际回源仍走API限速。文件缓存30天，Redis图片24小时，详情24小时且缓存键保留修订号，Redis继续256MiB LRU。持久磁盘用于断点续传和Redis淘汰后快速恢复；每轮完成后6小时再次扫描新增/过期图片，失败轮次5分钟后重试。进度写入私有artifacts/acceptance/cache-warmup.json。

验收：默认20、切40/60/100、跨页无重复、筛选保留数量并回第一页、末页余数、宝可梦不出现分页选择；缓存URL去重、跳过有效文件、拒绝HTML、续跑不重复回源、旧图片TTL延长。运行后记录实际缓存进度，不将后台启动等同于全量完成。

微信公众号：样本标题为“2026年11月新製品情報（多美卡TOMICA）”，用户确认正文全为图片；尚缺正文原图，不能据标题生成车型资料。该来源待用户上传原图，当前缓存仅处理数据库已登记且已允许访问的图鉴图片。


## 实际部署与验证

已部署dual-catalog:0.5.1，正式与演示API均healthy，生产独立cache-warmer运行，原有插件未重启。数据库结构仍0003，无业务记录改写。首轮队列19844张注册原图（其中2890个封面），全部3022条详情JSON已HTTP成功预热。全量图片为持续运行任务，不能将队列建立或若干图片成功写成全部完成。

本地后端95 passed, 5 warnings；原生逻辑15 pass / 0 fail。真实公网新增每页数量17项通过；历史详情/分类隔离32项、默认分页14项、多美卡搜索/满幅/放大27项、原图对应14项、宝可梦扩展详情20项均通过。真实6382 Redis缓存验证19项通过，其故障回退用例主动连接未监听端口产生ConnectionError属预期。各套件独立报告，不累计重叠用例数量。

首轮新增缓存测试fixture误用重复source_url触发唯一约束，修为两个不同写法规范化到同一URL后，全套94项通过。大页交互首次超时显示state.loading=true，API本身约40ms，浏览器图片连接排队；翻页取消旧图请求、图片低优先级/接口高优先级后，公网完整17项用时约7.5秒通过。另一次本地多美卡回归启动与服务器API重建重叠，0断言超时；部署healthy后同脚本公网27项全部通过，保留首轮失败证据而不计入通过。

截图：artifacts/acceptance/page-size-public.png；终端与断言记录：page-size-public.json、tomica-display-public.json、navigation-public.json、redis-pagination-browser.json、image-audit/image-verification.json、pokemon-details-public.json。

补充：批量缓存验收脚本误在192MiB API容器内另起Python进程，内核日志证实cgroup OOM导致API重启一次；运行API恢复healthy。检查改在独立限额一次性容器执行，不再共享API内存。期间发现API连接中断会被预热逐条记为图片失败，已改为中止本轮、记录retrying并30秒后从磁盘断点恢复，新增回归证明断线不会把整条队列误记为源图失败。故障前报告单独保留cache-warmup-before-retry-fix.json；新轮次从有效磁盘图片续跑。

最终补充终端：.venv/Scripts/python.exe -m pytest backend/tests -q → 95 passed, 5 warnings in 14.36s，exit=0；node scripts/verify-page-size.cjs（0.5.1公网）→ status:pass / assertions:17 / errors:[]，exit=0。原生逻辑与其他历史回归本轮已通过，0.5.1仅补充预热断线处理、版本标记，不改变其已验证的页面/API逻辑。

独立一次性验收容器（--rm --no-deps）实际完成8项真实批量缓存核验，REMOTE_EXIT=0；确认此前未点击的车型详情已Redis命中、TTL>80000秒、原图响应与磁盘原始字节SHA256一致，以及无浏览器点击时进度从300增至325。报告bulk-cache-verification.json保留status=running，没有把8项验收通过写成19844张图片已完成。最新私有快照时间2026-11-09T17:31:07.499346+00:00：详情3022/3022，图片确认就绪350/19844，失败0，其余后台处理中。最终API约123.8MiB/192MiB、预热90.12MiB/192MiB；两容器restart=0、OOM=false，正式/演示healthy，原插件仍Up 6 days。

最后一次页面验收移除请求调试日志后再次执行node scripts/verify-page-size.cjs：17项通过、errors:[]、exit=0（约7.96秒）；测试断言未弱化。临时验收容器已自动删除，持久预热服务按用户要求保留运行。
