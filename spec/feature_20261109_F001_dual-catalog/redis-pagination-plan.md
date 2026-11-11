# Redis缓存与多美卡分页

用户要求：服务器增加Redis，缓存加载数据，改善图片速度；多美卡每页20条，电脑端5列4行。沿用已有连续实现与部署授权。

## 设计与实施

1. 独立Redis实例127.0.0.1:6382，随机密码，256MiB缓存上限、LRU淘汰、RDB快照；不修改现有6379或其他插件。生产与演示分Redis DB，连接配置仅服务器0600环境文件保存。
2. 缓存原图字节、图鉴列表/查询、详情和筛选。图鉴缓存键包含数据修订号，日常同步或人工纠错后自然失效；图片按不可变图片ID缓存24小时。Redis失败短超时降级数据库/磁盘。
3. 图片Redis命中与磁盘命中不执行DNS、不等待源站限速锁；冷图回源在单独受限线程池执行，保持每源2秒间隔，不阻塞普通列表API。保留原图字节、来源与已有磁盘后备，不改图片权益状态。
4. TomicaQuery新增可选page，保留旧cursor API兼容原生客户端。网页使用page+limit20，返回总数/总页数；切筛选回第一页，上一页/下一页/页码跳转，不追加叠加。电脑宽度>=1024五列，移动端保持可读响应式。
5. 验证真实Redis读写与过期/失效、缓存故障降级、图片字节不变、分页边界及筛选后重置；公网测缓存前后延迟，32项详情/隔离与14项图片回归继续执行相关场景。部署后预热现有磁盘图片及首页/相邻页。

## 范围

缓存模块、图鉴仓储/API、图片快路径、配置与依赖、分页UI/样式、独立Redis准备脚本和相关测试/运行记录。数据库业务表、抓取身份、原有Redis与其他插件不变。


## 实际部署与已完成检查

本项目Redis8.0.5实例已建立，原有6379进程PID888未改变。独立服务active、6382仅回环，认证PING=PONG，生产DB0/演示DB1，内存256MiB上限。

65个后端单元测试通过（1条既有Starlette TestClient弃用提示），12个原生逻辑测试通过。新增真实Redis验证19项通过：字节读写、TTL真实过期、列表/详情/筛选/图片命中、内容一致、分页不重叠及真实连接失败回退。故障探针主动连接未监听端口，ConnectionError日志属于预期验证，不是6382实例故障。

预热已导入235张有效磁盘图片，前两页/宝可梦首页的51张图片全部HTTP200，无预热错误。服务内热请求：车型列表约4.2ms、原图约1.8ms；公网同机器测试，车型列表由约2962—2993ms变为热缓存40.7—45.1ms（首个样本99.7ms）。公网图片测试在并发浏览器验收时约91—184ms，均Redis命中；不把内网1.8ms当作用户公网延迟。

缓存仅服务读取，原始数据库资料未改；修订号自动隔离旧缓存，后台管理凭证/写操作不缓存。首访未缓存图片仍受源站网络和限速影响。缓存命中不再查询源站DNS或等待回源锁；冷图片下载前释放DB连接并独立限流，避免拖住搜索/翻页。

运行中处理了部署脚本首次健康探针早于Redis监听的时序问题，改为有界重试；Docker缓存层快照缺失通过本项目无缓存重建解决，未清理全局构建缓存、未重启Docker或原有插件。

## 最终版本与终端结果

正式运行dual-catalog:0.2.2，Redis真实缓存最大256MiB，当前约7.7MB，404个本项目缓存key。RDB已实际生成4304522字节，文件归独立账户、0600。旧6379与fish-search/qq-summary-bot/nginx保持运行，未清库。

```text
.venv/Scripts/python.exe -m pytest backend/tests -q
65 passed, 1 warning in 9.41s
exit_code=0

npm test
pass 12 / fail 0
exit_code=0

python -m scripts.verify_cache (server api container)
status: pass, assertions: 19
REMOTE_EXIT=0

node scripts/verify-pagination.cjs
status: pass, assertions: 14, errors: []
exit_code=0

node scripts/verify-navigation.cjs
status: pass, mode: deployed public frontend, assertions: 32, errors: []
exit_code=0

node scripts/verify-images.cjs
status: pass, assertions: 14, errors: []
exit_code=0
```

最后一次真实内网热缓存车型列表约4.5ms，图片约1.74ms；公网时延以cache-public-after.json为准。分页覆盖首/次/末页、跳第5页、无重复、筛选重置、详情保持、桌面5列4行和手机不溢出。末页不足20属于正常余数。截图artifacts/acceptance/tomica-20-five-columns.png已经在真实浏览器滚动加载图片并完成视觉检查。

原图数据、车型年份/品牌及宝可梦名字等业务记录不重写。只新增可选page参数，cursor旧客户端保持兼容。命中Redis不回源；未缓存照片第一次仍需按来源限速下载。缓存不是源站照片全部可用或微信正式发布的证明，原有来源/发布未完成项保持原记录。

没有启动本地额外服务；临时缓存验证/预热容器自动删除，测试浏览器已退出。服务器交付服务按用户要求保留运行。后续保留缓存失效、连接故障回退、冷图释放数据库、分页和详情竞态回归，防止重新引入本轮及历史缺陷。
