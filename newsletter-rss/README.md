# 邮件 Newsletter 转 RSS

Worker 把收到的邮件解析并存入 KV，以 RSS 输出。源码使用 `postal-mime`，依赖版本由 package-lock.json 固定。

1. 安装依赖：`npm ci`。
2. 在自己的 Cloudflare 账号创建 KV namespace，把 ID 填到 `wrangler.jsonc` 中 `ITEMS` 的占位符；参考 [Wrangler 配置文档](https://developers.cloudflare.com/workers/wrangler/configuration/)。
3. 设置 `FEED_TOKEN` secret，避免自己的邮件内容公开可读；不设置此项时输出不要求令牌。
4. 用 `npm run deploy` 部署到自己的账号。
5. 在自己的 Email Routing 域名把指定收件地址路由到此 Worker，并让 Newsletter 发送到这些地址。

如收件地址为 `moneystuff@example.com`，对应输出 `/feed/moneystuff.xml?token=<自己的令牌>`；`/feed.xml` 汇总全部邮箱。替换 OPML 的 Worker 主机和令牌后再导入。

目前每个邮箱输出最近 50 条，KV 邮件保存一年。不包含账号资源 ID、真实收件地址或密钥。部署、绑定域名和接收真实邮件均由使用者自行配置。
