# 凭据配置说明

本说明对应仓库中的环境变量、Cookie 读取代码和持久化位置。先选择需要的模块，再准备相应凭据；没有用到的来源保持空值。真实值在自己的电脑或服务器上填写，无需提供给公开仓库或 Agent 对话。

## 配置入口

在仓库根目录执行：

```sh
cp deploy/rss-stack/.env.example deploy/rss-stack/.env
chmod 600 deploy/rss-stack/.env
```

用本地编辑器填写 `.env`。此文件被 Git 忽略；不要使用会把全部环境变量打印到终端的检查方式。配置校验用 `docker compose config --quiet`，不带 `--quiet` 的完整输出可能展开凭据。

| 配置 | 内容与用途 |
| --- | --- |
| `COMPOSE_PROJECT_NAME` | 默认 `rss`，决定容器和卷名前缀；已有数据时不要随意更改 |
| `COMPOSE_FILE` | 启用的 Compose 文件；默认不启用可选授权适配器 |
| `RSSBOX_SITE_URL` | 自己的阅读入口，例如本机 HTTP 地址或自己的 HTTPS 域名；Compose 同时用于可信来源配置 |
| `BASE_URL` | 模板保留的兼容字段；当前 Compose 不读取它作为服务地址，不替代 `RSSBOX_SITE_URL` 或自动配置域名 |

在 Docker 中使用的内部源地址通常是 `http://rsshub:1200` 和 `http://feed-proxy/ext/...`，阅读器则使用自己的外部入口。

## 自己生成的密钥

分别运行 `openssl rand -hex 32`，生成独立的 `RSSBOX_SECRET_KEY` 与 `RSSHUB_ACCESS_KEY`，填入 `.env` 的同名字段，不使用示例占位符。

- `RSSBOX_SECRET_KEY`：Django 应用密钥，不是管理员登录密码；更换会影响已有登录会话。
- `RSSHUB_ACCESS_KEY`：自己的 RSSHub 访问密钥，用于路由 URL 的 `?key=...`。带这个参数的完整订阅地址也要保密。
- `RSS_PLAN_BRIDGE_KEY`：只有启用可选授权适配器时才生成，独立于上面两个值，用于容器内服务间认证。

管理员账号按所部署 RSSBox 版本的首次启动提示或上游管理流程初始化；不要假设仓库包含可用的默认管理员密码。自己的密码放在密码管理器中。

## 会员网站 Cookie

通用步骤：在自己的浏览器登录已订阅的网站，打开一篇自己能阅读的文章；打开开发者工具的 Network，重新加载，查看发给该网站的请求中的 `Cookie` 请求头。也可在 Application / Storage 的 Cookies 中查看指定字段；HttpOnly 字段应通过开发者工具查看，不要求用页面 JavaScript 读取。

只把该来源需要的值写入 `.env`，不要复制无关域名的 Cookie。Cookie 中可能含 `#`、空格、分号等字符，使用 dotenv 引号保存；若含特殊字符，依据 Docker Compose dotenv 规则检查解析，不把完整值输出到聊天。读取的是自己的登录会话，账号订阅权限仍由网站决定。

| `.env` 字段 | 需要的格式与取得位置 |
| --- | --- |
| `CAIXIN_COOKIE` | 财新登录请求的 Cookie 头，包含 `SA_USER_UID` 等实际会话字段；本库用它构造全文认证请求。若桌面端会话不适用，检查自己在移动网页端登录后的实际文章请求 |
| `NYT_S_COOKIE` | 纽约时报会话 Cookie 头，例如 `NYT-S=<自己的值>`；本库直接将此变量作为 HTTP Cookie 头，不能只填一个没有字段名的裸值 |
| `TWITTER_AUTH_TOKEN` | 自己登录 X 后 Cookies 中 `auth_token` 的值；提供给 RSSHub 的 Twitter 路由，是否可用还取决于上游接口与限制 |
| `INITIUM_MEMBER_COOKIE` | 端传媒来源需要时填写自己的会话 Cookie；这是传给 RSSHub 的可选字段，不是本库所有路由的共同要求 |
| `SINOCISM_COOKIE` | 自己登录 Sinocism 后的 Cookie 头，推荐明确写成 `substack.sid=<自己的值>`，或完整的该站 Cookie 头；按实际会话检查有效字段 |
| `THEDIFF_COOKIE` | 自己登录 The Diff 后的 `ghost-members-ssr` 值，或包含该字段的完整 Cookie 头 |
| `THEDIFF_COOKIE_SIG` | 同一次 The Diff 登录会话的 `ghost-members-ssr.sig` 值；若已包含在上一项完整头中则无需重复 |

示例只表示格式，不包含可用会话：

```dotenv
CAIXIN_COOKIE="SA_USER_UID=<自己的值>; <其他必要字段>"
NYT_S_COOKIE="NYT-S=<自己的值>"
SINOCISM_COOKIE="substack.sid=<自己的值>"
THEDIFF_COOKIE="ghost-members-ssr=<自己的值>"
THEDIFF_COOKIE_SIG="<同一次会话的签名值>"
```

Cookie 失效时，重新登录、更新 `.env`，然后在 `deploy/rss-stack` 执行 `docker compose up -d`，让 Compose 重建受环境变量变化影响的容器。单纯 `restart` 不会把新 `.env` 值注入已创建的容器。先检查一个来源是否恢复全文，再恢复批量更新；没有 Cookie 时不能把预览当作已获得全文。

## 模型接口与可选适配器

通用翻译：从自己选择的模型服务商账号控制台创建 API Key，在 RSSBox 管理界面配置接口 URL、Key、模型和参数，再把这个翻译器分配给订阅。该配置保存于 RSSBox 数据库，即 `rss_rssbox-data` 卷中的 `db.sqlite3`（项目名使用默认 `rss` 时）。数据库和数据库备份同样属于私有材料。

`TRANSLATION_FALLBACK_OPENAI_AGENT_ID` 是自己数据库里备用 Agent 的编号，不是 API Key；默认空值。只在明确希望使用备用翻译器时填写自己的编号，并验证相应服务的计费方式。

可选 `chatgpt_plan.py` 适配器不是通用部署的前提。本库保留的是具体实现，授权成功依赖客户端注册、账号权限与接口支持；不能把持有某类订阅等同于必然可用。不支持时使用自己已有的兼容 API 翻译，或保持原文模式。

如果确认自己的环境支持适配器，先查看 `python chatgpt_plan.py --help`，在自己的环境安装 [适配器依赖](../deploy/rss-stack/chatgpt-plan/requirements.txt)，通过它的 `login` 模式完成用户授权，将文件路径指定为私有的 `chatgpt-plan-private/credentials.json`。远程授权还需正确转发其回调端口。父目录权限 `700`、文件权限 `600`；应用会按这些权限写入。只有授权与 `probe` 成功后才把 `docker-compose.chatgpt-plan.yml` 加入自己的 `COMPOSE_FILE`。不从浏览器或其他应用配置中抽取令牌来替代授权。

## Cloudflare Tunnel（可选）

在自己的 Cloudflare 账号中创建远程管理的 Tunnel，按照连接器安装步骤取得此 Tunnel 的运行 token，将 token 本身填入 `.env` 的 `TUNNEL_TOKEN`；不要把整条 Docker 安装命令填进去。流程参考 [Cloudflare 官方创建说明](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)。

自己的阅读域名指向 `http://feed-proxy:80`，自己的 RSSHub 域名指向 `http://rsshub:1200`。阅读出口仍只放行 `/rss/*` 和 `/ext/*`，管理界面走 SSH。启动方式见 [部署说明](../deploy/rss-stack/README.md#5-可选-tunnel)。Tunnel token 与账号级 API token 用途不同，不相互替换。

## Newsletter Worker（可选）

此模块只需要自己的 Cloudflare 账号、KV 和用于收信的域名，不需要 Docker 环境里的会员 Cookie。

- KV namespace ID：由自己的账号创建，填到 `newsletter-rss/wrangler.jsonc` 中 `ITEMS` 的 ID 占位符；它是资源标识，不是访问密钥。
- `FEED_TOKEN`：另行生成一个随机值，在 `newsletter-rss` 目录执行 `npx wrangler secret put FEED_TOKEN`，按交互提示输入。真实值保存到 Worker secret，不写进配置文件。本地调试可用被 Git 忽略的 `.dev.vars`，详见 [官方 secret 文档](https://developers.cloudflare.com/workers/configuration/secrets/)。
- Cloudflare 登录或 API token：用于 Wrangler 访问自己的账号，交给 Wrangler 自己的登录和凭据管理，不填到 RSS 的 `.env`。
- Email Routing：把自己指定的收件地址绑定到这个 Worker；收件地址的本地部分决定 `/feed/<邮箱名>.xml`。

阅读地址是自己 Worker 的 `https://<自己的主机>/feed/<邮箱名>.xml?token=<自己的FEED_TOKEN>`。未设置 `FEED_TOKEN` 时本实现允许读取输出，因此私人的邮件订阅要设置令牌。带令牌的链接在阅读器、本地私有 OPML 和必要的服务配置中保存，不提交参考清单。

## 私有材料总表

| 位置 | 保存内容 | 更新/备份方式 |
| --- | --- | --- |
| `deploy/rss-stack/.env` | Django 密钥、RSSHub 密钥、来源 Cookie、可选 Tunnel 与桥接密钥 | 自己编辑；随私有配置备份 |
| RSSBox 的 `rssbox-data` 卷 | 数据库、模型接口与 API Key、订阅及文章译文 | 管理界面更新；一致性数据库备份 |
| `chatgpt-plan-private/credentials.json` | 可选适配器授权与刷新凭据 | 显式授权流程；私有配置备份 |
| Cloudflare Worker secrets | 邮件输出 `FEED_TOKEN` | Wrangler secret 管理，不写 Git |
| Cloudflare KV | 收到的 Newsletter 正文和元数据 | 单独规划备份；不在 Docker 备份中 |
| 自己的阅读器/私有 OPML | 可能带访问密钥的完整订阅地址 | 私有保存，不覆盖公共 `feeds.opml` |
| 自己的备份目录 | 上述数据库、配置、缓存与镜像 | 保存在私人存储，参见 [备份说明](../deploy/rss-stack/backup/README.md) |

不要把已填好令牌的 OPML 保存成被跟踪的 `feeds.opml` 后提交；本地私人版本可命名为被忽略的 `feeds.private.opml`。备份归档虽然包含可恢复系统所需材料，也会包含真实凭据与私人正文。
