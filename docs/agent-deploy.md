# Agent 部署 prompt

把下面整段复制给有目标主机访问能力的 Agent，替换环境参数。真实 Cookie、API Key、SSH 私钥和 Tunnel token 由使用者在私有文件或服务界面填写，不需要贴进对话。

```text
请帮助我部署 https://github.com/syncmeta/RSS 这套 RSS 系统，完成配置、构建、启动、订阅初始化与验证。请实际执行我已授权范围内的工作。

我的环境：
- 目标主机/操作系统/CPU 架构：<填写>
- SSH 访问方式：<现有连接或本地 SSH 配置别名，不填私钥>
- 仓库目录：<填写；未克隆时可使用 rss-public>
- 服务器部署目录：<填写，例如 /opt/rss>
- 已有服务、历史数据库或命名卷：<填写，没有则写无>
- 需要的模块：<官方 RSS / RSSHub / 会员全文 / 翻译 / 邮件 Newsletter>
- 需要的订阅：<从 subscriptions.md、feeds.opml 选择，或另给清单>
- 翻译服务、兼容接口 URL、模型：<填写；不需要则关闭；不填真实 Key>
- 访问方式：<仅本机 / SSH / 自有 HTTPS 反向代理 / Cloudflare Tunnel>
- 自己的阅读域名、RSSHub 域名、Newsletter 域名：<填写或写不使用>
- 私人备份位置：<填写>
- 已授权的执行范围：<填写目标主机上的安装、构建、启动；是否包含域名/Tunnel/Worker 配置>

请按以下方式工作：

1. 先克隆或检查仓库，阅读 README.md、deploy/rss-stack/README.md、docs/credentials.md、NOTICE.md，以及需要启用模块的代码和说明。使用实际文件和目标主机状态判断，不假设参考订阅一定可用，也不假设公开仓库包含作者的账号或现成镜像。

2. 检查目标主机是否正确，并查看 OS、CPU 架构、Git、Docker、Compose v2、磁盘、内存、端口占用和已有容器/卷。若有已有服务或数据，先识别其所有者和备份位置，准备迁移方式；不要直接覆盖现有配置、数据库或命名卷。需要系统安装、网络配置或已有服务变更时，遵守我给的执行范围。

3. 根据我的来源与模块选择最小可用配置。缺少必要环境信息时集中询问；同时继续完成不依赖这些信息的准备。没有会员 Cookie、模型账号或 Cloudflare 权限的可选模块保持关闭或待配置，其他可用部分继续推进。

4. 用 scripts/build-rsshub.sh 构建带本库路由的 rsshub-custom:local。它固定了上游源码提交并应用补丁。若目标机资源不足，可在相同 CPU 架构的机器构建并传镜像；不要以已有本地缓存或另一种架构的镜像冒充验证通过。

5. 从 .env.example 生成部署用 .env，独立生成 RSSBOX_SECRET_KEY、RSSHUB_ACCESS_KEY，需要桥接时再生成 RSS_PLAN_BRIDGE_KEY。私有配置文件权限 600，授权文件目录权限 700。请告诉我各来源凭据如何取得、变量格式和填写位置，由我在本地或服务管理界面填写；不要把真实凭据打印到对话、日志或版本库。用 docker compose config --quiet 检查配置，避免展开完整凭据。

6. 保持当前配置的访问边界：RSSBox 后台只监听本机并通过 SSH 管理；阅读入口经过限制路径的 feed-proxy；RSSHub 使用访问密钥。若我授权了 Tunnel，用我的账号和域名配置，阅读域名指向 feed-proxy:80，RSSHub 域名指向 rsshub:1200，启用 runtime overlay。不要把后台直接作为公开阅读入口。

7. 用我的订阅选择生成私有 OPML，例如 feeds.private.opml；保留公共 feeds.opml 中的占位符。RSSBox 内部可用 rsshub:1200、feed-proxy/ext/...，阅读器用我的外部主机。先预览 import_opml.py，再在授权目标执行写入；不要沿用作者原部署的数据库编号、Feed slug、Agent ID 或访问地址。公开参考清单有些条目是同一来源的不同方案，不需要全部重复订阅。

8. 在 RSSBox 中配置我的翻译器，为需要的订阅开启标题/正文翻译。先用短文章验证接口，再检查一篇包含图片的文章，核对正文完整性和图片保留。备用模型只有在我明确需要时才配置。可选 chatgpt_plan.py 需要自己的授权与接口能力，默认不启用；不支持时记录具体状态，使用我已提供的兼容 API 或原文模式。

9. 若启用 Newsletter，阅读 newsletter-rss/README.md，在我的 Cloudflare 账号创建 KV、配置自己的 namespace ID、用 Worker secret 保存 FEED_TOKEN，再绑定我自己的 Email Routing 收件地址。在授权范围内部署，验证测试邮件和带令牌的 RSS 输出。Docker 备份不覆盖 Cloudflare KV，需要单独说明其数据保存方式。

10. 检查服务状态、容器健康、管理入口、RSSHub 路由、至少一个官方源和所选侧车输出。验证 /rss/*、/ext/* 的阅读输出以及后台路径被拒绝的行为；验证原文、译文与图片。运行仓库回归测试并区分通过、失败、跳过。没有运行 Docker、没有真实模型调用、没有 Cookie 或没有成功收信的项目，明确写成未验证，不用配置解析或模拟测试代替真实运行证据。校验结果和报告中不要带访问密钥或私有链接参数。

11. 配置或演示备份工具，说明数据库、.env、授权文件、缓存、镜像及 Newsletter KV 分别保存在哪里。恢复验证使用备份副本或空的新环境；不要用 docker compose down -v 清理已有数据，也不要在旧实例仍写入时启动第二套公开 Tunnel 接管同一服务。

12. 最后交付：实际部署目录、启用模块、服务状态、管理方式、我自己的阅读入口、配置与数据位置、订阅数量、验证结果、备份与更新命令，以及未完成项和下一步。只报告已实际完成的部署，不把代码提交或镜像构建等同于线上可用。
```
