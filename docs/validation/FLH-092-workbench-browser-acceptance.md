# FLH-092 — 私有工作台浏览器验收（合成数据）操作手册

负责人：NAS Claude Code（准备启动脚本与本手册）。浏览器检查由 owner 亲自执行。

**状态：已准备，尚未执行任何浏览器检查。** 下文每个结果栏都留空，只能由 owner
在真实浏览器中填写。代理只用 curl 验证了服务端行为（见第 9 节），这不是浏览器证据。

**这次验收能证明什么，不能证明什么：**
- 使用的是 FLH-089 的**合成数据**（1,000 条记录、3,000 个单元、500 个 Concept），
  只能证明**界面与流程的机制**：保存、打开、分析、反馈、抽取、Concept Review、
  来源追溯、搜索、筛选、分页、重启后数据仍在。
- 分析器是本地规则分析器，抽取器是本地桩（stub），输出是机械生成的文本。在这里
  选择 **Accept** 只是测试按钮和状态流转，**不代表**对法语内容或分类质量的判断。
- 真实数据与真实 provider 的验收是之后单独的一步（第 8 节）。

---

## 0. 三个执行位置

| 标记 | 位置 | 用途 |
|---|---|---|
| **[NAS]** | NAS 上的终端 | 启动、停止、重启会话 |
| **[Mac]** | Mac 上的终端 | 建立 SSH 隧道 |
| **[浏览器]** | Mac 上的浏览器 | 所有界面检查 |

浏览器只连 Mac 本机的 `127.0.0.1:18990`，经 SSH 隧道转到 NAS 的
`127.0.0.1:18990`。服务端不监听局域网地址。

---

## 1. 前提条件与启动

### 1.1 前提 [NAS]

- 工作目录：`~/workspace/flh-nas-claude`
- 需要 `go`、`python3`、`curl`（启动脚本会逐个检查）。
- 需要已构建的前端：`web/dist/index.html` 与 `web/dist/assets/`。缺失时脚本会拒绝启动；
  构建方法见第 7 节“缺少前端构建”。
- 端口 `18990`（服务端）和 `18991`（本地抽取桩）在 NAS 的 `127.0.0.1` 上空闲。
- 会话目录必须在仓库**之外**，并且是**新的或空的**目录。本手册使用
  `~/flh092-session`。

### 1.2 首次启动 [NAS]

```bash
cd ~/workspace/flh-nas-claude
bash scripts/validation/flh092/serve.sh ~/flh092-session
```

脚本会依次：构建服务端 → 启动本地抽取桩与服务端（都只绑定 `127.0.0.1`）→
通过公开 API 写入合成数据（约 2–3 秒）→ 保持前台运行。

**预期输出**（数字以实际为准）：

```text
serve.sh: building the server (fresh run)…
serve.sh: seeding 1000 synthetic records and 500 Concepts…
serve.sh: seed summary: {"unanalyzed": 100, "rejected": 150, "accepted": 250, ...}

FLH-092 workbench session ready (fresh run). Synthetic data only; not network-namespace isolated.
  Server:   http://127.0.0.1:18990/   (PID …, log /home/…/flh092-session/server.log)
  Stub:     http://127.0.0.1:18991  (PID …, log /home/…/flh092-session/stub.log)
  Database: /home/…/flh092-session/fixture.db
  From the Mac:  ssh -N -L 18990:127.0.0.1:18990 <SSH_HOST>
  Then open:     http://127.0.0.1:18990/
Press Ctrl-C to stop. The data stays in /home/…/flh092-session.
```

保持这个终端打开。按 **Ctrl-C** 停止（见第 6 节）。

### 1.3 启动脚本固定的配置

脚本用 `env -i` 清空继承的环境变量，只传入以下设置。你的 shell 里的
`OPENAI_API_KEY`、`DB_PATH` 等不会被带入。

| 设置 | 值 | 含义 |
|---|---|---|
| `DB_PATH` | `~/flh092-session/fixture.db` | 隔离的合成数据库，**从不打开日常数据库** |
| `LISTEN_HOST` / `PORT` | `127.0.0.1` / `18990` | 只监听本机回环地址 |
| `AI_PROVIDER` | `rule-based` | 本地规则分析器，不调用外部服务 |
| `EXTRACTOR_PROVIDER` | `openai`，`OPENAI_BASE_URL=http://127.0.0.1:18991` | 指向本地桩；密钥是假的 `sk-local-fixture-not-a-secret` |
| `EMBEDDING_PROVIDER` / `SEMANTIC_SEARCH` | `disabled` / `disabled` | 不做向量与语义搜索 |
| `HTTP_TRUSTED_ORIGINS` | `http://127.0.0.1:18990,http://localhost:18990` | 去掉默认的 Vite `:5173` 开发例外 |

**关于 `HTTP_TRUSTED_ORIGINS`（已按代码核实）：** 服务端对 POST 等写请求检查 `Origin`。
同源的判断是 `Origin == "http://" + 请求的 Host`
（`internal/transport/http/browser_boundary.go`）。经隧道访问时，浏览器的 Host 和 Origin
都是 `127.0.0.1:18990`，本来就是同源，**不需要**额外的可信来源。脚本显式设置它，只是为了
去掉默认的 `:5173` 例外。Host 允许列表默认已包含 `127.0.0.1` 和 `localhost`。

**隔离说明：** 浏览器必须能连到服务端，所以这个会话**没有**像
`scripts/validation/flh089/run.sh` 那样使用 `unshare -rn` 网络命名空间。隔离只靠
上表的配置：本地分析器、回环地址上的桩、假密钥、关闭向量服务、独立数据库。

---

## 2. 建立隧道 [Mac]

把 `<NAS_SSH_HOST>` 换成你在 Mac 上平时能 `ssh` 登录 NAS 的别名或 `用户@地址`
（例如 `~/.ssh/config` 里的 Host 名）。本手册不假设它叫 `nas`。

```bash
ssh -N -L 18990:127.0.0.1:18990 <NAS_SSH_HOST>
```

- `-N` 表示只转发、不开 shell。终端看起来“卡住”是正常的；保持打开，按 Ctrl-C 关闭隧道。
- 先验证一下（在 Mac 的另一个终端）：

```bash
curl -sS http://127.0.0.1:18990/readyz
```

返回 HTTP 200 即可。若 Mac 本机 18990 已被占用，可以改用
`-L 28990:127.0.0.1:18990`，然后在浏览器中打开 `http://127.0.0.1:28990/`；写操作
仍然是同源请求，不会被拒绝。

---

## 3. 打开工作台 [浏览器]

1. 打开 **`http://127.0.0.1:18990/`**。
2. **预期初始页面：** 标题 “Concept Review — French Learning Hub”。界面默认英文
   （与浏览器语言无关）。顶部有视图按钮 **Learning Records**、**Knowledge Library**、
   **Concept Review**、**Annotation Inspector**、**Experiment Dashboard**，默认打开的是
   **Concept Review**，位置文字类似 `unit 1 of 50 loaded; more units follow in the queue`。
3. 点击顶部的 **Learning Records**（中文界面为“学习记录”），看到记录列表，最新的
   `#1000` 在最上面。

> 按钮名称在本手册中使用英文界面的原文。切换为简体中文后，界面文字会变化，但
> 学习内容、ID、SAME / NEW CONCEPT / INVALID 等决策词保持不变。

---

## 4. 逐步检查

每一步完成后在第 5 节的表格里填写结果。以下 ID（`#1001`、单元 `#3001`、
Concept `#501`）是在**新会话**里按本节顺序操作时的预期值；如果顺序不同，ID 可能不同，
按界面实际显示的为准。

### 步骤 1 — 保存一个问题

1. 在 **Learning Records** 中点击 **Add a learning question**（按钮随后变成
   **Hide question intake**）。
2. 确认默认模式是 **Question**（另一个模式是 **Capture JSON**）。
3. 在 **Your question** 中粘贴以下两行（**保留换行**）：

```text
[fx:9001] Est-ce qu'on dit « je me souviens de cette histoire » ou « je me rappelle de cette histoire » ?
J'ai vu les deux à l'écrit.
```

4. 在 **Where it came from (optional)** 中粘贴：

```text
Question de test synthétique FLH-092, écrite pour la vérification du navigateur.
```

5. 点击 **Save question**。

> `[fx:9001]` 是本地抽取桩的触发标记：桩只为带 `[fx:N]` 的记录生成单元。
> 没有这个标记时，抽取会成功但得到 0 个单元（这本身是合法结果）。

**预期：**
- 按钮短暂显示 **Saving…**，然后提示
  `Saved as new record #1001, not yet analyzed. Open saved record #1001`。
- 表单清空，可以再输入下一条。
- 列表最上面出现 `#1001`，状态 `No analysis`。
- 只输入空格或只填来源时，**Save question** 不可点击。

### 步骤 2 — 打开记录

1. 点击 **Open saved record #1001**。

**预期：**
- 标题 **Record #1001**；**Original input** 中保留了两行（换行可见）；
  **Original context** 显示上面的来源。
- **Analysis versions** 下显示 `No analysis.`。
- **Knowledge extraction** 下显示 `No extraction stored.`。
- 打开记录不会自动分析或抽取。

### 步骤 3 — 请求分析

1. 在 **Analysis versions** 区域点击 **Request analysis…**，出现说明文字。
2. 点击 **Create a new analysis version**。

**预期：**
- 提示 `Created analysis v1 with rule-based:v2:fr_l2_taxonomy_v1. It is unreviewed until a human gives feedback.`
- 显示 **Analysis v1**，**Effective interpretation** 中标注
  `Unreviewed candidate: no human has accepted or corrected it.`
- 规则分析器对这个问题给出的是较弱的猜测（例如 `grammar`，置信度 0.5），这是机械输出。

### 步骤 4 — 人工反馈

1. 在 **Feedback for analysis v1** 中选择 **Accept**。
2. 点击 **Record "accepted" for analysis v1**。

**预期：**
- 提示 `Recorded feedback #… (accepted) for analysis v1. This is the latest analysis, so the record's state follows it.`
- **Feedback history** 中出现一条 `accepted`。
- 这里的 Accept 只用于测试流程，**不是**对分析质量的认可。也可以试一次 **Correct**
  （需要填写 **Corrected category** 或 **Corrected explanation**）。

### 步骤 5 — 请求抽取

1. 在 **Knowledge extraction** 区域点击 **Request extraction…**。
2. 阅读说明后点击 **Send to the extraction provider**。

**预期：**
- 提示 `Stored extraction v1 with 3 units.`
- 摘要类似 `Current: v1 · Selection: automatic · Latest stored: v1 · 1 version stored`。
- **Extracted units** 下列出 3 个单元（`#3001`–`#3003`），内容是
  `Synthetic … statement v1 …` 这类合成文本，每个单元显示 `Awaiting concept review.`，
  并有链接 **Review unit #3001 in Concept Review** 与 **Inspect unit #3001**。

### 步骤 6 — Concept Review（从记录进入）

1. 点击 **Review unit #3001 in Concept Review**。

**预期：**
- 标题 **Concept Review for record #1001**，只显示该记录待审的单元。有
  **← Back to record #1001**。
- **Knowledge Unit (evidence)** 中显示 `synthetic topic 003 note 9001-0`。
- **Exact identity matches** 显示 `No exact-signature concept exists for this identity.`
- **Reviewed identity (for NEW CONCEPT)** 已预填 `target` =
  `synthetic topic 003 note 9001-0`、`pedagogical_intent` = `usage`。

2. 在 **Human decision** 中点击 **NEW CONCEPT**（点击即发送，没有二次确认）。

**预期：**
- 提示 `Created concept #501 and seeded SAME.`
- 单元 `#3001` 离开队列，界面显示该记录剩下的待审单元（`#3002`、`#3003`）。
- 点击 **← Back to record #1001**，单元 `#3001` 显示
  `Not awaiting review (already resolved or marked INVALID).`

### 步骤 7 — 来源追溯（Knowledge Library）

1. 点击顶部 **Knowledge Library**。
2. 在 **Search learned material** 中输入 `9001`，点击 **Search**。
3. 打开结果中的 Concept `#501`（`synthetic topic 003 note 9001-0`）。
4. 在 **Currently supporting this concept (1)** 下点击 **View source record #1001**。

**预期：**
- 结果显示 `1 unit filed here, 1 currently supporting · concept #501`。
- Concept 状态为 active（有支持）。
- 来源页标题 `Where unit #3001 came from: learning record #1001`；
  **What the learner wrote** 中是第 1 步输入的原文，**换行保留**；
  **Context** 是来源文字；并显示所用的 **Extraction v1** 与分析版本。

### 步骤 8 — 搜索、筛选与跳转

在 **Learning Records** 中：

1. **Search text** 输入 `exemple 42`，点击 **Search**。
   预期：提示 `Showing records whose original input or context contains “exemple 42” (letter case ignored; accents must match).`，列表只含 10 条匹配记录（`#915`、`#818`、`#721` …）。
2. 改为 `EXEMPLE 42`：结果与上一步相同（忽略大小写）。
3. 改为 `synthetique`（无重音）：预期 `No records contain “synthetique” with the current filters.`；
   改为 `synthétique`：只出现 `#1001`（来源文字中有这个词；不做重音折叠）。
   再试 `souviens`：只出现 `#1001`。
4. 改为 `%`：预期没有结果（`%` 按字面匹配，不是通配符）。点击 **Clear search**。
5. 搜索 `exemple 42` 后，**Record state** 选 `accepted`，再在 **Effective category**
   中选一个类别：列表随筛选缩小；无匹配时显示相应提示。
6. 在 **Go to record #** 输入 `500`，点击 **Go**。预期：
   `Showing records from #500 and older. Newer records are not shown.`（有搜索或筛选时，
   列表从 `#500` 或更早的匹配记录开始）。点击 **Show newest records** 恢复。
7. 输入 `abc` 后点 **Go**：预期 `Enter a record number, such as 42.`
8. 在搜索/筛选/跳转都生效时打开一条记录，再点 **← Back to records**：
   搜索词、筛选和位置都保持不变。
9. 不带搜索时滚到底部点击 **Load older records**：继续加载更旧的记录。
10. **长文本：** 打开 `#7` 或 `#57`（约 2,600 字符的原文）。检查换行、无横向溢出、
    滚动正常。

### 步骤 9 — Concept Review 的位置与分页（通用队列）

1. 点击顶部 **Concept Review**。预期位置文字：
   `unit 1 of 50 loaded; more units follow in the queue`。
2. 点击 **skip →** 若干次（例如到 unit 5），并在 **Search existing concepts** 的
   搜索框里改一下文字。
3. 切换到 **Learning Records**，再切回 **Concept Review**。预期：
   回到同一个单元，搜索文字也还在；位置文字为
   `unit … of … loaded from where you left off; earlier units are not loaded and more follow`，
   并出现 **Start from the beginning of the queue**。
4. 点击 **Start from the beginning of the queue**：回到 `unit 1 of 50 loaded; …`。
5. 一直点击 **skip →** 到 `unit 50 of 50 loaded; …`，再点一次 **skip →**。预期：
   短暂显示 `loading…`，然后进入下一页：`unit 51 of 100 loaded; more units follow in the queue`。
6. **在页尾做决定：** 在 unit 100（已加载的最后一个）上做一个明确的决定（例如
   **INVALID**，或选中一个 Concept 后 **SAME → selected**）。预期：下一个单元自动出现，
   而不是显示队列为空。
7. **大范围搜索：** 在 **Search existing concepts** 中输入 `synthetic concept`。预期：
   `Showing 50 of 500 matching concepts. Narrow the search, or show more.`；点击
   **Show 50 more** 后显示 100 个。显示、搜索或选择候选都**不会**记录任何标注。
8. **浏览器整页刷新（观察项）：** 当前实现把队列位置保存在页面内存中，整页刷新后会回到
   Concept Review 第一个单元。请记录实际表现，不作为失败判定。

### 步骤 10 — Capture JSON 模式

1. 在 **Learning Records** 中打开 **Add a learning question**，在 **Question** 模式里
   随便输入一句话，**不要保存**。
2. 切换到 **Capture JSON**，在 **Capture JSON** 文本框中粘贴仓库中的示例
   `examples/captures/chatgpt-example.json`（也可用 **Load from file** 选择本地副本）：

```json
{
  "schema_version": "learning_capture_v1",
  "capture_id": "chatgpt-example-001",
  "source": "chatgpt-web",
  "original_input": "Je parle japonais ou je parle le japonais ?",
  "original_context": "Whether French language names require an article after parler.",
  "analysis": {
    "category": "grammar",
    "explanation": "After parler, a language name is normally used without an article.",
    "confidence": 0.9,
    "uncertainty": "Usage may vary when the language is treated as an object."
  },
  "discussion_summary": "Compared parler japonais with apprendre le japonais."
}
```

3. 点击 **Import capture**。预期：
   `Imported capture chatgpt-example-001 as new record #… with imported analysis #… (unreviewed). Open imported record #…`
   打开后，导入的分析显示为未审阅（`Unreviewed candidate…`），导入**不代表**人工接受。
4. **重放（replay）：** 不改任何内容，再点一次 **Import capture**。预期：
   `Already imported: capture chatgpt-example-001 with identical content is record #…. Nothing new was stored.`
   ——同一 `capture_id` + 相同内容 = 返回已有记录，不会重复。
5. **冲突（conflict）：** 把 `original_input` 中的 `japonais ou` 改成 `chinois ou`，
   保持 `capture_id` 不变，再导入。预期：以 `Conflict (409)` 开头的提示，什么都没有被
   改写。真正的**新**导入需要新的 `capture_id`（例如 `chatgpt-example-002`）。
6. 切回 **Question** 模式：第 1 步输入的草稿还在；再切到 **Capture JSON**：JSON 也还在。

### 步骤 11 — 停止与重启后数据仍在

1. **[NAS]** 在运行脚本的终端按 **Ctrl-C**。预期输出：

```text
serve.sh: stopped the server and stub started by this run. Data kept in /home/…/flh092-session
serve.sh: restart with the same command: bash scripts/validation/flh092/serve.sh /home/…/flh092-session 18990 18991
```

2. **（可选）未知结果测试** [浏览器]：服务端停止期间，在 **Question** 模式中输入一个新问题
   并点击 **Save question**。预期：显示 `No confirmation was received (…), so the question may or may not have been saved. Your text is kept. …`
   ——是“未确认”，不是“失败”；文字保留。
3. **[NAS]** 用同一个命令重启：

```bash
cd ~/workspace/flh-nas-claude
bash scripts/validation/flh092/serve.sh ~/flh092-session
```

   预期：`building the server (restart run)…`，**没有** seeding 行，最后显示
   `FLH-092 workbench session ready (restart run).`
4. **[Mac]** 如果隧道断了，重新执行第 2 节的 `ssh` 命令。
5. **[浏览器]** 若做了第 2 小步：点击 **Check whether it was saved**（预期
   `It was not saved. Your text is kept and can be saved now.`）或
   **Send the same question again**（预期保存成功）。之后再点一次
   **Send the same question again** 或重新检查，都不会产生第二条记录。
6. **[浏览器]** 刷新页面，在 **Learning Records** 中确认 `#1001`、导入的记录、
   `#501` Concept（Knowledge Library 搜索 `9001`）仍然存在。

### 步骤 12 — 布局、键盘与语言

1. 窄窗口（约 400 px 宽）和宽窗口下，各视图无横向滚动，长文本正常换行。
2. 只用 **Tab** / **Shift+Tab** / **Enter** / **Space** 完成一次：保存问题 → 打开记录 →
   请求分析（含确认按钮）。焦点可见，确认按钮出现时焦点移到确认按钮。
3. 使用界面上的 **Language** 选择切换到 **简体中文**：应用文字变成中文；学习内容、
   法语例句、ID、决策词（SAME、NEW CONCEPT、INVALID 等）不变。刷新后仍为中文。
   切回 **English**。
4. 观察响应速度：打开 Learning Records、搜索、打开 Concept Review、加载下一页的体感。

---

## 5. 结果记录表（由 owner 填写）

浏览器与系统：______________________　日期：__________　会话目录：______________

| 步骤 | 检查内容 | 结果（通过 / 失败 / 未做） | 备注 |
|---|---|---|---|
| 1 | 保存问题（含换行与来源） | | |
| 2 | 打开记录：无分析、无抽取 | | |
| 3 | 请求分析：v1，unreviewed | | |
| 4 | 人工反馈 Accept / Correct | | |
| 5 | 请求抽取：3 个单元 | | |
| 6 | 从记录进入 Concept Review，NEW CONCEPT | | |
| 7 | Knowledge Library 来源追溯 | | |
| 8.1–8.4 | 文本搜索（大小写、重音、`%`） | | |
| 8.5 | 搜索 + 状态 + 类别筛选 | | |
| 8.6–8.7 | 跳转到记录 # 与无效输入 | | |
| 8.8 | 打开记录后返回，状态保持 | | |
| 8.9 | Load older records | | |
| 8.10 | 长文本布局 | | |
| 9.1–9.4 | 队列位置跨视图保持、从头开始 | | |
| 9.5 | 越过页尾加载下一页 | | |
| 9.6 | 页尾决定后出现下一个单元 | | |
| 9.7 | Showing 50 of N / Show 50 more | | |
| 9.8 | 整页刷新后的表现（观察项） | | |
| 10.1–10.3 | Capture JSON 导入，分析为 unreviewed | | |
| 10.4 | 相同内容重放：不重复 | | |
| 10.5 | 同 ID 不同内容：409 冲突 | | |
| 10.6 | 两种模式的草稿都保留 | | |
| 11.1 | Ctrl-C 停止，数据保留 | | |
| 11.2 | （可选）服务端停止时保存 = 未确认 | | |
| 11.3 | 重启：不重新写入合成数据 | | |
| 11.5 | 检查是否已保存 / 重发：无重复 | | |
| 11.6 | 重启后记录与 Concept 仍在 | | |
| 12.1 | 窄/宽窗口布局 | | |
| 12.2 | 键盘操作流程 | | |
| 12.3 | English / 简体中文 切换 | | |
| 12.4 | 响应速度体感 | | |

---

## 6. 停止与清理 [NAS]

- **停止：** 在运行脚本的终端按 **Ctrl-C**。脚本只停止它自己启动的服务端和桩，不会碰
  其他进程（例如日常实例或其他演示）。数据库保留。
- **意外退出：** 若服务端或桩自行退出，脚本会停止另一个并以非零状态退出，提示查看
  `~/flh092-session/server.log` 与 `stub.log`。
- **重新开始一个全新会话：** 使用另一个空目录，例如
  `bash scripts/validation/flh092/serve.sh ~/flh092-session-2`。
- **验收结束后**可以删除会话目录：`rm -rf ~/flh092-session`（只包含合成数据）。
- 写入合成数据中途被中断的目录会被拒绝重用（`incomplete seed`），请换一个空目录。

---

## 7. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| **[Mac]** `ssh` 报 `Could not resolve hostname` 或认证失败 | `<NAS_SSH_HOST>` 写错 | 先确认 `ssh <NAS_SSH_HOST>` 能登录，再加 `-N -L …` |
| **[Mac]** `bind [127.0.0.1]:18990: Address already in use` | Mac 本机端口被占用 | 改用 `-L 28990:127.0.0.1:18990`，浏览器打开 `http://127.0.0.1:28990/` |
| **[Mac]** `channel …: open failed: connect failed: Connection refused` / 浏览器连不上 | NAS 上的会话没在运行 | 在 NAS 上确认脚本终端显示 `session ready`；必要时重启 |
| **[浏览器]** 显示 `request host is not allowed`（403） | 用了 NAS 主机名或局域网 IP 访问 | 只通过隧道访问 `http://127.0.0.1:<端口>/` 或 `http://localhost:<端口>/` |
| **[NAS]** `port 18990 on 127.0.0.1 is already in use` | 已有会话或其他服务在用 | 停掉旧会话；或换端口：`serve.sh ~/flh092-session 18992 18993`，隧道改为 `-L 18992:127.0.0.1:18992` |
| **[NAS]** `stub port 18991 … already in use` | 桩端口被占用 | 第三个参数换一个端口，例如 `serve.sh ~/flh092-session 18990 18995` |
| **[浏览器]** 写操作报 `cross-origin browser request is not allowed`（POST 403） | 页面和 API 不是同一来源：例如通过 Vite 开发服务器（`:5173` 之外的端口）或别的代理访问 | 直接打开隧道地址 `http://127.0.0.1:<端口>/`；不要混用 `localhost` 页面与其他来源。脚本设置的 `HTTP_TRUSTED_ORIGINS` 只是额外例外，同源访问不依赖它 |
| **[浏览器]** `Extraction is not enabled on this server …` | 连到了别的服务端（例如日常实例，抽取默认关闭），而不是本会话 | 确认隧道目标端口是 `18990`，NAS 终端显示本会话 `ready` |
| 抽取成功但 `0 units` | 问题中没有 `[fx:N]` 标记 | 合成桩的预期行为；使用第 1 步给出的文字 |
| **[NAS]** `missing frontend build (…/web/dist)` | 前端未构建 | `cd ~/workspace/flh-nas-claude/web && npm ci && npm run build`，然后重新启动 |
| **[NAS]** `warning: web/src has files newer than web/dist` | 前端源代码比构建新 | 浏览器看到的是旧构建；需要时重新 `npm run build` |
| **[NAS]** `WORK_DIR must be a new/empty directory or one seeded by this script` | 目录里有其他文件 | 换一个新目录 |
| **[NAS]** `WORK_DIR must be outside the repository` | 目录在仓库内 | 使用 `~/flh092-session` 这类仓库外路径 |
| **[NAS]** `server did not become ready` | 服务端启动失败 | 查看 `~/flh092-session/server.log` |

---

## 8. 之后：真实数据验收（单独执行，简要清单）

这一步不使用 `serve.sh`，也不在本次 FLH-092 范围内执行。

- [ ] **先备份**日常数据库（按 `docs/RELEASE.md` 的备份步骤），确认备份可读。
- [ ] 在日常实例（`http://127.0.0.1:8080`，Compose）上，通过隧道
      `ssh -N -L 8080:127.0.0.1:8080 <NAS_SSH_HOST>` 访问。
- [ ] **真实 provider 调用可能产生费用。** 分析（若 `AI_PROVIDER=openai`）和抽取
      （`EXTRACTOR_PROVIDER=openai`）只在你点击确认按钮时发送一次，从不自动重试；
      是否启用、何时调用由你决定。抽取默认关闭，开启需要你自己修改配置。
- [ ] 用一条真实问题走一遍：保存 → 打开 → 分析 → 反馈 → （如已启用）抽取 →
      Concept Review → Knowledge Library 来源。
- [ ] 在真实数据上检查搜索、筛选、跳转、队列分页与长文本布局。
- [ ] 判断分析与抽取的**语言质量**（合成数据无法提供这一证据）。
- [ ] 将结果另行记录为 owner 证据（新的验证说明），不要改写本文件中的合成数据结果。

---

## 9. 代理执行的验证（仅服务端，非浏览器证据）

所有检查都在 NAS 上一次性的临时目录中进行（会话 scratchpad 下的 `flh092/`），端口
`28990`–`28995`；没有打开日常数据库，没有联系真实 provider。

| 检查 | 命令（摘要） | 结果 |
|---|---|---|
| 语法 | `bash -n scripts/validation/flh092/serve.sh` | 通过（本机未安装 shellcheck） |
| 首次启动 | `serve.sh <tmp>/work 28990 28991` | 构建、写入 1,000 条记录 / 500 个 Concept（2.2 秒、4,176 个请求），`session ready` |
| 就绪 / 静态 | `curl /healthz`、`/readyz`、`/`、`/assets/index-*.js` | 200、200、200 `text/html`、200 `text/javascript` |
| API | `/api/learning-records?limit=2`、`?q=exemple%2042`、`/api/reviewable-units?limit=50` | 200；搜索返回匹配记录；分页 50 条带 `next_cursor` |
| 手册中的搜索示例 | `q` = `exemple 42` / `EXEMPLE 42` / `synthetique` / `synthétique` / `%` / `souviens` | 10 / 10 / 0 / 1（#1001）/ 0 / 1（#1001）。注意 `écrit` 会匹配 21 条（合成长文本含 “écrite”），所以手册不用它 |
| Host 检查 | `Host: localhost:28990` / `Host: evil.example:28990` | 200 / 403 |
| 浏览器式写入 | `POST /api/captures`，`Origin` 与 `Sec-Fetch-Site: same-origin` | 201 新记录 #1001；相同内容重发 200；`Host`/`Origin` 为 `127.0.0.1:8080`（隧道换端口）200 |
| 跨源写入 | `Origin: http://evil.example`，`Sec-Fetch-Site: cross-site` | 403 `cross-origin browser request is not allowed` |
| 流程 | 分析 → `accepted` 反馈 → 抽取 | 分析 v1（rule-based）；反馈 201；抽取 3 个 active 单元 #3001–#3003 |
| Concept 与来源 | 为 #3001 创建 Concept 并 seed SAME；`/knowledge-library/concepts?q=9001`；`/knowledge-library/units/3001/source` | Concept #501，1 个支持单元；来源返回记录 #1001 原文（含换行） |
| Capture JSON | 导入 `chatgpt-example.json` 两次；改内容同 ID 再导入 | 201 / 200（`created:false`）/ 409 |
| 端口冲突 | 会话运行时用同一服务端端口、同一桩端口、同一目录启动 | 均以状态 2 拒绝，未创建目录 |
| Ctrl-C | 向脚本进程组发送 SIGINT | 两个子进程停止，端口释放，WAL 已合并，数据保留 |
| 重启持久性 | 同一目录再次启动 | `restart run`、无 seeding、`seed.json` 校验和不变，#1001 及其抽取仍在 |
| 仅 TERM 脚本 | 只向脚本 PID 发送 SIGTERM | 退出码 0，服务端与桩都被停止；无关的已有进程未受影响 |
| 意外退出 | `kill -KILL` 服务端 | 脚本退出码 1，桩被停止，提示查看日志 |
| 拒绝情形 | 非空外来目录、仓库内目录、未完成 seeding、目录含 `.env`、端口 80、两端口相同、无参数、缺少 `web/dist`（在临时假仓库中测试） | 均以状态 2 拒绝并给出明确信息 |

**未验证：** 任何浏览器渲染、键盘、布局、语言切换与响应速度；`web/src` 比构建新时的警告
（未修改前端文件以触发它）；macOS 端的 `ssh` 隧道。

**限制：**
- 会话不在网络命名空间中，隔离只依赖配置（见 1.3）。
- 合成数据只证明机制，不证明语言质量或真实规模。
- 整页刷新会丢失 Concept Review 的位置和问题输入的未保存草稿（当前实现即如此）。
