# 从真实对话生成一个 Capture

配合[两次试用演示](TWO_TRIAL_DEMO.zh-CN.md)使用。每次先完成一段真实法语学习对话，
选定其中**一个学习交互**：一个原始问题及其相关讨论。不要把两个独立问题合并。
原问题必须非空且不超过 10,000 UTF-8 字节；超长时先由你选择一个完整的原始问题，
不要让模型截断、改写或编造问题来适配限制。

复制下面整段提示词到该对话末尾，替换两处 `<<...>>`。`capture_id` 使用演示命令生成的
本次 ID；“原始问题”直接粘贴你当时的完整提问。输出后人工核对原文、上下文和可选分析，
再保存 JSON。这里的提示词不是校验器；最终以现有服务端校验为准。

```text
请把本对话中指定的一个法语学习交互导出为 French Learning Hub 的
learning_capture_v1。仅依据本对话中实际出现的信息。

本次 capture_id：<<粘贴本次生成的 ID>>
本次要保存的原始问题：
<<逐字粘贴当时的完整提问>>

只输出一个合法 JSON 对象，不要 Markdown 围栏、前后说明、注释、数组或多个对象。
使用双引号，正确转义引号、反斜杠和换行，不要尾逗号。

顶层只能有以下字段：
- schema_version：固定字符串 "learning_capture_v1"。
- capture_id：逐字使用上面提供的 ID。
- source：固定字符串 "chatgpt-web"。
- original_input：准确保留上面指定的原始问题，包括拼写错误、标点和换行。
  不翻译、不纠正、不把你的回答替换成我的问题，也不拼接其他独立问题。
- original_context：字符串，简短概括理解该问题所必需、且对话明确提供的上下文。
  不推测我的水平、经历、目的或未出现的事实；没有相关上下文时用空字符串 ""。
- analysis：可选对象，整个对象可以省略，规则见下文。
- discussion_summary：可选字符串，简短概括实际讨论、结论和未解决之处。
  保留争议/不确定性；没有足够依据时省略，不把推测写成已确认事实。

analysis 只是待人工审核的候选解释，不是人工认可、标注或检索评估 truth。
仅当本次讨论足以支持分类、解释及一个有依据的 confidence 数值时才提供它。
不要为了凑齐字段猜测 confidence；如果对话没有支持这个数值的依据，省略整个 analysis。
尤其不要惯例填入 0.9、1 或用 0 代替“未知”。省略 analysis 仍是合法 Capture。
若提供 analysis，只能包含：
- category：一个小写字符串，严格从 fr_l2_taxonomy_v1 选择：
  vocabulary, grammar, morphology, orthography, pronunciation, pragmatics,
  discourse, comprehension, translation, mixed, other。
- explanation：非空字符串，只记录本次讨论支持的解释。
- confidence：JSON 数字，有限值且在 0 到 1（含边界）之间；不是百分数字符串，
  也不代表校准概率或人工确认。
- uncertainty：可选字符串，说明实际存在的限制、歧义或未解决问题。
不要把 KnowledgeUnit 的 kind（如 usage、expression）用作这里的 category。

字段上限按 UTF-8 字节计算（不是汉字个数），服务端会去除字段首尾空白：
- capture_id：1–200 字节；匹配 [A-Za-z0-9][A-Za-z0-9._:-]*。
- original_input：1–10,000 字节；original_context：0–10,000 字节。
- analysis.explanation：1–20,000 字节；analysis.uncertainty：0–5,000 字节。
- discussion_summary：0–5,000 字节。
摘要与解释保持简短；不能为了长度限制改写原始问题。

不要添加数据库 ID（entry_id、analysis_id、id 等）、时间戳、version、analyzer、
provenance、feedback、annotations、KnowledgeUnits、Concepts、评估结果或任何其他字段。
上面的人类输入标签也不是 JSON 字段。不要把本提示词或占位符保存为学习内容。

ID 规则：每个不同交互/不同试用必须使用一个新 ID，例如带 chatgpt- 前缀的 UUID。
不要沿用另一试用或仓库示例的 ID。同一次导入的重试必须直接重交已经保存的原 JSON：
保持 ID 和全部 JSON 不变，不要重新生成内容，也不要生成新 ID。
```

服务端复用的约束见 [Capture](../internal/domain/capture.go)、
[Entry](../internal/domain/entry.go)、[Analysis](../internal/domain/analysis.go) 和
[HTTP 请求结构](../internal/transport/http/handler.go)。CLI 原样发送，最多读取 1 MiB；
首尾空白裁剪是服务端既有行为，不保证逐字节保留输入文件。
