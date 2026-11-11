# UI与地区图鉴验收记录

日期：2026-11-11；目标发布0.9.0。范围包括双主题、十地区合并索引、滚动自动加载、小程序地区选择；保留图标、原图和历史筛选/返回。

## 数据与本地验证

- `python -m backend.app.pokemon_regions --refresh`实际生成：关都153、城都256、丰缘211、神奥210、合众301、卡洛斯582、阿罗拉403、伽勒尔584、洗翠242、帕底亚664。共用物种跨地区保留，索引来自10份region与32份pokedex真实响应，静态版本1cdba692f1aaad06e9089041245951f1d34fec9cc0bc840013ba50ce4e31a0c0。
- `.venv/Scripts/python.exe -m pytest -q`：`151 passed, 1 skipped, 9 warnings in 21.12s`，退出0。Windows跳过POSIX打开文件重命名；测试使用SQLite和模拟外站，不等于真实外站抓取。
- `node --test miniprogram/tests/*.test.js`：`tests 19 / pass 19 / fail 0`，退出0。包含地区/属性/搜索传参、缓存picker恢复、迟到元数据、旧请求隔离、失败追加保留原cursor与原图/异色历史逻辑。
- 浏览器在服务器独立候选API的只读查询上验收，服务仅绑定127.0.0.1:8094，使用专用Redis命名空间，通过SSH本地转发18094访问；前端资源通过--local覆盖。不会把本地虚拟数据称为真实生产验收。
- 新UI用例覆盖地区联合筛选、三批实际滚动、停止自动连刷、首屏补足、最后短批停止、失败保留及重试、详情暂停、详情返回、刷新、旧地区请求取消、内部导航保存地区/属性/搜索。报告为artifacts/acceptance/ui-regions-local.json，最终公网结果另记。本地最终41项新UI断言通过，两个profile为desktop/mobile；保留的29项旧刷新断言也全部通过，各退出0。
- 旧刷新脚本把点击load-more改为实际滚动，快照等待稳定帧、自动滚动前等待恢复完毕；保留29项原比较和3像素位置阈值。新闻受控延迟阶段允许列表先到，避免等待被测试门闩故意挂起的恢复。曾出现一次手机40款刷新位置偏差未稳定复现，加入稳定帧等待和现场诊断。另有接口加载失败，其失败现场与转发终端记录确认测试SSH连接已失活（SSH session not active），同期服务器候选API为running、restarts=0、OOM=false且本机curl成功。恢复带keepalive的转发，正常浏览器取消连接不再输出异常风暴；原3像素断言保留，最终结果以新一轮及公网报告为准。

## 发布与公网结果

- 已发布镜像`dual-catalog:0.9.0`，operation_id=`eedc377fe76744bda3e10961b578cc09`；`scripts/deploy_release.py`退出0。回执`artifacts/acceptance/ui-regions-deployment.json`为pass，正式8092/演示8093均ready、revision=`0004_tomica_news`，plugins_unchanged=true、database_migration=false、data_import=false。
- 在服务器直接运行不可变发布镜像：`docker run --rm --network none --memory 384m --pids-limit 128 -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python dual-catalog:0.9.0 -m pytest -q -p no:cacheprovider`，原始摘要为`152 passed, 9 warnings in 43.03s`，REMOTE_EXIT=0。未挂载工作区、未连接生产数据库或外站；Linux日志轮转用例也通过。
- 公网运行`node scripts/verify-ui-regions.cjs`，退出0，`ui-regions-public.json`为pass、checks=41、profiles为desktop/mobile、errors为空；未启用--local覆盖。桌面Chrome和手机WebKit覆盖十地区联合筛选、自动滚动、失败重试、恢复与竞态。
- 公网历史回归分别运行`node scripts/verify-both-catalog-refresh.cjs`（29项）、`node scripts/verify-tomica-display.cjs`（27项）、`node scripts/verify-tomica-editions.cjs`（22项），全部退出0。对应`both-catalog-refresh-public.json`、`tomica-display-public.json`、`tomica-editions-public.json`均pass；保留原图与放大、Mark X名称搜索、分页/每页数量、详情关闭及刷新位置恢复。
- 公网地区元数据及`/api/pokemon?region=hisui&type=电&limit=17`连续请求均HTTP200、`X-Catalog-Cache: hit`；前者10地区，后者返回17条、total=18。双健康接口仍ready，Redis守护进程active；API及cache-warmer使用0.9.0镜像、running、restarts=0、OOMKilled=false。
- 实际公网页面截图位于`artifacts/acceptance/ui-regions-tomica-desktop.png`、`ui-regions-pokemon-desktop.png`、`ui-regions-tomica-mobile.png`、`ui-regions-pokemon-mobile.png`。另行等待视口内原图实际解码显示后截图，不使用前端覆盖或替代图片。
- 独立候选容器`dual-catalog-ui-review`已移除，18094测试转发已停止；正式API、缓存预热与原有插件继续运行。交付链接：`http://117.72.11.77/preview/?catalog=tomica&v=0.9.0`、`http://117.72.11.77/preview/?catalog=pokemon&v=0.9.0`。

## 历史修复影响与本轮复盘

本轮保留原有图标和原图，历史名称搜索、图片铺满/放大、关闭按钮居中、多美卡分页及双图鉴返回/刷新恢复已通过对应公网回归。主题覆盖层避免更换原有页面结构；地区索引离线交付，查询按全国编号排序；自动续页限制在用户向下浏览时触发，避免静止时连续拉完整库。地区范围是各版本地区图鉴的合并，允许跨地区重复；更新索引需显式刷新并随版本发布。相关功能已完成，原生微信真机发布边界见下文。

## 真实边界

地区范围合并各版本含扩展图鉴，不是首次登场世代；地区索引随发布离线交付，显式刷新后重新发布。页面不依赖用户设备访问PokeAPI。现有宝可梦资料与原图继续来自52poke。本轮没有数据库模式迁移、重写车型或更换照片。微信AppID/正式HTTPS域名仍未提供，原生小程序只完成源码与模拟测试，不宣称已在微信真机发布。
