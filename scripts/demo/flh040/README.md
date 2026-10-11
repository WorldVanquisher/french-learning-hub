# FLH-040 semantic search demo

Synthetic, local, and free: the FLH-034 demo library, a deterministic fake
embedding service, a Qdrant binary you supply, and the server with
`SEMANTIC_SEARCH=qdrant`. Everything binds `127.0.0.1`. See
[docs/SEMANTIC_SEARCH.md](../../../docs/SEMANTIC_SEARCH.md) for the operator
guide.

**The fake vectors prove mechanics only** (caching, publication, re-validation,
recovery). They are hashed bag-of-words vectors, so a "semantic" match here means
shared words, plus the occasional hash collision at 64 dimensions.

| File | Purpose |
| --- | --- |
| `fake_embeddings.py` | OpenAI-compatible `POST /v1/embeddings`; `GET /stats` counters; `POST /control` failure modes (`fail`, `bad_dims`, `nan`, `slow`) |
| `semantic_demo.sh` | `up`, `index`, `down`, `clean` for one demo directory |

## Run it

Download Qdrant 1.19.1 for your platform from its GitHub releases into a
temporary directory (no installation is needed), and build the workbench:

```bash
npm --prefix web ci && npm --prefix web run build
WORK=$(mktemp -d)/flh040-demo
sh scripts/demo/flh040/semantic_demo.sh up "$WORK" /path/to/qdrant "$PWD/web/dist"
# open http://127.0.0.1:18934/ → Knowledge Library → Search mode: Semantic
sh scripts/demo/flh040/semantic_demo.sh index "$WORK" status   # or sync, rebuild
curl -s http://127.0.0.1:18940/stats                             # provider counters
sh scripts/demo/flh040/semantic_demo.sh clean "$WORK"
```

`up` refuses a non-empty or in-repository directory and occupied ports.
`down` and `clean` signal only processes whose command line names the demo
directory. Ports: 18934 (server), 18933 (seed stub), 18940 (fake embeddings),
18941/18942 (Qdrant).
