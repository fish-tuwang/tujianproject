# 原图对照与修复

用户要求对比源站原图；按既有“一次性解决、只看效果调整”授权连续完成必要修正，不额外暂停确认。

## 已复现根因

1. backend/preview/app.js：display:none与loading=lazy同时使用，卡片不发起下载；强制eager后52poke图片因外站Referer返回403，浏览器报ERR_BLOCKED_BY_ORB。默认插画将种子/草/花画成同一形象。
2. backend/app/sources/pokemon.py：只给主条目保存image_url，地区形态没有保存原图。六尾alola在API中image_id为空，源站form2有037Vulpix-Alola.png。
3. backend/app/sync/service.py：封面按版本随机UUID排序选取。001-1封面实际对应源站“二次加工 CHINA”，未按来源顺序选图。
4. scripts/browser-smoke.js：仅验证卡片/按钮，未验证原图成功解码或形态图片身份。

证据：artifacts/image-audit下实时API、浏览器网络、HTTP403/200对照、源站与现页面截图。Tomica当前HTTP源站200。

## 直接修复范围

图片引用由后端按登记图片ID获取并缓存原始字节，限定来源域名/路径、实际图片类型/体积、限速，保留原图来源。预览缓存不伪造rights approved或正式HTTPS交付；正式发布保护不变。补齐形态image_url、封面按来源第一个有照片版本选取并显示版本对应图片；只回填本项目图片字段。原图加载失败明确显示缺图，不用相似插画替代。同步调整浏览器、原生图片URL及相应验证，保留其他业务字段和既有服务。

验证：图像签名/缓存/URL边界、真实源码形态映射、封面确定性回归；浏览器断言实际naturalWidth>0、每编号不同URL、地区形态不同图片、图片与源站字节摘要一致，重新截效果图。

## 已实际验证

- 后端单元：`.venv/Scripts/python.exe -m pytest backend/tests -q` → `58 passed, 1 warning in 8.95s`，退出0。警告仍为Starlette TestClient的httpx弃用提示。
- 原生逻辑：`npm test` → `tests 12 / pass 12 / fail 0`，退出0；不等于微信真机编译。
- 真实网页专项：`node scripts/verify-images.cjs` → `{"status":"pass","assertions":14,"errors":[],"base_url":"http://117.72.11.77"}`，退出0。验证三只妙蛙有不同原图、形态图片与属性一致、版本照片和源站封面、原图解码、横幅与手机布局。
- 原图字节对照：7个样本代理/源站均HTTP200，SHA256逐项一致。样本：妙蛙种子/草/花、通常/阿罗拉六尾、多美卡007-1与001-1。报告artifacts/image-audit/original-byte-checks.json。
- 数据回填：1101款车型封面改为源站第一个可用照片版本。车型/版本的名字、年份、品牌等字段未重写。
- 1025条宝可梦主图全部有来源图片，全国编号与图片文件名编号匹配的异常数0。图片按访问需求缓存，不声称已逐张下载并验证所有图片字节。
- 移除图鉴及横幅中的角色/汽车替代插画及其旧素材；缺图时不冒用其他条目的形象。浏览器/API原图缓存、源站归属和正式发布权限状态分开。

版本dual-catalog:0.1.8。对照报告artifacts/image-audit/comparison.html，效果截图fixed-pokemon.png、fixed-tomica.png、fixed-alola-detail.png与fixed-mobile.png。历史“仅卡片存在”的8项验收不能证明图片正确，本轮增加实际解码和对应关系检查。

## 最终回填结果与边界

第一轮回填224个有其他形态的宝可梦，共1308个图片字段；按源站“官方绘图”位置处理最后6个条目（9个特殊形态图片）后，pokemon_forms总数1317、image_id为空0。1025个主条目原图关联均存在；有版本照片但缺封面的车型数0。回填只处理图片关联，未重算名字/年份/品牌/属性等资料。

实际终端输出：

```text
forms_total|1317
forms_without_art|0
cars_missing_cover_despite_photo|0
REMOTE_EXIT=0
special form original images passed: 10
```

这证明已存记录的关联完整，不把它等同于所有源站照片均已逐张下载检查。7张原图字节对照及10个特殊形态原图实际HTTP200/图片类型通过；源站缺图或临时不可访问时保留明确缺图状态。当前实际缓存按访问需求生成。

修复前后journal已下载到artifacts/image-audit，并备份到服务器/opt/dual-catalog/backups/image-repair-*-20261109.json。临时回填容器已退出并清理，生产及预览服务继续运行，既有插件保持原状。当前图片专项验证使用最新0.1.8，终端58 passed / npm pass12 / 图片专项pass14。
