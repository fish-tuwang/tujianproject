# Wiki地区分类修正（0.9.1）

日期：2026-11-11。用户明确选择按全国图鉴编号分段展示，替代0.9.0的跨版本地区图鉴合并规则。

## 根因与来源

旧索引将PokéAPI region.pokedexes求并集：卡洛斯包含密阿雷和异次元共582种，帕底亚包含北上/蓝莓共664种。线上复现：`region=kalos&q=赛富豪`返回全国1000号，`region=paldea&q=皮卡丘`返回25号；这符合旧合并定义，却不符合用户最新确认的全国编号分段。

2026-11-11实际查阅神奇宝贝百科：

- https://wiki.52poke.com/zh-hans/宝可梦列表（Pokémon_GO） ：地区标题、洗翠及未确认分类；借用分类口径，不按GO已登场名单删减全国图鉴。
- https://wiki.52poke.com/zh-hans/宝可梦列表（按全国图鉴编号） ：全国编号及第九世代906起的完整列表。
- https://wiki.52poke.com/zh-hans/地区图鉴 ：明确区别分版本地方图鉴；本次不再使用此合并口径。

## 新规则

| 分类 | 全国编号 | 种数 |
| --- | --- | --- |
| 关都 | 0001–0151 | 151 |
| 城都 | 0152–0251 | 100 |
| 丰缘 | 0252–0386 | 135 |
| 神奥 | 0387–0493 | 107 |
| 合众 | 0494–0649 | 156 |
| 卡洛斯 | 0650–0721 | 72 |
| 阿罗拉 | 0722–0807 | 86 |
| 伽勒尔 | 0810–0898 | 89 |
| 洗翠 | 0899–0905 | 7 |
| 帕底亚 | 0906–1025 | 120 |
| 未确认 | 0808–0809 | 2 |

1025个物种各出现于一个分类，地区形态仍在原详情中，不改变物种全国编号。照片、详情资料和数据库不变。删除原跨版本抓取合并代码，以离线分段表生成schema_version=2的索引；CLI --refresh仅重建已核对规则，不声称自动发现新世代。地区缓存及筛选游标继续绑定内容版本，新版本不命中旧集合缓存。

## 实施与验证

- [x] 修正地区索引、元数据及浏览器/小程序文案，新增未确认分类并保留刷新恢复白名单。
- [x] 保留游标隔离、联合筛选、不可变快照及旧未筛选游标测试，替换被用户新选择明确废止的跨地区重复断言。
- [x] 完整Python/小程序测试通过。
- [x] 发布0.9.1，双接口健康、原插件不变，无迁移/导入。
- [x] 公网逐地区翻完游标，核对范围、计数、1025完整去重、短列表、未确认刷新及旧交互回归。
- [x] 保存发布回执、实际结果与截图。

## 实际执行结果

- 本地`python -m pytest -q`：`151 passed, 1 skipped, 9 warnings in 21.89s`，退出0；Windows跳过的POSIX打开文件轮转用例在Linux镜像测试通过。
- `node --test miniprogram/tests/*.test.js`：tests 20 / pass 20 / fail 0，退出0；包含未确认分类名称、稳定key和全国编号。小程序仍为源码测试，不宣称微信真机发布。
- 服务器不可变镜像验证：`docker run --rm --network none --memory 384m --pids-limit 128 -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python dual-catalog:0.9.1 -m pytest -q -p no:cacheprovider`，输出`152 passed, 9 warnings in 40.83s`，REMOTE_EXIT=0；无代码挂载、不访问外站和生产数据库。
- 发布脚本`python3 /opt/dual-catalog/app/scripts/deploy_release.py --image dual-catalog:0.9.1 --reason "Wiki national-number region groups; separate Hisui and unconfirmed; replace overlapping regional union"`，REMOTE_EXIT=0。operation_id=`f0d1ddb0e47d4e6d8e1d959dfeb9b2e5`，回执`artifacts/acceptance/wiki-regions-deployment.json`为pass；8092/8093均ready、revision=0004_tomica_news，plugins_unchanged=true、database_migration=false、data_import=false。
- 公网`node scripts/verify-ui-regions.cjs`：status=pass、checks=61，desktop/mobile均pass，退出0；逐类走完所有游标并验证1025个全国编号各一次，含短列表结束、未确认刷新、卡洛斯搜不到帕底亚的赛富豪、自动滚动/失败重试/旧请求隔离。报告副本`artifacts/acceptance/wiki-regions-public.json`。
- 公网历史回归`node scripts/verify-both-catalog-refresh.cjs`：29项、退出0；`node scripts/verify-tomica-display.cjs`：27项、退出0。报告副本`wiki-regions-refresh-public.json`、`wiki-regions-tomica-display-public.json`。
- 11个分类以默认limit=12请求两遍，第二遍全部`X-Catalog-Cache: hit`，退出0；证据`artifacts/acceptance/wiki-regions-cache.json`。API、demo API和cache-warmer均0.9.1、running、restarts=0、OOM=false，Redis服务active。
- 实际公网卡洛斯截图`artifacts/acceptance/wiki-regions-kalos-desktop.png`，等待视口内原图显示后截取，无页面资源覆盖。

交付地址：http://117.72.11.77/preview/?catalog=pokemon&v=0.9.1 。浏览器已有筛选会按新归类重新查询，旧1025条基础资料与照片不变。

历史修复影响：原图与放大、Mark X搜索、多美卡分页、双图鉴独立筛选及关闭/刷新位置均由对应公网回归保持通过。复盘：错误源于将地方图鉴收录与全国编号地区分段混用；删除跨版本合并步骤，以一份明确的分段表生成索引，并在界面显示范围和数量。当前1025种已核验，今后出现新全国编号时需核对Wiki并更新分段边界。
