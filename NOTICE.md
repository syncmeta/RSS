# 许可证与来源

根目录 LICENSE 为 MIT，以下部分另有许可，根 MIT 不覆盖这些路径：

| 路径 | 许可与来源 |
| --- | --- |
| `deploy/rsshub-custom-routes/`、`lib/` | AGPL-3.0，RSSHub 路由与衍生修改，保留上游声明与完整许可文本 |
| `deploy/rss-stack/` | GPL-3.0，包含 RSSBox 原始文件、补丁及在其进程内运行的工具；完整文本见 rssbox-patches/LICENSE |
| `newsletter-rss/`、文档、订阅清单 | MIT；npm 依赖遵循各自许可 |

RSSHub：https://github.com/DIYgod/RSSHub 。RSSBox：https://github.com/versun/rssbox 。
容器引用的上游软件并未复制进本库，其源码、版权与许可见各镜像上游。
财新路由中的 RSA 常量来自 RSSHub 上游公开代码与财新公开客户端脚本，并非部署者的私钥；保持上游声明。个人 Cookie、账号密钥不在公开版本中。

2026-10-16：把订阅目录与可公开的自建软件整理到本库，保留既有提交历史。
