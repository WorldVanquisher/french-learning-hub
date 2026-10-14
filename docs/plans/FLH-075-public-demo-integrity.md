# FLH-075 Public-demo static confinement and complete domain fingerprint

Owner: local Claude Code. Branch label supplied: `fix/flh-075-public-demo-integrity`.
No Git/GitHub command or subagent was used. Input:
[FLH-074 acceptance](../validation/FLH-074-public-demo-acceptance.md) (F1, F2),
with its harness `scripts/validation/flh074/` used unchanged. Evidence:
[validation](../validation/FLH-075-public-demo-integrity.md).

**Not changed:**
- the FLH-074 report and harness;
- `AGENTS.md`, migrations, AWS/Windows tools;
- unrelated production code;
- the artifact preparation code. It needed no change: `Build` stores the
  fingerprint `ComputeFingerprint` returns.

## F1: static root confinement (`internal/transport/http/workbench.go`)

- **Mechanism:** `NewWorkbenchHandler` opens `os.OpenRoot(webDir)` (Go 1.24+;
  `go.mod` is 1.26.5) and serves `index.html` and `/assets/` from `root.FS()`.
  Each open is resolved against the root's directory handle, so there is no
  path-string prefix check and no pre-check that a swapped link could race.
- **Policy:**
  - relative links (file or directory, any depth) are followed only if they
    resolve inside the root;
  - absolute links, and links escaping the root, are refused;
  - directories stay unlisted;
  - an escaping `index.html` is a startup error;
  - the `-web-dir` path itself may be a link (resolved once).
- **Responses:** `fileOnlyFS` reports every open failure as not found, so a
  refused link answers `404` (not `500`) and does not reveal why.
- **Routing:** unchanged (`/`, `/assets/`, the `/api` strip, root API
  passthrough).
- **Not covered:** hard links, bind mounts and other filesystem aliases.
  Release directories stay read-only, and the release rule is "no links in the
  web build".

## F2: complete domain fingerprint (`internal/publicdemo/database.go`)

**Read dependencies inspected:** `KnowledgeLibraryService`, the sqlite concept
and knowledge repositories, and `domain/effective_annotation.go`.
- **Tables read:** entries, analyses, feedback, extractions,
  `entry_current_extractions`, units, admission **recommendations** and
  overrides, Concepts, links, memberships, distinctions, unit judgments.
- **Latest-wins reads:** recommendations, overrides, feedback, links,
  distinctions and judgments are ordered by `created_at COLLATE
  flh_timestamp_v1`. Effective annotation compares SAME, DISTINCT and relation
  `created_at` across tables.

**Contract `flh075_domain_fingerprint_v2`:**
- **Content:** a SHA-256 over every library-relevant table's content columns.
  The previously missing ones are `knowledge_admission_recommendations`,
  `entry_current_extractions`, the link/distinction/judgment
  score/evidence/resolver fields, and the capture fields.
- **Order:** an `order_rank` for each latest-wins row, computed across all
  ordered tables by parsed RFC 3339 instant, with equal instants sharing a
  rank. Unparseable values rank last and include their raw text.
- **Absolute timestamps are excluded,** so the fingerprint stays reproducible
  per fixture. The exact bytes remain bound by `files["demo.db"]`.
- **Required-empty tables:** `annotation_operations` and all `semantic_*`
  tables, whose counts are digested.
- **Exempt:** `schema_migrations` (checked exactly elsewhere) and
  `sqlite_sequence`.
- **Coverage guard:** a test fails if any table in the schema is not covered,
  required empty or exempted.

**Manifest:**
- `domain_fingerprint.version` is required to equal the v2 contract, and the
  counts must match exactly.
- **Compatibility:** v1 manifests (FLH-073, no version) and unknown versions
  are refused at load, with explicit rebuild guidance. Nothing is upgraded in
  place, and retained artifacts are not modified.

## Files

| File | Change |
| --- | --- |
| `internal/transport/http/workbench.go` | `os.Root` confinement, 404 for refused opens, symlink policy comment |
| `internal/transport/http/workbench_symlink_test.go` | New |
| `internal/publicdemo/database.go` | v2 fingerprint: coverage, order ranks, empty tables, count check |
| `internal/publicdemo/artifact.go` | `DomainFingerprint.Version` and the version gate |
| `internal/publicdemo/publicdemo_test.go` | Fingerprint tests |
| `docs/PUBLIC_DEMO.md` | Symlink policy, fingerprint v2, rebuild steps |
| This plan, the validation report | New |
