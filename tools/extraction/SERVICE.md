# Private extraction service (`flh_extraction_service_v1`)

**PROTOTYPE, private.** `flh_extraction/service.py` serves the existing offline practice
pipeline over HTTP, so a staged FLH can call it. Its pipeline:
1. ground a learner's question and its evidence (`practice.draft`);
2. review it (`review2`);
3. build the Workbooks feed (`feed2`);
4. preview an agent return, read-only (`portable.import_any`).

The service is standard library only:
- it holds no state between requests and keeps no request body;
- it contacts no model, provider or network.

FLH's own extractor setting (`EXTRACTOR_PROVIDER`: `disabled` | `openai`) is unchanged; the Go
app does not call this service yet. Wiring it in is a separate, owner-approved change (§7).

```sh
cd tools/extraction
python3 -B -m flh_extraction.service smoke                       # one-command smoke: in-process server, 15 checks
python3 -B -m flh_extraction.service serve --port 8090           # loopback; Ctrl-C stops it
python3 -B -m flh_extraction.service manifest                    # the deployment identity, no server
docker build -f Dockerfile.service -t flh-extraction-service:local .
docker run --rm --read-only --memory 256m --cpus 1 --cap-drop ALL --security-opt no-new-privileges \
    -p 127.0.0.1:8090:8090 flh-extraction-service:local
python3 -B -m flh_extraction.service smoke --url http://127.0.0.1:8090   # the same checks against the container
```

## 1. Endpoints

| Method and path | Answer |
|---|---|
| `GET /healthz` | 200 `{"status": "alive"}` |
| `GET /readyz` | 200 only after the self-check (a built-in synthetic source drafts to its pinned ID, with one quote located and one refused); else 503 with the status and an error class |
| `GET /metrics` (as the speech service) | requests by outcome since start (`ok`, `client_error`, `busy`, `timeout`, `internal`) and the deployment ID; no request content |
| `GET /manifest` | `flh_extraction_deployment_manifest_v1`: `deployment_id`, the SHA-256 of each of the 15 packaged code files, the rules (drafter, cues, material hash, feed and packet schemas), limits and result codes. `model.kind` is `rules`, `learned_weights` is null: no model is loaded |
| `POST /v1/review` | the draft beside its evidence, the 2.2 review (states, cues, conflicts, moves) and the batch plan |
| `POST /v1/feed` | `flh_practice_review_feed_v1` with the 2.2 additions (`feed_seq`, `previous` optional) |
| `POST /v1/import-preview` | the read-only classification of an agent return against a packet (v1, v2 or v3) |

**Requests.**
- Every `POST` sends `Content-Type: application/json`, `Content-Length` and
  `X-FLH-Contract: flh_extraction_service_v1`.
- Its body is `flh_extraction_request_v1` with `"contract": "flh_extraction_service_v1"`.
- `sources` lists the revisions of one source, oldest first.
- `decisions` and `attempts` are the learner's own records (`flh_practice_decision_v1`,
  `flh_practice_attempt_v1`), sent by the caller. The service stores none of them.

**Responses.**
- Every `200` is `flh_extraction_result_v1` with `contract`, `deployment_id`, `status: "ok"` and
  the operation's fields.
- A client that pinned a deployment ID refuses a `200` from any other deployment (the client's
  `expect_deployment`).

## 2. Result codes

| HTTP | `error.type` | When |
|---|---|---|
| 400 | `invalid_request` | not JSON, a wrong schema or contract field, a missing `X-FLH-Contract` header, a bad `feed_seq` |
| 404 | `not_found` | no such path |
| 405 | `method_not_allowed` | `GET` on `/v1/*`, `POST` on health, readiness or the manifest |
| 409 | `contract_mismatch` | the client speaks another contract version; the body adds `service_contract` |
| 411 | `length_required` | no `Content-Length` |
| 413 | `too_large` | body > 256 KiB, > 8 revisions, > 64 items per source, > 1,000 decisions, > 5,000 attempts |
| 415 | `unsupported_media_type` | not `application/json` |
| 422 | `invalid_source` | a source fails `flh_practice_source_v1` validation, or the revisions are not one source |
| 422 | `invalid_decisions` | decisions or attempts are malformed, or name items, revisions or practice IDs not in the request (an attempt may name a practice ID offered now, offered in `previous`, or withdrawn there) |
| 422 | `invalid_return` | an agent return or packet cannot be read (unsupported format version, missing fields) |
| 503 | `not_ready` | the self-check has not passed |
| 503 | `busy` | 4 requests are already in flight; nothing was processed |
| 504 | `timeout` | no result within 5 s; the result is discarded |
| 500 | `internal` | anything else; no traceback, no input text |

**Retries.**
- The service never retries.
- Its client (`service.call`) never retries either. A connection failure is returned as status 0
  with `unavailable`, and the caller decides.
- FLH's rule applies: no automatic retry; an explicit retry is the user's action.

## 3. Bounds and isolation

- **Size and work:**
  - body 256 KiB;
  - 8 revisions per request;
  - 64 proposal items per source;
  - 1,000 decisions and 5,000 attempts.
- **Time and concurrency:**
  - one deadline per request: 5 s, `--timeout`;
  - at most 4 requests in flight (`--max-inflight`). The next one is refused with `busy`,
    never queued without bound.
- **Network:**
  - the server binds `127.0.0.1` by default;
  - any other address must be private (RFC 1918 or ULA);
  - `0.0.0.0` is accepted only inside a container whose port is published on a private
    address.
- **Image:**
  - `python:3.12-slim` pinned by digest plus the 15 package files (the existing
    `.dockerignore` allowlist), user 10002;
  - it runs `--read-only` with 256 MB and 1 CPU.

## 4. Logs and request IDs

One JSON line per request on standard error, with:
- method, path and status;
- result code;
- request ID;
- bytes in and out;
- duration in milliseconds.

`X-Request-Id`: a well-formed ID from the caller (letters, digits, `._-`, at most 64; FLH's own
are 16 hex) is echoed on the response and logged. Otherwise the service generates one.

Never a body, a quote, a header value or an address beyond the path (`tests/test_service.py`
checks that learner text is absent).

## 5. Identity

`deployment_id = flh-extraction-rules@<12 hex of the code identity>/flh_extraction_service_v1/flh_practice_drafter_v1`.

- **Code identity:** the SHA-256 of the canonical map of the 15 packaged files' hashes.
- **Change detection:** any code or rule change gives a new identity. The container's
  `/manifest` must equal the host's for the same tree (checked in the rehearsal).

## 6. Acceptance for deployment

A deployment of the extraction service is accepted when:
1. `/readyz` is 200;
2. `/manifest`'s `deployment_id` equals the one recorded for the release;
3. `smoke --url` passes 15/15;
4. the application workflow (`scripts/app_workflow.py`) passes against it, with:
   - every capture stored;
   - the service grounding FLH's stored text exactly as the library does;
   - an extractor failure leaving the entry unchanged;
   - `unavailable` reported once, without retry, when the service is down;
5. its logs contain no learner text;
6. it is reachable only privately.

The model endpoint has its own acceptance (`docs/validation/EXTRACTION-3.md`, "Deployment
acceptance").

## 7. Runtime rehearsal and Release contract (R4)

- `python3 -I -B scripts/runtime_rehearsal.py --image TAG --work NEW_DIR [--build-context DIR] [--server-bin FLH_SERVER]`
  runs the container on loopback and checks:
  - its identity and the 15-check smoke;
  - the contract and size refusals;
  - a deadline of 0.001 s (504);
  - that logs carry no learner text;
  - restart without state (no mount, an empty `docker diff`);
  - FLH staying ready while the service is stopped, and the recovery order.

  It removes every container it starts.
- `python3 -I -B scripts/service_bench.py [--image TAG]` measures cold and warm latency and
  peak memory on the R4 synthetic traffic.
- For Release:
  - environment, flags, ceilings, restart, outage recovery and teardown:
    `deploy/aws/model-runtime/EXTRACTION-SERVICE-RUNTIME.md`;
  - pin the `deployment_id`, not the image ID.

## 7a. Stable and experimental (R4)

| Stable: `flh_extraction_service_v1` (changes need a new contract version) | Experimental: may change without a version bump |
|---|---|
| routes, envelope (`flh_extraction_request_v1` / `flh_extraction_result_v1`), header, result codes, bounds, `deployment_id` format | the R4 contracts `flh_learning_loop_v1`, `flh_agent_context_v1`, `flh_agent_corrections_v1` (`LOOP.md`); none is served over HTTP |
| the feed `flh_practice_review_feed_v1` with `flh_practice_feed_additions_v1`. `reason_code` is an open set: consumers keep unknown codes verbatim (`flh_extraction/feed_interop.py`) | the grounding checks `flh_grounding_checks_v2` (`grounding_quality.py`): not in the review or the service |
| the sealed examples `fixtures/service_v1/01–09` (`scripts/service_examples.py --check`) | `review` response fields `text`, `cues[].detail` and `plan.effects`: human-readable, not for parsing |

## 8. Not done here

- **FLH calling this service** (an `EXTRACTOR_PROVIDER=http` or a practice API) changes shared
  configuration and HTTP contracts. It needs the owner and the Release lane: proposal in
  `docs/validation/EXTRACTION-3.md`.
- **Authentication.** There is none: the service is private by network placement, like FLH's
  workbench.
