# 可重复的本地学习流程：真实对话 → Capture → Concept Review

这份手册用于面试前反复使用产品。每次从一段真实法语学习对话中选择一个学习交互，
保存为一个 Capture；次数没有固定上限。所有试用记录累计在独立数据库
`data/local-trial/app.db`，重启服务后仍然存在，并且不会修改日常数据库 `data/app.db`。

基础循环不需要 API key：

```text
完成一段真实讨论
  → 用提示词生成一个 learning_capture_v1 JSON
  → 人工核对并保存文件
  → cmd/capture 原样提交到 POST /captures
  → 查看 Entry、可选 Analysis 和 Learning Inventory
```

可选后半段需要显式启用 OpenAI Extractor：

```text
有效 Analysis
  → 显式 Knowledge Extraction
  → 零个或多个 KnowledgeUnit
  → 在 Concept Review 中作人工判断
  → 只读质量与检索报告
```

Capture 导入不会读取 ChatGPT 对话、调用模型、自动分析、自动抽取知识或创建人工标签。
导入的 Analysis 只是待人工审核的候选解释。

## 1. 首次建立持久试用环境

需要 Bash、Go 1.26.5、curl 和 Python 3。Python 只用于生成 UUID、格式化 JSON，
不实现任何领域校验。Concept Review 另需 Node.js/npm。

以下命令均从仓库根目录运行。终端 A：

```bash
umask 077
export TRIAL_ROOT="$PWD/data/local-trial"
export DB_PATH="$TRIAL_ROOT/app.db"
export PORT=18080
export AI_PROVIDER=rule-based
export EXTRACTOR_PROVIDER=disabled
export EMBEDDING_PROVIDER=disabled
mkdir -p "$TRIAL_ROOT/captures" "$TRIAL_ROOT/receipts"
go run ./cmd/server
```

保持终端 A 运行。终端 B 同样从仓库根目录开始：

```bash
umask 077
set -o pipefail
export TRIAL_ROOT="$PWD/data/local-trial"
export FRENCH_HUB_URL=http://localhost:18080
curl -fsS "$FRENCH_HUB_URL/healthz"
```

健康检查应返回 `{"status":"ok"}`。同时确认终端 A 明确显示监听 `:18080` 且数据库路径为
`data/local-trial/app.db`；若端口被占用，先换一个 `PORT`，并同步修改终端 B 的 URL。
不要向碰巧响应的其他服务提交私人内容。

`data/` 已被仓库的 `.gitignore` 排除，因此试用数据库、Capture 和回执不会进入版本控制。
它们仍是本机上的普通持久文件：服务停止或机器重启不会删除它们。请按私人学习数据保护；
不要提交、分享或放入不受信任的同步目录。

### 以后重启

终端 A 每次重新进入仓库后执行：

```bash
umask 077
export TRIAL_ROOT="$PWD/data/local-trial"
export DB_PATH="$TRIAL_ROOT/app.db"
export PORT=18080
export AI_PROVIDER=rule-based
export EXTRACTOR_PROVIDER=disabled
export EMBEDDING_PROVIDER=disabled
go run ./cmd/server
```

终端 B 重新设置：

```bash
umask 077
set -o pipefail
export TRIAL_ROOT="$PWD/data/local-trial"
export FRENCH_HUB_URL=http://localhost:18080
```

始终复用同一个 `DB_PATH`。换成临时目录、删除 `app.db` 或误用默认 `make run`，都不会打开
这套累积数据。可用 `curl -fsS "$FRENCH_HUB_URL/learning-records/summary"` 确认记录总数。

## 2. 完成一次真实讨论并生成 Capture

先完成一段真实法语学习讨论，再从中选择**一个学习交互**：一个原始问题及其相关讨论。
不要把多个独立问题合并到同一 Capture。

在终端 B 为这个新交互生成唯一 ID，并准备对应文件名：

```bash
CAPTURE_ID="chatgpt-$(python3 -c 'import uuid; print(uuid.uuid4())')"
CAPTURE_FILE="$TRIAL_ROOT/captures/$CAPTURE_ID.json"
RECEIPT_FILE="$TRIAL_ROOT/receipts/$CAPTURE_ID.txt"
printf 'capture_id=%s\nfile=%s\n' "$CAPTURE_ID" "$CAPTURE_FILE"
```

把 ID 和原始问题填入[可复制的 Capture 提示词](CAPTURE_PROMPT.zh-CN.md)，在原对话末尾发送。
提示词要求 ChatGPT 只输出一个 `learning_capture_v1` JSON 对象。

收到输出后先人工核对：

- `original_input` 是否准确保留你的原问题，而不是模型的改写或回答；
- `original_context` 和 `discussion_summary` 是否只包含对话中实际出现的事实；
- `capture_id` 是否与终端生成的值完全相同，`source` 是否为 `chatgpt-web`；
- 若存在 `analysis`，分类、解释、不确定性和 confidence 是否确有对话依据。

没有充分依据时，整个 `analysis` 可以省略。合法 JSON 不等于语言解释正确，最终判断仍由你负责。

## 3. 保存并导入

运行下面的命令，粘贴 ChatGPT 输出的**纯 JSON**，换行后按 Ctrl-D 保存：

```bash
cat > "$CAPTURE_FILE"
```

先做 JSON 语法检查。该命令不是第二套 Capture 校验器；字段规则仍只由服务端负责：

```bash
python3 -m json.tool "$CAPTURE_FILE" >/dev/null && echo 'JSON syntax OK'
```

通过现有 CLI 导入，并保留回执：

```bash
go run ./cmd/capture -url "$FRENCH_HUB_URL" -file "$CAPTURE_FILE" | tee "$RECEIPT_FILE"
ENTRY_ID=$(awk '$1 == "entry_id:" {print $2}' "$RECEIPT_FILE")
ANALYSIS_ID=$(awk '$1 == "analysis_id:" {print $2}' "$RECEIPT_FILE")
test -n "$ENTRY_ID" && test -n "$ANALYSIS_ID"
printf 'entry_id=%s analysis_id=%s\n' "$ENTRY_ID" "$ANALYSIS_ID"
```

新导入应显示 `capture stored (new)` 和 `created: true`。`analysis_id: null` 表示 Capture
没有候选 Analysis，不是导入失败。不要假设数据库 ID 连续或从 1 开始；以后都从对应回执读取。

## 4. 查看这次保存的内容

```bash
curl -fsS "$FRENCH_HUB_URL/captures/$CAPTURE_ID" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/entries/$ENTRY_ID" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/entries/$ENTRY_ID/analyses" | python3 -m json.tool
if [ "$ANALYSIS_ID" != null ]; then
  curl -fsS "$FRENCH_HUB_URL/analyses/$ANALYSIS_ID/effective" | python3 -m json.tool
fi
curl -fsS "$FRENCH_HUB_URL/learning-records?limit=200" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/learning-records/summary" | python3 -m json.tool
```

Capture 回执只保存来源、摘要和引用；原问题在 Entry，候选解释在独立且版本化的 Analysis。
含导入 Analysis 的新记录初始为 `unreviewed`，其 provenance 是
`imported:chatgpt-web:learning_capture_v1`；不含 Analysis 的记录为 `unanalyzed`。
Inventory 按 Entry 选择最新 Analysis 和其最新 Feedback，不会把导入分析自动视为人工认可。

如果重启或开启新终端后要恢复本次 ID，可从已保存的文件和回执读取：

```bash
CAPTURE_FILE="$TRIAL_ROOT/captures/$CAPTURE_ID.json"
RECEIPT_FILE="$TRIAL_ROOT/receipts/$CAPTURE_ID.txt"
ENTRY_ID=$(awk '$1 == "entry_id:" {print $2}' "$RECEIPT_FILE")
ANALYSIS_ID=$(awk '$1 == "analysis_id:" {print $2}' "$RECEIPT_FILE")
```

## 5. 重试、冲突和纠错

网络中断或不确定上次是否成功时，直接重交**同一个已保存文件**：

```bash
go run ./cmd/capture -url "$FRENCH_HUB_URL" -file "$CAPTURE_FILE"
```

| 情况 | HTTP | 结果 |
| --- | --- | --- |
| 新 `capture_id` | 201 | 创建 Entry 和可选 Analysis，`created: true` |
| 同一 ID、相同规范化内容 | 200 | 返回原 ID，`created: false`，不新增记录 |
| 同一 ID、不同有效内容 | 409 | 非零退出；已有 Entry、Analysis 和回执保持不变 |

服务端按规范化内容指纹判断，JSON 缩进或键顺序不影响结果。实际重试仍应复用保存的原文件，
不要再次请求模型生成，也不要只保留 ID 后重写内容。

Capture 没有覆盖更新操作。若导入后发现候选分析需要接受、纠正或拒绝，应使用现有的
`POST /analyses/{id}/feedback` 流程，参见[人工反馈](../README.zh-CN.md#人工反馈和有效分析)。
不要以新 ID 重新导入同一次交互来假装更新，也不要修改原文件再用同一个 ID 提交。

若要专门验证 409，复制 Capture 文件并只改副本，再提交副本；这只是一次冲突探针，
不是新的学习交互。验证后重新查询原 Capture 和 Inventory，确认内容与总数没有变化。

## 6. 可选：显式 Knowledge Extraction

Capture 循环到这里已经完成。Knowledge Extraction 是独立、显式且会调用 Provider 的操作；
默认禁用，没有本地规则式 Extractor，也不会静默回退。

在终端 A 按 Ctrl-C 停止服务。保留相同的 `TRIAL_ROOT`、`DB_PATH` 和 `PORT`，读取你自己的
密钥与模型名，再用同一个数据库重启：

```bash
read -r -s -p 'OPENAI_API_KEY: ' OPENAI_API_KEY; printf '\n'
read -r -p 'OPENAI_MODEL: ' OPENAI_MODEL
export OPENAI_API_KEY OPENAI_MODEL
export EXTRACTOR_PROVIDER=openai
go run ./cmd/server
```

服务读取进程环境，不自动加载 `.env`。`AI_PROVIDER=rule-based` 与 Extractor 相互独立；
`OPENAI_BASE_URL` 可覆盖默认 API 地址。不要把密钥放入 Capture、回执、数据库或仓库文件。

Extraction 只接受最新有效状态为 `unreviewed`、`accepted` 或 `corrected` 的 Entry。
先查看当前 Analysis：

```bash
curl -fsS "$FRENCH_HUB_URL/entries/$ENTRY_ID/analyses" | python3 -m json.tool
```

如果 `ANALYSIS_ID` 为 `null`，可以显式运行一次默认的本地规则 Analyzer，生成一个新版本候选：

```bash
curl -fsS -X POST "$FRENCH_HUB_URL/entries/$ENTRY_ID/analysis" | python3 -m json.tool
```

不要对已有导入 Analysis 的记录无意追加版本；Inventory 和 Extraction 都选择最新 Analysis。
被 rejected 的最新 Analysis 没有有效解释，不能抽取。应先按真实判断处理分析，不要为演示强行接受。

显式运行一次 Extraction：

```bash
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$FRENCH_HUB_URL/entries/$ENTRY_ID/extractions"
curl -fsS "$FRENCH_HUB_URL/entries/$ENTRY_ID/extractions" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/entries/$ENTRY_ID/current-extraction" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/reviewable-units?entry_id=$ENTRY_ID" | python3 -m json.tool
```

成功返回 HTTP 201，并保存 Extraction 版本、来源 Analysis/Feedback、Extractor provenance 和
`units`。`units: []` 是成功的零产出，仍是当前 Extraction；它不等于请求失败，也不能宣称
已经提取到知识点。`extractions: []` 表示从未保存成功 Extraction。空 reviewable 队列还可能
由 Admission、已有 SAME 或 INVALID 导致，应查看 Extraction 本身。

常见结果：禁用 Extractor 为 503；无有效 Analysis 或最新 Analysis 被拒绝为 409；Provider
失败为 502/504；Provider 输出违反领域约束为 422。每次成功 POST 都追加 Extraction 版本，
不是幂等重试，不能像 Capture 一样随意重复提交。

## 7. 可选：在 Concept Review 审核 KnowledgeUnits

保持后端运行。在终端 B 从仓库根目录执行；第一次使用先安装锁定依赖：

```bash
cd web
npm ci
FRENCH_HUB_URL=http://localhost:18080 npm run dev
```

打开 Vite 打印的地址，进入 **Concept Review**。它显示当前 Extraction 中等待处理的 Unit。
根据实际判断记录 SAME、NEW CONCEPT、DISTINCT、BROADER/NARROWER/RELATED 或 INVALID。

候选的展示、搜索、选择或跳过不会创建标签；只有显式动作才写入人工权威。NEW CONCEPT
可以为尚未解析的 Unit 建立 seed SAME；选择现有 Concept 的普通 SAME 才可能成为后续检索
评估的合格人工 truth。不要为了得到非空指标随意创建标签。

**Annotation Inspector** 只读展示后端计算的有效标注；**Experiment Dashboard** 只读展示
数据质量和检索比较。它们不是复习调度器或掌握度系统。也可直接查看报告：

```bash
curl -fsS "$FRENCH_HUB_URL/annotation-dataset/v1/quality" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/retrieval-evaluation/v1" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/retrieval-comparison/v1" | python3 -m json.tool
```

没有合格的显式人工 SAME 样本时，Recall@1/3/5 和 MRR 为 `null`，不是测得 0 分。
自动 SAME 不算人工 truth；NEW CONCEPT 的 `seed_unit_same` 因时间泄漏被排除。embedding
默认未注册，比较报告会将其标为 `unavailable`；启用 Extractor 不会启用 embedding。
`valid: true` 仅表示 Dataset 结构通过检查，不能证明语言质量、检索效果或模型性能。

## 8. 下一段讨论具体重复什么

服务和持久数据库无需重建。每个新的真实学习交互只重复：

1. 完成讨论并选择一个原始问题。
2. 重复第 2 节：生成**新的** `CAPTURE_ID`，填写同一提示词。
3. 重复第 3 节：保存为以新 ID 命名的 JSON，导入并保留回执。
4. 重复第 4 节：核对 Entry、Analysis 和累积 Inventory。
5. 如果要把这条记录推进到 Concept 层，再选择性重复第 6、7 节。

不要为新讨论沿用旧 ID；不要为旧 Capture 的重试生成新 ID或新内容。每个 Capture 文件与
同名回执形成一对，方便跨终端、跨重启恢复 `entry_id` 和 `analysis_id`。

## 9. 可选的仓库示例冒烟测试

仓库示例只验证工具链，不能算作你的真实用户试用、人工标签或评估结果。若想先测试 CLI，
建议停止试用服务并用另一个数据库 `data/local-trial/smoke.db` 启动，避免污染累积记录：

```bash
export DB_PATH="$TRIAL_ROOT/smoke.db"
export PORT=18081
export EXTRACTOR_PROVIDER=disabled
go run ./cmd/server
```

在另一终端提交两个不同形态的固定夹具：

```bash
go run ./cmd/capture -url http://localhost:18081 -file examples/captures/chatgpt-example.json
go run ./cmd/capture -url http://localhost:18081 -file examples/captures/manual-example.json
go run ./cmd/capture -url http://localhost:18081 -file examples/captures/chatgpt-example.json
```

预期前两次是新导入，第三次是幂等重放。测试完停止 smoke 服务，再按第 1 节用
`data/local-trial/app.db` 和 18080 重启真实试用环境。

## 10. 面试观察记录（每次使用新增一行）

| 日期 / capture_id | 原问题与 Entry/Analysis ID | 导入与 Inventory 观察 | Extraction / Unit / Concept 判断 | 报告状态或未运行原因 |
| --- | --- | --- | --- | --- |
| 待填 | 待填 | 待填 | 待填或“未运行” | 待填或“未运行” |

每次可用一句话总结：“我观察到 ___；证据是 ___；系统实际实现 ___；我尚未验证 ___。”
只记录亲自运行所得结果。没有 Provider 时不要声称运行过 Extraction；没有明确人工标注时不要
声称有 human labels；没有合格样本时不要把 null Recall/MRR 当作性能结果。未来复习生成、
调度、掌握度和学习式 SAME Resolver 也不属于当前实现。
