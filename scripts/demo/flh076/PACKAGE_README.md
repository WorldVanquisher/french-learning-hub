# FLH read-only public demo: release package

This directory is a self-contained release of the read-only Knowledge Library
demo. `RELEASE.json` names its label, the source-revision label, the artifact
identity, the model provenance and the release status:
- `CANDIDATE`: real-model vectors with recorded provenance;
- `BLOCKED`: mechanical test vectors. **Do not publish a BLOCKED package.**

| Path | Contents |
| --- | --- |
| `bin/linux-amd64/`, `bin/linux-arm64/` | `flh-server` (the demo server) and `flh-prepare` (the validator), static Linux builds |
| `artifact/` | The synthetic database, vectors, fixtures, manifest (and `provenance.json` for model vectors) |
| `web/` | The demo web build |
| `deploy/` | `flh-public-demo.service.example` (systemd), `nginx-flh-public-demo.conf.example`, `ctl.sh` (start/status/stop without systemd) |
| `validate-release.sh` | Checksum, symlink and artifact validation |
| `SHA256SUMS` | Every other file's SHA-256 |

**Runtime needs:** Linux (amd64 or arm64), this directory and a loopback
port.

**Not needed:** an encoder or GPU, Windows, Qdrant, cloud credentials, API
keys or network egress. The demo reads its artifact read-only, writes nothing
and calls no AI service.

## Validate

```sh
./validate-release.sh        # 0 = CANDIDATE valid; 3 = BLOCKED (mechanical vectors); 1 = invalid
```

## Start, status, stop (without systemd)

```sh
PORT=18970 ALLOWED_HOST=demo.example.org deploy/ctl.sh start /run/flh-demo   # or any writable runtime dir
deploy/ctl.sh status /run/flh-demo
deploy/ctl.sh stop /run/flh-demo
```

The server binds `127.0.0.1` only. For public use, put a TLS reverse proxy in
front: see `deploy/nginx-flh-public-demo.conf.example`. For systemd, adapt
`deploy/flh-public-demo.service.example`. Neither is installed for you.

## Install and roll back

1. Unpack into a new release directory, for example
   `/srv/flh-demo/releases/<label>`.
2. Run `./validate-release.sh` there.
3. Make the directory read-only for the service user.
4. Switch the `/srv/flh-demo/current` symlink, *outside* the release
   directory, to the new release. Restart the service.
5. Check `deploy/ctl.sh status`, or `curl -s http://127.0.0.1:18970/knowledge-library/demo`:
   the artifact version and `real_model` must be what you released.

**Rollback:** point `current` back at the previous release directory and
restart. Releases are immutable; nothing is migrated.
