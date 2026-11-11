# 图鉴 API 契约

公共 GET：`/api/tomica`、`/api/tomica/filters`、`/api/tomica/{UUID}`、`/api/pokemon`、`/api/pokemon/{dex}`。
列表参数 q/limit/cursor；多美卡增加 brand/year（unknown 表示未知），宝可梦增加 type（中文标准属性）。limit 1—100，默认30。返回 items/next_cursor，游标绑定筛选哈希、来源修订及最后排序键；400表示无效游标，409 CATALOG_CHANGED表示数据已更新。多美卡按有效年份空值最后及UUID排序，宝可梦按全国编号整数排序。所有筛选、排序及详情使用人工覆盖后的值；源值保留。

详情含全部基础字段、image_url/image_status、source_url、checked_at/updated_at（UTC ISO8601），图片不可用为null。多美卡含variants，宝可梦含forms/evolutions；进化提供from/to_name及available。

管理 Bearer 鉴权：GET `/api/admin/runs`、`/api/admin/issues`；POST `/api/admin/sync` body source/mode，POST `/api/admin/runs/{id}/retry`；PATCH `/api/admin/overrides` body kind/entity_key/field/value。202表示已入队；409 SOURCE_BUSY表示同源忙；401无效凭证；503 ADMIN_DISABLED表示未启用管理。覆盖结果含source_value/override_value/effective_value/actor/updated_at。

错误均为code/message，参数错误422，不存在404。健康GET `/health/live`及`/health/ready`（数据库和迁移head）。公共接口不请求来源网站。

`GET /api/pokemon/regions`返回definition/index_version/national_source_url/items；items含key/name/national_range/species_count/source_url。0.9.1起region按Wiki全国编号分段分类，支持kanto/johto/hoenn/sinnoh/unova/kalos/alola/galar/hisui/paldea/unknown；每个全国编号只属于一个分类，unknown为808–809，hisui为899–905。列表region与type/q取交集，total为真实筛选总数，仍按全国编号升序。地区缓存与游标绑定离线索引内容版本，旧索引地区游标返回400 INVALID_CURSOR；region为空继续兼容原未筛选游标。

适配器：SourceCandidate(kind,source_key,fields,evidence)；ParsedPage(source,url,discovered_urls,candidates,issues,content_hash)。仓储Session由调用方持有并提交；发布仅upsert不删除，身份缺失不自动合并。

CLI：python -m backend.app.worker init-db/seed-demo --confirm-demo/work/schedule/probe/report/sync --source tomica|pokemon --mode incremental|full [--limit N]。限量报告complete=false。任务状态queued/running/succeeded/partial/limited/failed；SyncService enqueue_run与retry_run只flush，调用方提交；周full对queued提升，对running记录followup。报告不输出连接秘密。
