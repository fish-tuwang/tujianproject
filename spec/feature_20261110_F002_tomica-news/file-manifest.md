# 新品月刊文件

新增：backend/app/news.py，backend/migrations/versions/0004_tomica_news.py，backend/data/tomica-news/2026-11.json，backend/preview/news-assets/7张SHA256命名原图，backend/tests/test_tomica_news.py，scripts/seed_tomica_news.py，scripts/prepare_news_demo.py，scripts/verify-tomica-news.cjs。

修改：backend/app/models.py、main.py，backend/migrations/versions/0001_catalog.py，backend/tests/test_migrations.py，backend/preview/index.html、app.js、style.css，Dockerfile.release，CHANGELOG.md、README.md、docs/deployment.md；相关新旧spec部署/来源记录。

部署/证据：artifacts/deploy_tomica_news.py；服务器/opt/dual-catalog/deploy_tomica_news.py与私有tomica-news-deploy.json。验收脚本与本地SQLite仅供测试，原生小程序本轮UI不变。
