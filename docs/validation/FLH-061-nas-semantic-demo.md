# FLH-061 NAS acceptance of the FLH-060 semantic demo (human-executed)

**Executed by the human owner on the NAS, not by a coding agent.** This record
was written on 2026-10-12 during FLH-062 by local Claude Code. It is based only
on the human's summary of their NAS transcript, as supplied in the FLH-062 task.
The agent did not see the transcript itself or any raw evidence, and ran nothing
on the NAS. The summary gives no execution date, exact command lines or artifact
hashes, so none are recorded here.

Contract and commands: [FLH-060 plan](../plans/FLH-060-semantic-demo.md),
[demo README](../../scripts/demo/flh060/README.md). Earlier evidence:
[FLH-060 validation](FLH-060-semantic-demo.md), which lists the NAS runs as NOT
RUN.

## Reported by the human

| Item | Reported result |
| --- | --- |
| Mechanical checks | **18/18 passed** on the NAS |
| Embedding service | The real E5 service with the `singleton_v1` batching policy on the Windows GPU, reached through Tailscale |
| Catalog | 15 Concepts indexed (7 FLH-034 seed Concepts + 8 FLH-060 contrast Concepts) |
| Live budget | 9 embedding POSTs and 22 positions |
| Restart | The demo directory persisted across stop/start |
| Cache reuse | `sync` and `rebuild` made zero embedding calls |
| Offline and recovery | Behaved as the walkthrough expects: semantic search failed explicitly while the service was switched offline, then worked again |

9 POSTs and 22 positions are what `walkthrough --allow-live` plans for the
15-Concept catalog, and the 18 checks are its check count. The figures match
the agent's macOS live run in FLH-060. The summary doesn't say whether
`walkthrough` was the exact command, nor which mode (native or Compose) ran.

## Not established by this record

- **Browser interaction: NOT RUN.** No workbench or browser acceptance is
  claimed.
- **Raw evidence** (walkthrough JSON, gateway counters and budget, service
  `/metrics` deltas) stays outside the repository with the human. No artifact
  hash is given, because none was supplied.
- **Not mentioned in the summary, so not established here:**
  - the Linux Docker Qdrant `--user` ownership;
  - Compose real mode and whether a NAS container can reach the tailnet address;
  - the Windows run of the fixed `run-diagnostic.ps1`.
- **No quality claim:** no relevance, semantic-quality, determinism, latency or
  production-scale claim follows from these mechanical checks.
