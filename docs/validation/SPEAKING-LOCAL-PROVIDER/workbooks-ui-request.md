# Request to the workbooks lane (Speaking UI): local transcriber wording

Not applied here: `web/` belongs to the workbooks lane. No API change is needed.

## What changed in the backend

`SPEAKING_TRANSCRIPTION_PROVIDER=local` (this task) sends a take's audio to the
operator's own transcription service. It appears in `GET /speaking/prompts`
as `providers.transcription.name =
"local:<deployment_id>:speaking_transcription_v1"`, for example
`local:whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/ac92e8688ef9e17b:speaking_transcription_v1`.
Nothing is billed, and the service stores nothing.

Two more facts matter to the UI:
- With the local provider, a connection closed without an answer is a definite
  failure (`failed`, `provider_unavailable`), so "Send again" works without
  `confirm_unknown_retry`. Only a timeout is `unknown`.
- `invalid_output` now also covers audio the service refuses: longer than
  120 s, undecodable, or empty. As before, it covers silence and non-French
  speech.

## Strings that are wrong for a local transcriber

| Key | Today (en) | Problem |
|---|---|---|
| `speaking.transcribe.confirmText` | "… once to {provider}. The request may be billed." | not billed; `{provider}` is a long identity |
| `speaking.transcribe.sendAgain` | "Send audio again (may be billed twice)" | not billed |
| `speaking.transcribe.outcomeUnknown` | "… It may have been processed and billed. …" | not billed |
| `speaking.failure.invalid_output` | "the answer was not usable" | fine, but could say what to do |

## Proposed (choose by `providers.transcription.name` starting with `local:`)

| Key | en | zh-CN |
|---|---|---|
| `speaking.transcribe.confirmTextLocal` | "This sends the audio of take {n} ({duration}, {size}, {type}) once to your own transcription service on this machine. Nothing is billed." | "这会把第 {n} 段录音的音频（{duration}，{size}，{type}）发送给本机上你自己的转写服务一次。不会计费。" |
| `speaking.transcribe.sendAgainLocal` | "Send audio again" | "再次发送音频" |
| `speaking.transcribe.outcomeUnknownLocal` | "The last transcription took too long and its outcome is unknown. Nothing was retried. Sending again is free." | "上一次转写耗时过长，结果未知。没有自动重试。再次发送不会计费。" |
| `speaking.failure.invalid_output` (both providers) | "the answer was not usable (silence, another language, or audio the transcriber could not read); type what you said" | "结果不可用（静音、其他语言，或转写服务无法读取的音频）；请输入你说的话" |

Keep showing the full provider name somewhere (for example in the
"Machine transcript received from {transcriber}" line), because it is the
provenance.
