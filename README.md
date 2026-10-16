# 我整理的一些 RSS

整理一份自用 RSS 订阅列表，以及可自行部署的抓取、全文、翻译和邮件转 RSS 软件。

本仓库现在同时包含完整的自建工程与参考订阅清单。RSSHub、RSSBox、Redis、Nginx 等上游组件通过源码构建或容器组合使用；这里提供自写路由、补丁、侧车和部署工具。

- [部署一整套](deploy/rss-stack/README.md)：RSSHub + RSSBox + Redis + 限制路径的 Nginx，Cloudflare Tunnel 可选。
- [参考订阅列表](subscriptions.md)与 [OPML](feeds.opml)：官方源可直接使用，自建地址、密钥和会员源需替换为自己的配置。
- [邮件 Newsletter 转 RSS](newsletter-rss/README.md)：Cloudflare Worker、KV 和收信处理源码。
- [备份与恢复](deploy/rss-stack/backup/README.md)：一致性数据库快照、私有配置和镜像备份工具。
- [踩坑记录](notes.md)与 [许可证及来源](NOTICE.md)。

## 包含的软件

| 部分 | 作用 |
| --- | --- |
| `deploy/rss-stack/` | Compose、Nginx、源初始化、媒体审计和修复、历史合并、备份恢复 |
| `deploy/rss-stack/rssbox-patches/` | 抓取修复、串行更新、翻译完整性和图片保护、备用模型处理 |
| `deploy/rss-stack/*/proxy.py` | Anthropic、Claude Blog、Laura Shin、Sinocism、The Diff 等来源的适配 |
| `deploy/rsshub-custom-routes/` | 财新、纽约时报、地大路由，以及 RSSHub 修改补丁 |
| `lib/routes/truthsocial/` | Truth Social 路由 |
| `newsletter-rss/` | 邮件转 RSS Worker 源码及依赖锁文件 |
| `deploy/rss-stack/tests/` | 源适配与翻译回归测试 |

## 使用前

参考清单描述的是路由与方案，来源可能改版或失效。`YOUR-*` 是占位符，OPML 导入器不会自动替换它。付费来源需要使用者自己的有效订阅及 Cookie。

公开版本不包含个人账号、Cookie、OAuth 凭据、真实服务地址、数据库、文章缓存或备份归档。不要把填好的 `.env` 和生成的订阅链接提交回来。私有开发仓库的 Git 历史没有导入这里。

## 验证

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s deploy/rss-stack/tests -v
```

测试覆盖本库的补丁与适配逻辑；不代替真实 Cookie、外部网站、模型账号和完整容器运行验证。RSSBox 目前引用 `latest`，更新镜像前应复核挂载补丁与上游接口。
