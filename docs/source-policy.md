# 来源访问与复用记录

核对日期：2026-11-09。HTML固定样本来自以下公开页面；样本保留网页结构用于本地解析测试，不下载页面引用的图片。

| 样本 | 来源 | 人工核对 |
|---|---|---|
| tomica-number.html | http://tomica.minibird.jp/t-tomica/number/tba000.html | 001-1，1970.9，1/60；001-2，1974.9；WANTED不是照片 |
| tomica-special.html | http://tomica.minibird.jp/t-tomica/special/tto%20Honda.html | 本田特注，关联039-8 |
| pokemon-list.html | https://wiki.52poke.com/zh-hans/宝可梦列表（按全国图鉴编号）/简单版 | 全国编号1、妙蛙种子、Bulbasaur |
| pokemon-detail.html | https://wiki.52poke.com/zh-hans/妙蛙种子 | 草/毒，0.7m，6.9kg，茂盛/叶绿素 |
| pokemon-forms.html | https://wiki.52poke.com/zh-hans/六尾 | 通常火属性，阿罗拉形态冰属性 |
| pokemon-evolution.html | https://wiki.52poke.com/zh-hans/伊布 | 8个分支；水之石→134，雷之石→135 |

Tomica robots.txt返回404，状态未知，不代表内容或图片复用许可。52poke robots.txt返回200，禁止index.php等路径，读取wiki与zh-hans公开条目。请求按来源串行、间隔至少2秒，动态读取robots，无访问控制绕过。

正式公开内容的复用状态单独核对，正式图片交付默认pending；本地演示可采用自有原创插画，明确示意用途，不能冒充实物照片。更新责任：项目维护者在正式发布前核对来源条款与署名。

```json
{"tomica":{"crawl":"public-limited","text":"pending","images":"pending","evidence":[]},"pokemon":{"crawl":"robots-checked","text":"pending","images":"pending","evidence":[]}}
```

浏览器与开发版客户端允许引用白名单源站缩略图，标注“源站图片”，加载失败显示原创插画。source_image_url不等于已获复用许可或转存完成；image_status仍pending，image_url仅返回经确认且已交付自有HTTPS的图片。正式发布检查要求内容复用、HTTPS图片及合法域名证据。

2026-11-09图片修复：预览使用登记图片ID的同源原图缓存，图片字节不重绘、不调色；保留source_image_url与来源。缓存只允许既定来源、图片签名与体积上限，每源至少2秒。缓存不更改rights_status、正式image_url及HTTPS发布保护。原图缺失时显示缺图，不再显示角色或汽车插画。
