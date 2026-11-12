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

在浏览器工作台里的日常操作顺序、界面上的实际按钮名称（中英对照）、哪些操作在本地完成、
哪些需要配置 Provider，以及没有收到确认时怎么恢复，见[第 11 节](#11-工作台日常流程浏览器实测)。

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

在工作台中直接保存一个问题（FLH-091）：
- **入口：** 在 **Learning Records** 中点击 **Add a learning question**，默认模式 **Question**。
- **保存：** 输入问题和可选的来源，点击 **Save question**。
  - 问题按原文保存为未分析（unanalyzed）的记录，不运行分析或提取，也不代表人工认可。
  - 之后可在记录中显式请求分析和提取。
- **导入 JSON：** **Capture JSON** 模式就是原有的 JSON 导入；导入的候选 Analysis 保持未审阅（unreviewed）。
- **没有收到确认：** 文本会保留。
  - 用 **Check whether it was saved** 查询，或用 **Send the same question again** 重发同一次提交；它不会被保存两次。
- **浏览器存储：** 问题文本不会写入浏览器存储。

记录增多后，在工作台 **Learning Records** 中查找旧记录（FLH-089）：
- **跳转：** 在 **Go to record #** 输入记录编号可直接定位，只需一次请求，不必反复点击
  **Load older records**。
  - 列表顶部会说明从哪条记录开始；**Show newest records** 回到最新记录。
  - 编号不存在或不符合筛选条件时，列表会说明，并从下一条更早的匹配记录开始。
- **筛选：** **Effective category** 按后端计算的有效类别筛选，可与 **Record state** 组合。
- **文本搜索（FLH-090）：** 在 **Search text** 中输入文字并点击 **Search**。
  - **匹配范围：** 后端在学习者的原始输入或上下文中查找字面子串，忽略大小写，但重音须一致；
    `%`、`_` 按普通字符处理。
  - **不搜索的内容：** 不搜索生成的解释。
  - **组合：** 可与状态、类别筛选和跳转组合使用。

对应的 API：

```bash
curl -fsS "$FRENCH_HUB_URL/learning-records?limit=20&before_entry_id=$((ENTRY_ID + 1))" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/learning-records?category=grammar&limit=20" | python3 -m json.tool
curl -fsS "$FRENCH_HUB_URL/learning-records?q=bien%20que&limit=20" | python3 -m json.tool
```

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
`POST /analyses/{id}/feedback` 流程，参见[人工反馈](ARCHITECTURE.md#35-human-feedback)与[有效分析](ARCHITECTURE.md#36-effective-analysis)（英文）。
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

服务读取进程环境，以及工作目录中可选的 `.env`（从仓库根目录运行时即根目录的 `.env`）；进程中已设置的变量优先，因此这里 `export` 的值（包括 `DB_PATH`、`PORT`）会覆盖 `.env`。`AI_PROVIDER=rule-based` 与 Extractor 相互独立；
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

**离开后返回（FLH-089）：**
- **分页读取（FLH-090）：** 队列按页读取，每页 50 个 Unit；跳过最后一个已加载的 Unit 时
  才读取下一页。
- **恢复位置：** 切换到其他视图再回来，或点击 reload queue，会从离开时的 Unit 读取一页，并
  恢复为它输入的搜索文本。
  - 更早的 Unit 不会加载；**Start from the beginning of the queue** 会从队列开头重新读取。
- **Unit 已不在队列中：** 例如已在记录中处理过，队列会从队列顺序中的下一个 Unit 继续，并
  提示哪个 Unit 已不再等待审阅。
- **大型 Concept 目录：** 搜索结果每次显示 50 个，并标明总数；用 **Show 50 more** 查看
  其余结果。

**决定前阅读内容（FLH-093）：**
- 单元卡片先显示知识陈述与例句；**Show the original question for unit #N** 会在原地展开原始问题和上下文，
  不会丢失队列位置、搜索文本或身份草稿。
- 候选卡片的 **Show what concept #N contains** 显示该 Concept 的首选解释（仅在人工选定时）和后端计算的
  当前支持单元，每个单元都能查看自己的原始问题。不计为支持的成员与历史单元只显示数量。
- 选中候选后，右栏顶部的 **Compare before deciding** 与左侧单元卡片并排，说明 SAME 只是新增归属，
  不会合并或删除任何单元或记录。这些查看都是只读请求。

候选的展示、搜索、选择或跳过不会创建标签；只有显式动作才写入人工权威。NEW CONCEPT
可以为尚未解析的 Unit 建立 seed SAME；选择现有 Concept 的普通 SAME 才可能成为后续检索
评估的合格人工 truth。不要为了得到非空指标随意创建标签。

**记录阶段与跨视图链接（Daily workflow v1.0 RC）：**
- 记录详情顶部的 **Where this record stands** 列出三步：分析（只描述并归类问题）、提取（生成知识陈述）、
  概念决定，并给出唯一的 **Next:**。它每次都从服务器的当前记录读取，不存储任何状态。
- 已有决定的当前 Unit 会显示 “Filed under Concept #N (CURRENT SAME …)” 或 INVALID，并可
  **Open Concept #N in Knowledge Library**；知识库的来源页可 **Open record #N in Learning Records**；
  AI 建议条目可打开其记录或当前 Concept。顶部的 **← Back to …** 返回原视图，原视图状态保持不变。
  这些链接都是只读的。

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

## 11. 工作台日常流程（浏览器实测）

本节按 2026-11-12 的两次浏览器实测编写：一次英文界面，一次简体中文界面，都在 headless
Chromium 中逐一点击下面列出的按钮。服务是一次性的本地实例：全新数据库，只监听
`127.0.0.1`，`AI_PROVIDER=rule-based`（默认），其他 Provider 全部为 `disabled`。两次实测中
都没有任何请求离开本机服务。没有实测过的内容在文中单独注明。证据记录见
[docs/validation/RELEASE-READINESS-20261112.md](validation/RELEASE-READINESS-20261112.md)。

服务怎么启动不影响下面的操作：本地试用按第 1、7 节；Docker 发布版按
[RELEASE.md](RELEASE.md)；使用真实 Provider 的私人日常使用按 [DAILY_USE.md](DAILY_USE.md)。

### 11.1 界面语言与入口

- 首次打开时界面为英文（与浏览器语言无关）。页面右上角的 **语言**（Language）可选
  **简体中文**，选择保存在当前浏览器里。界面文字会翻译；学习内容、法语例句、ID、Provider
  名称、服务器原始错误信息，以及 SAME、NEW CONCEPT 等决定词不翻译。
- **说明语言**（Explanation language）只决定显示哪种语言的解释，与界面语言无关。
- 打开工作台时默认显示 **概念审阅**（Concept Review），不是主页。顶部视图依次为：
  **主页**、**学习记录**、**知识库**、**听力**、**阅读**、**写作**、**口语**、**错题本**、
  **模拟考试**、**概念审阅**、**标注检查器**、**实验面板**。
- **主页**（Home）显示“你想练习什么？”和八个入口：听力、阅读、写作、口语、语法、词汇、
  错题本、模拟考试。主页本身不保存、不评分，也不调用模型。

### 11.2 一个问题从保存到概念（实际顺序）

| 步骤 | 中文界面 | 英文界面 | 实测结果 |
| --- | --- | --- | --- |
| 1 | **学习记录** → **添加学习问题** | Learning Records → Add a learning question | 打开问题录入，默认模式“问题” |
| 2 | 填写 **您的问题**、可选的 **问题来源（可选）** → **保存问题** | Your question, Where it came from (optional) → Save question | 本地保存，`POST /captures` 201，不调用模型 |
| 3 | **打开已保存的记录 #N** | Open saved record #N | 顶部 **这条记录进行到哪一步** 显示“下一步： 在下方请求分析。保存问题时没有向任何模型发送内容。” |
| 4 | **请求分析…** → **创建新的分析版本** | Request analysis… → Create a new analysis version | 默认 `AI_PROVIDER=rule-based` 时在本地生成，提示“已使用 `rule-based:v2:fr_l2_taxonomy_v1` 创建分析 v1”；规则分析只有英文解释，中文栏显示未存储。`AI_PROVIDER=openai` 时这一步是一次 Provider 调用（本次未实测） |
| 5 | 在 **分析 v1 的决定** 中选 **接受**、**更正** 或 **拒绝** → **为分析 v1 记录“已接受”** | Accept / Correct / Reject → Record "accepted" for analysis v1 | 未选择时按钮显示“请选择要记录的决定”。记录反馈在本地完成（201），下一步变为“在下方请求提取，以生成知识陈述。” |
| 6 | **请求提取…** → **发送给提取服务** | Request extraction… → Send to the extraction provider | 默认 `EXTRACTOR_PROVIDER=disabled`：返回 503，显示“此服务器未启用提取 (503) knowledge extraction is not enabled。服务器在调用任何提取服务之前就会拒绝；未存储任何内容。”需要 `EXTRACTOR_PROVIDER=openai` 和密钥 |
| 7 | **概念审阅** → **单元队列** | Concept Review → Unit queue | 没有提取出的单元时显示“没有等待审阅的单元。”；有单元后按第 7 节作 SAME、NEW CONCEPT 等决定 |
| 8 | **概念审阅** → **AI 建议** | AI suggestions | 默认显示“此服务器未启用 AI 建议（SUGGESTION_PROVIDER 为 disabled）。已存储的建议仍可打开。” |

第 6 步之后的单元审阅、AI 建议确认和知识库链接需要真实的提取结果，本次实测没有 Provider，
因此没有走到；对应规则见第 7 节和 [DAILY_USE.md](DAILY_USE.md) 第 5 节。

### 11.3 四项技能、错题本和模拟考试

| 视图 | 实测的操作（中文界面） | 本地还是 Provider |
| --- | --- | --- |
| 听力：练习册脚本 | **练习册听力脚本** → **导入 〈标题〉** → **显示答案和依据** → **保存为学习问题…** → 填写“你没掌握什么，或想问什么？” → **保存学习记录** → “已保存为学习记录 #N。” | 本地。导入不调用模型（201）；错题保存为带来源链接的记录 |
| 听力：自己的视频 | **← 全部听力材料** → **添加视频**：**YouTube 视频链接**、**标题**、**法语文字稿（可选）** → **保存材料** | 保存在本地，链接不会被访问。之后 **准备练习** 需要 `LISTENING_PROVIDER=openai`；默认显示“练习准备功能已关闭（LISTENING_PROVIDER=disabled）。你的材料和文字稿已保存。” |
| 阅读 | **使用这个示例** → **显示答案和依据** → **保存为学习问题…** → **保存学习记录** | 本地。为自己粘贴的文章点 **准备练习** 需要 `READING_PROVIDER=openai`（本次未实测） |
| 写作 | **开始这个任务** → **使用示例草稿（故意含有错误）** → **保存为版本 1** | 本地。页面显示“此服务器未配置反馈（WRITING_PROVIDER=disabled）。写草稿、修改和比较仍然可用。” **请求版本 N 的反馈** 需要 `WRITING_PROVIDER=openai` |
| 口语 | 题目列表每题有 **开始** | 页面说明：录音和回放不发送任何内容，只有“发送音频转写”（`SPEAKING_TRANSCRIPTION_PROVIDER`）和“请求反馈”（`SPEAKING_PROVIDER`）会调用 Provider。实测没有麦克风，录音未实测 |
| 错题本 | 已保存的错题显示 **标记为重练** → 变为 **已标记为重练：移除** → **重练** → **开始重练** | 本地。标记是追加记录；重练中的作答只留在页面里 |
| 模拟考试 | **开始“〈试卷标题〉”** → 选择答案（立即保存）→ **提交我的答案** → **立即提交** → 显示答案、解析和依据 | 本地，没有 Provider，也没有官方分数 |
| 知识库 | 搜索框和搜索模式“关键词 / 语义 / 混合” | 关键词搜索在本地。语义和混合模式需要单独构建的索引和嵌入服务（`SEMANTIC_SEARCH`，见 [SEMANTIC_SEARCH.md](SEMANTIC_SEARCH.md)） |

### 11.4 没有收到确认时怎么办

- **保存问题时响应丢失（已实测）**：实测让请求到达服务器、但浏览器收不到回答。页面显示
  “结果未知。没有收到确认（…），问题可能已保存，也可能未保存。您的文本已保留。请检查是否已保存，
  或再次发送同一个问题：它不会被保存两次。”点击 **检查是否已保存** 后显示
  “已保存：记录 #N。”和 **打开已保存的记录 #N**。服务器上只有一条这样的记录。如果检查结果是
  未保存，点 **再次发送同一个问题**；不要改动文字后再保存，否则可能产生第二条记录。
- **提取未启用（已实测）**：503，什么都没有保存，可以直接离开；启用 Provider 后再请求。
- **其他“结果未知”提示（界面文字已核对，未逐一模拟断网）**：
  - 添加视频：“服务器没有响应：不确定是否已保存。”应先查看列表再保存。
  - 导入练习册脚本：再次导入是安全的，会打开同一课。
  - 使用阅读示例：先查看自己的阅读练习再重试。
  - 模拟考试开始或提交：用 **查看状态** 或 **再次提交同样的答案**；重复提交返回同一个结果。
- 调用 Provider 的操作都只发送一次，从不自动重试；结果未知时用页面上的检查或显式重发按钮
  （[DAILY_USE.md](DAILY_USE.md) 第 4 节）。

### 11.5 哪些操作需要配置 Provider

| 操作 | 需要的设置（默认值） | 未配置时 |
| --- | --- | --- |
| 保存问题、导入 Capture、记录反馈、概念决定、阅读示例、写作草稿、错题本、模拟考试、练习册脚本 | 不需要 | 在本地完成（已实测，概念决定除外） |
| 请求分析 | `AI_PROVIDER`（`rule-based`） | 默认在本地生成规则分析（已实测）；设为 `openai` 才调用模型 |
| 请求提取 | `EXTRACTOR_PROVIDER`（`disabled`） | 503，未存储任何内容（已实测） |
| AI 建议 | `SUGGESTION_PROVIDER`（`disabled`） | 显示未启用提示（已实测） |
| 听力 **准备练习** | `LISTENING_PROVIDER`（`disabled`） | 显示已关闭提示（已实测） |
| 阅读 **准备练习** | `READING_PROVIDER`（`disabled`） | 未实测 |
| 写作 **请求版本 N 的反馈** | `WRITING_PROVIDER`（`disabled`） | 显示未配置提示（已实测） |
| 口语转写与反馈 | `SPEAKING_TRANSCRIPTION_PROVIDER`、`SPEAKING_PROVIDER`（`disabled`） | 未实测（没有麦克风） |
| 知识库语义 / 混合搜索 | `SEMANTIC_SEARCH`（`disabled`）及嵌入设置 | 未实测 |

本节只证明这些操作在本地实例上按上述方式工作，不证明 Provider 输出质量，也不代表任何部署
已经完成。启用 Provider 后的行为以 [DAILY_USE.md](DAILY_USE.md) 为准。
