# AI 资讯来源清单（定向采集入口）

> 用法：**先用 `web_fetch` 抓下面的 feed/API，再用 `web_search` 补盲区**。
> feed 是结构化的（自带日期与 URL），比搜索摘要可靠且零成本；
> `web_search` 只在 feed 没覆盖到主题、或需要交叉核对时使用。
> 通用规则：返回内容里**自带日期字段的，直接读字符串比对时间窗**，
> 不要自己换算 Unix 时间戳——模型算纪元秒很容易错几天。

## 一手 · 论文

### arXiv cs.AI（Atom XML，免 key）

```
https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=20
```

- 每条含 `<title>` `<published>`（ISO 8601）`<summary>` `<id>`（即 abs 链接）；
- 按 `published` 是否落在时间窗内过滤，超窗的直接丢弃；
- 主题偏移时换检索词：`search_query=all:%22large+language+model%22`、`cat:cs.CL`、`cat:cs.LG`；
- 本机出国走代理，**偶发瞬时 502 是代理抖动不是接口挂了**——`web_fetch` 会自动重试一次，
  若仍失败等几秒重试一次，再失败才跳过并说明；
- `export.arxiv.org` 持续失败时的兜底：主站最新列表
  `https://arxiv.org/list/cs.AI/recent`（HTML，含标题/作者/提交日期），
  或 `https://arxiv.org/list/cs.CL/recent`。

### Hugging Face（Papers / Daily Papers / Blog / 模型首发）

今天的 AI 前沿越来越「代码先行」。HF 的 **Daily Papers** 由社区投票筛选当日值得关注的
论文，并直接关联模型、数据集和 Demo Space；几乎所有主流开源模型（Llama、Mistral、
Qwen、DeepSeek 等）都在 HF 首发，**官方 Blog 和模型页是追踪开源动态最直接的途径**。

| 内容 | 入口 |
|---|---|
| Daily Papers（某天） | `https://huggingface.co/papers?date=YYYY-MM-DD`（HTML） |
| Daily Papers（JSON API） | `https://huggingface.co/api/daily_papers?date=YYYY-MM-DD` |
| 热门论文榜 | `https://huggingface.co/papers/trending` |
| 官方 Blog | `https://huggingface.co/blog`（feed 尝试 `https://huggingface.co/blog/feed.xml`） |
| 模型首发追踪 | `https://huggingface.co/api/models?sort=createdAt&direction=-1&limit=20`（JSON，按创建时间倒序） |

> ⚠️ **本机出口实测（2026-10-25）：代理对 huggingface.co 整域返回 502**，沙箱内外一致，
> 直连超时（机器无国际直连路由）。入口本身在浏览器里是可用的——如果你终端起的服务
> 也全部 502，说明出口代理同样拦了这个域：**全部跳过并在报告里说明，不要用记忆补**；
> 换网络/换代理后这些入口无需改代码即可恢复。

### Papers with Code（已由 Hugging Face 承接）

原 PWC 于 2025 年关停，核心理念——**论文 ↔ 代码 ↔ 排行榜的关联**——由 HF 延续：

- 旧域名 `https://paperswithcode.com/` 及其全部路径（含 `/sota`）**302 跳转**
  到 `https://huggingface.co/papers/trending`（已实测验证）；
- 找某篇论文的官方实现、社区复现：进 HF 论文页（`huggingface.co/papers/<id>`），
  页面直接关联 "Models citing this paper / Datasets / Spaces"；
- SOTA 位置：看论文页与其引用的 model 卡上的 benchmark 结果，不再有独立的 PWC 榜单页。

对工程师和需要复现的研究者，这是从「读论文」到「跑起来」的桥梁；对简报而言，
"PWC 已并入 HF" 本身也是一条值得记录的生态变化。


## 一手 · 厂商新闻室

| 厂商 | 入口 | 注意 |
|---|---|---|
| Anthropic | `https://www.anthropic.com/news` | 列表带日期；页面顶部轮播的日期可能与条目不符，以条目自身日期为准 |
| OpenAI | `https://openai.com/news/rss.xml`（RSS） | **HTML 页 `openai.com/news/` 有 Cloudflare 防护，脚本抓必 403，不要用**。RSS 按 pubDate 从新到旧、1300+ 条，靠日期过滤窗口 |
| Google DeepMind | `https://deepmind.google/discover/blog/` | 部分条目跳转到 blog.google，日期可能在落地页 |

### max_chars 怎么给

feed/API 返回的是原始 XML/JSON，**别传小值**——`max_chars=120` 会被截成 500 字符的残片，根本读不出条目。建议：arXiv `max_results=10~20` 配 `max_chars=16000`；HN 配 `max_chars=12000`；OpenAI RSS 条目多，靠截断取最前面（最新）的部分即可。不确定长度时宁大勿小，截断有明确提示。

## 二手 · 社区风向

### Hacker News（JSON，免 key）

```
https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story&hitsPerPage=50
```

- `hits[]` 含 `title / url / created_at / points / num_comments`；
- 按 `created_at` 字符串比对时间窗过滤，不要用 `numericFilters` 手算时间戳；
- `query=AI` 噪声大（会命中 URL 里带 ai 的无关帖），以 `title` 是否真的相关为准；
- 需要热度视角时换 `search?query=AI&tags=story`（按 points 排序的历史热门）。

### Reddit r/MachineLearning（Atom）

```
https://www.reddit.com/r/MachineLearning/.rss        （常被拒）
https://old.reddit.com/r/MachineLearning/.rss        （备选）
```

- 本环境实测两个地址都 fetch failed；失败即跳过并说明。

## 使用顺序

1. arXiv（研究）→ 2. 三家新闻室 + HF（产品/公司/开源首发）→ 3. HN（社区风向）→ 4. Reddit / PWC 关联页（可用则用）→ 5. `web_search` 补以上都没覆盖的主题。
