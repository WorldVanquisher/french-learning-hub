# Extraction service runtime contract for Release (R4; local rehearsal only)

**Status.** Prepared and rehearsed locally with Docker on loopback and synthetic data. No
registry push, no cloud call, no change to `compose.yaml`, the daily wrapper or FLH's Go code.
FLH does not call this service; wiring it in is the owner's decision with Release (§6). The
contract itself (routes, codes, bounds, logs) is `tools/extraction/SERVICE.md`.

## 1. Identity (R4)

| Tree | Image (local build) | `deployment_id` |
|---|---|---|
| merged base `58c0ba8b` | `sha256:f7b28efb…` (cached; equal to the R3 image), uncached rebuild `sha256:e8ec777b…` | `flh-extraction-rules@b0bd175f5d97/flh_extraction_service_v1/flh_practice_drafter_v1` |
| this change | `sha256:b00773bf…` (`flh-extraction-service:r4-candidate`, local only) | `flh-extraction-rules@e978b6c2bdb6/flh_extraction_service_v1/flh_practice_drafter_v1` |

- **Pin the `deployment_id`, not the image ID.** The image ID differs between cached and
  uncached builds of the same tree; the deployment ID does not. It hashes the 15 packaged code
  files and changes with any code or rule change.
- **R4 changes the identity once.** It is a bug fix in `/v1/feed`: attempts that name practice IDs
  withdrawn by the previous feed are accepted. Before, they were refused with 422 after a feed
  that offered nothing. Request and response shapes are unchanged. A pin on `b0bd175f5d97`
  must move to `e978b6c2bdb6` with this change.

## 2. Environment contract (R4-EXT-011)

**The service reads no environment variable, file, secret or network resource.** Every setting
is a command-line flag with a safe default:

| Flag | Default | Contract |
|---|---|---|
| `--host` | `127.0.0.1` (image: `0.0.0.0` inside the container) | loopback, or a private address (RFC 1918, ULA). Publish the container port on loopback or a private address only |
| `--port` | `8090` | any free port |
| `--max-inflight` | `4` | requests processed at once; the next is refused with `503 busy`, never queued |
| `--timeout` | `5` (seconds) | per-request deadline; `504 timeout` after it, the result discarded |

The image sets `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `PYTHONPATH` and
`FLH_IN_CONTAINER=1`. Nothing needs to be added. **Do not** pass AWS settings, `OPENAI_*`,
`.env` files or FLH's database path: the service needs none and keeps no learner data.

**Staging pin (Release, R4).** Release's opt-in staging override
(`deploy/aws/private-staging/staging/runtime/extraction.override.yaml`) requires
`FLH_EXTRACTION_DEPLOYMENT_ID`. It checks the value against
`flh-extraction-rules@<12 hex>/flh_extraction_service_v1/flh_practice_drafter_v1` (default
`e978b6c2bdb6`) and records it as the container label `org.flh.extraction.expect-deployment-id`
for the `/manifest` comparison.

**FLH side.** The app has no provider for this service. If the owner approves wiring it in,
Release would own the settings (proposal only):
- a private URL, empty meaning disabled;
- the pin, reusing `FLH_EXTRACTION_DEPLOYMENT_ID`, so that a 200 from another deployment is
  refused;
- a client timeout of at least the service deadline plus 2 s, so 7 s.

The client rules stay those of `service.call`:
- no automatic retry;
- a connection failure is reported once as `unavailable`.

## 3. Container flags and resource ceilings (R4-EXT-012)

These are the flags used by every local rehearsal (`scripts/runtime_rehearsal.py`, `RUN_FLAGS`):

```sh
docker run -d --name flh-extraction \
  --read-only --memory 256m --memory-swap 256m --cpus 1 --pids-limit 64 \
  --cap-drop ALL --security-opt no-new-privileges --restart no \
  -p 127.0.0.1:8090:8090 IMAGE
```

- **No volume, tmpfs, environment file or secret.**
- **`--restart no`.** The local rehearsal uses it, so a crash stays visible.
- **`unless-stopped` on staging.** Release's staging override uses it, so the sidecar returns
  after a host reboot. Callers still never retry, and §5's recovery order stays the runbook.
  This is listed for the owner as an accepted difference.
- **On Compose:**
  - attach the service to the private network only (`flh-staging_default`), with no `ports:`
    entry;
  - FLH reaches it as `http://flh-extraction:8090`;
  - the operator reaches it through SSM port forwarding.

| Ceiling | Value | Measured (R4, `scripts/service_bench.py`, this host) |
|---|---|---|
| memory | 256 MiB, no swap | container cgroup peak **24.3 MiB** after 1,200 warm requests including the largest legal body (254 KB); host process peak RSS 33.3 MiB |
| CPU | 1 | warm p50 2.6–4.9 ms on corpus requests, 84 ms on the largest legal body; 5 cold starts ready in 0.31 s median |
| processes | 64 | one Python process with 4 worker threads |
| request body | 256 KiB (service limit) | one byte over is `413 too_large` |
| deadline | 5 s (service limit) | the largest legal request answers in 155–166 ms; a container started with `--timeout 0.001` answers it `504` and stays ready |

## 4. Restart and state (R4-EXT-013)

Rehearsed with `docker restart`. Results:
- ready again in 0.31 s with the same `deployment_id`;
- the counters start again at zero;
- the same feed request gives the same `feed_id`;
- `docker inspect` shows no mount and a read-only root filesystem;
- `docker diff` is empty.

**The container keeps no learner state.** Every request carries the sources, decisions and
attempts it needs. The learner's records stay with FLH or Workbooks.

**Losing the container loses nothing.** A restart, replacement or rollback of the image needs
no data step.

## 5. FLH with the service unavailable, and recovery (R4-EXT-014)

Rehearsed against the FLH server built from this tree (loopback, its own SQLite file, providers
disabled). With the extraction container stopped:
- one review call returns status 0 `unavailable` within 1 ms, with no automatic retry;
- FLH's `/readyz` stays 200, because FLH does not depend on this service.

Recovery, in order (each step was verified):

1. `docker start flh-extraction` (0.1 s).
2. Wait for `GET /readyz` 200 (0.3 s). The self-check must pass first; 503 `failed` means the
   image is wrong: stop here.
3. Check that `GET /manifest` `deployment_id` equals the pinned one; otherwise stop and roll back
   the image.
4. Run `python3 -B -m flh_extraction.service smoke --url URL`: 15/15.
5. The caller retries explicitly. The service and its client never retry by themselves.

## 6. Teardown and its evidence (R4-EXT-015)

```sh
docker rm -f flh-extraction                  # stop and remove; there is no volume to remove
docker image rm IMAGE                        # only if no other container uses it
docker ps -a --filter name=flh-extraction --format '{{.Names}}'   # expect no output
docker volume ls --filter dangling=true      # expect nothing new from this service
```

Record these as the teardown evidence:
1. the empty `docker ps -a` output;
2. the `deployment_id` that ran, and the time it was removed;
3. that its logs held no learner text (`scripts/runtime_rehearsal.py` checks every line is the
   documented JSON with none of the synthetic markers);
4. the removed image ID, if the image was removed.

The rehearsal tears down every container it starts, also after a failure, and reports
`containers_left: []`.

**On the staging host, the Compose project owns the container:**
1. `docker compose rm -sf flh-extraction`;
2. then the evidence above.

Removing the service never touches FLH's database or backups.

## 7. Not done, and who decides

| Item | Owner of the decision |
|---|---|
| FLH calling this service (`EXTRACTION_SERVICE_*`, a Compose service entry) | owner + Release |
| pushing an image to a registry, running it on the staging host | owner (cloud write) |
| `restart: unless-stopped` in Release's staging override (adopted by Release; differs from the rehearsal's `no`) | owner (accept or ask for `no`) |
