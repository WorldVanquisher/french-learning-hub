# 两次真实对话试用：Capture → 学习清单

目标是亲自验证“外部对话可保存、可查询、可安全重试”。基础试用不需要 API key。
两个试用来自**两段不同的真实对话**，各选一个学习交互；仓库示例仅用于无凭据冒烟测试，
不能当作你已经完成的真实学习或评估结果。

实际路径：外部对话 → [导出提示词](CAPTURE_PROMPT.zh-CN.md) → 一个
`learning_capture_v1` JSON → `cmd/capture` → `POST /captures` → SQLite 中的 Entry、
可选版本 1 Analysis 与导入回执 → 只读 Learning Inventory。
服务端不读取 ChatGPT 对话、不调用模型来导入、不自动触发分析或 Knowledge Extraction。

## 1. 启动独立环境

需要 Bash、Go 1.26.5、curl、Python 3（仅生成 UUID、查看/编辑 JSON，不做领域校验）。
可选工作台另需 Node.js/npm，参见 [Quick start](QUICKSTART.md)。
以下命令从仓库根目录运行。终端 A：

```bash
umask 077
export DEMO_DIR="$(mktemp -d /tmp/french-hub-demo.XXXXXX)"
export DB_PATH="$DEMO_DIR/app.db"
export PORT=18080
export AI_PROVIDER=rule-based
export EXTRACTOR_PROVIDER=disabled
export EMBEDDING_PROVIDER=disabled
go build -buildvcs=false -o "$DEMO_DIR/server" ./cmd/server
go build -buildvcs=false -o "$DEMO_DIR/capture" ./cmd/capture
printf 'export DEMO_DIR=%q\nexport FRENCH_HUB_URL=http://localhost:%s\n' "$DEMO_DIR" "$PORT"
"$DEMO_DIR/server"
```

保持终端 A 运行。在终端 B（同一仓库根目录），先复制执行上面打印的两行 `export`，然后：

```bash
umask 077
set -o pipefail
curl -fsS "$FRENCH_HUB_URL/healthz"
```

应返回 `{"status":"ok"}`。同时确认终端 A 成功监听 18080；若端口被占用、构建或启动失败，
先解决再导入，不能向碰巧响应的其他服务提交。可改 A 的 `PORT` 后重启，并重新复制 B 的 URL。
所有数据库、JSON、回执和二进制都在本次临时目录；`data/app.db` 不受影响。
保留该目录路径直到演示结束；临时目录不适合长期保存私人学习记录。

## 2. 试用一：第一段真实对话

在终端 B 生成一个新 ID：

```bash
TRIAL1_ID="chatgpt-$(python3 -c 'import uuid; print(uuid.uuid4())')"
printf '%s\n' "$TRIAL1_ID"
```

完成第一段真实学习对话，把此 ID 和你的原始问题填入[提示词](CAPTURE_PROMPT.zh-CN.md)，
发到该对话末尾。人工核对输出；没有可信的候选分析时允许完全省略 `analysis`。
运行下面命令，粘贴**纯 JSON**，换行后按 Ctrl-D 保存（不是把 JSON 当 shell 命令执行）：

```bash
cat > "$DEMO_DIR/trial-1.json"
```

保存后导入并记录服务端分配的 ID：

```bash
"$DEMO_DIR/capture" -url "$FRENCH_HUB_URL" -file "$DEMO_DIR/trial-1.json" | tee "$DEMO_DIR/trial-1.receipt.txt"
ENTRY1_ID=$(awk '$1 == "entry_id:" {print $2}' "$DEMO_DIR/trial-1.receipt.txt")
ANALYSIS1_ID=$(awk '$1 == "analysis_id:" {print $2}' "$DEMO_DIR/trial-1.receipt.txt")
printf 'entry_id=%s analysis_id=%s\n' "$ENTRY1_ID" "$ANALYSIS1_ID"
```

应看到 `capture stored (new)`、`created: true`。`analysis_id: null` 表示没有导入分析，
不是失败。导入失败则先检查错误，不要继续使用空 ID。不要假设数据库 ID 是 1、2。

## 3. 试用二：另一段真实对话

使用另一段真实对话中的一个问题，重新应用同一提示词，但使用新的 ID：

```bash
TRIAL2_ID="chatgpt-$(python3 -c 'import uuid; print(uuid.uuid4())')"
test "$TRIAL1_ID" != "$TRIAL2_ID" && printf '%s\n' "$TRIAL2_ID"
cat > "$DEMO_DIR/trial-2.json"
```

在 `cat` 等待输入时粘贴第二份纯 JSON，换行、Ctrl-D，再运行：

```bash
"$DEMO_DIR/capture" -url "$FRENCH_HUB_URL" -file "$DEMO_DIR/trial-2.json" | tee "$DEMO_DIR/trial-2.receipt.txt"
ENTRY2_ID=$(awk '$1 == "entry_id:" {print $2}' "$DEMO_DIR/trial-2.receipt.txt")
ANALYSIS2_ID=$(awk '$1 == "analysis_id:" {print $2}' "$DEMO_DIR/trial-2.receipt.txt")
printf 'entry_id=%s analysis_id=%s\n' "$ENTRY2_ID" "$ANALYSIS2_ID"
```

应再次是新导入，且两个 `entry_id` 不同。核对两份回执中的 `capture_id` 分别等于
`TRIAL1_ID`、`TRIAL2_ID`；不要把第一份 JSON 仅改 ID 冒充第二段真实对话。

## 4. 查询原记录、分析和学习清单

```bash
for capture_id in "$TRIAL1_ID" "$TRIAL2_ID"; do
  curl -fsS "$FRENCH_HUB_URL/captures/$capture_id" | python3 -m json.tool
done
for entry_id in "$ENTRY1_ID" "$ENTRY2_ID"; do
  curl -fsS "$FRENCH_HUB_URL/entries/$entry_id" | python3 -m json.tool
  curl -fsS "$FRENCH_HUB_URL/entries/$entry_id/analyses" | python3 -m json.tool
done
for analysis_id in "$ANALYSIS1_ID" "$ANALYSIS2_ID"; do
  if [ "$analysis_id" != null ]; then
    curl -fsS "$FRENCH_HUB_URL/analyses/$analysis_id/effective" | python3 -m json.tool
  fi
done
curl -fsS "$FRENCH_HUB_URL/learning-records?limit=20" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/learning-records/summary" | python3 -m json.tool
```

回执只含引用及摘要，原文在 Entry；Analysis 单独存储。逐项核对原问题（服务端会裁剪首尾
空白）、上下文和解释。带分析的记录初始为 `unreviewed`，来源为
`imported:chatgpt-web:learning_capture_v1`；不带分析为 `unanalyzed`。
Inventory 选择每个 Entry 的最新 Analysis 及其最新 Feedback，不会自动认可导入分析。
这时新库的 summary 应有 2 个 Entry；状态数取决于两份实际输出是否含分析。

## 5. 重放与冲突：已有内容不会被静默改写

直接重交已保存的第一份文件，**不要再让 ChatGPT 生成一次**：

```bash
"$DEMO_DIR/capture" -url "$FRENCH_HUB_URL" -file "$DEMO_DIR/trial-1.json"
```

| 情况 | HTTP | CLI 与存储结果 |
| --- | --- | --- |
| 新 ID | 201 | `capture stored (new)`，`created: true`，分配新 ID |
| 相同 ID、相同规范化内容 | 200 | `capture already existed (idempotent replay)`，`created: false`，返回原 ID，退出 0 |
| 相同 ID、有效但不同的内容 | 409 | 非零退出码，`capture_id already exists with different content`，原数据不变 |

服务端比较规范化内容指纹；JSON 缩进/键顺序变化不是内容冲突。重试仍应保留文件原样。
未知字段或非法 JSON 通常返回 400；不支持的 schema、非法字段值或分析返回 422。

可在**副本**上改摘要，验证 409；原文件保持不变。这是故意构造的冲突探针，不是新学习记录：

```bash
curl -fsS "$FRENCH_HUB_URL/learning-records?limit=20" > "$DEMO_DIR/inventory.before.json"
python3 - "$DEMO_DIR/trial-1.json" "$DEMO_DIR/conflict.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    capture = json.load(f)
capture["discussion_summary"] = (
    "conflict probe" if capture.get("discussion_summary") != "conflict probe"
    else "different conflict probe"
)
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump(capture, f, ensure_ascii=False)
PY
"$DEMO_DIR/capture" -url "$FRENCH_HUB_URL" -file "$DEMO_DIR/conflict.json"
printf 'CLI exit=%s (expected 1)\n' "$?"
curl -fsS "$FRENCH_HUB_URL/learning-records?limit=20" > "$DEMO_DIR/inventory.after.json"
cmp "$DEMO_DIR/inventory.before.json" "$DEMO_DIR/inventory.after.json" && echo 'inventory unchanged'
curl -fsS "$FRENCH_HUB_URL/captures/$TRIAL1_ID" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/learning-records/summary" | python3 -m json.tool
```

核对回执的原摘要仍在、总数仍为 2。Capture 没有更新操作；分析纠错走现有
`POST /analyses/{id}/feedback` 的 accepted/corrected/rejected 流程，见
[人工反馈](../README.zh-CN.md#人工反馈和有效分析)。不要以新 ID 重复导入来假装更新。

## 6. 可选：显式 Knowledge Extraction

到此已经完成基础两次试用。只有确实要调用外部 Provider 时才继续；导入本身不需要它。
在终端 A 按 Ctrl-C 停止服务，保留原来的 `DB_PATH`、`PORT` 和 `DEMO_DIR`，输入你自己的
Provider 配置并重启（密钥不回显，不写入命令历史或 JSON）：

```bash
read -r -s -p 'OPENAI_API_KEY: ' OPENAI_API_KEY; printf '\n'
read -r -p 'OPENAI_MODEL: ' OPENAI_MODEL
export OPENAI_API_KEY OPENAI_MODEL
export EXTRACTOR_PROVIDER=openai
"$DEMO_DIR/server"
```

`AI_PROVIDER=rule-based` 与 Extractor 独立；服务读取进程环境，不自动加载 `.env`。
当前适配器默认访问 `https://api.openai.com/v1`，可用既有 `OPENAI_BASE_URL` 配置覆盖。
只有 `unreviewed`、`accepted`、`corrected` 的最新分析可用于抽取。
在终端 B 选择本次真实的 Entry（第二次可改为 `ENTRY2_ID`）：

```bash
ENTRY_ID="$ENTRY1_ID"
curl -fsS "$FRENCH_HUB_URL/entries/$ENTRY_ID/analyses" | python3 -m json.tool
```

若无分析，可**显式**运行一次现有本地 Analyzer，然后查看其候选解释再决定是否继续：

```bash
curl -fsS -X POST "$FRENCH_HUB_URL/entries/$ENTRY_ID/analysis" | python3 -m json.tool
```

不要对已经导入的分析无意追加新版本：Inventory 和抽取都会选择最新版本。
被 rejected 的当前分析没有有效解释；应先进行真实的反馈/分析处理，不能为演示强行接受。
准备好后显式抽取并查询结果：

```bash
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$FRENCH_HUB_URL/entries/$ENTRY_ID/extractions"
curl -fsS "$FRENCH_HUB_URL/entries/$ENTRY_ID/extractions" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/entries/$ENTRY_ID/current-extraction" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/reviewable-units?entry_id=$ENTRY_ID" | python3 -m json.tool
```

成功返回 201，包含 Extraction `id`、`version`、来源 Analysis/Feedback 和 `units`。
也可用返回的 Extraction ID 调用 `GET /extractions/{id}`。`units: []` 是**成功但零产出**，
仍保存一个版本且默认成为当前 Extraction；不要把它记成请求失败或“已经有知识点”。
`extractions: []` 则表示没有保存过成功的 Extraction；空 reviewable 队列也可能因为
Admission、已有 SAME 或 INVALID，应检查 Extraction 本身。禁用时为 503；启用后
unanalyzed/rejected 为 409；Provider 失败为 502/504，非法输出为 422，不静默回退。
每次成功 POST 都追加版本，和 Capture 重放不同；不要把重复抽取当作幂等操作。

## 7. 可选：Concept Review 与只读报告

在终端 B 从仓库根目录启动工作台；`FRENCH_HUB_URL` 会让 Vite 代理连接试用库服务：

```bash
cd web
npm ci
npm run dev
```

打开 Vite 打印的地址。Concept Review 显示当前可审核 Unit；按真实判断选择
SAME、NEW CONCEPT、DISTINCT、BROADER/NARROWER/RELATED 或 INVALID。
看见/搜索/选择候选、跳过都不会产生标签。NEW CONCEPT 可建立 seed SAME；普通 SAME
针对已有 Concept。不要为了得到非空指标随意标 SAME。Annotation Inspector 用来只读核对
有效标注，Experiment Dashboard 用来查看后端报告。它们没有复习调度或掌握度计算。

停止 Vite 后（或在已设置相同 URL 的另一终端）读取原始报告：

```bash
curl -fsS "$FRENCH_HUB_URL/annotation-dataset/v1/quality" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/retrieval-evaluation/v1" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/retrieval-comparison/v1" | python3 -m json.tool
```

默认 exact signature、weighted lexical、BM25 可用；embedding 未启用时比较行是
`unavailable`。`EXTRACTOR_PROVIDER=openai` 不会启用 embedding。
没有合格样本时 Recall@1/3/5 和 MRR 为 `null`（UI 显示 `—`），不是测得 0 分。
评估正例要求当前显式人工 SAME、有效 active Admission、目标在当前非 retired catalog；
自动 SAME 不算人工 truth，NEW CONCEPT 的 `seed_unit_same` 因时间泄漏被排除。
所以即使做了两次抽取和新建 Concept，也可能没有评估样本。质量报告 `valid: true`
只证明结构通过校验；无效 Dataset 会产生 `blocked_invalid_dataset` 和空指标。
两个真实试用足以观察流程，不能据此宣称检索质量或 ML 效果。

## 8. 面试记录表（只填实际观察）

| 项目 | 试用一观察 / 证据 | 试用二观察 / 证据 | 系统实际实现的边界 |
| --- | --- | --- | --- |
| 真实问题、capture_id、entry_id、analysis_id | 待填 | 待填 | 原文与版本化解释分开；null 分析合法 |
| 原文/上下文是否忠实、需要什么人工修正 | 待填 | 待填 | 模型输出需人工核对；导入校验不证明语言解释正确 |
| 新导入、重放、冲突、Inventory 状态 | 待填 | 待填 | 原子导入；同 ID 不允许改内容 |
| Extraction ID、Unit 数或未运行原因 | 待填 | 待填 | 显式 Provider 调用；成功可以是零 Unit |
| 我实际提交的 Concept 判断与理由 | 待填/未运行 | 待填/未运行 | 人工动作创建标注；检索候选不创建标签 |
| 合格样本数、报告状态、指标或 null | 待填 | 待填 | 只读基线评估；不训练 ML，不证明掌握度 |

可用一句话说明：“我观察到 ___；证据是 ___；系统目前实现 ___；我尚未验证 ___。”
未来复习生成、调度、掌握度、学习式 SAME Resolver 都不能当作这次已实现或已验证的功能。
结束时在服务/工作台终端按 Ctrl-C；记录需要保留的证据，不要把私人 JSON、数据库或密钥提交到仓库。
