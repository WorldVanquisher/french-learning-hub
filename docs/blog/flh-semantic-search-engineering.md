# 给法语学习笔记加语义搜索：模型只负责生成向量

> 回顾性草稿，2026-10-12 整理，尚未发布。文中引用的报告日期为 2026-10-10 至
> 2026-10-12。英文版：[flh-semantic-search-engineering.en.md](flh-semantic-search-engineering.en.md)。

French Learning Hub（FLH）是我的个人法语学习服务：我把学习中遇到的问题记下来，
系统提取知识单元，再由我把它们整理成持久的 Concept（例如"depuis 表示仍在持续的事"）。
代码主要由 AI 编码代理（Claude Code 和 Codex）在我的任务合同和审查下实现；
GPU 上的诊断和 NAS 上的验收由我本人执行。本文区分四类证据：**事实**（代码与
schema）、**作者测试**（实现代理自己跑的测试）、**独立测试**（另一个代理做的验收）
和**人工观察**（我本人执行、代理未复核的结果）。

## 一、为什么关键字搜索不够

Knowledge Library 原有的搜索是关键字前缀匹配，不做词干、同义词或语义。
问题在于：要找的往往是一个意思，可能用英文描述，而 Concept 的标识是法语语法点。
在 FLH-060 演示的真实模型运行里（作者测试，合成数据），关键字 `weather` 返回 0 条；
语义查询 "what the weather was like when I was a child" 把"imparfait 表示过去的背景和习惯"
排在第一位。关键字 `miss` 能命中"tu me manques"，只是因为标题里恰好有 miss 这个词。

## 二、职责划分：权威、生成器、索引

```text
SQLite（权威：Concept + 向量缓存 + 发布指针）
   │  semantic-index build/sync/rebuild（显式命令）
   ├──> E5 服务（Windows RTX 4070，经 Tailscale）只把文本变成向量
   └──> Qdrant（可丢弃、可从 SQLite 重建的索引）
搜索：查询向量 → Qdrant 候选 → 逐条回到 SQLite 复核
```

- **SQLite 是唯一权威。** 搜索结果都要回到 SQLite 复核，缺失、过期或来自其他模型的命中直接丢弃，
  不做替换，也不回退到关键字搜索。
- **模型只是向量生成器。** E5 区分角色：查询加 `query: ` 前缀，Concept 文档加 `passage: ` 前缀。
  前缀只由版本化的表示类型决定（`concept_search_query_v2` 或 `concept_embedding_text_v1`），
  不从文本内容推断。
- **部署身份不可变。** `EMBEDDING_MODEL_ID` 是完整的部署 ID：模型版本、角色合同、
  dtype、批处理策略和 manifest 摘要。任何会改变向量的配置都会产生新身份、新索引空间和新缓存，
  两种模型的向量不会混在一起。

## 三、独立验收发现的问题

第一版（FLH-040）的作者测试都通过了，但独立验收（FLH-041）用两个 SQLite 连接复现了一个缺陷：
旧的索引运行在失去所有权后，仍能覆盖、清空新运行已完成的记账，因为只有最后的
"完成"一步做了所有权检查（独立测试）。

FLH-042 的修复是：

- **租约。** 每个索引空间同一时间只允许一个运行持有 SQLite 租约，每次记账写入都要验证租约。
- **私有集合。** 每个运行写自己的 Qdrant 集合。
- **单点发布。** 发布只是一次受租约保护的指针切换。

第二轮独立验收（FLH-043）模拟了"写入已生效但确认丢失"：Qdrant 里有四个私有点，
SQLite 只记了两行。结果是命令退出 1、旧发布不变、恢复时零次嵌入调用，这项通过了。
同一轮还发现两个缺陷：

- 搜索恰好遇到发布切换时，会把健康的新发布报告成"未构建"；
- 健康的 `sync` 不会清理之前删除失败的旧集合。

FLH-044 修复了这两项。此后，搜索遇到发布切换最多重试一次；连续两次切换就明确报错。

这些设计的意义在于：Qdrant 和 SQLite 之间没有跨库事务，我也不声称有。能做到的是：
任何运行只写自己的集合，搜索只读已发布的指针，"健康"只来自对每个点的 ID、载荷和向量的
完整核对，而不是点的数量。`status` 把"记录的历史"和"当下核对的健康"分开显示。

## 四、显式索引与持久缓存

文档向量缓存在 SQLite 里，键为（内容哈希, 表示, 模型身份, 维度）。只有 `semantic-index`
命令会调用嵌入服务，搜索只嵌入一条查询，服务启动时不调用。FLH-060 演示在服务前加了一个计数网关，
分别统计查询和文档，并在发送前扣除预算。

实现代理在 macOS 上对真实 E5 服务做了一次有预算的运行（作者测试），结果如下：

- 用掉 9 次 POST、22 个位置：建索引 2 次 POST、15 个文档位置；7 次搜索各 1 个查询位置；
- 关键字搜索 0 次调用；
- 重启后 `sync` 0 次调用，`rebuild` 复用 15 个缓存向量、0 次调用；
- 服务端 `/metrics` 的增量与网关计数一致。

模拟服务离线时，语义搜索返回 502，关键字搜索和索引状态照常工作；恢复后无需重建。

我本人在 NAS 上重做了这套演示（人工观察）：18/18 项机械检查通过，同样是 9 次 POST、
22 个位置，`sync`/`rebuild` 零调用，重启后数据仍在，离线和恢复行为符合预期。
浏览器交互没有测试。

## 五、GPU、Tailscale 与 float16

E5 服务跑在我的 Windows 笔记本 RTX 4070 上，NAS 通过 Tailscale 访问它。嵌入服务在另一台机器上，
随时可能不在线，所以"服务不可用"必须是一个被明确处理的状态，而不是隐藏的回退。
FLH-058 的一次探索运行（独立测试）发现：同一文档在不同批次形状中，有 112 个重复向量超出了预先声明的容差。
报告认为 float16 加上按批填充是一个合理解释，但没有确认原因。

于是 FLH-059 写了一个有界诊断：6 种配置，每种 456 个位置，判定规则事先登记。
我在那台 GPU 上运行了它（人工观察）：

- float16 `dynamic_v1`：359 次容差失败，32 个排序中有 4 个 top-5 顺序变化；
- float16 `singleton_v1`（每条输入单独编码）：424/424 个比较向量逐位相等，零失败。

所以现在用的是 singleton 部署。这只说明了这台机器、这组输入上的情况，不代表普遍的确定性。
我也没有做任何 GPU 性能基准。

## 六、检索评估：数字和它的边界

FLH-058 用现有 Go 检索器跑同一个冻结夹具（48 个单目标查询，24 个 Concept），
Recall@5 结果如下：

| 检索器 | Recall@5 |
| --- | --- |
| E5 | **44/48**（MRR@5 0.653） |
| BM25 | 32/48 |
| 加权词法 | 30/48 |
| 精确签名 | 0/48 |

精确签名得 0 是结构性的：这个夹具里没有可能匹配的签名。

这些数字的局限必须一起说：

- 标签是作者提出、**未经人工审核**的合成提案。
- 每个 Concept 对应一对法语和英语改写，有 7 个例句在成对查询中重复出现。
- 留出集与开发集在数量、否定、倒装等构造上语义相关，而且作者见过全部提案，
  所以它不是盲测，也不能说明泛化。
- 没有做显著性检验。
- top-1 上 E5 对加权词法丢了 4 题、对 BM25 丢了 5 题。
- 4 个"无匹配"查询仍各返回 5 条结果，例如"PostgreSQL 备份"排出了 imparfait，分数 0.846。

## 七、一个诚实的失败

在 FLH-060 的真实运行中（作者测试，原始证据在仓库外），"saying I don't do something anymore"
排第一的是"tu me manques"（0.8531），按演示设计意图对应的"ne … plus"排第二（0.8426）。所有分数都挤在
0.81–0.87 之间。余弦分数不是概率，不是相关性判定，也不代表"同一 Concept"。
它只是排序依据，而这次的排序与设计意图不符。演示里的搜索句只是示例输入，不是标签，
所以这是一个观察，不是一次打分。

## 八、还没做的

- 浏览器端验收；
- 经人工审核的相关性标注，以及重新分组、去相关的留出集；
- 任何新的模型实验都需要单独授权。

这不是 RAG，没有训练模型，也不会自动把单元归入 Concept：
SAME 判定仍然只来自人工。

## 来源

- 代码：[semantic_index.go](https://github.com/WorldVanquisher/french-learning-hub/blob/main/internal/application/semantic_index.go)、
  [semantic_search.go](https://github.com/WorldVanquisher/french-learning-hub/blob/main/internal/application/semantic_search.go)、
  [migrations/010](https://github.com/WorldVanquisher/french-learning-hub/blob/main/migrations/010_semantic_index.sql)、
  [migrations/011](https://github.com/WorldVanquisher/french-learning-hub/blob/main/migrations/011_semantic_index_runs.sql)、
  [cmd/semantic-index](https://github.com/WorldVanquisher/french-learning-hub/tree/main/cmd/semantic-index)、
  [E5 服务](https://github.com/WorldVanquisher/french-learning-hub/tree/main/tools/embedding/e5)、
  [FLH-060 演示](https://github.com/WorldVanquisher/french-learning-hub/tree/main/scripts/demo/flh060)
- 文档：[SEMANTIC_SEARCH.md](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/SEMANTIC_SEARCH.md)
- 报告：
  [FLH-041](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-041-vector-search-acceptance.md)、
  [FLH-043](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-043-index-consistency-acceptance.md)、
  [FLH-045 计划](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/plans/FLH-045-retrieval-evaluation.md)、
  [FLH-049](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-049-evaluation-and-ci.md)、
  [FLH-058](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-058-real-e5-exploration.md)、
  [FLH-059](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/plans/FLH-059-e5-reproducibility.md)、
  [FLH-060](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-060-semantic-demo.md)、
  [FLH-061](https://github.com/WorldVanquisher/french-learning-hub/blob/main/docs/validation/FLH-061-nas-semantic-demo.md)

真实运行的原始证据（逐条请求、计数器、诊断输出）保存在仓库之外。
