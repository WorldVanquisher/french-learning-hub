# 法语学习应用

[English](README.md)

这是一个使用 Go 和 SQLite 构建的小型法语学习服务。它保存学习者提出的原始问题及其上下文，并把分析、人工反馈、知识抽取和 Concept 标注作为独立、可追溯的数据层保存。

核心原则：

- 原始输入始终是真实来源，不会被 AI 生成内容覆盖。
- 分析、反馈、抽取和标注在需要保留历史时采用版本化或只追加记录。
- `KnowledgeUnit` 是不可变的抽取证据；`KnowledgeConcept` 才是长期学习身份。
- `unit_concept_memberships` 是 CURRENT SAME 的唯一当前权威。
- 后端、应用层、领域层和 SQLite 存储层保持分离。
- 默认规则分析器完全在本地运行；OpenAI 分析和知识抽取必须显式启用。
- 标注 Inspector 和 Dataset 都是只读视图，不会创建新的标注权威。

详细设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，前端运行说明见 [web/README.md](web/README.md)。

## 当前能力

项目目前支持：

1. 保存学习条目及其原始上下文。
2. 为同一条目追加多个版本化分析。
3. 追加接受、纠正或拒绝分析的人工反馈。
4. 根据最新反馈只读计算当前有效分析。
5. 查询、汇总和 JSONL 导出跨条目的学习清单。
6. 原子、幂等地导入 `learning_capture_v1` 结构化学习记录。
7. 使用 `cmd/capture` 从文件或标准输入提交 Capture。
8. 从条目的当前有效解释中显式抽取不可变 `KnowledgeUnit`。
9. 通过固定规则和人工覆盖计算 Admission 状态。
10. 使用持久化 `KnowledgeConcept`、保守的精确签名解析器和人工标注工作台管理 Concept 身份。
11. 只读查看 M11-A Effective Annotation 状态。
12. 通过 JSON 或 NDJSON 获取 `concept_annotation_dataset_v1` 当前快照。

这不是最终消费者产品，也不是间隔重复 Review Engine、掌握度系统或 ML 解析器。

## 环境要求

- Go 1.26 或更高版本（使用 `net/http` 基于方法的路由）
- 不需要 CGO；SQLite 使用纯 Go 的 `modernc.org/sqlite` 驱动
- 若运行标注前端，需要 Node.js/npm

## 目录结构

```text
cmd/server               服务端入口和优雅关闭
cmd/capture              向 POST /captures 提交文件或 stdin 的轻量 CLI
internal/domain          领域实体、验证、仓库与 Analyzer/Extractor 接口
internal/application     应用用例和只读投影
internal/analyzer        本地规则 Analyzer 与可选 OpenAI Analyzer
internal/extractor       可选 OpenAI Knowledge Extractor
internal/captureclient   Capture CLI 使用的 HTTP 客户端
internal/storage/sqlite  SQLite 仓库与迁移执行器
internal/transport/http  HTTP DTO、Handler 和路由
internal/config          环境变量配置
migrations               嵌入式 SQL 迁移
examples/captures        learning_capture_v1 示例
web                      React + Vite + TypeScript 标注工作台
```

## 配置

配置来自环境变量。默认配置可直接启动本地服务：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8080` | HTTP 监听端口 |
| `DB_PATH` | `data/app.db` | SQLite 文件路径 |
| `HTTP_READ_TIMEOUT` | `10` | 读取超时（秒） |
| `HTTP_WRITE_TIMEOUT` | `10` | 写入超时（秒） |
| `AI_PROVIDER` | `rule-based` | `rule-based` 或 `openai` |
| `EXTRACTOR_PROVIDER` | `disabled` | `disabled` 或 `openai` |
| `OPENAI_API_KEY` | 无 | 启用 OpenAI 时必需；不会被记录 |
| `OPENAI_MODEL` | 无 | 启用 OpenAI 时必需 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API 基础地址 |
| `OPENAI_TIMEOUT` | `8` | 单次 Provider 请求超时（秒） |

`AI_PROVIDER` 和 `EXTRACTOR_PROVIDER` 相互独立。例如，可以使用本地规则分析器，同时单独启用 OpenAI 知识抽取器。

### Analyzer

- `rule-based`：默认、本地、确定性、无 API 费用。命名规则引擎会记录命中的规则、不确定性原因和启发式置信度。`NeedsAI` 只是一项建议，不会自动调用 OpenAI。
- `openai`：显式启用后调用 OpenAI Responses API。每条分析都会保存 `openai:<model>:fr_l2_taxonomy_v1` 来源信息。

配置错误会阻止服务启动，不会静默回退。Provider 超时返回 `504`，其他 Provider 故障返回 `502`，失败时不会写入分析记录。

## 启动

```bash
make run
# 或
go run ./cmd/server
```

首次启动时会自动创建数据库目录、数据库文件并执行迁移。默认监听 `http://localhost:8080`。

## 基础 API

### 健康检查

```bash
curl localhost:8080/healthz
# {"status":"ok"}
```

### 学习条目

创建条目：

```bash
curl -X POST localhost:8080/entries \
  -H 'Content-Type: application/json' \
  -d '{"original_input":"Je suis fatigué","original_context":"给朋友发消息"}'
```

读取和列出条目：

```bash
curl localhost:8080/entries/1
curl 'localhost:8080/entries?limit=20'
```

`original_input` 必填。未知 JSON 字段和空输入返回 `400`。

### 分析

```bash
curl -X POST localhost:8080/entries/1/analysis
curl localhost:8080/entries/1/analyses
```

分析使用共享的 `fr_l2_taxonomy_v1` 分类词表：

```text
vocabulary, grammar, morphology, orthography, pronunciation,
pragmatics, discourse, comprehension, translation, mixed, other
```

重复分析同一条目会追加版本 2、3 等，不会修改旧版本。

### 人工反馈和有效分析

反馈状态为 `accepted`、`corrected` 或 `rejected`：

```bash
curl -X POST localhost:8080/analyses/1/feedback \
  -H 'Content-Type: application/json' \
  -d '{"status":"accepted","user_note":"正确"}'

curl -X POST localhost:8080/analyses/1/feedback \
  -H 'Content-Type: application/json' \
  -d '{"status":"corrected","corrected_category":"grammar","corrected_explanation":"manger 的现在时"}'
```

```bash
curl localhost:8080/analyses/1/feedback
curl localhost:8080/analyses/1/effective
```

有效分析是只读投影。只有最新反馈（按 `created_at`、再按 `id`）决定当前状态：

- `unreviewed`：没有反馈，当前值等于原分析。
- `accepted`：保留原分析。
- `corrected`：存在的纠正字段覆盖原字段。
- `rejected`：`effective` 为 `null`，但原分析仍保留供审计。

## 学习清单

学习清单为每个条目选择最新分析及其最新反馈，并形成一个只读当前行。它不会写入数据，也不会调用 AI。

```bash
curl 'localhost:8080/learning-records?state=corrected&limit=50'
curl localhost:8080/learning-records/summary
curl 'localhost:8080/learning-records/export?state=accepted'
```

支持的状态：`unanalyzed`、`unreviewed`、`accepted`、`corrected`、`rejected`。列表支持 `state`、有效 `category`、`analyzer`、`limit` 和 `before_entry_id` 过滤/分页。

导出端点返回 `application/x-ndjson; charset=utf-8`，每行一个记录，不包含外层数组。

## 结构化 Capture 导入

`POST /captures` 接收 `learning_capture_v1` 文档，把在其他地方完成的法语讨论导入为普通学习条目和可选的版本 1 分析。

它不是聊天机器人：不会联系 ChatGPT 或其他模型，不抓取网页或对话，也不解析 HTML/Markdown。服务只保存客户端显式提供的结构化字段。

```bash
curl -X POST localhost:8080/captures \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version":"learning_capture_v1",
    "capture_id":"manual-2026-08-04-001",
    "source":"manual",
    "original_input":"Comment dit-on apple ?",
    "original_context":"词汇查询",
    "discussion_summary":"询问 apple 的法语表达。"
  }'
```

导入按 `capture_id` 幂等：

- 新 ID：`201 Created`，`created: true`。
- 相同 ID、相同规范化内容：`200 OK`，`created: false`，不新增记录。
- 相同 ID、不同内容：`409 Conflict`，不会覆盖已有数据。

读取 Capture 元数据：

```bash
curl localhost:8080/captures/manual-2026-08-04-001
```

`source` 只是描述性元数据，不授予信任。该服务与其他端点一样没有内置认证，不应在没有外部认证保护的情况下直接暴露给不可信网络。

## Capture CLI

`cmd/capture` 是纯传输客户端。它不会分析、规范化、重写或指纹化负载，也不会调用模型。

```bash
# 从文件读取
go run ./cmd/capture -file examples/captures/manual-example.json

# 从 stdin 读取
go run ./cmd/capture < examples/captures/manual-example.json
```

后端地址优先级：

```text
-url 参数  ->  FRENCH_HUB_URL  ->  http://localhost:8080
```

幂等重放也返回成功退出码。冲突、验证错误或服务端错误会使用非零退出码和安全的简短错误消息，不会输出学习内容或凭据。

## Knowledge Extraction 与 Admission

Knowledge Extraction 把一个学习交互显式转换为零个或多个不可变 `KnowledgeUnit`。零个 Unit 是合法结果。抽取只在调用下列端点时发生，不会因创建条目、分析、反馈或 Capture 而自动运行。

条目只有在当前分析状态为 `unreviewed`、`accepted` 或 `corrected` 时才可抽取；`unanalyzed` 和 `rejected` 返回 `409`。

```bash
curl -sS -X POST http://localhost:8080/entries/1/extractions
curl -sS http://localhost:8080/entries/1/extractions
curl -sS http://localhost:8080/extractions/10
```

每次成功抽取都会追加一个按条目版本化的 `KnowledgeExtraction`，保存来源 analysis、feedback、extractor 和时间戳。后续分析或反馈不会修改旧 Extraction。

知识类型使用独立的 `fr_l2_knowledge_v1` 词表：

```text
vocabulary, grammar, morphology, orthography,
pronunciation, usage, expression
```

### Extractor

唯一语义 Extractor 是显式启用的 OpenAI Extractor：

```bash
export EXTRACTOR_PROVIDER=openai
export OPENAI_API_KEY=replace-with-your-key
export OPENAI_MODEL=replace-with-your-model
go run ./cmd/server
```

默认 `EXTRACTOR_PROVIDER=disabled`；此时服务仍可运行，但抽取端点返回 `503`。没有规则式语义 Extractor，也没有静默回退。

### Admission

固定规则集 `knowledge_admission_v1` 为每个 Unit 生成：

- `active`：默认进入活动学习池。
- `suppressed`：例如同一 Extraction 中同 kind、同规范化 canonical 的后续精确重复项。
- `needs_review`：置信度低，需要人工判断。

Unit 不会因为被 suppressed 而删除。人工可以追加 `active` 或 `suppressed` Override，最新人工 Override 决定有效状态，机器建议和全部 Override 历史仍保留。

```bash
curl -X POST localhost:8080/knowledge-units/100/admission-overrides \
  -H 'Content-Type: application/json' \
  -d '{"decision":"suppressed","reason":"mastered","note":"已经掌握"}'

curl localhost:8080/knowledge-units/100/admission
curl localhost:8080/knowledge-units/100/admission-overrides
```

## KnowledgeConcept 与人工标注

`KnowledgeUnit` 是某一次 Extraction 的不可变证据；`KnowledgeConcept` 是跨 Extraction 的持久学习身份。Concept 身份使用版本化 schema `fr_l2_concept_identity_v1`，包含：

- `target`
- `pedagogical_intent`
- `scope`
- `identity_features`

确定性 resolver 只在完整规范化签名精确匹配且唯一时允许自动 SAME。它不使用 embedding、向量、LLM 相似度，也不会自动推断 BROADER/NARROWER。

CURRENT SAME 只来自 `unit_concept_memberships`。`unit_concept_links` 是只追加历史事件，不能单独证明当前成员关系。

人工标注词汇：

- `SAME`：Unit 与 Concept 是同一学习身份。
- `DISTINCT`：显式负身份对，Unit 不是该 Concept；它不是关系，也不是 INVALID。
- `BROADER` / `NARROWER` / `RELATED`：非成员关系。
- `INVALID`：Unit 本身不应参加 Concept 解析；这是 Unit 级判断。
- `RejectSame`：清除错误 CURRENT SAME 的成员级历史纠正，不自动等于 DISTINCT。

候选展示、搜索、选择、跳过或创建界面状态都不是标签。只有显式人工操作创建标注权威。

### 标注工作台

`web/` 提供两个本地视图：

- **Concept Review**：写入显式人工 SAME、DISTINCT、关系、INVALID 或新 Concept。
- **Annotation Inspector**：只读显示当前 Effective Annotation。

启动方法见 [web/README.md](web/README.md)。该前端是内部标注/数据收集工具，不是最终 Review Engine。

## Effective Annotation（M11-A）

M11-A 从已持久化事实按需构建 `EffectiveAnnotationSnapshot`：

```text
只追加 judgment / distinction / concept-link 历史
                    +
unit_concept_memberships 的 CURRENT SAME 权威
                    ↓
        EffectiveAnnotationSnapshot
```

关键语义：

- 最新 Unit Judgment 决定 INVALID；INVALID 优先并抑制 SAME、DISTINCT 和关系输出。
- CURRENT SAME 只由 membership projection 决定，并保留对应 decision 的完整来源。
- DISTINCT 只来自显式 distinction 事件，并受更新 SAME 纠正的抑制规则约束。
- BROADER/NARROWER/RELATED 只保留已接受且未被结构性取代的有效事件。
- 所有输出保留 ID、source、resolver version、evidence 和时间戳。

M11-B 通过以下只读端点公开该投影：

```bash
curl localhost:8080/knowledge-units/101/effective-annotation
curl localhost:8080/effective-annotations
```

集合只包含每个条目的 CURRENT Extraction Unit，包括 resolved、unresolved 和 invalid，排除历史 Extraction Unit。

## Concept Annotation Dataset v1（M11-C）

Dataset v1 是稳定、版本化、只读的当前快照。它消费 M11-A 权威，不重新计算 SAME、INVALID、DISTINCT 或关系语义。

```bash
# JSON envelope
curl -sS localhost:8080/annotation-dataset/v1

# 相同逻辑记录、相同顺序的 NDJSON
curl -sS localhost:8080/annotation-dataset/v1/export
```

Schema version：

```text
concept_annotation_dataset_v1
```

每条记录包含：

- 原始 `KnowledgeUnit` 证据；
- `entry_id`、Extraction 版本、analysis/feedback/extractor 来源；
- 机器 Admission、最新 Override 和有效 Admission；
- 带完整 Concept 身份快照的有效 SAME、DISTINCT 和关系；
- 最新 Unit Judgment；
- 保守的显式 `human_labels`。

`human_labels` 与有效系统状态不是同一概念：

- 人工 CURRENT SAME 产生 human SAME。
- `resolver:automatic` SAME 可以使状态为 resolved，但不会成为人工 gold。
- 显式有效人工 DISTINCT 是负身份证据。
- BROADER/NARROWER/RELATED 保持关系类型，不转换为 DISTINCT。
- 有效人工 INVALID 是 Unit 级排除证据，不恢复旧的 pair-level 标签。

记录按 `entry_id`、Extraction version、Unit ordinal、Unit ID 升序排列。JSON 和 NDJSON 使用同一应用层表示；每行 NDJSON 都重复 `schema_version`。

Dataset v1 不决定 `gold` 或 `training_ready`，不生成训练/验证/测试切分，不计算指标，不训练模型，也不实现候选检索。数据集质量验证和评估属于后续里程碑。

## 开发与验证

```bash
make test          # 全部 Go 测试
make vet           # go vet
make fmt           # gofmt -w .
make build         # 构建服务端到 bin/server
make build-capture # 构建 Capture CLI 到 bin/capture

cd web
npm test
npm run build
```

验证 Go 二进制时，建议输出到临时目录，避免在仓库根目录产生构建产物：

```bash
go build -o /tmp/french-learning-hub-server ./cmd/server
go build -o /tmp/french-learning-hub-capture ./cmd/capture
```
