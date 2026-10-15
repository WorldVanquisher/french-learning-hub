# FLH-076 public demo release tooling

Operator guide: [docs/PUBLIC_DEMO.md](../../../docs/PUBLIC_DEMO.md). Real-vector
preparation commands (`plan`, `embed`, `status`, `import`) are in
`scripts/demo/flh073/prepare`.

| Path | Purpose |
| --- | --- |
| `package.sh` | Portable release package; `CANDIDATE` only for a validated model artifact with a pinned E5 deployment, otherwise `...-BLOCKED` |
| `validate-release.sh` | Copied into each package: checksums, no symlinks, no unlisted files, artifact and release validation |
| `PACKAGE_README.md` | Copied into each package as `README.md` |
| `smoke_package.sh` | Loopback smoke of a package (host builds off Linux) |
| `deploy/` | `flh-public-demo.service.example` (systemd), `nginx-flh-public-demo.conf.example`, `ctl.sh` (start/status/stop) — examples, never installed |
| `browser/run.sh`, `browser/accept.mjs` | Real-browser acceptance with the installed Chrome, through a task-local `playwright-core` (no browser download) |

**Tool behaviour:**
- No tool here runs Git, installs a service, opens a port beyond loopback,
  publishes anything or changes DNS.
- The browser acceptance's injected 503 is a client-side fault, labelled in
  its results.
- Mechanical artifacts prove UI and route mechanics only.
