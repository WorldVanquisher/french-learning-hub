# FLH-073 public demo tooling

Operator guide: [docs/PUBLIC_DEMO.md](../../../docs/PUBLIC_DEMO.md).

| Path | Purpose |
| --- | --- |
| `fixtures/catalog.json` | Synthetic catalog: 8 learner questions with analyses and units, 12 Concepts, 8 preset queries. No real data. Preset texts are demonstration inputs, not labels or expected answers |
| `prepare/` | `go run ./scripts/demo/flh073/prepare build -out DIR` and `validate -artifact DIR [-release]` |
| `smoke.sh` | Local loopback smoke of the whole demo (`bash smoke.sh /abs/new/dir [port]`) |

**`build`**
- **Steps:**
  1. Seed a new SQLite database through the real application services:
     entries, analyses (analyzer `fixture:flh073:fr_l2_taxonomy_v1`), a
     scripted extractor (`fixture:flh073:knowledge_extraction_v1`), Concepts
     and CURRENT SAME memberships.
  2. Compute **mechanical** vectors (`flh073_mechanical_hash_v1`: signed
     feature hashing of normalized words, 64 dimensions) for every Concept
     document and every preset query envelope.
  3. Write `manifest.json`, `demo.db`, `vectors.json` and `fixtures.json`.
  4. Validate the result with the server's own loader.
- **Refused output:** inside the repository, or into a non-empty directory.
- **Reproducibility:** `vectors.json`, the artifact version and the domain
  fingerprint are reproducible from the same fixtures. `demo.db` bytes are not
  (row timestamps); its hash binds the one artifact.

**`validate`** loads the artifact exactly as the server does.

| Exit | Meaning |
| --- | --- |
| 0 | Valid |
| 1 | Invalid (with the reason) |
| 2 | Usage error |
| 3 | `-release` with mechanical vectors: **BLOCKED** |

Use a built binary to see code 3: `go run` reports every non-zero exit as 1.

**No live model call exists in this tooling.** A releasable artifact needs
real-model vectors in the same `vectors.json` schema, produced by a separately
authorized run.
