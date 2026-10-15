# FLH-081 deployment proposal: read-only public demo on the NAS

Status: **PROPOSAL, nothing installed or changed.** Every command below is for
the human owner to run after approval. Candidate and evidence:
[FLH-081 validation](../validation/FLH-081-integrated-release-candidate.md).

## Summary

| Decision | Proposal |
| --- | --- |
| Hostname | **`flh.vanquisher.world`**, pending human confirmation. There is no DNS record today |
| Release | `flh-public-demo-flh081-rc1.tar.gz`, SHA-256 `536966c46cc3ed70d201fbd2439cd0e1eb3c047151af86de011d8580bb3981df` |
| Rollback release | `flh-public-demo-flh078-rc1.tar.gz`, SHA-256 `78fb5495499d185212ca1fcf0ebf484da73f2b200983e5dd2c2de0e8d45aa906`. Same artifact, binaries and web; only `ctl.sh` (not used by systemd) and `RELEASE.json` differ |
| Demo listener | `127.0.0.1:18970` (loopback only; free today) |
| Proxy listener | nginx on `127.0.0.1:18971` (loopback only; free today) |
| Public ingress | **Option A: Cloudflare Tunnel** (outbound-only; no inbound port, no public listener on the NAS) |
| TLS | Terminated at the Cloudflare edge; cloudflared → nginx → demo over loopback HTTP |
| Service account | `flh-demo` system user and group, no login shell, no home (absent today) |
| Layout | `/srv/flh-demo/{archive,releases/<package>,current→releases/<package>}`, root-owned and read-only (absent today) |
| Service | systemd unit `flh-public-demo.service` (proposed file verified for syntax). The server is started directly; `ctl.sh` is for manual use only |
| Limits | `MemoryHigh=128M`, `MemoryMax=256M`, `CPUQuota=200%`, `TasksMax=64`, `LimitNOFILE=4096`; egress blocked to loopback (`IPAddressDeny=any`, `IPAddressAllow=localhost`) |
| Logs | journald for the service (startup and shutdown only; the server logs no requests). nginx access log without query strings or client IP, 14-day rotation |

## What was inspected (relevant only)

Inspected without credentials, private content or unrelated directory scans:

| Fact | Finding |
| --- | --- |
| Host | Arch Linux x86_64, kernel 7.1.8, systemd 261 (PID 1), 8 CPUs, 15.7 GB RAM (about 7 GB available), `/` 352 GB free |
| Listeners | Nothing listens on TCP 80, 443, 8080, 8443 or 18970–18989 |
| Reverse proxies and tunnels | No nginx, Caddy, Traefik, HAProxy or cloudflared binary or process |
| Present | `tailscale`/`tailscaled` (running), Docker (`dockerd`, `containerd` running; **not** proposed for this service) |
| Account and paths | No `flh-demo` user or group; `/srv` exists; `/srv/flh-demo` absent |
| Privilege | The task user has no passwordless sudo. Every install step below needs the owner's root |
| DNS | `flh.vanquisher.world` has no address. `vanquisher.world` resolves to `185.199.109.153` (a GitHub Pages address). **The DNS provider and its nameservers were not determined** |
| Public inbound | **Not assumed and not tested.** Whether the NAS has a public IP, CGNAT or a router port forward is unknown |

**Missing prerequisites (named, not installed):**
1. Owner confirmation of `flh.vanquisher.world`.
2. Knowing where `vanquisher.world` DNS is hosted. Option A needs the zone in
   a Cloudflare account; it currently resolves the apex to GitHub Pages.
3. The `nginx` package (Arch `extra`).
4. The `cloudflared` package. Check with `pacman -Si cloudflared` before relying
   on it.
5. A Cloudflare account. The free tier is sufficient for a tunnel; nothing paid
   is required.
6. Root on the NAS for the steps below.

## Ingress options

| Option | Public inbound needed? | Custom hostname | New software on the NAS | Cost | Assessment |
| --- | --- | --- | --- | --- | --- |
| **A. Cloudflare Tunnel** (recommended) | No (outbound-only) | Yes, if the zone is on Cloudflare | cloudflared, nginx | Free tier | No listener exposed, TLS and DDoS at the edge. Needs a DNS move/onboarding if the zone is elsewhere. Cloudflare sees the traffic |
| B. Public VPS reverse proxy over Tailscale | No for the NAS; yes for the VPS | Yes, any DNS | nginx on the NAS bound to the tailnet address, or LISTEN_HOST set to the tailnet IP | **Paid VPS** (out of scope now) | Full control of TLS (certbot on the VPS), more moving parts |
| C. Router port forward 443 → NAS nginx + Let's Encrypt | **Yes** (unverified; CGNAT would make it impossible) | Yes | nginx, certbot | Free | Exposes the home IP; requires router changes. Not proposed without proof of inbound reachability |
| D. Tailscale Funnel | No | **No**: `<node>.<tailnet>.ts.net` only | None (already installed) | Free | Fine as a **temporary external preview** before DNS is ready; does not meet the `flh.vanquisher.world` goal |

**Recommendation:** A. If the zone cannot move to Cloudflare, choose between B
(paid) and C (once inbound reachability is proven). D can serve as an
interim external test.

## Proposed files

They are kept outside the repository in `~/flh081/proposal/`.

| File | SHA-256 | Notes |
| --- | --- | --- |
| `flh-public-demo.service` | `dc512466b60463ffc55d2fdd503f23542458dcf2825a877d7450efdc08f57b69` | The FLH-076 template plus: hostname, `IPAddressDeny=any` / `IPAddressAllow=localhost`, memory/CPU/task/fd limits, `StartLimit*`, extra sandboxing (`ProtectProc`, `SystemCallFilter=@system-service`, …), journald identifier. `systemd-analyze verify` passes with no warnings |
| `nginx-flh-public-demo.conf` | `c4fa56d97c536082d650e5b0be0de068f35d2278e8e1e71b6bbb46c5e65c45e5` | The FLH-076 block adapted: listen `127.0.0.1:18971` (no TLS; the edge terminates it), `CF-Connecting-IP` trusted from loopback only for per-visitor rate limiting, GET/HEAD only, 10 r/s burst 20, 20 connections, HSTS, privacy log format. `nginx -t` **BLOCKED** (nginx absent) |
| `cloudflared-config.yml` | `f74378b0d16db31afd5d3d0c59ceb51455287f60f1b62280d1e2339d5abf72f7` | Ingress `flh.vanquisher.world` → `http://127.0.0.1:18971`, catch-all 404, `no-autoupdate`. `TUNNEL_UUID` is a placeholder; credentials stay in `/etc/cloudflared/` (0600), never in the repository or a package |

**Resource sizing** (measured in FLH-081, `resource_probe.py`):
- **Memory:** 21 MB RSS idle and 28 MB peak at 8-way load, so 256 MB is a
  roughly 9× margin and `MemoryHigh` at 128 MB throttles well before the hard
  limit.
- **Threads and CPU:** 15 threads under load, and about 12.7 ms CPU per
  request. `CPUQuota=200%` caps the demo at 2 of 8 cores, about 150 req/s,
  well above the edge per-visitor limit.
- **Startup:** ready in 0.27 s.
- **Disk:** about 70 MB per release, plus 41 MB per archived tarball.

## Ordered deployment commands (for later human approval)

Run on the NAS as the owner. `R` is the candidate's location after the task.
Stop at any step that does not produce the stated result.

```sh
# 0. Confirm prerequisites (decisions, not commands): hostname, Cloudflare zone, Option A.
R=$HOME/flh081/release; P=$HOME/flh081/proposal
NAME=flh-public-demo-flh081-rc1

# 1. Verify the candidate and the rollback package.
(cd "$R" && sha256sum -c "$NAME.tar.gz.sha256")                        # OK; 536966c4…
(cd ~/flh078/release && sha256sum -c flh-public-demo-flh078-rc1.tar.gz.sha256)   # OK; 78fb5495…

# 2. Service account (no login, no home).
sudo useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/bin/nologin flh-demo

# 3. Versioned, root-owned, read-only layout.
sudo install -d -o root -g root -m 0755 /srv/flh-demo /srv/flh-demo/releases /srv/flh-demo/archive
sudo install -o root -g root -m 0444 "$R/$NAME.tar.gz" "$R/$NAME.tar.gz.sha256" /srv/flh-demo/archive/
sudo install -o root -g root -m 0444 ~/flh078/release/flh-public-demo-flh078-rc1.tar.gz \
  ~/flh078/release/flh-public-demo-flh078-rc1.tar.gz.sha256 /srv/flh-demo/archive/
(cd /srv/flh-demo/archive && sha256sum -c "$NAME.tar.gz.sha256" flh-public-demo-flh078-rc1.tar.gz.sha256)
for t in "$NAME" flh-public-demo-flh078-rc1; do
  sudo tar -xzf "/srv/flh-demo/archive/$t.tar.gz" -C /srv/flh-demo/releases --no-same-owner
  sudo chown -R root:root "/srv/flh-demo/releases/$t"
  sudo chmod -R a-w,a+rX "/srv/flh-demo/releases/$t"
done

# 4. Validate in place as the service user (writes nothing).
sudo -u flh-demo /srv/flh-demo/releases/$NAME/validate-release.sh                # CANDIDATE …, exit 0

# 5. Point "current" at the release (atomic switch).
cd /srv/flh-demo && sudo ln -sfn "releases/$NAME" current.new && sudo mv -T current.new current

# 6. Install, check and start the service (loopback only).
sudo install -o root -g root -m 0644 "$P/flh-public-demo.service" /etc/systemd/system/flh-public-demo.service
sudo systemd-analyze verify /etc/systemd/system/flh-public-demo.service       # no output
sudo systemctl daemon-reload
sudo systemctl enable --now flh-public-demo.service
systemctl --no-pager status flh-public-demo.service
ss -ltn 'sport = :18970'                                                       # 127.0.0.1:18970 only
curl -fsS http://127.0.0.1:18970/readyz
curl -fsS http://127.0.0.1:18970/knowledge-library/demo | python3 -c 'import json,sys; a=json.load(sys.stdin)["artifact"]; print(a["version"], a["manifest_sha256"], a["real_model"])'
#   expect: d025f217f4d76396 dfe6e94de6664c18be2ae65a27ad9b6c107e7ceefb56a1627fe3f54d4788bcab True
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' http://127.0.0.1:18970/healthz   # 403
systemd-analyze security flh-public-demo.service | tail -1                    # record the exposure score

# 7. nginx on loopback (install is a prerequisite decision).
sudo pacman -S --needed nginx
sudo install -d -m 0755 /etc/nginx/conf.d
sudo install -o root -g root -m 0644 "$P/nginx-flh-public-demo.conf" /etc/nginx/conf.d/flh-public-demo.conf
#   ensure /etc/nginx/nginx.conf's http{} block contains:  include /etc/nginx/conf.d/*.conf;
#   and that the stock server{} does not listen on a public address (or remove it).
sudo nginx -t
sudo systemctl enable --now nginx
ss -ltn | grep -E ':(80|443|18971)\b'                                          # only 127.0.0.1:18971 expected
curl -fsS -H 'Host: flh.vanquisher.world' http://127.0.0.1:18971/readyz
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Host: flh.vanquisher.world' http://127.0.0.1:18971/   # 405

# 8. Cloudflare Tunnel (needs the zone in Cloudflare; interactive login in a browser).
sudo pacman -S --needed cloudflared                                            # verify availability first
cloudflared tunnel login
cloudflared tunnel create flh-demo                                             # prints TUNNEL_UUID; writes ~/.cloudflared/<uuid>.json
sudo install -d -m 0700 /etc/cloudflared
sudo install -m 0600 ~/.cloudflared/<TUNNEL_UUID>.json /etc/cloudflared/
sed "s/TUNNEL_UUID/<TUNNEL_UUID>/g" "$P/cloudflared-config.yml" | sudo tee /etc/cloudflared/config.yml >/dev/null
cloudflared tunnel route dns flh-demo flh.vanquisher.world                     # creates the proxied CNAME
sudo cloudflared --config /etc/cloudflared/config.yml service install         # or the packaged unit, if provided
sudo systemctl enable --now cloudflared
#   Cloudflare dashboard: SSL/TLS "Always Use HTTPS" on, minimum TLS 1.2; optional edge rate-limit rule.
```

## External acceptance checks

Run these from a network that is neither the LAN nor the tailnet, such as a
phone on mobile data.

| # | Check | Expect |
| --- | --- | --- |
| 1 | `dig +short flh.vanquisher.world` | Cloudflare proxy addresses |
| 2 | `curl -sSI https://flh.vanquisher.world/` | `200`, valid certificate for the host, `Strict-Transport-Security`, `X-Frame-Options: DENY` |
| 3 | `curl -sSI http://flh.vanquisher.world/` | Redirect to `https://` |
| 4 | `curl -fsS https://flh.vanquisher.world/api/knowledge-library/demo` | `artifact.version` `d025f217f4d76396`, `manifest_sha256` `dfe6e94d…`, `real_model: true`, `read_only: true` |
| 5 | `…/api/knowledge-library/concepts?q=subj`; `…/api/knowledge-library/demo/semantic-search?preset=miss-someone`; `…/api/knowledge-library/demo/hybrid-search?preset=subjunctive` | `200` with results |
| 6 | `…/api/knowledge-library/units/1/source` | Original question "Why is it « il faut que je fasse »…" |
| 7 | `curl -X POST …/api/knowledge-library/concepts`; `…/api/knowledge-library/demo/semantic-search?q=free`; `…/artifact/demo.db`; `…/RELEASE.json`; `…/api/entries` | `405`; `400`; `404`; `404`; `404` |
| 8 | 50 rapid requests from one client | Some `503` from the nginx rate limit (10 r/s, burst 20) |
| 9 | Browser: open the site, run a keyword search, a semantic preset and a hybrid preset, open a Concept, open its source, go back | Matches the FLH-076/078 browser flows (`accept.mjs`); no console errors |
| 10 | On the NAS: `ss -ltn` | Only loopback listeners for 18970/18971; no new public port |
| 11 | `sudo systemctl restart flh-public-demo` then check 4 again | Same identity |
| 12 (optional) | Reboot the NAS | Service, nginx and tunnel come back; check 4 passes |

## Logging and monitoring

- **Demo:** `journalctl -u flh-public-demo`. It logs only startup (artifact
  identity, warnings) and shutdown, never request contents. Retention follows
  the host's existing journald configuration, which is not changed.
- **nginx:** `/var/log/nginx/flh-public-demo.{access,error}.log`.
  - The access format omits the query string (visitor search text) and the
    client IP.
  - Rotation: keep 14 days. Use the package's logrotate policy if present,
    otherwise add `/etc/logrotate.d/flh-public-demo` (daily, `rotate 14`,
    `compress`, `missingok`).
- **cloudflared:** `journalctl -u cloudflared`.
- **Liveness:** `curl -fsS http://127.0.0.1:18970/readyz` (works with the
  public Host allowlist set; measured). An external uptime check of
  `https://flh.vanquisher.world/healthz` is optional.

## Rollback and removal

1. **Previous release:**
   ```sh
   cd /srv/flh-demo && sudo ln -sfn releases/flh-public-demo-flh078-rc1 current.new && sudo mv -T current.new current
   sudo systemctl restart flh-public-demo
   ```
   Then repeat the identity check (the artifact is the same).
2. **Take it offline immediately** without touching the release:
   `sudo systemctl stop cloudflared`. Optionally delete the public hostname in
   Cloudflare.
3. **Stop the demo only:** `sudo systemctl stop flh-public-demo`. nginx then
   returns 502 on loopback only.
4. **Full removal:**
   - `sudo systemctl disable --now cloudflared nginx flh-public-demo`;
   - remove `/etc/systemd/system/flh-public-demo.service`,
     `/etc/nginx/conf.d/flh-public-demo.conf` and `/etc/cloudflared/`;
   - `cloudflared tunnel delete flh-demo`;
   - `sudo userdel flh-demo`;
   - `sudo rm -rf /srv/flh-demo`, after keeping the archive tarballs if
     wanted.

**A future release** follows steps 1, 3, 4 and 5: archive, extract
read-only, validate, then switch `current`. After that,
`systemctl restart flh-public-demo` and the external checks. Keep the last
known-good release extracted for step 1 of rollback.

## Risks and open points

- **DNS:** the zone location is unknown, and moving it to Cloudflare affects
  the apex GitHub Pages site. The owner must confirm before any DNS change.
- **Cloudflare:** it terminates TLS and sees all traffic. For this synthetic,
  read-only demo that is acceptable, but it is a trust decision.
- **Unverified on this host:** nginx and cloudflared configurations (both
  absent), and the runtime behaviour of the unit's sandboxing directives,
  which were only syntax-checked. Run `systemd-analyze security` and the
  identity check after step 6.
- **Encoder address in the package:** `RELEASE.json` and
  `artifact/provenance.json` contain the encoder's tailnet address. Neither is
  served (404 verified), so this matters only if the tarball is shared.
- **Retrieval quality:** not claimed. With 12 synthetic Concepts, one of 8
  semantic presets ("although") ranks a non-intuitive Concept first.
- **Real-browser acceptance:** NOT RUN in FLH-081. Prior FLH-078 evidence
  covers byte-identical server, web and artifact; external check 9 repeats it
  in production.
