# QQ图鉴查询

本项目独立QQ组件使用949494401，用户已确认在该账号已加入的QQ群启用，仅响应明确@该账号的消息。沿用原鱼项目的个人QQ/NapCat接入方式；图鉴查询不依赖旧项目代码、数据或网站登录账号。

## 用法

- `@949494401 多美卡 Mark X`
- `@949494401 宝可梦 皮卡丘的种族值`
- `@949494401 高达 飞翼`
- `@949494401 帮助`

多个结果以5条一页列出，在同一群内用同一个QQ@回复序号查看，或发送“下一页/上一页”。候选15分钟有效，三个图鉴分别搜索；未指定类别时在三类图鉴中找名称。单类别最多展示前100个匹配结果，宽泛关键词可进一步缩小。宝可梦可在名字后添加种族值、获得方式、属性相性、招式学习器、技能或异色；保留游戏和形态上下文。多美卡与高达回复不展示来源链接，网页详情仍要求原有登录。

## 服务器操作

SSH后在 `/opt/dual-catalog/app` 执行：

```bash
python3 scripts/qq_bot_ops.py status
python3 scripts/qq_bot_ops.py login-qr
docker logs --tail 100 dual-catalog-qq-bridge
docker logs --tail 100 dual-catalog-qq-account
python3 scripts/view_logs.py collection --limit 100
```

`login-qr`通过QQ组件的实际刷新API获取新登录码，文件为 `/opt/dual-catalog/qq/login-qr.png`，仅root可读；二维码短期有效，不要上传GitHub。扫码后以本机登录状态及get_login_info返回账号核实身份，再用真实群内@查询确认发送回执。没有实际登录和QQ发送成功消息ID，不能标为接入完成。

限制群范围使用下列命令，仅重建本项目QQ桥接，不重启其他图鉴服务：

```bash
python3 scripts/qq_bot_ops.py configure --groups '群号1,群号2'
```

`--groups '*'`表示该QQ已加入的全部群。停止两个新组件可执行：

```bash
docker compose --env-file /opt/dual-catalog/.env.qq-bot -f compose.qq.yaml stop
```

## 隔离与验证

QQ接口3002、WebUI6099和桥接8096均仅监听127.0.0.1，不开放公网端口。HTTP事件校验实际运行版本采用的原始请求体HMAC-SHA1签名；QQ API调用用独立Bearer，内部图鉴凭证仅发往8092。图片从图鉴API服务器端读取，验证路径并转换为QQ图片消息，不公开私有图片地址。只做查询，不接受好友/加群申请或执行群管理操作。

`.env.qq-bot`和 `qq/`位于项目源码目录之外，不进入Git；状态按10001/10002独立UID持久化。桥接内存128MiB、QQ端512MiB，无core dump，容器日志限制5MiB×3。查询与发送事件记入已有私有collection.jsonl；重复消息ID保留24小时去重，同一群同一人限两秒一次。

原有7个图鉴容器、数据库和账号保持不变。实际服务器查询已覆盖Mark X、皮卡丘种族值、飞翼高达，并核对三类图片及详情链接；该检查不向QQ群发送测试消息。最终登录和群内往返结果以实施计划、服务器 `qq/deployment.json`及发送审计回执为准。
