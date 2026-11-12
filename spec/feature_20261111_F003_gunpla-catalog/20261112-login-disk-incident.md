# 2026-11-12 登录不可用恢复

用户现象：登录页面显示“服务暂时不可用，请稍后重试”。

直接证据：生产API登录返回500，AuthStore._reserve_attempt 在 BEGIN IMMEDIATE 报 sqlite3.OperationalError: disk I/O error；根分区非root可用空间为0，inode仅使用16%。两套API的只读PostgreSQL健康检查仍返回200，不能据此判定登录正常。

根因：该PostgreSQL集群业务库仅有 dual_catalog 与 dual_catalog_demo，数据库大小约123MB与9.7MB，诊断日志目录却约23GiB；log_statement=all 记录所有查询和绑定值。按日期命名、同名文件持续追加，11月11日单文件约14GiB、11月12日约5.1GiB。

恢复顺序：暂停自身 cache-warmer；仅删除未被任意容器引用的40个本项目历史镜像标签，保留当前0.11.3、上一版0.11.2与构建基础0.1.0，先释放可用空间；确认真实登录可用后，备份该PG集群配置，收窄全SQL日志为DDL，限制诊断绑定参数长度并启用官方七天循环日志，热加载无数据库重启。切换日志文件后，按文件大小递增压缩大于100MiB的已关闭日期日志，完整解压比对SHA256及源文件inode/大小/mtime，验证后才替换原文件为gzip历史。

范围：不改应用镜像、网页、数据库结构、图鉴记录、原账号密码、单会话规则、原图缓存或采集频率；不操作三个原有插件容器。应用访问IP、鉴权、发布及采集审计日志保持原轮转规则。

验证：`node scripts/verify-private-auth.cjs`，电脑Chrome与手机WebKit共34项通过、退出0，实际完成登录改密、图鉴及原图访问、单会话替换、退出和无注册检查；只使用临时账号，保留两个真实账号。新增有效登录及三类图鉴API实测4项通过、退出0；高达列表使用有效的limit=20参数。


最终结果：四个已关闭日期日志合计24,069,926,760字节，逐个完整SHA256校验后压缩为1,661,416,258字节，日志内容保留。磁盘最终可用22,849,191,936字节（约21.3GiB），df显示使用率62%，此前非root可用空间为0。原PG配置备份在 /opt/dual-catalog/backups/pg-logging-20261112T013819/，成功归档回执在 /opt/dual-catalog/backups/pg-logging-20261112T013853/receipt.json。配置检查无错误、无待重启参数；应用镜像仍为0.11.3、两套接口ready/0005_gunpla、原三个插件ID一致。

预缓存已恢复运行，详情18,926/18,926就绪、失败0；恢复检查采样时图片31,617项就绪、33项预热失败；后续本轮处理完37,264项，37,215项就绪、49项HTTPStatusError，状态partial，按既有机制5分钟后继续重试；未扩大本次登录故障修复为逐一调查原图错误，不称全部原图预热成功。预缓存运行316.4秒期间，新SQL诊断日志增长0字节。临时验收账号已按精确用户名停用并删除，旧会话实测401；生产与演示鉴权SQLite均quick_check=ok，两个真实账号的非会话指纹不变，生产账户仍为2、演示为0。本机临时凭证及会话删除，原私有凭证保留。

服务器恢复操作已写入原deploy.jsonl的server_recovery_finished事件，实际状态和目录在 data/artifacts/acceptance/login-storage-recovery.json；浏览器鉴权结果在本地 artifacts/acceptance/login-disk-auth-public.json，三图鉴登录冒烟在 login-disk-recovery.json。运行记录和查询方式同步GitHub；本次未部署新应用镜像。
