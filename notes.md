> **暂时由 Claude 撰写，作者尚未过目。**

# RSSHub / RSSBox 踩过的坑

清单里的订阅大多跑在 [RSSHub](https://github.com/DIYgod/RSSHub) 和
[RSSBox](https://github.com/versun/rssbox) 上。下面是搭的过程中遇到的问题，均为实测结论。

---

## 1. RSSBox：长文正文会被解析库悄悄削掉三到五成

现象是某个 Substack 源「有时全有时不全」——每天的短简报完好，长文却缺一大块。
一开始以为是抓漏了，其实是抓回来之后被削的。

拿同一份 XML，把 feedparser 的 `SANITIZE_HTML` 开关各解析一次：

| 文章 | XML 里的原始长度 | sanitize=ON（= 库里存的） | sanitize=OFF | 损失 |
|---|---|---|---|---|
| 长文 A | 29,261 | **14,599** | 36,324 | 50% |
| 长文 B | 16,047 | **11,047** | 16,639 | 31% |
| 长文 C | 136,894 | **98,916** | 145,780 | 28% |
| 短讯 | 2,270 | 2,290 | 2,290 | ~0 |

**sanitize=ON 那一列与数据库里存的数字逐条完全一致**，据此定位。

feedparser 6.0.14 默认 `SANITIZE_HTML=True`，会把白名单之外的排版标签
**连同标签里的内容一起丢掉**。Substack 长文全是带说明的图片块和嵌入区块，所以损失惨重；
短讯是纯段落，毫发无伤。

```python
import feedparser
feedparser.SANITIZE_HTML = False
import feedparser.api          # 6.x 实际读取的是 api 子模块里的同名变量
feedparser.api.SANITIZE_HTML = False
```

排查时排除掉的两个方向，写下来省得别人重走：存正文的字段是 `TextField`（没有长度上限），
取正文的函数直接 `return content_item.value`（没有截断逻辑）。
**两处都不是原因——内容在解析阶段就已经没了。**

另外：改完之后**已经入库的旧条目不会自动补全**。RSSBox 抓取时只 `bulk_create` 新条目，
不更新已存在的，历史条目要按 guid 显式回填。

## 2. RSSBox：翻译成功了，订阅地址却一直返回空

最阴的一个。后台看一切正常——翻译任务成功、数据库里译文俱在、条数对得上，
但阅读器里那条订阅是空的。

根因是上游把一行代码注释掉了：翻译完成后本该把 `translation_status` 置回 `True`，
那一行被 `#` 掉了，于是状态永远停在 `None`。而缓存层的逻辑是：

```python
if feed.translation_status is None:
    # 翻译正在进行中，不更新缓存
    return cache.get(cache_key)      # 新 feed 没有旧缓存 → 返回 None → 空 feed
```

于是「翻译中」这个状态永远不会结束。取消那行注释即可。

## 3. RSSBox：译文撞上模型 token 上限时，整段已翻好的内容会被丢弃

上游只接受 `finish_reason == "stop"`，一旦输出撞上限（`"length"`）就当作失败，
`result_text` 保持空字符串。**十几万字符的长文几乎必然撞上限，结果是整篇不翻，
而不是翻出九成。** 改成 `length` 也收下、只记一条警告，更合理。

## 4. RSSBox：另外两处会让抓取静默失败的地方

- `feed.status` 裸访问：feedparser 在传输层失败（连接重置 / TLS 错误 / 超时）时
  **根本不设 `status` 属性**，裸访问抛 `AttributeError`——既把真正的错误盖掉，
  又跳过了本该接手的 httpx 兜底路径。用 `feed.get("status")`。
- `If-None-Match: None`：上游无条件设置这个 header，而 etag 在「上游不回 ETag」
  或「上次走了手动抓取路径」时是 `NULL`。httpx 对 `None` 的 header 值抛 `TypeError`，
  直接打死这次抓取。只在非空字符串时设置即可。

还有一处：解析成功但**零条目**时上游是裸 `return`，`fetch_status` 停在 `None`、日志不动——
**订阅就此静默死掉，任何地方都没有报错**。有一条订阅就是这样悄悄没的，很久之后才发现。

## 5. RSSHub：容器里的 Node 缺新根证书，表现只有一句 `fetch failed`

某个站点抓不动，报错只有没有上下文的 `fetch failed`。原因是它的中间证书由一个较新的
ISRG 根签发，而容器镜像里 Node 的根证书库还没收录这个根。

不用重建镜像。顺着中间证书的 AIA 扩展把根证书取下来，DER 转 PEM，挂进容器：

```yaml
environment:
  NODE_EXTRA_CA_CERTS: /etc/rsshub-certs/isrg-root.pem
volumes:
  - ./certs:/etc/rsshub-certs:ro
```

## 6. RSSBox：换机器时想保住订阅链接，只要显式指定 slug

RSSBox 的订阅地址是 `/rss/<slug>`，slug 在创建 feed 时生成一次、之后就是库里的普通字段。
**重建 feed 时显式指定原来的 slug**，阅读器那边一个字都不用改。

顺带澄清一个容易走弯路的地方：slug 和 `RSSBOX_SECRET_KEY` **没有绑定关系**——
那个 key 只在创建时参与一次运算。换机器时不需要为了保住 slug 去翻旧机器的 secret key。

## 7. 翻译模型：Gemini 的两个具体坑

- **模型列表里列着的，不代表能调用。** `gemini-2.5-flash-lite` 在
  `/v1beta/openai/models` 的返回里赫然在列，实际调用却是
  `404 This model is no longer available to new users`。以调用结果为准。
- **OpenAI 兼容端点不吃 `safety_settings`。** 三种写法实测全部 400。
  要设安全策略只能走 Gemini 原生 API。

## 8. 小内存机跑长文翻译：先确认 `vm.swappiness` 不是 0

严格说这不是 RSSBox 的问题，但翻译长文正是触发它的场景，所以记在这里。

一台 967MB 内存 + 2GB swap 的机器，从某天下午起几乎**每小时被 OOM 杀一次进程**，
而 swap 一个字节都没动过：

```
$ swapon --show
NAME      TYPE SIZE USED PRIO
/swapfile file   2G   0B   -2      ← 2GB，用了 0

$ cat /proc/sys/vm/swappiness
0
```

`vm.swappiness = 0` 让内核几乎不换出匿名页，于是内存吃紧时它选择杀进程，
而不是用那 2GB 交换空间。改掉之后跑一轮全量翻译（24 条源，最长的一条 1831 秒），
内存在 106~396MB 之间浮动、**swap 用到 342MB**，一次 OOM 都没有。
同样的负载在 `swappiness=0` 时的表现是 load average 冲到 61、整机卡死到只能去后台硬重启。

VPS 镜像里 `vm.swappiness=0` 并不罕见，很多「性能优化」教程也这么教。
内存充裕时它没问题，小内存机上它是个陷阱。
