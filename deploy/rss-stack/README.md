# 部署指南

Docker Compose 组合 RSSHub、RSSBox、Redis、Nginx 与抓取侧车。管理界面默认只监听本机，所有持久化数据保存在 Docker 卷中。以下命令在一台安装了 Docker 和 Compose v2 的 Linux 主机执行；RSSHub 构建需要较多内存，可在另一台同架构机器构建后传送镜像。

凭据的获取方式、变量格式与存放位置见 [凭据配置说明](../../docs/credentials.md)。

部署前确认目标机器的系统、CPU 架构、Docker/Compose 版本、可用内存、磁盘和端口。已有容器、数据库或命名卷时先备份，再确定复用或迁移方式；Compose 项目名会影响卷名。按需要选择来源、翻译和邮件模块，具体实现与参数以本仓库代码及各服务当前的上游文档为准。

## 1. 构建带自写路由的 RSSHub

在仓库根目录执行：

```sh
./scripts/build-rsshub.sh
```

脚本检出指定的 RSSHub 上游提交、应用补丁、覆盖本库路由，然后通过上游 Dockerfile 构建 `rsshub-custom:local`。需要 Git、Docker、网络和足够的磁盘空间。构建目录 `.rsshub-build/` 被 Git 忽略。

## 2. 配置并启动

```sh
cd deploy/rss-stack
cp .env.example .env
chmod 600 .env
# 编辑 .env：生成两个独立随机密钥，配置自己的域名和所需的来源 Cookie。
# 例如：openssl rand -hex 32（各运行一次，填入两个 CHANGE_ME 字段）
docker compose config --quiet
docker compose up -d
```

默认配置启用 runtime、Anthropic 分类及 The Diff overlay；没有账号的付费来源不能提供会员全文。所有卷自动创建，普通停止用 `docker compose down`，`down -v` 会删除数据。

| 本机地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:8001` | RSSBox 管理界面 |
| `http://127.0.0.1:8000/rss/<slug>` | RSSBox 输出 |
| `http://127.0.0.1:8000/ext/<name>.xml` | 自建侧车输出 |
| `http://127.0.0.1:1200/<route>?key=<key>` | RSSHub 路由 |

按 RSSBox 容器启动日志完成管理员登录。远程管理使用 `ssh -L 8001:127.0.0.1:8001 user@your-server`。公开服务可接自己的 HTTPS 反向代理或 Tunnel；同步修改 `.env` 中的 `RSSBOX_SITE_URL`。`/rss/*`、`/ext/*` 是阅读出口，后台路径由 Nginx 拒绝。付费全文出口也应限制在自己的阅读环境使用。

## 3. 加入参考订阅

[根目录 OPML](../../feeds.opml) 与 [清单](../../subscriptions.md) 可供 RSSBox 或阅读器参考。先复制为私有的 `feeds.private.opml`，把需要的条目中的 `YOUR-RSSHUB-HOST`、`YOUR-FEED-HOST`、`YOUR-NEWSLETTER-WORKER`、密钥等占位符替换为自己的值。官方 RSS 不依赖自建服务，同一来源的不同方案按需选择，不必重复订阅。

可在管理界面手工加入，或将替换好的 OPML 导入 RSSBox：

```sh
docker compose cp ../../feeds.private.opml rssbox:/tmp/feeds.opml
# 预览；仍含占位符的条目会跳过。
docker compose exec -T rssbox python manage.py shell < import_opml.py
# 确认自己的 OPML 后写入；相同源地址不会重复创建。
docker compose exec -T -e RSS_IMPORT_APPLY=1 rssbox python manage.py shell < import_opml.py
```

如需通过内网抓 RSSHub，可使用 `http://rsshub:1200`。侧车地址在容器内用 `http://feed-proxy/ext/<name>.xml`；阅读器中用自己的 HTTPS 主机。

## 4. 翻译

在 RSSBox 管理界面配置自己的兼容模型接口、密钥和模型，再按订阅开启标题或正文翻译。默认不自动选择其他付费供应商；需要备用模型时，显式填写本机数据库中创建的 Agent ID。

补丁对 HTML 图片做保护、拒绝不完整输出，并让各更新频率共享串行锁。长文章仍需足够的模型额度与超时预算，来源的结构变化也可能导致抓取失败。

`chatgpt_plan.py` 与 `docker-compose.chatgpt-plan.yml` 作为可选适配器源码保留，默认不开启。其授权依赖相应的客户端注册、权限和账号支持，不能假设任意账号都可用。运行 `python chatgpt_plan.py --help` 查看命令。私有授权文件只存 `chatgpt-plan-private/`，不要上传或复用其他应用的令牌。通用 API 翻译不需要此 overlay。

## 5. 可选 Tunnel

先在自己的 Cloudflare 账号创建 Tunnel，把自己的 token 写入 `.env`。公开的阅读域名指向 `http://feed-proxy:80`，RSSHub 域名指向 `http://rsshub:1200`；后台保持 SSH 访问。然后运行：

```sh
docker compose --profile tunnel up -d cloudflared
```

runtime overlay 把 Tunnel 与 RSSBox 后台隔离，Tunnel 网络中的 `rssbox` 别名也指向 feed-proxy。

## 维护工具

- `audit_translation_media.py`、`verify_translation_media.py`：数据库与输出图片检查，后者需显式传 `--ids`、`--base-url`。
- `repair_translation_media.py`：默认预览，`--apply` 才写入；在 RSSBox 环境执行前先备份数据库，并把脚本及 `public-proxies/` 一起复制进去。
- `merge_rss_history.py`：只对离线数据库副本合并历史；先看 `--help`，不得直接操作正在更新的数据库。
- [backup/](backup/README.md)：独立保存数据库、私有配置、全文缓存与镜像。

RSSBox 补丁目录包含 `.orig` 上游原件以便比对。上游镜像变化时可能需要调整补丁；本库不自动修改正在运行的服务。

批量工具必须显式选自己的对象：Anthropic 的 `translate_content.py` 使用 `RSS_TRANSLATE_FEED_IDS`（逗号分隔）；`probe_translation_fallback.py` 使用 `RSS_PROBE_AGENT_ID`；The Diff 的回填及翻译脚本要求自己的 `--feed-id`，翻译另需 `--agent-id`、`--container`。先备份和查看参数，再在自己的环境使用。

## 部署验证

启动后检查容器状态和健康检查，分别验证管理入口、RSSHub 路由、官方源和所选侧车输出。阅读入口应能返回 `/rss/*`、`/ext/*`，其余后台路径由代理拒绝。开启翻译时先用短文验证模型接口，再检查一篇带图片的文章，核对正文完整性、图片和阅读器中的显示。邮件模块单独验证收信与带令牌的 Feed 输出。

仓库测试、配置解析和镜像构建分别验证不同环节；外部来源、会员全文、模型调用和实际容器运行需在部署环境中验证。缺少账号或未启用的模块记录为待配置，未实际运行的检查记录为未验证。

部署完成后记录服务入口、管理方式、启用模块、配置和数据位置、备份方式及尚未完成的项目。备份恢复先在副本或空环境中验证；迁移时先停止旧实例写入并隔离旧 Tunnel，再切换服务入口。
