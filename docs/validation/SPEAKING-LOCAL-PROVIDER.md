# Speaking: local transcription provider and model evaluation (v2)

Follows `SPEAKING-MODEL-V1.md` (whose files are unchanged). Scope: FLH's
transcription provider wiring, `tools/speaking`, and model evaluation. The
practice queue and the Speaking/public-demo UI belong to other lanes; nothing
there was edited. No AWS command, no OpenAI call, no learner data: audio is the
frozen public MLS/FLEURS/SLR57 material from v1 plus synthetic signals.

Real inference (the pretrained Whisper service answering FLH's normal API) is
recorded in `SPEAKING-LOCAL-PROVIDER/real-inference/`; fixtures and fakes live
only in Go tests (`internal/speaking/speakingfake`,
`internal/transport/http/speaking_local_integration_test.go`).

## Summary

- **FLH can now use the local service.** With `SPEAKING_TRANSCRIPTION_PROVIDER=local`,
  the stored provenance is `local:<deployment_id>:speaking_transcription_v1`. The
  provider has its own URL and timeout, sends no key, and runs beside OpenAI feedback.
- **Real requests work end to end.** Pretrained Whisper answered FLH's normal
  Speaking API, and the learner's confirmation step is unchanged.
- **Running the real service found three gaps, now fixed:**
  - a restarted service left an "unknown" outcome that blocked the next click;
  - refused audio was reported as an outage;
  - the service's deadline started only after the queue, so FLH gave up first.
- **whisper-small beats whisper-base everywhere:** 12–20 WER points better on
  MLS test, FLEURS and accented French, with paired CIs that exclude 0 (every
  MLS and SLR57 speaker is better; 124 of 129 FLEURS sentence groups). It
  costs about 3× the latency (17 s for a 120 s take) and 1.4 GiB of memory.
  Both v1 results reproduce exactly with this code.
- **The language rule wrongly refuses some correct French.** That happens on
  1.6–4.7 % of accented takes (small 1.6–3.7 %, base 4.0–4.7 %) and on native
  takes of 1–2 s.
- **Warning-only would be worse.** It turns every English or Mandarin answer
  into a fluent French "transcript". A stricter threshold, P(fr) < 0.01, keeps
  the protection and rescues most accented takes (proposed, not applied).
- **Noise:** quiet speech is fine. Noisy speech and background talkers are
  transcribed rather than refused, and confidence cannot tell them apart; the
  learner's check remains the safeguard.
- **Reproducible builds:** hash-locked requirements; two builds give the same
  `deployment_id`. `tools/speaking/RUNBOOK.md` covers deploy, check and roll back.
- **Training:** the pilot lost punctuation because its targets had none. The
  controlled punctuated-target experiment is prepared, with data pinned. Its
  local smoke resumes deterministically after SIGKILL and keeps punctuation
  (A5 passes), but shows no accuracy gain: KEEP_BASELINE. The 180-step AWS job
  is specified and blocked on a budget.
- **Recommendation: serve pretrained whisper-small** through the local provider (§8).

## Work packages

| # | Package | Status | Evidence |
|---:|---|---|---|
| 1 | Port the smallest working local provider | implemented, verified | §1 |
| 2 | Real pretrained Whisper request through FLH's endpoint | verified | §2 |
| 3 | Confirmation step kept; provenance in the saved result | verified | §2 |
| 4 | Local transcription beside the feedback provider | verified | §2 |
| 5 | Identity, version and timeout visible and verifiable | implemented, verified | §1, §2 |
| 6 | Startup, readiness while loading, recovery after restart | verified; one gap fixed (lost answer after a restart) | §1, §2 |
| 7 | Invalid format, empty, overlong, oversized input through the API | verified; overlong/undecodable now `invalid_output` | §2 |
| 8 | Browser formats against the local provider | verified (webm/opus, m4a, mp3, wav; ogg refused by FLH) | §2 |
| 9 | Slow inference, cancellation, duplicates; nothing left behind | verified; service deadline now counts from arrival | §1, §2 |
| 10 | whisper-base vs whisper-small: WER, latency, peak memory | covered by v1; paired test added; v1 reproduced with this code | §3 |
| 11 | Short clips and accented French separately; premature language rejection | verified; examples recorded (correct French refused) | §4 |
| 12 | Warning-only language policy on a separate sample | evaluated: not recommended (turns English/Mandarin into French text); P(fr) < 0.01 proposed instead (D-L1) | §4 |
| 13 | Noisy and quiet recordings; where to abstain | verified; no new abstention for small; background-speech risk recorded (D-N1) | §5 |
| 14 | Service errors, timeouts, malformed answers → understandable states | implemented, verified | §1, §2, §6 |
| 15 | Reproducible service build, runbook, pinned identity, rollback | implemented, verified (two builds, same identity) | §6, `tools/speaking/RUNBOOK.md` |
| 16 | Audit the pilot's data and punctuation regression; one controlled experiment with punctuated data | implemented (audit; FLEURS train pinned and prepared; config identical but for data) | §7.1, §7.2 |
| 17 | Bounded local training smoke; checkpoint and resume behaviour | verified (24 steps; planned stop and SIGKILL; deterministic resume) | §7.3 |
| 18 | Candidate vs baseline under the documented rule | verified: KEEP_BASELINE (A1, A6 fail; A5 now passes) | §7.4 |
| 19 | Next AWS training job spec and owner commands, not launched | implemented; **launch blocked** (no budget; agents run no AWS command) | §7.5, `tools/speaking/aws/README.md` §6 |
| 20 | Provider patch, real-inference evidence, comparison, limits, recommendation | delivered | Summary, §8 |

## 1. The provider (items 1, 5)

`docs/validation/SPEAKING-MODEL-V1/go-local-provider.patch` still applied to
current main without conflict (two hunks moved by 2 and 5 lines). Ported as is, plus four changes found while
verifying it:

| Change | Why |
|---|---|
| A local answer must carry `flh.deployment_id` equal to `SPEAKING_TRANSCRIPTION_MODEL`; otherwise `provider_unavailable`, nothing stored as text | The stored provenance must name the model that actually answered. A service restarted with other weights is refused (real run: whisper-small behind a base configuration → 502, `failed`). |
| Service HTTP 413/415/422 (audio refused) → `invalid_output`, not `provider_unavailable` | Overlong or undecodable audio is not an outage; sending it again cannot help. |
| Local only: a connection closed without an answer is a definite failure, not an unknown outcome | Found by the first real run: after `docker restart`, Docker's port proxy accepts and then resets connections. FLH recorded `unknown`, so the next clicks needed `confirm_unknown_retry` (`real-inference/run1-restart-gap.json`). The local service bills and keeps nothing, so a new request is safe. A timeout stays `unknown` (the service may still be working). |
| Startup log line: `speaking transcription: local deployment <id>, timeout 1m0s, request deadline 1m30s` | Identity and timeout visible without reading settings. |

Service side (`tools/speaking`): the 504 deadline is now counted from the
request's arrival (queue wait included) and defaults to 50 s, below FLH's 60 s.
`--inference-timeout` overrides it, and `GET /manifest` publishes the limits in force. Before, a queued
request could wait 2 × 90 s before its own 90 s started, so FLH gave up first and recorded an unknown outcome while the
service kept working. Limits are not part of `deployment_id`; the code is, so
the identity changed to `whisper-base@e37978b90ca9/…/ac92e8688ef9e17b`.

Settings: `SPEAKING_TRANSCRIPTION_PROVIDER=local`, `SPEAKING_TRANSCRIPTION_MODEL`
(= `deployment_id`), `SPEAKING_TRANSCRIPTION_BASE_URL`,
`SPEAKING_TRANSCRIPTION_TIMEOUT` (default 60 s). Failure table:
`tools/speaking/CONTRACT.md` §6.

Tests (fakes, no model):
- `internal/speaking/local_test.go`: no key sent, provenance, deployment check, 11 service answers mapped to failure code and outcome, factory wiring beside OpenAI feedback with separate URLs, keys and timeouts.
- `internal/transport/http/speaking_local_integration_test.go`: the normal Speaking API wired from configuration as `cmd/server` does:
  - transcription, replay and confirmation;
  - feedback beside it;
  - stop, loading, ready, other weights and dropped answer;
  - timeout with the acknowledgement rule;
  - a second click while one runs.
- `cmd/server/speaking_deadline_test.go`, `internal/config/speaking_config_test.go`.
- `tools/speaking/tests/test_audio_service.py`: the deadline counts from arrival and is published.

## 2. Real inference through FLH (items 2–6, 7–9, 14)

`tools/speaking/scripts/verify_local_provider.py` ran FLH's server, built from
this tree, against the pretrained whisper-base container: CPU, 4 threads,
`--memory 2g`, published on 127.0.0.1 only. Feedback went to a synthetic local
stand-in for the Responses endpoint, configured as `SPEAKING_PROVIDER=openai`
in the same process. Report: `real-inference/verify-whisper-base.json`;
manifest: `real-inference/manifest-whisper-base.json`.

Identity (item 5):
- The `deployment_id` from the offline `manifest` command equals the one served at `/manifest`. It also matches `providers.transcription.name` in `GET /speaking/prompts` and the `transcriber` stored on every transcription: `local:whisper-base@e37978b90ca9/flh_speaking_transcribe_v1/cpu-fp32/ac92e8688ef9e17b:speaking_transcription_v1`.
- The request rows carry `deadline_at − started_at` = 90 s (60 + 30), or 38 s with a 2 s timeout. The startup log states both.

| Scenario (item) | What FLH answered | Service calls |
|---|---|---|
| FLH up, service never started (6) | 502 `provider_unavailable`, `failed` | 0 |
| Request while the service is `loading` (6) | 502 `provider_unavailable`, `failed`; readiness went down → `loading` 0.5 s → `warming` 4.4 s → `ready` 4.9 s | 0 |
| Real transcription, 12.7 s MLS test clip, webm/opus (2) | 201 in 1.10 s; WER 29.7 % on this clip (v1 test-set WER for base: 27.1 %) | 1 |
| Before confirmation (3) | 0 transcript versions: a machine transcript is not a transcript | — |
| Confirm unchanged, then corrected (3) | v1 `origin: transcription`, v2 `origin: corrected`, both linked to the transcription; still there after an FLH restart | 0 |
| Feedback on v2 beside local transcription (4) | 201, `openai:stub-feedback-model:speaking_feedback_v1`. The stand-in saw its Bearer key, its model and the confirmed text. | 0 |
| Same `Idempotency-Key` again (9) | 200, `Idempotency-Replayed`, same text | 0 |
| Second click on another take while a 93 s take runs (9) | 409 `request_in_progress`. The same key while running: 200 replayed, `in_progress`. The first finished: 201 in 4.6 s, WER 19.9 %. | 1 |
| Client gives up after 0.5 s (9) | FLH finished anyway; a lookup by key showed `completed` 4.0 s later | 1 |
| FLH timeout 2 s, 93 s take (9, 14) | 504 `provider_timeout`, `unknown`. The next click: 409 `outcome_unknown`. Acknowledged retry with 60 s: 201, `after_unknown`. | 2 |
| Service deadline 1 s, 93 s take (5, 14) | service 504 → FLH 502 `provider_unavailable`, `failed` (definite) after 3.4 s. The encoder pass runs before the next deadline check. | 1 |
| `docker restart` of the service (6) | right after: 502, `failed` (run 1: `unknown`, then 409 for every later click). Ready again in 9.8 s; the next click got 201 with the same `deployment_id`. | 1 |
| whisper-small served, FLH configured for base (6, 14) | 502 `provider_unavailable`, `failed`, no text (service 400 `unknown_model`) | 1 |
| Formats (8): webm/opus, m4a as `audio/mp4` and `audio/x-m4a`, mp3, wav | all 201 (WER on the one clip: 29.7, 24.3, 24.3, 13.5, 16.2 %); `audio/ogg` refused at take creation (422: FLH accepts four containers) | 5 |
| Take with 0 bytes, declared 125 s, or over 8 MiB (7) | 422 at take creation | 0 |
| Empty audio; wav bytes sent as webm; body over 8 MiB (7) | 422, 422 (magic bytes), 413 before any call | 0 |
| Undecodable webm (7, 14) | 502 `invalid_output`, `failed` (service 422) | 1 |
| 127 s of audio declared as 119 s (7) | 502 `invalid_output` in 0.37 s (service 422 `audio_too_long` while decoding) | 1 |
| 3 s of silence (7, 13) | 502 `invalid_output` in 55 ms (service `no_speech`; the model is not run) | 1 |
| 48 kHz stereo wav of 8,256,078 bytes (43 s, just under FLH's 8 MiB) (7) | 201 in 3.1 s: the service's request limit (8 MiB + 64 KiB) covers FLH's largest take | 1 |

Left behind (item 9), after successes and failures (garbage, overlong and silence again on the last container):
- `docker diff` shows only `/tmp/torchinductor_uid_1000`, an empty directory torch creates at import, and the `/sources` mount point.
- No 48-byte window of any sent clip occurs in `flh.db`, its WAL or its shared-memory file.
- No transcript word appears in FLH's or the service's logs, and no `Authorization` header in the service's logs.
- FLH's working directory holds only the database and logs.

Peak memory of the service container (cgroup `memory.peak`, which includes page cache):
- whisper-base: 720–911 MiB;
- whisper-small: 1,415 MiB.

## 3. whisper-base vs whisper-small on the frozen set (item 10)

Already measured in v1 (`SPEAKING-MODEL-V1/evals`, `/service`). This task
adds two things: a paired comparison on identical utterances, and a re-run
with the current code. Command: `analyze.py models` → `analysis/models.json`.

| Set (clusters) | base WER | small WER | small − base, 95 % CI | clusters better / worse (sign test) | utterances better / worse |
|---|---|---|---|---|---|
| MLS test (8 speakers) | 27.1 % | 14.9 % | −12.2 [−12.8, −11.6] | 8 / 0 (p = 0.008) | 212 / 9 |
| FLEURS dev, out of domain (137 sentences) | 27.5 % | 13.3 % | −14.2 [−16.0, −12.5] | 124 / 5 (p < 0.001) | 237 / 18 |
| SLR57 accented, test/ca16 (12 speakers) | 37.7 % | 17.8 % | −19.9 [−23.7, −16.6] | 12 / 0 (p < 0.001) | 252 / 48 |

| Cost (CPU, 4 threads) | whisper-base | whisper-small |
|---|---|---|
| Service latency, 10 s / 30 s / 60 s / 120 s take (v1 bench, median) | 0.8 / 1.9 / 3.4 / 5.6 s | 2.5 / 3.4 / 10.1 / 17.3 s |
| Service peak memory (v1 bench; this run, cgroup) | 644 MiB; 720–911 MiB | 1,304 MiB; 1,415 MiB |
| Ready after start | 5.2 s | 7.3 s |
| Batch evaluation peak RSS (v1 eval) | 948 MB | 1,703 MB |

Re-run with this tree's code (`reeval/`): the raw and served text of all
240 MLS test utterances is identical to v1, for both models, so the comparison
holds for what is served now. The service code changed in this task; the
decoding code did not. The run times, under a host load average of about 9:
base RTF 0.078, peak RSS 931 MB; small RTF 0.34, peak RSS 1,620 MB.

Verdict: whisper-small is better on every set, every speaker of MLS test and
SLR57, and 124 of 129 FLEURS sentence groups with a difference. It costs about 3× the latency and 2× the memory,
and a 120 s take still finishes in about 17 s.

## 4. Short clips, accents and the language rule (items 11, 12)

Commands:
- `python -m flh_speaking robustness --set short|language` → `robustness/<model>-<set>.json`.
- `analyze.py short|language|thresholds` → `analysis/*.json`.

Every clip's raw model output is stored, and both language policies are
applied to the same inference.

**Short native French (item 11).** 64 MLS test and 64 FLEURS dev utterances
were cut 1, 1.5, 2, 3 and 5 s after the speech onset, at the quietest 30 ms
frame near the target.

A first run cut from the start of the file. It gave 39 of 64 FLEURS 1 s clips
as `no_speech`, because FLEURS recordings begin with up to a second of silence.
Those cuts measured the silence, not the speech, so that run was discarded,
the cut was fixed (`robustness.onset`, test added) and the run repeated.

| Clips refused, MLS / FLEURS (of 64 each); `not_french` in brackets | 1 s | 1.5 s | 2 s | 3 s | 5 s | full |
|---|---|---|---|---|---|---|
| whisper-small | 5 (3) / 1 (0) | 0 / 2 (1) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| whisper-base | 6 (4) / 1 (0) | 2 (2) / 1 (0) | 1 (1) / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Natural FLEURS clips under 5 s (11; median 4.6 s): both models transcribe all
11, with WER 37.2 % (base) and 16.9 % (small). For native speech, premature
rejection is a 1–2 s problem: from 3 s up, no clip is refused by either model.

**Accented French (item 11),** v1's SLR57 test/ca16 by duration, from the
stored v1 outputs (`analysis/short.json`):

| Duration | n | base: refused `not_french` | base WER (if not refused) | small: refused | small WER (if not refused) |
|---|---|---|---|---|---|
| < 1.5 s | 123 | 2.4 % | 42.2 % (41.3) | 1.6 % | 20.0 % (18.1) |
| 1.5–2 s | 133 | 2.3 % | 35.8 % (34.9) | 2.3 % | 20.4 % (18.3) |
| 2–3 s | 171 | 4.1 % | 39.0 % (36.5) | 0.6 % | 17.4 % (17.2) |
| 3–5 s | 76 | 13.2 % | 35.3 % (29.5) | 2.6 % | 15.0 % (13.4) |
| ≥ 5 s | 12 | 8.3 % | 31.1 % (28.1) | 0 % | 12.0 % (12.0) |

v1 said these rejections were "mostly short takes". By count that holds for
whisper-base (13 of its 24 refusals are under 3 s), but its refusal rate is
highest for 3–5 s takes (13 %), so duration alone does not explain it. For
whisper-small the rate is low at every duration. The refused drafts are mostly
correct French, for example:

| Reference | Draft that was thrown away | Detected as |
|---|---|---|
| Nous sommes Canadiens. | Nous sommes canadiens. | pt (small), id (base) |
| Mon camarade est malade. | Mon camarade est malade. | tl (base) |
| Bonjour monsieur. | Bonjour monsieur. | tr (both) |
| Oui, on a du transport. | Oui, on a du transport. | yo (small) |
| Est-ce qu'ils sont tous des soldats? | Est-ce qu'ils sont tous des soldats ? | es (small) |

**Warning-only language policy, on a separate sample (item 12).** The sample
was kept apart from everything v1 used:
- 300 SLR57 dev takes (Niger, West African French; v1 used test/ca16, Central Africa);
- 40 English and 40 Mandarin FLEURS dev utterances after the 10 per language v1 used;
- MLS dev, full and cut to 1.5 and 2 s.

"Warning-only" means a clip the rule would refuse is transcribed instead, with
`possibly_not_french`.

| whisper-small | n | refused now | refused, warning-only | WER now → warning-only |
|---|---|---|---|---|
| Accented French (Niger) | 300 | 11 (3.7 %) | 0 | 22.2 % → 20.5 % (the 11 rescued: 48 % WER) |
| Native French, full / 1.5 s / 2 s | 100 each | 0 / 0 / 0 | 0 | 13.6 % unchanged |
| English | 40 | 40 | **0: 40 fluent French texts** | — |
| Mandarin | 40 | 40 | **0: 40 fluent French texts** | — |
| **whisper-base** accented (Niger) | 300 | 12 (4.0 %) | 0 | 43.7 % → 42.1 % (the 12 rescued: 52 % WER) |
| whisper-base native full / 1.5 s / 2 s | 100 each | 0 / 2 / 2 | 0 | 22.0 % unchanged |
| whisper-base English + Mandarin | 80 | 80 | **0: 80 fluent French texts** | — |

Warning-only is **not recommended as a default.** With French forced, Whisper
translates other-language speech into fluent French. Examples: "Les autorités
locales sont réunis dans la ville…" from English audio, and "Je pense que ce
n'est pas le cas." from Mandarin. FLH stores no warning, and the workbench shows
none. A learner who answered in English would be handed a French "transcript"
they never said, ready to confirm. That costs more than rescuing 11 accented
takes, about half of which were good.

**A better change: a stricter threshold.** whisper-small's refused accented
drafts had P(fr) of about 0.008–0.16, while other languages sit at about
0.0001. whisper-base separates them less well. The
threshold was chosen on the v1 sets only (accented ca16, MLS, FLEURS and v1's 20
non-French clips): P(fr) < 0.01 refuses no accented or native French there and
all 20 other-language clips. It was then confirmed on the separate sample
(`analysis/thresholds.json`, with the P(top) > 0.6 condition):

| whisper-small, separate sample | now (0.2) | proposed (0.01) |
|---|---|---|
| Accented French refused (300) | 11 | **1** |
| Native French cut to 1 s / 1.5 s refused (127 / 128) | 3 / 1 | 1 / 1 |
| English + Mandarin refused (80) | 80 | **80** |
| whisper-base: accented / native 1 s / English + Mandarin | 12 / 4 / 80 | 5 / 0 / 80 |

Proposal (owner decision D-L1): `NOT_FRENCH_FR_MAX` 0.2 → 0.01 as decoding
policy `flh_speaking_transcribe_v2`. It is a transcript-changing rule, so it
needs a new `deployment_id` and a re-run of the v1 evaluations. It is not
applied here.

## 5. Noise and low levels (item 13)

`python -m flh_speaking robustness --set noise` → `robustness/<model>-noise.json`;
`analyze.py noise` → `analysis/noise.json`.

The set: 40 MLS test utterances (5 per speaker).
- Babble from 4 other speakers, and white noise, at an SNR of 20, 10, 5 and 0 dB, measured as RMS over the whole clip.
- The clean clip scaled to −35 down to −65 dBFS.
- The noises alone at −30 dBFS.

WER, served (all clips transcribed unless noted):

| Condition | whisper-base | whisper-small |
|---|---|---|
| clean | 25.7 % | 14.3 % |
| −35 / −45 / −55 / −65 dBFS | 25.7 / 25.5 / 26.2 / 28.0 % | 14.3 / 14.7 / 15.2 / 17.2 % |
| babble 20 / 10 / 5 / 0 dB | 29.1 / 41.5 / 62.8 / 94.5 % | 15.9 / 22.7 / 35.5 / 90.5 % |
| white 20 / 10 / 5 / 0 dB | 29.5 / 44.7 / 63.5 / 94.9 % | 15.4 / 21.9 / 36.6 / 59.9 % |
| babble alone (no target speech) | 20 / 20 transcribed | 20 / 20 transcribed |
| white noise alone | 17 `no_speech`, 2 `not_french`, 1 transcribed | 5 `no_speech`, 9 `not_french`, 6 transcribed |

What this shows:
- **Quiet takes need no new rule.** Speech scaled down to −65 dBFS keeps its
  accuracy (base 28 %, small 17 %), and real silence is already refused by the
  −70 dBFS sound gate.
- **The service never abstains on noisy speech.** whisper-small keeps a usable
  draft down to 5 dB (36 %); whisper-base degrades from 10 dB. At 0 dB both
  return text that is 60–95 % wrong. whisper-base attaches `low_confidence` to
  26–30 of 40 such clips; whisper-small to 1–5, because it stays confident.
  FLH ignores warnings today.
- **Other people talking with no learner speech is transcribed every time.**
  This is the most likely real failure: a take recorded in a café.
- **The service's SNR estimate is unreliable:** babble at 0 dB reads as about 13 dB.

Candidate rule: abstain (`no_speech`) when the window's average log-probability
is below T. The cost is measured on the v1 clean evaluations, not on this set:

| T (whisper-base) | noisy drafts caught (WER of them) | WER of the rest | clean MLS / FLEURS / accented takes lost |
|---|---|---|---|
| −0.8 | 103 of 480 (89 %) | 36.4 % | 0.4 / 0.3 / 12.6 % |
| −1.0 | 66 of 480 (93 %) | 40.0 % | 0.4 / 0.0 / 4.7 % |

For whisper-small the same rule is a poor signal: at T = −0.6 it catches 68 of
480 noisy drafts (79 % WER) and loses 7.3 % of clean accented takes; at −1.0 it
catches 6.

**Where the service should abstain (recommendation, not applied):**
- **Keep** the −70 dBFS sound gate and the model's no-speech rule. Quiet
  speech is handled well, and white noise alone is mostly refused.
- **No new automatic abstention for noisy speech with whisper-small.**
  Its confidence does not separate good noisy drafts from bad ones, and a
  threshold would refuse accented learners first (2–7 %).
- With whisper-base, `avg_logprob < −1.0` → `no_speech` would remove 66 drafts
  that are 93 % wrong, at a cost of 4.7 % of accented takes. It is not worth it
  if whisper-small is served.
- **Background speech without the learner** is transcribed by both models every
  time, and no signal here separates it. The protection is the learner's
  confirmation step, plus the UI telling the learner to record in a quiet
  place. A further option, if the owner wants it (decision D-N1): store
  `flh.warnings` (`low_confidence`, `repetitive_output`, `possibly_not_french`)
  and show them in the workbench. That needs Go, API and UI changes in other
  lanes.

## 6. Service build and runbook (items 14, 15)

**Failure states (item 14).** Every way the service can answer maps to one of
FLH's three stored codes and one outcome; the table is `tools/speaking/CONTRACT.md` §6.
- Unit tests: `local_test.go`, 11 answers plus refused, foreign and keyless cases.
- HTTP tests: `speaking_local_integration_test.go`.
- Real service: §2.

Two of these mappings are new, and both were found by running the real
service:
- a lost answer after a restart is a definite failure;
- refused audio is `invalid_output`, not `provider_unavailable`.

The workbench still describes every transcriber as possibly billed. The
wording request is in `workbooks-ui-request.md`; that UI belongs to the
workbooks lane.

**Reproducible build and runbook (item 15).**
- `requirements.txt` pinned only the direct packages. Resolving it again a day
  after the image was built already gave two different transitive versions
  (`filelock` 4.2.11 → 4.2.12, `regex` 2026.11.15 → 2026.11.18, the latter
  released that day).
- `requirements-cpu.lock` now pins all 39 installed packages with wheel hashes,
  exactly the set of the image that produced every v1 and v2 number. It is
  resolved inside the pinned base image under the old image's versions as
  constraints (`scripts/lock_from_report.py`).
- The Dockerfile installs `--require-hashes --no-deps` from the lock and runs `pip check`.
- `RUNBOOK.md` covers the pinned identity, build and verification, the
  supported configuration, deployment, checks, upgrade, rollback and cleanup.

Reproducibility check (`tools/speaking/scripts/build_twice.sh`; this run used an equivalent script outside the repository, under the CPU lock and with the image tags `cpu-v2a`/`cpu-v2b`):
- The image was built twice from the lock, the second time with `--no-cache`.
  Both resolved the same 39 packages (`pip freeze` identical, and identical to
  the original image's), and `pip check` passed.
- `manifest` printed the same `deployment_id`s in both images, equal to those
  the service reported in the real-inference run:
  - `whisper-base@e37978b90ca9/…/ac92e8688ef9e17b`;
  - `whisper-small@973afd24965f/…/d20b5c67adbff447`.
- The image IDs differ (`20df66af…`, `9ecdc825…`): layer timestamps change them,
  so they are not the identity; the `deployment_id` is.

`requirements-gpu.lock` (the AWS image) was resolved the same way. It shares
every version with the CPU lock except torch (`2.15.0` from PyPI with its
CUDA 13 set). `cuda-bindings` and `cuda-pathfinder` are held at 13.4.4 and
1.8.5: the newest releases were 13 and 5 days old, against the two-week rule
of `requirements.txt`. `pip install --dry-run --require-hashes` accepted all 58
hashes. The GPU image itself was not built here: it is about 7 GB, and its
only use is the AWS job.

## 7. The pilot's punctuation regression and the controlled experiment (items 16-19)

### 7.1 Audit (item 16)

`analyze.py audit DATA_V1` → `analysis/audit.json`, from the v1 files and the
frozen dataset outside the repository:

| | punctuated outputs | capitalised outputs | WER |
|---|---|---|---|
| MLS train targets (1,440) | 0 % | 0 % | — |
| base, MLS test / FLEURS dev / SLR57 | 100 / 100 / 95 % | 99 / 100 / 73 % | 27.1 / 27.5 / 37.7 % |
| v1 pilot candidate (encoder-only, 180 steps) | 6.7 / 6.6 / 13.4 % | 8.8 / 15.9 / 13.6 % | 26.6 / 28.5 / 36.1 % |

The decoder was frozen, yet the candidate stopped writing punctuation and
capitals. Every training target was lower-case without punctuation, and
cross-attention lets the encoder steer the frozen decoder's choice of tokens.
The loss rewarded exactly that. The pilot's dev split is also MLS (0 %
punctuated), so its dev loss fell (0.494 → 0.483 → 0.480 at steps 60/120/180)
while the style regressed. Freezing the decoder does not protect style; the
targets must carry it. The normalized-WER changes were small: −0.5 points on
MLS test (not significant), +1.0 (worse) on FLEURS, −1.6 on SLR57.

### 7.2 One controlled experiment with punctuated data (item 16)

The only change from the pilot is the training data.

- **Data:** FLEURS French train with raw transcriptions (case and punctuation
  kept; CC BY 4.0, the licence and repository revision already pinned for
  FLEURS dev). It replaces MLS. Pin: `pins.FLEURS_FR_TRAIN` (the Hub's LFS
  SHA-256 and git blob). Preparation: `prepare-punctuated`, rule
  `flh_fleurs_fr_punctuated_train_v1`, manifest `dataset_manifest_punct.json`.
  - train: 1,440 utterances (as the pilot), 4.65 h, 1,382 sentences (58 second readers), 99.9 % punctuated;
  - dev: 100 other sentences;
  - excluded: no FLEURS dev sentence, no normalized held-out text (MLS dev/test, FLEURS dev); 58 clips over 20 s;
  - FLEURS publishes no speaker ids, so speaker overlap with FLEURS dev cannot be ruled out. For this candidate, FLEURS dev is near-domain, and SLR57 is reported beside it.
- **Config:** `configs/punct-base-encoder.json`, identical to
  `pilot-base-encoder.json` apart from its note: whisper-base, encoder only,
  seed 20261117, 180 steps, batch 2 × 8, lr 1e-5, final step as candidate.
- **Question:** does the style regression (A5) disappear when the targets keep
  punctuation, without losing accuracy on the fixed holdout? Acceptance is
  unchanged: `flh_speaking_acceptance_v1` (A1–A7) on MLS test, FLEURS dev and
  the probes, with SLR57 accent as an extra guard.

### 7.3 Local smoke (item 17)

`configs/punct-base-encoder-smoke.json`: the experiment's settings for 24
steps, dev loss every 12, a checkpoint every 4 (2 kept). It ran on this host's
CPU in a 1.8 GB container (`--oom-score-adj 1000`) at about 28.6 s per step
under a load average of 5–11. Evidence: `training/punct-smoke-*`.

| Phase | What happened |
|---|---|
| Start | Loss check before any update: library loss = independent log-softmax NLL = 0.513549 over 135 tokens. 20,590,592 of 72,593,920 parameters trainable (encoder only). |
| A: planned stop | `--max-steps-this-run 10`: checkpoint `step-000010` written at the stop, then exit (`"status": "interrupted"`); `step-000008` kept beside it. |
| B: SIGKILL | Resumed "from step-000010 at step 10"; the dev loss at step 12 was 0.750 (100 punctuated sentences); `docker kill` landed after step 18 was logged. LATEST still named `step-000016`, written atomically. |
| C: resume | "resumed from step-000016 at step 16". Steps 17 and 18 were recomputed with the **same losses as before the kill** (0.729691, 0.448551): data order, RNG and optimizer state came back exactly. Completed at step 24, dev loss 0.744. |
| Checkpoint | `step-000024`: 439 MB, with the model (290 MB), trainer state (165 MB), byte-copied tokenizer files and `run_manifest.json` (config `964950bd…`, data `920b74a0…`, base files, `suitable_for_production: false`). `train.verify_checkpoint` reports no problem. |

The smoke checks the mechanics; 24 steps is not the experiment.

### 7.4 Candidate vs baseline (item 18)

The smoke candidate (`step-000024`) was evaluated on the fixed holdout with
the same commands as v1: `evaluate` on MLS test and FLEURS dev, `probes`, then
`accept` (rule `flh_speaking_acceptance_v1`, unchanged), plus SLR57 accent as
an extra guard.
- Evidence: `evals/punct-smoke-*.json`, `evals/probes-punct-smoke.json`,
  `acceptance-punct-smoke.json`.
- `analyze.py verify` recomputes every summary and the verdict from
  per-utterance outputs: 0 problems.

| Criterion | v1 pilot (MLS, 180 steps) | punctuated smoke (FLEURS, 24 steps) |
|---|---|---|
| A1 MLS test gain ≥ 2 points, CI < 0 | fail: −0.48 [−1.77, +0.84] | fail: +0.21 [−0.59, +0.92] |
| A2 FLEURS dev CI upper ≤ +1 | fail: +0.98 [−0.28, +2.31] | pass: −0.58 [−1.56, +0.46] (near-domain for this candidate) |
| A3 no speaker worse by > 5 points | pass (worst +3.7) | pass (worst +1.9) |
| A4 abstention preserved | pass | pass (26/28 probes as expected; 2 recorded only) |
| **A5 punctuation and case ≥ 0.8 × base** | **fail: 6.6 % / 15.9 % punctuated / capitalised (base 100 / 99.7)** | **pass: 100 % / 100 %** |
| A6 gain on overlap-free items | pass (no gain to explain) | fail: follows A1 (all 240 items overlap-free) |
| A7 RTF ≤ 0.5 | pass (0.048) | pass (0.051) |
| SLR57 accent (guard) | 36.1 % WER, 13 % punctuated | 36.5 % WER (base 37.7 %), 97.7 % punctuated (base 94.9 %) |
| **Verdict** | KEEP_BASELINE | **KEEP_BASELINE** |

Read with care: 24 steps is a mechanics check, not the experiment, and the
pilot's style at step 24 was never measured (only at step 180). What the smoke
shows:
- with punctuated targets, the candidate keeps punctuation and case on every
  output;
- it loses nothing on the other sets (A2, A3, accent);
- it does not improve MLS test.

The full 180-step run (§7.5) is the experiment. It tests whether style holds
over the pilot's whole schedule, and whether any accuracy gain (A1) appears.

### 7.5 The AWS job, prepared and not launched (item 19)

`tools/speaking/aws/README.md` §6 has the job and the owner's exact commands.
`render.py` now takes a run name (`RUN=punct` → job
`flh-speaking-punct-<time>`, tag `Run=punct`); the reviewed bounds are
unchanged and tested (`tests/test_aws_render.py`). Example rendering with the
documentation placeholder account: `aws/flh-speaking-punct-20261118-000000.json`.

| Assumption | Value |
|---|---|
| Data | dataset `920b74a0…379b` (551 MB) + whisper-base `e37978b9…` (290 MB) in S3 under `speaking/` |
| Runtime | 1 × ml.g5.xlarge Spot; 180 steps well under 15 min plus 5–10 min startup; cap 1 h (wait 2 h) |
| Cost | ≤ $1.41 compute worst case (≈ $0.35–0.50 expected) + ≈ $0.76/month storage until cleanup |
| Blocked on | an owner budget, and the owner running the commands (AGENTS.md: agents run no AWS command) |

## 8. Recommendation, limits, decisions and next commands (item 20)

**Serve pretrained whisper-small with `SPEAKING_TRANSCRIPTION_PROVIDER=local`.**
- Deployment `whisper-small@973afd24965f/flh_speaking_transcribe_v1/cpu-fp32/d20b5c67adbff447`.
- A 2 GB, 4-CPU container bound to 127.0.0.1; timeouts 50 / 60 / 75 s.
- If 2 GB cannot be reserved beside the NAS services, serve whisper-base
  (`…/ac92e8688ef9e17b`, 1 GB) instead, knowing it is about twice as wrong.
- Serve no fine-tuned candidate: both v1's pilot and this smoke are KEEP_BASELINE.
- Keep the learner's confirmation step: drafts normalize learners' own wording,
  and noisy or background speech still produces text.

Operational limits (measured on this host, CPU, 4 threads):

| Limit | Value |
|---|---|
| Take | 8 MiB and 120 s (FLH and service agree; a 48 kHz stereo wav just under 8 MiB passes) |
| Containers | webm/opus, mp4/m4a, mp3, wav (FLH refuses ogg) |
| Concurrency | one inference; 2 waiting; a further request gets 429 → `provider_unavailable` |
| Latency, whisper-small | 2.5 s (10 s take) to 17.3 s (120 s take); about 3× slower under a load average of 9 |
| Memory, whisper-small | peak about 1.4 GiB (cgroup, with page cache); 1.6 GB RSS in batch evaluation |
| Readiness | ready 5–10 s after start; requests before that are `provider_unavailable` (definite) |
| Abstains on | silence below −70 dBFS (55 ms, model not run), the model's no-speech judgement, other languages |
| Does not abstain on | noisy speech (usable to 5 dB SNR), other people talking without the learner |
| Wrong refusals (small) | accented French 1.6–3.7 %; native French cut to 1 s about 5 %; none from 2 s |

Owner decisions:

| # | Decision | Recommendation |
|---|---|---|
| D-S1 | Turn on local transcription for daily use | Yes, whisper-small, per `RUNBOOK.md` |
| D-S2 | Release lane: forward `SPEAKING_TRANSCRIPTION_BASE_URL`/`_TIMEOUT` in Compose and the daily wrapper (`release-lane-handoff.patch`, tested), choose how the Compose container reaches the service, and update `docs/RELEASE.md`/`docs/DAILY_USE.md` | Apply. A private host address or a Compose service on the internal network; never a public port |
| D-S3 | Workbooks lane: wording for a local, unbilled transcriber (`workbooks-ui-request.md`) | Apply |
| D-L1 | Language rule P(fr) < 0.01 as `flh_speaking_transcribe_v2` | Yes, after re-running the v1 evaluations under the new identity |
| D-N1 | Store and show `flh.warnings` in FLH (Go, API, UI) | Optional; it helps with noisy takes |
| D-T1 | AWS budget for the 180-step punctuated job (≤ $1.41 + ≈ $0.76/month) | If accuracy beyond pretrained small is wanted. Otherwise stop training work and serve small |

Next commands (owner):

```sh
# serve (tools/speaking/RUNBOOK.md §2-§5)
cd tools/speaking && docker build --build-arg TORCH_INDEX=cpu -t flh-speaking:cpu-$(date -u +%Y%m%d) .
# FLH: SPEAKING_TRANSCRIPTION_PROVIDER=local
#      SPEAKING_TRANSCRIPTION_MODEL=whisper-small@973afd24965f/flh_speaking_transcribe_v1/cpu-fp32/d20b5c67adbff447
#      SPEAKING_TRANSCRIPTION_BASE_URL=http://127.0.0.1:8765/v1  SPEAKING_TRANSCRIPTION_TIMEOUT=60  HTTP_WRITE_TIMEOUT=75
# re-check
python3 -I -B docs/validation/SPEAKING-LOCAL-PROVIDER/analyze.py verify
# experiment on AWS (after a budget): tools/speaking/aws/README.md §6
```
