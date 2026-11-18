# Proposed AGENTS.md section (not applied: AGENTS.md is a shared file)

To add after "Speaking v1 (private workbench)" once the owner accepts the local
transcription service (owner decision D1 in `../SPEAKING-MODEL-V1.md`):

```markdown
Local Speaking transcription (tools/speaking, optional):

- `tools/speaking/` is a local French transcription service and its research
  tooling: pinned Whisper revisions and public datasets (`pins.py`), the frozen
  speaker/book-disjoint evaluation set, training and evaluation commands, and a
  loopback-only HTTP service answering FLH's existing transcription client
  (`flh_speaking_transcription_v1`, `tools/speaking/CONTRACT.md`).
- Decoding policy `flh_speaking_transcribe_v1`: forced French, greedy, no
  prompt; abstains (`no_speech`, `not_french`) instead of inventing text on
  silence, noise or other languages. A transcript is a draft the learner
  confirms; homophones (ces/ses, a/à, leur/leurs) are the model's guess.
- The service keeps nothing: audio is decoded in memory, never written, cached
  or logged. Never train on learner recordings without an explicit owner
  decision (consent, retention limit, deletion path).
- Its `deployment_id` (GET /manifest) is the model identity; any weight, rule,
  code or library change yields a new one. Set it as
  `SPEAKING_TRANSCRIPTION_MODEL`.
- Agents must not run AWS commands for it; `tools/speaking/aws/README.md` holds
  the owner's commands.
```
