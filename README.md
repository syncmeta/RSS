# 我整理的一些 RSS

参考 RSSHub 官方文档配置好 Cookie，再参考本仓库的 feeds.opml，就得了。部分需要从邮件 Newsletter 转出来。

具体操作请让 Agent 处理，本仓库可以让 Agent 少绕一些弯路，因为这些路由都是摸索出来的。

### 财新（需订阅账号）

| 名称 | 来源 | 路由 / 地址 | 说明 |
|---|---|---|---|
| 财新 - 最新文章 | RSSHub | `/caixin/latest?fulltext=true` | 自写路由，`?fulltext=true` 出付费全文 |
| 财新 - 观点 | RSSHub | `/caixin/channel/opinion?fulltext=true` | 自写路由 |
| 财新 - 中国改革 | RSSHub | `/caixin/channel/cnreform?fulltext=true` | 自写路由 |
| 财新 - 比较 | RSSHub | `/caixin/channel/bijiao?fulltext=true` | 自写路由 |

### 纽约时报（需订阅账号）

| 名称 | 来源 | 路由 / 地址 | 说明 |
|---|---|---|---|
| 紐約時報 - 首頁（全文） | RSSHub | `/nytimes/fulltext/homepage` | 自写路由，走 samizdat GraphQL |
| 紐約時報 - 雜誌（全文） | RSSHub | `/nytimes/fulltext/magazine` | 自写路由 |
| 紐約時報 - The Upshot | RSSHub | `/nytimes/fulltext/theupshot` | 自写路由 |
| 紐約時報 - DealBook | RSSHub | `/nytimes/fulltext/dealbook` | 自写路由 |
| 紐約時報 - 視覺調查 | RSSHub | `/nytimes/fulltext/visual-investigations` | 自写路由 |
| 紐約時報 - 首頁 | 直连 | <https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml> | 官方 RSS，只有摘要 |
| 紐約時報 - 觀點 | 直连 | <https://rss.nytimes.com/services/xml/rss/nyt/Opinion.xml> | 官方 RSS |
| 紐約時報 - 藝術 | 直连 | <https://rss.nytimes.com/services/xml/rss/nyt/Arts.xml> | 官方 RSS |
| 紐約時報 - 雜誌 | 直连 | <https://rss.nytimes.com/services/xml/rss/nyt/Magazine.xml> | 官方 RSS |

### 中国地质大学（北京）

| 名称 | 来源 | 路由 / 地址 | 说明 |
|---|---|---|---|
| 地大 - 北地新闻 | RSSHub | `/cugb/news/bdxw` | 自写路由，学校官网没有 RSS |
| 地大 - 教务处学生专区 | RSSHub | `/cugb/jwc/xszq` | 自写路由 |

### X / Twitter

| 名称 | 来源 | 路由 / 地址 | 说明 |
|---|---|---|---|
| X / Andrej Karpathy | RSSHub | `/twitter/user/karpathy` | — |
| X / Andrew Ng | RSSHub | `/twitter/user/AndrewYNg` | — |
| X / Mark Gurman | RSSHub | `/twitter/user/markgurman` | — |
| X / Ming-Chi Kuo | RSSHub | `/twitter/user/mingchikuo` | — |
| X / Brian Krebs | RSSHub | `/twitter/user/briankrebs` | — |
| X / Laura Shin | RSSHub | `/twitter/user/laurashin` | — |

### AI / 科技

| 名称 | 来源 | 路由 / 地址 | 说明 |
|---|---|---|---|
| Anthropic Research | RSSHub | `/anthropic/research` | 官网没有 RSS |
| 即刻 - AI探索站 | RSSHub | `/jike/topic/63579abb6724cc583b9bba9a` | 即刻圈子 |
| Latent Space | 直连 | <https://www.latent.space/feed> | — |
| Ben's Bites | 直连 | <https://www.bensbites.com/feed> | — |
| Founder Park | 直连 | <https://wechat2rss.bestblogs.dev/feed/f940695505f2be1399d23cc98182297cadf6f90d.xml> | 微信公众号，经 wechat2rss 转 RSS |

### 评论 / 长文

| 名称 | 来源 | 路由 / 地址 | 说明 |
|---|---|---|---|
| Sinocism | 直连 | <https://sinocism.com/feed> | Substack，付费部分只给摘要 |
| The Diff | 直连 | <https://www.thediff.co/feed> | — |
| Essays - Benedict Evans | 直连 | <https://www.ben-evans.com/benedictevans?format=rss> | — |
| Works in Progress | 直连 | <https://www.worksinprogress.co/rss.xml> | — |
| Money Stuff | 邮件转 RSS | `/feed/moneystuff.xml` | 彭博邮件专栏，自建 Worker 收信转 RSS |
| Benedict's Newsletter | 邮件转 RSS | `/feed/benedict.xml` | 同上 |

### 论坛

| 名称 | 来源 | 路由 / 地址 | 说明 |
|---|---|---|---|
| 前沿快讯 - LINUX DO | 侧车抓取 | <https://linux.do/c/news/34.rss> | 站点按 TLS 指纹拦截，需用 curl 抓取后本地伺服 |

共 33 条。

## 来源类型

- **RSSHub** —— 跑在自建 [RSSHub](https://github.com/DIYgod/RSSHub) 上。完整地址是 `https://<你的 RSSHub>/<路由>?key=<你的 ACCESS_KEY>`。
- **直连** —— 站点自己提供的 RSS。
- **邮件转 RSS** —— 只发邮件的 newsletter。用一个 Cloudflare Worker 收信转 Atom：Email Routing 收信 → 存 KV → 按 feed 输出。
- **侧车抓取** —— 有些站（如 linux.do）在 Cloudflare 后面按 TLS 指纹拦截，`curl` 能过、Node/Python 的 HTTP 客户端一律 403。用一个只跑 `curl` 的小容器定时抓下来落盘，再由 nginx 当静态文件伺服。

## 自写的 RSSHub 路由

官方 RSSHub 没有这几条：

| 路由 | 做什么 |
|---|---|
| `/cugb/news/:channel`、`/cugb/jwc/:channel` | 中国地质大学（北京）的新闻和教务通知，学校官网没有 RSS |
| `/nytimes/fulltext/:section` | 纽约时报付费全文，走 samizdat GraphQL（开放 APQ），不需要跑浏览器 |
| `/caixin/channel/:column`、`/caixin/latest?fulltext=true` | 财新栏目页与付费全文 |

依赖各自的订阅 cookie，通过环境变量传给 RSSHub。本仓库不含任何 cookie。

## 翻译

RSSHub 和 RSSBox 的若干问题见 [notes.md](notes.md)。
