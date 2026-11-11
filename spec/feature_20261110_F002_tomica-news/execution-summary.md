# 新品月刊执行记录

本轮范围：按月新品推送、用户7张原图分组、多角度详情/原图查看与持续部署授权。用户素材2—6仅归No.114，第1/7张各自独立；不补猜正式名称、售价、发售日。图片逐字节保留水印，不联网访问被拒绝的公众号；本文来源仅为用户上传，未实现公众号自动发现。

本地：独立SQLite API8094只读复制200条真实Tomica与Pokemon25/37，导入本月数据，预热5个旧封面。新品/迁移测试16通过，原图子集4通过（10 deselected）。完整后端110 passed, 9 warnings in 15.97s；原生逻辑15 pass / 0 fail；均真实执行。浏览器最终32项真实本地检查覆盖按月索引、原图HTTP字节、5+1+1组、图册解码、放大、深链/刷新/历史、页码/筛选保持、分类隔离与迟到响应。原图检验通过SHA256与用户附件本体比较。

首次迁移检查2失败：0001迁移动态遍历现有ORM导致提前创建新品表。沿用既有pokemon_details排除修复，仅追加tomica_news排除，添加0003阶段无新品表断言；保留原0002往返与Pokemon旧数据断言后，16项及全套110项通过。

已部署dual-catalog:0.6.0，生产/演示均healthy且0004_tomica_news。部署脚本完整执行REMOTE_EXIT=0；后续--check纯SELECT/文件/Redis核验REMOTE_EXIT=0，不在常驻API内另启Python进程。首轮部署脚本的核验曾调用同内容import并commit，实际结果始终unchanged未改数据；已改成只读计算内容摘要并匹配存储，重复导入动作只在授权部署阶段执行。

两库各导入1篇、3组、7张原图，第一次created1，第二次created0/updated0/unchanged1，均redis_warmed7。核对所有旧表原ID均保留，正式1997车型/15515版本/1025Pokemon/1317形态/1025扩展详情及19844图像登记未减少，演示原资料和1条人工覆盖保留。两库pg_dump备份通过pg_restore --list核验，生产8051914字节、演示36957字节，目录0700文件0600。原插件容器ID保持，预热健康后恢复；旧镜像0.5.1与备份保留，不降库。

公网新品32项通过，最后断言errors=[]，exit0；node scripts/verify-navigation.cjs为32项、verify-page-size.cjs为17项、verify-tomica-display.cjs为27项、verify-pokemon-details.cjs为20项，均exit0。各套件独立统计，不累加重叠项。

实际截图：artifacts/acceptance/tomica-news-desktop-public.png（再次等待前5张旧车图与新品封面解码后拍摄）、tomica-news-no114-public.png、tomica-news-mobile-public.png；JSON为tomica-news-public.json。截图已实际查看桌面、详情和手机布局。用户上传JPG不裁剪/不重编码，HTTP字节与原附件一致。

本地8094服务PID56940命令经确认后停止，测试浏览器均finally退出；交付服务与全量缓存按授权保留。全量老图缓存仍running，最新线上核验确认1999/19844就绪、1次源图失败待后台续试；新品7图均已预热，不把整队列写成完成。公众号自动发现/联网采集尚未接通，本期只基于用户明确上传材料。

交付：http://117.72.11.77/preview/?catalog=tomica&v=0.6.0 ，月刊#tomica-news/2026-11，单款#tomica-news/2026-11/no-114-gardener-truck。

