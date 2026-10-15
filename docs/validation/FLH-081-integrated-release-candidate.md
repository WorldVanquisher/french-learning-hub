# FLH-081 validation: integrated public-demo release candidate

Date: 2026-10-15 (UTC). Host: the NAS (Arch Linux x86_64, systemd 261, 8 CPUs,
15.7 GB RAM; go 1.27.1, node 26.9.0). Working directory:
`/home/worldvanquisher/workspace/flh-nas-claude`. Branch (supplied):
`release/flh-081-demo-candidate`. Baseline (supplied):
`145983623fd83f71fbb968769ab767c2e3efc5a1`. Implementation owner: NAS Claude
Code. Deployment proposal:
[docs/plans/FLH-081-public-demo-deployment.md](../plans/FLH-081-public-demo-deployment.md).

**Not used:** Git/GitHub, subagents, Windows, the encoder, any model call,
vector regeneration, Docker, AWS, paid resources, dependency installation,
DNS changes, public listeners, or service installation/changes.
Everything ran as the unprivileged user. Every server run was inside an
`unshare -rn` namespace that has loopback only.

**Outcome: candidate `flh081-rc1` is built and passes every local check. It
is not deployed.**

| Step | Result |
| --- | --- |
| 1. FLH-078 candidate located and verified | PASS: SHA-256 matches; packaged `validate-release.sh` exit 0 (CANDIDATE) |
| 2. Real-vector artifact reused | PASS: extracted copy, 5 files byte-identical; no encoder contact, model call or regeneration |
| 3. Integrated candidate built | **CANDIDATE**; differs from FLH-078 rc1 only in `deploy/ctl.sh` (FLH-080 fix) and `RELEASE.json` |
| 4. Offline validation (`candidate_check.py`) | **93 PASS / 0 FAIL**; the FLH-078 tarball gives the same 93/0; negative control FAILs as designed |
| Resource measurement | 0.27 s to ready, 21 MB RSS idle, 28 MB peak, 0 errors in 2,000 requests |
| Real browser | **NOT RUN**: no browser on the NAS. Prior evidence covers identical bytes (below) |
| 5. Deployment proposal | Written; prerequisites named, nothing installed |

## 1–2. Retained FLH-078 candidate and artifact

| Item | Value |
| --- | --- |
| Tarball | `~/flh078/release/flh-public-demo-flh078-rc1.tar.gz` |
| SHA-256 | `78fb5495499d185212ca1fcf0ebf484da73f2b200983e5dd2c2de0e8d45aa906` |
| `.sha256` file | Matches (`sha256sum -c` OK); unchanged after this task |
| Extracted to | `~/flh081/rc1-extract/flh-public-demo-flh078-rc1/` |
| Packaged `validate-release.sh` | Exit 0, `CANDIDATE: checksums, artifact, model provenance and release validation passed` |
| Reused artifact copy | `~/flh081/artifact/` (`cp -a` from the extraction; files mode 0444) |

**Artifact identity:**

| Field | Value |
| --- | --- |
| Version | `d025f217f4d76396` |
| `manifest.json` SHA-256 | `dfe6e94de6664c18be2ae65a27ad9b6c107e7ceefb56a1627fe3f54d4788bcab` |
| Vectors | `model`, `real_model: true`, 768 dimensions, `release_status: model_vectors` |
| Model id | `multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff` |
| Domain fingerprint | `c92c71c4b62c1ec2cd1ff5b8386a3fe0c200a7541026f67a43c7bdb656ea2689` (`flh076_domain_fingerprint_v3`) |

**Artifact file hashes** (`~/flh081/artifact.sha256`):

```text
00180b4c4687e84e4bb7e036989f133ca1bc04b47066eaf541d7e2e9c634fd89  demo.db
0e3d1912d9ae9bb83d1a154e4f7d45e8b667d8e728ad43eeebf7bcfe0627b08e  fixtures.json
dfe6e94de6664c18be2ae65a27ad9b6c107e7ceefb56a1627fe3f54d4788bcab  manifest.json
45ae960fbfd63c247c11cfad3367fe46e86ee3402683a8a4ff016fd474eba27f  provenance.json
6a916e280c71c61818e6e6ba58fd3c8399bedf9dd66c7c5edb3b3324368a0ea1  vectors.json
```

## 3. Integrated candidate and source provenance

**Source:** the checkout was copied to `~/flh081/src` with `tar`. The copy
excludes `.git`, `web/node_modules`, `web/dist` and `captures/`. `captures/`
holds 16 learner capture files, which are not build inputs, so they were not
duplicated.

**Manifest:**
- `~/flh081/source-manifest.sha256` lists 569 files (SHA-256
  `bd4bc571537fe6f345ddefd23739503d919ff5ac314ddb4086522014803ffff4`);
- the copy verifies against it, before and after packaging;
- the checkout still verifies against it at handoff. The only additions are
  this task's two new helpers, which are not build inputs.

**Local modifications:** no edits were made to source by this task.

**Baseline correspondence:** no Git was run, so **that the checkout equals
`145983623fd8…` is the human's statement, not verified here**. Supporting
evidence from file contents only:
- `deploy/ctl.sh` = `1cb5746a…` (the FLH-080 delivered version);
- `scripts/validation/flh077/accept.sh` = `aae1c635…` (FLH-080);
- `scripts/demo/flh076/package.sh` = `4d43b25e…` (FLH-078).

The label is the supplied baseline with no suffix, because the source was not
modified. If the human finds that the checkout differed from that commit, the
label is wrong and the package must be rebuilt.

**Build inputs** (selected; all are in the manifest):

| File | SHA-256 |
| --- | --- |
| `go.mod` | `7abc807de7f5cb370dca7fc914118a32680e33a2f7068c86a438572a1e9e7580` |
| `go.sum` | `0f23aaacd83d619e0dc63fa3ab00800123d6881d683de40097ad346b7a3f7489` |
| `scripts/demo/flh076/package.sh` | `4d43b25ec3ecb102a095d1443393b6f3c6353bac94e1fcea192376343854d800` |
| `scripts/demo/flh076/validate-release.sh` | `2c72fd14ae1dcd17ed79de0ee04a8db548928533a65439e39ee9dd01c15f5e26` |
| `scripts/demo/flh076/deploy/ctl.sh` | `1cb5746ab4188296e6ec92db559c6c5d3c503132bdbd1695a9fe67acc734ef9b` |
| `scripts/demo/flh076/deploy/flh-public-demo.service.example` | `2a1e4316eac921afadb3065f5c6143a80dc94433e63b6d88b5c0bbc31eb00798` |
| `scripts/demo/flh076/deploy/nginx-flh-public-demo.conf.example` | `b7d8c13e11fe3134f6ea96430bfc03ce801d1a0b2de030f70dce4709b640942c` |
| `scripts/demo/flh076/PACKAGE_README.md` | `1072f7bcb3cf688a2f96e350d03aa90ea8bb766cbf6b7f3fb84824b9d77a8a8c` |
| `scripts/demo/flh073/prepare/main.go` | `228c14c0c1108d4eaaab3064639044c5ea8394e4337bd88338eb07479e53253a` |
| `web/package-lock.json` | `6e56a2b75aa6845901a7ac3ec352f7acd49a5b5be17bb174bd0b498e7416feed` |

**Build commands**, run in `~/flh081/src`:

```sh
(cd web && npm_config_cache=~/flh081/npm-cache npm ci --no-audit --no-fund)
bash scripts/demo/flh076/package.sh --artifact ~/flh081/artifact \
  --revision 145983623fd83f71fbb968769ab767c2e3efc5a1 --label flh081-rc1 --out ~/flh081/release \
  --expected-deployment 'multilingual-e5-base@d128750597153bb5987e10b1c3493a34e5a4502a/flh_e5_role_prefix_v1/float16/singleton_v1/5a3e23f28a05baff'
```

**Candidate:**

| Item | Value |
| --- | --- |
| Tarball | `~/flh081/release/flh-public-demo-flh081-rc1.tar.gz` (41,335,570 bytes) |
| SHA-256 | **`536966c46cc3ed70d201fbd2439cd0e1eb3c047151af86de011d8580bb3981df`** |
| Unpacked tree | `~/flh081/release/flh-public-demo-flh081-rc1/` (70 MB: `linux-amd64` 36 MB, `linux-arm64` 34 MB, web 200 KB, artifact 680 KB) |
| `RELEASE.json` | label `flh081-rc1`, `source_revision` `145983623fd83f71fbb968769ab767c2e3efc5a1`, built `2026-10-15T15:36:07Z`, `CANDIDATE`, artifact `d025f217f4d76396` |

**Comparison with FLH-078 rc1:** both packages list 18 files in `SHA256SUMS`.
Exactly two files differ:
- `deploy/ctl.sh` (FLH-080 D3 fix);
- `RELEASE.json` (label, revision, build time).

The binaries (both architectures), the web bundle, `validate-release.sh`,
`README.md`, the templates and all five artifact files are **byte-identical**.

## 4. Offline validation: `scripts/validation/flh081/candidate_check.py`

```sh
unshare -rn python3 -B scripts/validation/flh081/candidate_check.py \
  --tarball ~/flh081/release/flh-public-demo-flh081-rc1.tar.gz --work "$HOME/flh081/check rc1" \
  --revision 145983623fd83f71fbb968769ab767c2e3efc5a1 --artifact-version d025f217f4d76396
```

The script reuses the package's own `validate-release.sh` and `deploy/ctl.sh`,
the packaged `linux-amd64` server, and the unchanged FLH-076
`smoke_package.sh`. It adds:
- identity checks;
- representative routes;
- provenance against the artifact's own `fixtures.json`;
- a restart comparison.

**Result: 93 PASS / 0 FAIL**, in 2.4 s. Evidence is in `~/flh081/check rc1/`:
`results.tsv`, `summary.json`, `netns.txt`, `smoke.log`, `ctl.log`.

| Area | Checks |
| --- | --- |
| No runtime encoder dependency | The namespace has only `lo` and no route (`netns.txt`). The encoder named in `RELEASE.json` (`100.118.109.6:8765`) is unreachable: `Network is unreachable`, so no packet left the host. Every semantic and hybrid preset still answers from cached vectors |
| Package | Tarball `.sha256`; relative single-directory members; extracted read-only into `install root/` (a path with a space); `validate-release.sh` exit 0 CANDIDATE; `RELEASE.json` CANDIDATE, revision label, artifact version, real model |
| Existing smoke | `smoke_package.sh`: PACKAGE SMOKE PASSED |
| Native startup | `ctl.sh start` → `started`. The process argv is the packaged `bin/linux-amd64/flh-server` |
| Identity | `/knowledge-library/demo`: version `d025f217f4d76396`, manifest SHA-256, model id, `real_model: true`, `vector_source: model`, 768 dimensions; counters 0/0; presets equal to the artifact fixtures |
| Routes | Root and `/api` health/readiness/demo; keyword `subj`; all 8 semantic presets (exact preset text, model id, none stale); 3 hybrid presets (`concept_hybrid_rrf_v1`); 11 cached-vector lookups, 0 refused |
| Provenance | All 12 Concepts listed. For all 11 supporting units: original question and context equal the fixture, extractor `fixture:flh073:knowledge_extraction_v1`, current Concept consistent |
| Denied | POST/PUT/PATCH/DELETE on 5 paths → 405; private API and free-text routes → 404; free text on demo routes → 400; 8 private-file paths (`demo.db`, `RELEASE.json`, `SHA256SUMS`, `provenance.json`, `deploy/ctl.sh`, traversal, `/assets/`) → 404, no SQLite bytes |
| Restart persistence | stop (port closed, process gone) → start → counters reset and **34 responses byte-identical**; final stop; package bytes unchanged; no SQLite side files |

**Controls:**
- **The FLH-078 tarball** through the same script, with its own label
  `41de9f06…+flh078-wt`: 93 PASS / 0 FAIL (`~/flh081/check flh078 rc1/`).
- **Negative control:** the flh081 tarball with a wrong `--revision`. Exactly
  one FAIL, `RELEASE.json source_revision`, and exit 1
  (`~/flh081/check negative control/`).

**Host-header behaviour,** measured with `ALLOWED_HOST=flh.vanquisher.world`:
- `Host: 127.0.0.1:PORT` → 200 for `/healthz`, `/readyz`, `/knowledge-library/demo`;
- `Host: flh.vanquisher.world` → 200;
- `Host: evil.example` → 403.

Local health checks therefore work with the public allowlist set.

**Retrieval observation (not a blocker, not a quality claim):** in semantic
mode the `although` preset's top hit is "ne … pas encore: not yet", not
"« bien que » means although". The other 7 presets' top hits are the
intuitive Concepts. Relevance on 12 synthetic Concepts has never been claimed.

### Resource measurement: `scripts/validation/flh081/resource_probe.py`

The probe runs in `unshare -rn` against the extracted candidate, sending 2,000
mixed GETs at concurrency 8 over loopback (`~/flh081/resources/resources.json`).

| Metric | Value |
| --- | --- |
| `ctl.sh start` to ready | 0.27 s |
| RSS idle / after load / peak (VmHWM) | 21.0 MB / 24.1 MB / 27.8 MB |
| Threads idle / under load | 8 / 15 |
| Throughput | 374 req/s; latency p50 8 ms, p95 77 ms, p99 84 ms, max 99 ms; 0 errors |
| CPU | 25.4 s for 2,000 requests, about 12.7 ms per request on average |

The semantic and hybrid paths dominate. At the proposed 10 req/s per visitor
edge limit, CPU use is about 0.13 core per 10 req/s.

**Disk:** about 70 MB per extracted release (36 MB of it is the one
architecture used), plus the 41 MB tarball. Three retained releases need about
0.35 GB.

### Real browser: NOT RUN

There is no Chrome or Chromium on the NAS, and none was installed.

**Prior evidence, kept separate:** FLH-078 D ran `accept.mjs` (37/0) and
`candidate_browser.mjs` (50/0). Those runs used the packaged Linux server
serving the **same** artifact in a loopback-only namespace. The `flh081-rc1`
server binaries, web bundle and artifact are byte-identical to those of
FLH-078 rc1; only `deploy/ctl.sh` changed, and it plays no part in browser
behaviour. That prior run was not repeated here.

## Validation of the deployment proposal artifacts

| File | SHA-256 | Check |
| --- | --- | --- |
| `~/flh081/proposal/flh-public-demo.service` | `dc512466b60463ffc55d2fdd503f23542458dcf2825a877d7450efdc08f57b69` | `systemd-analyze verify` on a path-substituted copy: exit 0, **no warnings** (syntax only; nothing loaded or installed) |
| `~/flh081/proposal/nginx-flh-public-demo.conf` | `c4fa56d97c536082d650e5b0be0de068f35d2278e8e1e71b6bbb46c5e65c45e5` | **BLOCKED**: nginx not installed, so `nginx -t` could not run |
| `~/flh081/proposal/cloudflared-config.yml` | `f74378b0d16db31afd5d3d0c59ceb51455287f60f1b62280d1e2339d5abf72f7` | **BLOCKED**: cloudflared not installed. A template with `TUNNEL_UUID` placeholders and no credentials |

The first draft of the unit put `StartLimit*` in `[Service]`, which `verify`
flagged. They were moved to `[Unit]` before the hash above was taken.

## Release blockers

**None found** for the package itself.

**Deployment prerequisites,** detailed in the plan:
- human confirmation of the hostname and its DNS provider;
- an ingress path for a NAS without assumed public inbound access (the
  proposal recommends a Cloudflare Tunnel);
- nginx and cloudflared, both absent;
- root for the service account, `/srv` layout and unit installation.

**Low-severity note:** `RELEASE.json` and `artifact/provenance.json` inside
the package record the encoder's tailnet address (`100.118.109.6:8765`). They
are not served over HTTP (404 verified). The address is a non-routable CGNAT
tailnet IP. Anyone given the tarball can read it.

## Files and evidence

**Repository files added:**

| File | SHA-256 |
| --- | --- |
| `scripts/validation/flh081/candidate_check.py` | `c6ebff809693196ca893032222cd8f487bd1784db9881a86fcbb5198f9447cd0` |
| `scripts/validation/flh081/resource_probe.py` | `2111abfccec812f205e67e1bc7eea63710cd9caf1e8568c94e54ae5e255393e0` |
| `docs/validation/FLH-081-integrated-release-candidate.md` | — |
| `docs/plans/FLH-081-public-demo-deployment.md` | — |

No production file, shared document or historical report was edited.

**Outside the repository** (`~/flh081/`, 589 MB):
- `release/` holds the candidate;
- `rc1-extract/`, `artifact/` and `artifact.sha256`;
- `src/` with `source-manifest.sha256`, `npm-cache/`, `npm-ci.log` and
  `package.log`;
- `check rc1/`, `check flh078 rc1/` and `check negative control/`;
- `resources/` and `proposal/`.

`~/flh078/` was not modified.

**At handoff:**
- no `-public-demo-artifact` process is running;
- ports 18970, 18971 and 18981–18989 are closed;
- the temporary host-header test directory was removed.
