# FLH-097 follow-up — correctness review of AI-assisted Concept suggestions

Owner: NAS Claude Code (sole implementation owner of this follow-up).

**Scope:** a bounded review of the merged FLH-097 code in four areas:
1. generation request recovery;
2. the confirmation transaction and replay;
3. annotation and evaluation boundaries;
4. the daily-wrapper configuration.

**Method:**
- synthetic data, temporary databases, a local fake provider and a docker shim;
- no paid provider call, no browser, no daily database or private settings.

**Correction to an earlier report:**
[FLH-097 validation](FLH-097-concept-suggestions.md) said its working tree held
uncommitted FLH-092 to FLH-095 work. Those milestones were later merged through
PR119. That report's results are unchanged; only that statement is out of date.
This note does not describe Git state beyond that.

## 1. Findings

| # | Area | Location | Failure scenario | Impact | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Generation | `internal/application/concept_suggestion_service.go`, `Generate` | The key was looked up **before** taking the in-flight slot. Request B read "not committed"; request A then committed and released the slot; B took the slot and called the provider again. | A second paid call under a key whose result was already terminal. The commit-time replay hid it from the client. | **Fixed:** the slot is taken first, so the lookup happens while holding it. |
| 2 | Generation | same, run commit | A client disconnect after the provider answered canceled the request context, so the commit failed with `context canceled`. | A possibly billed result was discarded. The key stayed open, so a resend paid again. | **Fixed:** the commit uses `context.WithoutCancel` with a 10-second bound. |
| 3 | Generation (workbench) | `web/src/pages/ConceptSuggestions.tsx` | A same-key resend that returned a stored **failed** run (201 with the replay header) showed "Suggestions stored… Nothing was applied" and cleared the selection. There was no explicit control to retry a failed run. | A failure presented as success; the retry path was unclear. | **Fixed:** a failed replay is reported as a failure. A failed run offers **Generate again as a new request**, which uses a new key and states that it calls the model again and may be billed. |
| 4 | Confirmation | `internal/storage/sqlite/concept_suggestion_repository.go`, `deriveItemState` | Right after a successful confirmation, the item listed `unit_has_current_same`, which is its own SAME. A replay after a later correction gave no explicit signal that the historical event was no longer current. | Confusing stale signals. A replay could be read as current authority. | **Fixed:** `confirmation.still_current` is derived on read. A confirmed item's own current SAME is no longer reported as stale. The workbench labels a corrected confirmation as historical. |

**Checked, no product defect:**
- **Confirmation atomicity.** The stale checks, the human SAME event, the CURRENT SAME projection and the receipt are written in one transaction, which takes the write lock first.
- **Stale cases.** All six are refused with `409` and write no event: extraction changed, membership created, INVALID, target retired, target identity changed, DISTINCT recorded.
- **Concurrent confirmations** produce one event.
- **A lost confirmation response:** the replay returns the same event.
- **Annotation and evaluation boundaries.** Generation alone creates no label or effective SAME. A confirmed SAME keeps human attribution and suggestion provenance, and evaluation keeps excluding it as unclassified. The new regression tests pin this down.
- **The wrapper** already refused an invalid `SUGGESTION_PROVIDER`; this follow-up adds behavioural tests for it.

One test failed during development: the comparison report returned 500. The cause was my test fixture, which registered only two of the comparison's three required retrievers; it was not a product defect.

## 2. Exact retry, replay and crash semantics after this follow-up

| Situation | What is stored | What a same-key resend does |
| --- | --- | --- |
| Success, response lost (write timeout, network drop) | Completed run | Replays it; no provider call |
| Client disconnects **after** the provider answered | Completed run (detached commit) | Replays it; no provider call |
| Provider timeout / error / invalid output | Failed run (code only) | Replays the failed run; no provider call. Retrying is the explicit **Generate again as a new request** with a new key |
| Client disconnects **during** the provider call | Nothing | Calls the provider again (its side is unknown and may have been billed) |
| Server stops before commit | Nothing; the in-memory slot disappears | Calls the provider again |
| Commit fails (storage error) | Nothing (`500`) | Calls the provider again |
| Same key, different `unit_ids` | Nothing new | `409`, no call |
| Same key while this process is still generating | Nothing new | `409`, no call |
| Two server processes, same key, at once | At most one run (unique key) | Both may call the provider |

**What is guaranteed, and what is not:**
- A request can never stay "in progress" beyond its own handler: the slot is released on every return, including a panic.
- Exactly-once provider execution is **not** claimed across crashes, failed commits or multiple processes.
- At most one run is ever stored per key.

Confirmation replay:
- Each item has at most one confirmation (`UNIQUE(item_id)`).
- A replay returns the original event and changes nothing.
- `still_current` reports whether that event is still the unit's CURRENT SAME.
- A unit that is already resolved is never reassigned.

## 3. Tests added

| Test | Proves |
| --- | --- |
| `TestGenerate_SameKeyRequestNeverCallsProviderTwice` | The overtaking same-key request gets `409`; a later replay makes no call; exactly one provider call |
| `TestGenerate_ResultIsStoredWhenClientDisconnectsAfterProvider` | A result is stored although the request context was canceled after the provider returned |
| `TestGenerate_ClientCancellationDuringProviderStoresNothing` | Nothing stored; the slot is released; the key can be resent |
| `TestGenerate_PersistenceFailureReleasesKey` | A storage error stores nothing and releases the key; the resend calls the provider again (documented) |
| `TestConceptSuggestions_ConfirmedItemIsNotStaleBecauseOfItsOwnSame` | No stale reason; `still_current: true` |
| `TestConceptSuggestions_ReplayAfterCorrectionIsHistoricalOnly` | Replay after REASSIGN: original event, `still_current: false`, current Concept unchanged, no new event |
| `TestConceptSuggestions_SecondSuggestionForResolvedUnitIsRefused` | Two runs for one unit: the second confirmation is `409 unit_has_current_same`; membership unchanged |
| `TestConceptSuggestions_AnnotationAndEvaluationBoundaries` | After generation only: no effective SAME, no dataset label, 0 quality human SAME. After confirmation: effective annotation is `resolved` with a human decision whose evidence names the item; the dataset label names that event; quality is valid with 1 human SAME; evaluation shows 1 unclassified exclusion and 0 samples; comparison is valid with 0 samples |
| `ConceptSuggestions.test.tsx`: failed replay + new-key retry; superseded confirmation | The failed replay is reported as a failure; the retry sends one new keyed request for the same units, stored before sending; a corrected confirmation is shown as historical |
| `scripts/validation/flh094/test_wrapper.sh` (+6 checks) | Unknown provider refused for `check` and `up` before any start; openai suggestions alone require the key; unset, `disabled` and `openai` accepted and labelled |

**Mutation checks:**
- Restoring the old lookup-before-slot order fails the first test.
- Restoring the cancelable commit context fails the second.
- With the fixes in place, both pass.

## 4. Commands and results (2026-10-22)

| Command | Result |
| --- | --- |
| `go test -race -count=1 ./internal/application/ -run TestGenerate_ -v` | 4 pass |
| `go test -race -count=1 ./internal/transport/http/ -run ConceptSuggestions -v` | 13 pass (16 subtests) |
| `cd web && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/ConceptSuggestions.test.tsx src/i18n` | 23 pass (10 suggestion tests) |
| `bash scripts/validation/flh094/test_wrapper.sh <scratchpad>/flh097fu-wrapper` | 32 PASS, 0 failures; only `docker compose config` ran for real |
| `NODE_OPTIONS=--no-experimental-webstorage make verify` | exit 0: gofmt, Go tests, vet, builds; frontend typecheck, **312 tests in 24 files**, production build |
| `go test -race -count=1 ./internal/application/ ./internal/transport/http/ -run 'TestGenerate_\|ConceptSuggestions'` | pass |

**Public-demo checks were not rerun.** This follow-up changes no migration, no
demo boundary and no demo-served route. The new `still_current` field appears
only on suggestion routes, which the demo does not expose.

## 5. Remaining limitations

- **No exactly-once guarantee.** Provider execution can repeat after a cancellation during the call, a server stop before commit, a failed commit, or two processes using the same key. Each of these is reported as an unknown outcome or a `500`, never as success.
- **In-flight protection is per process.**
- **Not evaluated:** real-model suggestion quality, browser behaviour and a real `docker compose up`.
