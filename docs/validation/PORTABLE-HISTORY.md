# Portable learning history (2026-11-19)

Synthetic disposable databases only. No migration, no provider call, **no import**: the check
of a file is a report and never writes.

## Export (`learning_history_export_v1`)

The export is NDJSON: a `header` line, one line per record, and a `footer` with the record count
and the SHA-256 of the record lines.

| Record | Portable `key` (matched by the check) | Optional text |
|---|---|---|
| `listening_material` | `listening:script:<pack/script>` or `listening:video:<id>` | none |
| `speaking_take` | `speaking:prompt:<prompt_id>:take:<n>` | transcript texts (`transcripts`) |
| `writing_draft` | `writing:prompt:<prompt_id>:draft:<v>` or `writing:learner-task:<created_at>:draft:<v>` | draft text (`notes`) |
| `notebook_record` | `notebook:capture:<capture_id>` | the record's words, context and attempt (`notes`) |

**What is and is not exported:**
- Never exported: audio bytes (never stored) and credentials or configuration (never read).
  `?audio=` and `?credentials=` are refused with `400`, and tests check the files for credential
  patterns.
- Texts are off by default. Each text is `included`, `omitted` (it exists but was not selected)
  or `absent` (the record has none), and the header counts the omitted ones.
- Each record also carries the server's own `ref`, which is not portable.

**Two files:**
- `.ndjson`: opens as text; the app's check reads it.
- `.txt`: a readable copy for any editor; not importable.

**Where it is offered:**
- Workbench: Review Today → **Export or check your learning history…**
- CLI: `go run ./cmd/history-export -dir DIR [-name NAME] [-transcripts] [-notes] [-url URL]`. It
  writes both files into `DIR` only. A name must be a plain name (no separator, no `..`, no
  leading dot), and the directory must exist. It never overwrites a file or follows a planted
  link, and checks paths before any request.

## Check a file (`POST /learning-history/import-preview`)

| Integrity | Meaning |
|---|---|
| `complete` | footer count and SHA-256 match |
| `truncated` | no footer, the count differs, or an incomplete line (named by number) |
| `corrupted` | valid lines that do not match the checksum (edited after export) |
| `unchecked` | an older `speaking_attempt_export_v1` file (`GET /speaking/export`): no header or checksum; its missing parts are listed |
| `unreadable` | not an export |

**Row statuses:**
- `new`: no stored record has the key.
- `same`: the stored record matches.
- `conflict`: the fields differ and are listed. The proposed resolution is to keep the stored
  record: records are append-only and never overwritten, so the file's version would be skipped.
- A text omitted on either side is never reported as a difference.

## Items 071–080

| Item | Status | Evidence |
|---|---|---|
| 071 preview with optional texts | Implemented | `TestHistoryExport_Options…`, `HistoryExport.test.tsx` |
| 072 no audio, no credentials | Implemented | refusal test; pattern scan |
| 073 format version, stable references | Implemented | header `format`; stable keys asserted |
| 074 omitted vs absent | Implemented | take 1 `omitted`, take 2 `absent`; UI wording |
| 075 truncated or corrupted, read-only | Implemented | no footer, cut line, edited value, garbage; table counts unchanged |
| 076 conflicts with a proposed resolution | Implemented | a version added after export → `conflict [transcripts]`, keep stored |
| 077 older exports | Implemented | `speaking_attempt_export_v1` → `unchecked`, 0 conflicts, missing parts listed |
| 078 no path escape | Implemented | `TestSafeFile_RefusesEveryEscape`, `TestWriteNew_NeverOverwritesOrFollowsALink`, `TestRun_…` |
| 079 text vs app import | Implemented | `files` list and UI wording |
| 080 synthetic round trip | Verified | same server: all `same`; fresh server: all `new` |

**Defect found and fixed:** an older export's empty transcript list read as `null` and was
reported as a conflict. `null` and `[]` now both mean "no version".
