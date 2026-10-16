# RSS

复制这句话给 Agent：

```text
参考这个部署：https://github.com/syncmeta/RSS
```

自用的一套RSS系统，包括[订阅列表](subscriptions.md)、[爬取](#爬取)、[翻译](#翻译)、[存储](#存储)、[补丁](#补丁)。

可以按自己的来源和账号部署整套系统，也可以只取订阅清单、路由或某个模块使用。RSSHub、RSSBox、Redis、Nginx 通过源码构建或容器组合使用，本库提供自写路由、全文侧车、补丁及部署维护工具。

## 订阅列表

[参考订阅清单](subscriptions.md)按来源分类说明路由和用途；[feeds.opml](feeds.opml)提供 40 条参考订阅，包含官方源、RSSHub 路由、邮件 Newsletter 和自建全文侧车。

官方 RSS 可以直接使用。`YOUR-*` 是占位符，需要替换成自己的服务地址、访问密钥和邮件订阅令牌；付费来源使用自己的有效订阅账号。OPML 不包含作者的私人订阅地址。替换后可以导入阅读器，或用 [OPML 导入工具](deploy/rss-stack/import_opml.py)加入 RSSBox；默认预览，显式指定后才写入。

## 爬取

- [RSSHub 自写路由](deploy/rsshub-custom-routes/)：财新、纽约时报、中国地质大学（北京）等来源；[构建脚本](scripts/build-rsshub.sh)把路由和补丁装进 RSSHub 镜像。
- [公共来源侧车](deploy/rss-stack/public-proxies/proxy.py)：Anthropic Research、X / Laura Shin。
- [Anthropic News / Engineering](deploy/rss-stack/anthropic-sections/proxy.py)与 [Claude Blog](deploy/rss-stack/claude-blog/proxy.py)：独立抓取并输出 RSS。
- [Sinocism](deploy/rss-stack/sinocism-proxy/proxy.py)与 [The Diff](deploy/rss-stack/thediff-proxy/proxy.py)：使用自己的会员 Cookie 获取全文。
- [邮件转 RSS](newsletter-rss/README.md)：Cloudflare Worker 收信、KV 保存内容、按邮箱输出 Newsletter RSS。
- [Truth Social 路由](lib/routes/truthsocial/)与 [curl 抓取侧车](deploy/rss-stack/docker-compose.yml)：补充特定来源。

## 翻译

[RSSBox 翻译补丁](deploy/rss-stack/rssbox-patches/agent.py)提供长文分段、完整性检查和可配置的备用模型处理；[图片保护模块](deploy/rss-stack/rssbox-patches/translation_integrity.py)保留 HTML 图片及其顺序，拒绝残缺译文。

在 RSSBox 管理界面配置自己的模型接口、API Key 和模型，再为订阅开启标题或正文翻译。凭据保存在自己的 RSSBox 数据库中。未配置翻译时仍可使用原文订阅。[翻译配置步骤](deploy/rss-stack/README.md#4-翻译) · [模型凭据放置位置](docs/credentials.md#模型接口与可选适配器)。

## 存储

[Compose 配置](deploy/rss-stack/docker-compose.yml)用 `rssbox-data` 卷保存 RSSBox 的 SQLite 数据库、订阅、文章、译文及模型配置，`redis-data` 保存 Redis 数据，`ext-feeds` 保存侧车生成的 Feed 和全文缓存。默认 Compose 项目名为 `rss`，实际卷名带 `rss_` 前缀。

[备份与恢复工具](deploy/rss-stack/backup/README.md)可保存一致性数据库快照、私有配置、全文缓存与精确镜像；[历史合并工具](deploy/rss-stack/merge_rss_history.py)用于离线数据库副本。邮件 Newsletter 单独保存在自己的 Cloudflare KV 中，不在上述 Docker 备份范围内。普通停止用 `docker compose down`；`down -v` 会删除卷。

## 补丁

[补丁目录](deploy/rss-stack/rssbox-patches/)保留修改后的文件及 `.orig` 上游原件，便于比对升级：

- [抓取修复](deploy/rss-stack/rssbox-patches/fetch_feeds.py)：保留原文 HTML，处理状态码、ETag 等抓取问题。
- [翻译执行](deploy/rss-stack/rssbox-patches/translate_feeds.py)：管理译文保存与订阅可见状态。
- [串行更新](deploy/rss-stack/rssbox-patches/serial_feed_updater.py)和 [定时配置](deploy/rss-stack/rssbox-patches/rt_cron)：不同更新频率共用锁，减少并发占用。
- [RSSHub 修改补丁](deploy/rsshub-custom-routes/fork-vs-upstream.patch)：与自写路由一起应用到指定的上游源码。

[踩坑记录](notes.md) · [测试目录](deploy/rss-stack/tests/) · [许可证与上游来源](NOTICE.md)。根目录 MIT 不覆盖所有模块，RSSHub 路由和 RSSBox 衍生代码分别保留相应许可。

## 部署

完整步骤见 [部署说明](deploy/rss-stack/README.md)。需要 Git、Docker、Compose v2；RSSHub 源码构建需要额外内存和磁盘，可在同架构机器构建后传镜像。默认所有宿主机端口仅监听本机，远程管理走 SSH，阅读域名可选接自己的 HTTPS 反向代理或 Cloudflare Tunnel。

```sh
git clone https://github.com/syncmeta/RSS.git rss-public
cd rss-public
./scripts/build-rsshub.sh
cd deploy/rss-stack
cp .env.example .env
chmod 600 .env
# 按下方凭据说明填写自己的配置；替换两个 CHANGE_ME 随机密钥。
docker compose config --quiet
docker compose up -d
```

## 凭据如何获取、放在哪里

首次只需生成两个独立随机密钥；其他账号凭据按自己启用的模块提供。`.env` 的路径是 `deploy/rss-stack/.env`，从 [.env.example](deploy/rss-stack/.env.example)复制，权限设为 `600`。

| 凭据 | 获取方式 | 放置位置 |
| --- | --- | --- |
| `RSSBOX_SECRET_KEY` | 本机运行一次 `openssl rand -hex 32` | `.env` |
| `RSSHUB_ACCESS_KEY` | 再独立生成一次，供自己的 RSSHub URL 使用 | `.env` |
| 会员网站 Cookie | 自己登录已订阅的网站，从浏览器开发者工具取当前请求所需 Cookie | `.env` 对应来源字段 |
| 模型 API Key | 自己所选模型服务商的账号控制台 | RSSBox 管理界面的模型配置，随数据库持久化 |
| `TUNNEL_TOKEN`（可选） | 自己的 Cloudflare Tunnel 连接器安装步骤 | `.env` |
| Worker `FEED_TOKEN`（可选模块） | 自己生成独立随机令牌，用 Wrangler secret 写入 | Cloudflare Worker secret；本地调试可用忽略的 `.dev.vars` |
| KV namespace ID | 自己创建的 Cloudflare KV namespace | `newsletter-rss/wrangler.jsonc`；它是资源标识，不是访问密钥 |
| 可选适配器授权文件 | 运行本库适配器的显式授权流程，且账号和客户端须支持相应权限 | `deploy/rss-stack/chatgpt-plan-private/credentials.json` |

Cookie 的具体字段、格式、获取步骤、失效更新，以及 `.env`、模型数据库、邮件令牌和备份的对应关系，见 [凭据配置说明](docs/credentials.md)。不要把真实 Cookie、密钥、带令牌的订阅链接发到 Issue、提交 Git 或贴进 Agent 对话；由自己在本地文件或服务管理界面填写。

## 验证与适用范围

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s deploy/rss-stack/tests -v
```

测试覆盖本库的补丁与适配逻辑；完整运行还需在自己的部署环境验证网站、Cookie、模型接口和容器。来源可能改版或失效；RSSBox 当前引用 `latest`，升级前需复核补丁。公开仓库不包含作者的账号凭据、数据库、文章缓存、备份或私有开发历史。
