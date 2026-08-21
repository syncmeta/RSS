# 订阅清单

我自己在用的一份 RSS 订阅清单，连同每条订阅对应的 RSSHub 路由。

整理出来是因为：好用的源不好找，而**找到之后最麻烦的一步往往是「这个站没有 RSS，怎么把它变成 RSS」**。
这里把两件事都写下来了——订阅了什么，以及每一条是怎么来的。

`feeds.opml` 可以直接导入阅读器。里面所有指向自建服务的地址都是占位符，
换成你自己的实例地址即可；不需要自建的那些是公开地址，导进去就能用。

> 清单里有几条需要**你自己的付费订阅账号**（财新、纽约时报）。
> 这里只列路由，不提供任何账号或 cookie。

## 清单

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
| Founder Park | 直连 | <https://wechat2rss.bestblogs.dev/feed/f940695505f2be1399d23…> | 微信公众号，经 wechat2rss 转 RSS |

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
| 前沿快讯 - LINUX DO | 侧车抓取 | `https://linux.do/c/news/34.rss` | 站点按 TLS 指纹拦截，需用 curl 抓取后本地伺服 |

共 **33** 条。

## 几类来源分别是什么意思

- **RSSHub** —— 路由跑在自建的 [RSSHub](https://github.com/DIYgod/RSSHub) 实例上。
  表里写的是路由路径，完整地址是 `https://<你的 RSSHub>/<路由>?key=<你的 ACCESS_KEY>`。
  官方公共实例大多没有这些自写路由，也扛不住需要登录态的源。
- **直连** —— 站点自己提供的 RSS，公开地址，拿来就能用。
- **邮件转 RSS** —— 只发邮件不发 RSS 的 newsletter（比如彭博的 Money Stuff）。
  做法是给它一个专用收件地址，收到信后转成 RSS 条目。我用的是一个 Cloudflare Worker，
  几十行代码：Email Routing 收信 → 存 KV → 按 feed 输出 Atom。
- **侧车抓取** —— 有些站（如 linux.do）在 Cloudflare 后面**按 TLS 指纹**拦截：
  `curl` 能拿到，Node/Python 的 HTTP 客户端一律 403。做法是用一个只跑 `curl` 的小容器
  定时抓下来落盘，再由 nginx 当静态文件伺服，阅读器去读那个本地地址。

## 自己写的 RSSHub 路由

清单里有几条用的是官方 RSSHub 没有的路由，都是自己写的：

| 路由 | 做什么 |
|---|---|
| `/cugb/news/:channel`、`/cugb/jwc/:channel` | 中国地质大学（北京）的新闻和教务通知——学校官网没有任何 RSS |
| `/nytimes/fulltext/:section` | 纽约时报付费全文。走 samizdat GraphQL 接口（开放 APQ），不需要跑浏览器 |
| `/caixin/channel/:column`、`/caixin/latest?fulltext=true` | 财新栏目页与付费全文 |

这几条依赖你自己的订阅 cookie，通过环境变量传给 RSSHub。**本仓库不含任何 cookie。**

## 翻译

英文源我用 [RSSBox](https://github.com/versun/rssbox)（原 RSS Translator）翻成繁体中文，
输出格式是「译文 || 原文」对照。翻译模型用的是 Gemini 的 flash-lite 系列——
这类活对模型要求不高，便宜的够用，但**一次要翻十几万字符的长文时有几个坑**，
见 [notes.md](notes.md)。

## 关于技术细节

这个仓库只放清单。搭建过程中真正卡过我的几个问题——
长文正文被解析库悄悄削掉三到五成、翻译成功但订阅地址一直返回空、
Cloudflare 面板给出过期的隧道凭据——单独记在 [notes.md](notes.md) 里。
都是实测结论，不是推断。
