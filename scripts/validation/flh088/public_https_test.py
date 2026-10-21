#!/usr/bin/env python3
"""FLH-088 offline checks of deploy/aws/host/flh-public-https.

Part 1 runs the tool's `render` command and its argument/privilege refusals.
Part 2 runs preflight/enable/status/disable against an isolated FLH_SYSROOT
with fake system tools (dnf, rpm, nginx, certbot, systemctl, curl, ss) and a
fake recursive DNS resolver on 127.0.0.1: DNS outcomes, nginx-configuration
and renewal refusals, INCOMPLETE status, staging -> production reruns and
disable. No real nginx, certbot, systemd, network or AWS; nginx -t on the
rendered files happens on the instance (enable runs it before every reload).

    python3 -B scripts/validation/flh088/public_https_test.py
"""
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TOOL = os.path.join(REPO, "deploy", "aws", "host", "flh-public-https")
HOST = "demo.example.com"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def run(args, env_extra=None):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "FLH_CONFIG": "/nonexistent"}
    env.update(env_extra or {})
    return subprocess.run(["bash", TOOL] + args, capture_output=True, text=True, env=env)


def strip(text):
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def balanced(text):
    depth = 0
    for c in text:
        depth += {"{": 1, "}": -1}.get(c, 0)
        if depth < 0:
            return False
    return depth == 0


with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "r")
    p = run(["render", out, HOST, "flh-demo"])
    check("render exits 0", p.returncode == 0, p.stderr)
    files = sorted(os.listdir(out)) if os.path.isdir(out) else []
    check("render writes exactly the three nginx files", files == ["10-http.conf", "20-https.conf", "nginx.conf"], files)
    main, http, https = (open(os.path.join(out, f)).read() for f in ("nginx.conf", "10-http.conf", "20-https.conf"))
    allc = strip(main + http + https)

    check("no unrendered shell variables", "${" not in allc and "$2" not in allc and "$3" not in allc)
    check("braces balanced in every file", all(balanced(strip(t)) for t in (main, http, https)))
    check("every directive line ends with ; or a brace",
          all(re.search(r"[;{}]\s*$", l) for l in allc.splitlines() if l.strip()), "")

    # Main configuration.
    check("nginx.conf includes only the FLH site directory", re.findall(r"^\s*include\s+(\S+);", strip(main), re.M) == ["/etc/nginx/flh-demo/*.conf"])
    check("nginx.conf: server_tokens off, logs to journald", "server_tokens off;" in main and main.count("syslog:server=unix:/dev/log") == 2)

    # Listeners: only 80 and 443, never the application port.
    listens = re.findall(r"^\s*listen\s+([^;]+);", allc, re.M)
    check("listeners are only 80 and 443", sorted(set(l.split()[0] for l in listens)) == ["443", "80"], listens)
    check("no listener on 18970 or on a specific address", not any(":" in l or "18970" in l for l in listens))

    # Upstream: only the loopback demo.
    proxies = re.findall(r"^\s*proxy_pass\s+([^;]+);", allc, re.M)
    check("single upstream http://127.0.0.1:18970", proxies == ["http://127.0.0.1:18970"], proxies)
    check("HTTP port has no proxy_pass", "proxy_pass" not in strip(http))

    # Port 80.
    check("80: default server drops other names (444)", re.search(r"listen 80 default_server;\s*server_name _;\s*location / \{ return 444; \}", http))
    check("80: ACME challenge served from the webroot only", "location ^~ /.well-known/acme-challenge/" in http and "root /var/lib/flh-acme;" in http)
    check("80: redirect to https on the exact host", f"return 301 https://{HOST}$request_uri;" in http)
    check("80: exact server_name", re.findall(r"server_name\s+([^;]+);", http) == ["_", HOST])

    # Port 443.
    check("443: unknown SNI rejected", re.search(r"listen 443 ssl default_server;\s*ssl_reject_handshake on;", https))
    check("443: exact server_name", re.findall(r"server_name\s+([^;]+);", https) == [HOST])
    check("443: Let's Encrypt certificate paths for the cert name",
          "/etc/letsencrypt/live/flh-demo/fullchain.pem;" in https and "/etc/letsencrypt/live/flh-demo/privkey.pem;" in https)
    check("443: TLS 1.2/1.3 only", "ssl_protocols TLSv1.2 TLSv1.3;" in https)
    check("443: GET/HEAD only", "if ($request_method !~ ^(GET|HEAD)$) { return 405; }" in https)
    check("443: no request bodies forwarded", "proxy_pass_request_body off;" in https and "client_max_body_size 1k;" in https)
    check("443: Host passed, forwarding headers blanked",
          "proxy_set_header Host $host;" in https and all(f'proxy_set_header {h} "";' in https for h in ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded")))
    check("443: per-address rate and connection limits", "limit_req zone=flh_demo" in https and "limit_conn flh_demo_conn 20;" in https)
    check("443: security headers", all(h in https for h in ("X-Content-Type-Options nosniff", "Referrer-Policy no-referrer", "X-Frame-Options DENY")))
    check("no HSTS (keeps the documented rollback to private access clean)", "Strict-Transport-Security" not in allc)
    # Standard ports only: visitors never see a port in the public URL.
    urls = re.findall(r"https://[^\s;]+", allc)
    check("every https:// URL is port-less on the exact host", urls == [f"https://{HOST}$request_uri"], urls)
    check("TLS listeners are only on 443", sorted(l for l in listens if "ssl" in l) == ["443 ssl", "443 ssl default_server"], listens)
    check("no alternative public port (8443/8080/4443) anywhere", not re.search(r"\b(8443|8080|4443)\b", allc))

    # Staging certificate name and PORT from the deploy configuration.
    cfg = os.path.join(tmp, "deploy.env")
    with open(cfg, "w") as f:
        f.write("PORT=18999\n")
    p = run(["render", os.path.join(tmp, "s"), HOST, "flh-demo-staging"], {"FLH_CONFIG": cfg})
    s = open(os.path.join(tmp, "s", "20-https.conf")).read() if p.returncode == 0 else ""
    check("render honours PORT from deploy.env and the staging cert name",
          "proxy_pass http://127.0.0.1:18999;" in s and "/etc/letsencrypt/live/flh-demo-staging/" in s, p.stderr)

    # Host-name validation (also what reaches HTTP_ALLOWED_HOSTS and certbot -d).
    bad = ["", "203.0.113.7", "Demo.Example.com", "*.example.com", "localhost", "demo.example.com:443",
           "demo.example.com.", "demo..example.com", "-demo.example.com", "demo.example.com;evil", "demo example.com",
           "demo.example.com\nserver_name evil", "a" * 64 + ".example.com", "demo.example.123"]
    for h in bad:
        p = run(["render", os.path.join(tmp, "bad"), h, "flh-demo"])
        check(f"refuses host {h!r}", p.returncode == 2 and not os.path.exists(os.path.join(tmp, "bad")), p.stderr.strip())
    for h in ["demo.example.com", "flh-demo.example.co.uk", "x1.example.com"]:
        p = run(["render", os.path.join(tmp, "ok-" + h), h, "flh-demo"])
        check(f"accepts host {h!r}", p.returncode == 0, p.stderr.strip())
    for c in ["", "Flh", "../x", "a" * 41]:
        p = run(["render", os.path.join(tmp, "badc"), HOST, c])
        check(f"refuses cert name {c!r}", p.returncode == 2)

    # preflight names a port-80/443 conflict instead of choosing another port.
    fake = os.path.join(tmp, "fakebin")
    os.makedirs(fake)
    def fake_tool(name, body):
        path = os.path.join(fake, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
    fake_tool("getenforce", "echo Permissive")
    fake_tool("systemctl", "exit 3")
    path = fake + ":" + os.environ.get("PATH", "/usr/bin:/bin")
    for holder, port in (("xray", "443"), ("httpd", "80")):
        fake_tool("ss", 'case "$*" in *":%s"*) echo \'LISTEN 0 511 0.0.0.0:%s 0.0.0.0:* users:(("%s",pid=7,fd=3))\' ;; esac' % (port, port, holder))
        p = run(["preflight", HOST], {"FLH_ALLOW_NONROOT": "1", "PATH": path})
        check(f"preflight stops when {holder} holds port {port}", p.returncode == 1
              and f"port {port} is already in use" in p.stderr and holder in p.stderr, p.stderr.strip())
    fake_tool("ss", 'case "$*" in *":80"*|*":443"*) echo \'LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=7,fd=3))\' ;; esac')
    p = run(["preflight", HOST], {"FLH_ALLOW_NONROOT": "1", "PATH": path})
    check("preflight accepts ports held by nginx (re-run) and continues to the next check",
          p.returncode == 1 and "already in use" not in p.stderr and "is not active" in p.stderr, p.stderr.strip())

    # Privileged commands refuse non-root before doing anything.
    if os.geteuid() != 0:
        for args in (["enable", HOST], ["disable"], ["preflight", HOST]):
            p = run(args)
            check(f"{args[0]} refuses non-root", p.returncode == 2 and "run as root" in p.stderr, p.stderr.strip())
    p = run(["bogus"])
    check("unknown command exits 2 with usage", p.returncode == 2 and "usage" in p.stderr)
    p = run(["enable", HOST, "--wat"], {"FLH_ALLOW_NONROOT": "1"})
    check("unknown enable option exits 2", p.returncode == 2)

# --- Behavioural tests: preflight DNS, enable/rerun/disable, nginx and renewal refusals ---
# Real script, isolated FLH_SYSROOT, fake system tools on PATH, and a fake
# recursive DNS resolver on 127.0.0.1 (FLH_RESOLVER) that exercises the real
# DNS query code. Nothing touches the real /etc, systemd, network or AWS.

EIP, OLD = "203.0.113.10", "198.51.100.7"
PRISTINE = "# package default nginx.conf (fixture)\nuser nginx;\nhttp { include /etc/nginx/conf.d/*.conf; }\n"


class FakeResolver:
    """UDP DNS server; behaviour[qtype] is ("answer", [addr...]) | ("nodata",) |
    ("nxdomain",) | ("servfail",) | ("timeout",) | ("nonrecursive",) | ("cname", target)."""

    def __init__(self):
        self.behaviour = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                return
            i = 12
            while data[i]:
                i += 1 + data[i]
            question = data[12:i + 5]
            qtype = struct.unpack(">H", data[i + 1:i + 3])[0]
            kind = self.behaviour.get(qtype, ("nodata",))
            if kind[0] == "timeout":
                continue
            flags, answers = 0x8180, []
            if kind[0] == "nxdomain":
                flags = 0x8183
            elif kind[0] == "servfail":
                flags = 0x8182
            elif kind[0] == "nonrecursive":
                flags = 0x8100
            elif kind[0] == "answer":
                fam = socket.AF_INET if qtype == 1 else socket.AF_INET6
                for a in kind[1]:
                    rd = socket.inet_pton(fam, a)
                    answers.append(struct.pack(">HHHIH", 0xC00C, qtype, 1, 300, len(rd)) + rd)
            elif kind[0] == "cname":
                target = b"".join(bytes([len(l)]) + l.encode() for l in kind[1].split(".")) + b"\0"
                answers.append(struct.pack(">HHHIH", 0xC00C, 5, 1, 300, len(target)) + target)
            reply = data[:2] + struct.pack(">HHHHH", flags, 1, len(answers), 0, 0) + question + b"".join(answers)
            self.sock.sendto(reply, addr)


FAKES = {
    "ss": "exit 0",
    "getenforce": "echo Permissive",
    "curl": '''case "$*" in
  *api/token*) echo token ;;
  *public-ipv4*) echo "$FAKE_IP" ;;
  *readyz*) echo '{"status":"ready"}' ;;
  *) exit 7 ;;
esac''',
    "dnf": '''echo "dnf $*" >> "$FAKE/calls.log"
case "$1 $2" in
  "-y -q") mkdir -p "$FLH_SYSROOT/etc/nginx/conf.d" "$FLH_SYSROOT/etc/nginx/default.d"
           [ -e "$FLH_SYSROOT/etc/nginx/nginx.conf" ] || cp "$FAKE/pristine.conf" "$FLH_SYSROOT/etc/nginx/nginx.conf" ;;
esac
exit 0''',
    "rpm": '''case "$1" in
  -qf) case "$2" in
         */etc/nginx/nginx.conf) [ "${FAKE_NGINX_UNOWNED:-}" = 1 ] && { echo "file $2 is not owned by any package"; exit 1; }
                                 echo nginx-core-1.28.0-1.amzn2023 ;;
         */certbot) echo certbot-2.11.0-1.amzn2023 ;;
         *) echo "file $2 is not owned by any package"; exit 1 ;;
       esac ;;
  -ql) echo /usr/bin/certbot
       case "${FAKE_RENEWAL:-timer}" in
         timer) echo /usr/lib/systemd/system/certbot-renew.service; echo /usr/lib/systemd/system/certbot-renew.timer ;;
         cron) echo /etc/cron.d/certbot ;;
       esac ;;
  -V) [ -n "${FAKE_RPMV:-}" ] && printf '%s\\n' "$FAKE_RPMV"; [ -z "${FAKE_RPMV:-}" ] || exit 1 ;;
esac''',
    "nginx": 'exit "${FAKE_NGINX_T:-0}"',
    "certbot": '''echo "certbot $*" >> "$FAKE/calls.log"
name=""; prev=""
for a in "$@"; do [ "$prev" = --cert-name ] && name=$a; prev=$a; done
mkdir -p "$FLH_SYSROOT/etc/letsencrypt/live/$name" "$FLH_SYSROOT/etc/letsencrypt/renewal"
echo cert > "$FLH_SYSROOT/etc/letsencrypt/live/$name/fullchain.pem"
{ echo "[renewalparams]"; echo "authenticator = webroot"
  [ "${FAKE_NO_HOOK:-}" = 1 ] || echo "renew_hook = systemctl reload nginx"; } > "$FLH_SYSROOT/etc/letsencrypt/renewal/$name.conf"''',
    "systemctl": '''echo "systemctl $*" >> "$FAKE/calls.log"
st="$FAKE/units"; mkdir -p "$st"
args=""; for a in "$@"; do case "$a" in --quiet|--now) ;; *) args="$args $a" ;; esac; done
set -- $args
case "$1" in
  enable) shift; for u in "$@"; do touch "$st/$u.enabled" "$st/$u.active"; done ;;
  disable) shift; for u in "$@"; do rm -f "$st/$u.enabled" "$st/$u.active"; done ;;
  is-enabled) [ -e "$st/$2.enabled" ] && echo enabled || { echo disabled; exit 1; } ;;
  is-active) case "$2" in
      flh-public-demo.service) ok=1 ;;
      crond) [ "${FAKE_CROND:-}" = 1 ] && ok=1 || ok=0 ;;
      *) [ -e "$st/$2.active" ] && ok=1 || ok=0 ;;
    esac
    [ "$ok" = 1 ] && { echo active; exit 0; }; echo inactive; exit 3 ;;
  show) [ "${FAKE_NEXT:-}" = none ] && echo "" || echo "${FAKE_NEXT:-Wed 2026-10-21 04:12:00 UTC}" ;;
  *) exit 0 ;;
esac''',
}


class Host:
    def __init__(self, base, resolver):
        self.dir = tempfile.mkdtemp(dir=base)
        self.root = os.path.join(self.dir, "root")
        self.fake = os.path.join(self.dir, "fake")
        self.bin = os.path.join(self.fake, "bin")
        os.makedirs(self.bin)
        os.makedirs(os.path.join(self.root, "etc", "flh-demo"))
        for name, body in FAKES.items():
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(path, 0o755)
        with open(os.path.join(self.fake, "pristine.conf"), "w") as f:
            f.write(PRISTINE)
        rel = os.path.join(self.fake, "flh-release")
        with open(rel, "w") as f:
            f.write("#!/bin/sh\necho 'live identity: (match)'\n")
        os.chmod(rel, 0o755)
        self.resolver = resolver
        self.env = {
            "PATH": self.bin + ":" + os.environ.get("PATH", "/usr/bin:/bin"), "FAKE": self.fake,
            "FLH_SYSROOT": self.root, "FLH_RELEASE": rel, "FLH_RESOLVER": f"127.0.0.1:{resolver.port}",
            "FLH_ALLOW_NONROOT": "1", "FLH_INSTALL_OWNER": str(os.getuid()), "FLH_INSTALL_GROUP": str(os.getgid()),
            "FAKE_IP": EIP,
        }

    def run(self, *args, **extra):
        env = dict(self.env)
        env.update(extra)
        return run(list(args), env)

    def path(self, *p):
        return os.path.join(self.root, *p)

    def read(self, *p):
        with open(self.path(*p)) as f:
            return f.read()

    def calls(self):
        try:
            with open(os.path.join(self.fake, "calls.log")) as f:
                return f.read().replace("--now ", "").replace("--quiet ", "")
        except FileNotFoundError:
            return ""


resolver = FakeResolver()


def dns(a, aaaa):
    resolver.behaviour = {1: a, 28: aaaa}


with tempfile.TemporaryDirectory() as base:
    h = Host(base, resolver)

    # preflight: DNS outcomes (real query code against the fake resolver).
    cases = [
        ("A = EIP, AAAA verified empty", ("answer", [EIP]), ("nodata",), 0, "preflight ok"),
        ("AAAA present (IPv6 destination)", ("answer", [EIP]), ("answer", ["2001:db8::1"]), 1, "has AAAA 2001:db8::1"),
        ("AAAA lookup SERVFAIL", ("answer", [EIP]), ("servfail",), 1, "AAAA lookup for flhdemo.example.com failed (rcode-2)"),
        ("AAAA lookup timeout", ("answer", [EIP]), ("timeout",), 1, "failed (timeout)"),
        ("AAAA from a non-recursive server", ("answer", [EIP]), ("nonrecursive",), 1, "failed (resolver-not-recursive)"),
        ("AAAA NXDOMAIN contradicting A", ("answer", [EIP]), ("nxdomain",), 1, "contradicting the A answer"),
        ("second A destination (old VPS kept)", ("answer", [OLD, EIP]), ("nodata",), 1, "replace the existing A record"),
        ("A still at the old destination", ("answer", [OLD]), ("nodata",), 1, f"A is '{OLD}', expected only {EIP}"),
        ("A is a CNAME", ("cname", "elsewhere.example.net"), ("nodata",), 1, "is a CNAME (elsewhere.example.net)"),
        ("name does not exist", ("nxdomain",), ("nxdomain",), 1, "has no A record (nxdomain)"),
        ("A lookup SERVFAIL", ("servfail",), ("nodata",), 1, "A lookup for flhdemo.example.com failed (rcode-2)"),
    ]
    for name, a, aaaa, code, text in cases:
        dns(a, aaaa)
        p = h.run("preflight", "flhdemo.example.com")
        out = p.stdout + p.stderr
        check(f"preflight DNS: {name}", p.returncode == code and text in out, out.strip())
    check("preflight changes nothing", not os.path.exists(h.path("etc", "nginx")) and "certbot certonly" not in h.calls()
          and "dnf -y" not in h.calls() and "systemctl enable" not in h.calls())

    dns(("answer", [EIP]), ("nodata",))
    HOSTNAME = "flhdemo.example.com"

    # First enable (staging) on a pristine package configuration.
    p = h.run("enable", HOSTNAME, "--staging")
    check("enable --staging succeeds on the pristine package nginx.conf", p.returncode == 0, (p.stdout + p.stderr).strip())
    check("staging: original nginx.conf saved byte for byte", h.read("etc", "nginx", "nginx.conf.flh-original") == PRISTINE)
    check("staging: nginx.conf is this tool's", h.read("etc", "nginx", "nginx.conf").startswith("# FLH-088: nginx for the FLH read-only public demo only"))
    check("staging: certbot used --staging and cert name flh-demo-staging",
          re.search(r"certbot certonly .*--cert-name flh-demo-staging .*--staging", h.calls()))
    check("staging: renewal timer from the package file list enabled before HTTPS",
          h.calls().index("systemctl enable certbot-renew.timer") < h.calls().index("systemctl daemon-reload"))
    check("staging: state records host, cert and renewal",
          h.read("etc", "flh-demo", "public-https.env") == f"PUBLIC_HOST={HOSTNAME}\nCERT_NAME=flh-demo-staging\nRENEWAL=timer certbot-renew.timer\n")
    check("staging: drop-in sets HTTP_ALLOWED_HOSTS",
          f"Environment=HTTP_ALLOWED_HOSTS={HOSTNAME}" in h.read("etc", "systemd", "system", "flh-public-demo.service.d", "50-public-host.conf"))
    check("staging: output says the next step is production", "next: enable" in p.stdout)

    # Safe rerun: production over staging.
    p = h.run("enable", HOSTNAME)
    check("rerun enable (production) succeeds", p.returncode == 0, (p.stdout + p.stderr).strip())
    check("rerun: saved original is still the package file (not overwritten)", h.read("etc", "nginx", "nginx.conf.flh-original") == PRISTINE)
    check("rerun: HTTPS uses the production certificate", "/etc/letsencrypt/live/flh-demo/fullchain.pem" in h.read("etc", "nginx", "flh-demo", "20-https.conf"))
    last = [l for l in h.calls().splitlines() if l.startswith("certbot certonly")][-1]
    check("rerun: production certbot call uses flh-demo without --staging", "--cert-name flh-demo " in last and "--staging" not in last, last)
    check("rerun: staging certificate cleanup is announced", "certbot delete --cert-name flh-demo-staging" in p.stdout)
    p = h.run("status")
    check("status reports the renewal timer and its next run", "renewal:      certbot-renew.timer active, next Wed 2026-10-21" in p.stdout, p.stdout)

    # disable restores the package configuration; enable works again afterwards.
    p = h.run("disable")
    check("disable succeeds", p.returncode == 0, (p.stdout + p.stderr).strip())
    check("disable: package nginx.conf restored, saved copy consumed",
          h.read("etc", "nginx", "nginx.conf") == PRISTINE and not os.path.exists(h.path("etc", "nginx", "nginx.conf.flh-original")))
    check("disable: drop-in, state and site files removed",
          not os.path.exists(h.path("etc", "systemd", "system", "flh-public-demo.service.d"))
          and not os.path.exists(h.path("etc", "flh-demo", "public-https.env"))
          and not os.listdir(h.path("etc", "nginx", "flh-demo")))
    check("disable: renewal timer stopped", "systemctl disable certbot-renew.timer" in h.calls())
    p = h.run("enable", HOSTNAME)
    check("enable again after disable succeeds", p.returncode == 0, (p.stdout + p.stderr).strip())

    # Existing nginx configuration is refused, never silently disabled.
    def fresh(**setup):
        x = Host(base, resolver)
        os.makedirs(x.path("etc", "nginx", "conf.d"))
        with open(x.path("etc", "nginx", "nginx.conf"), "w") as f:
            f.write(setup.get("conf", PRISTINE))
        for rel, body in setup.get("files", {}).items():
            os.makedirs(os.path.dirname(x.path(*rel.split("/"))), exist_ok=True)
            with open(x.path(*rel.split("/")), "w") as f:
                f.write(body)
        return x

    def refused(x, p, text, conf=PRISTINE):
        return (p.returncode == 1 and text in p.stderr and "certbot certonly" not in x.calls()
                and x.read("etc", "nginx", "nginx.conf") == conf
                and not os.path.exists(x.path("etc", "nginx", "flh-demo", "10-http.conf")))

    x = fresh()
    p = x.run("enable", HOSTNAME, FAKE_RPMV="S.5....T.  c /etc/nginx/nginx.conf")
    check("refuses a locally modified nginx.conf (rpm -V)", refused(x, p, "differs from package nginx-core") and not os.path.exists(x.path("etc", "nginx", "nginx.conf.flh-original")), p.stderr.strip())
    x = fresh()
    p = x.run("enable", HOSTNAME, FAKE_RPMV="S.5....T.  c /etc/nginx/mime.types")
    check("other modified package files do not count as nginx.conf changes", p.returncode == 0, p.stderr.strip())
    x = fresh(files={"etc/nginx/conf.d/vhost.conf": "server { listen 8080; }\n"})
    p = x.run("enable", HOSTNAME)
    check("refuses other configuration in conf.d (names it)", refused(x, p, "conf.d/vhost.conf"), p.stderr.strip())
    x = fresh(files={"etc/nginx/default.d/extra.conf": "location /x {}\n"})
    p = x.run("enable", HOSTNAME)
    check("refuses other configuration in default.d", refused(x, p, "default.d/extra.conf"), p.stderr.strip())
    x = fresh()
    p = x.run("enable", HOSTNAME, FAKE_NGINX_UNOWNED="1")
    check("refuses an nginx.conf not owned by a package", refused(x, p, "not owned by a package"), p.stderr.strip())
    marked = "# FLH-088: nginx for the FLH read-only public demo only (flh-public-https).\n"
    x = fresh(conf=marked)
    p = x.run("enable", HOSTNAME)
    check("refuses a managed nginx.conf whose saved original is missing", refused(x, p, "is missing; refusing", conf=marked), p.stderr.strip())
    x = fresh(files={"etc/nginx/nginx.conf.flh-original": "old\n"})
    p = x.run("enable", HOSTNAME)
    check("refuses to overwrite an existing saved original", refused(x, p, "already exists"), p.stderr.strip())
    x = fresh(files={"etc/nginx/flh-demo/other.conf": "server {}\n"})
    p = x.run("enable", HOSTNAME)
    check("refuses unexpected files in the tool's site directory", refused(x, p, "unexpected files"), p.stderr.strip())

    # Renewal must be the package's own mechanism and must work before HTTPS.
    x = fresh()
    p = x.run("enable", HOSTNAME, FAKE_RENEWAL="none")
    check("no package renewal mechanism: refused before any certificate", refused(x, p, "ships no renewal timer or cron file"), p.stderr.strip())

    def incomplete(x, p, text):
        return (p.returncode == 3 and "INCOMPLETE" in p.stderr and text in (p.stdout + p.stderr)
                and "certbot certonly" in x.calls()
                and not os.path.exists(x.path("etc", "nginx", "flh-demo", "20-https.conf"))
                and not os.path.exists(x.path("etc", "systemd", "system", "flh-public-demo.service.d", "50-public-host.conf"))
                and not os.path.exists(x.path("etc", "flh-demo", "public-https.env")))
    x = fresh()
    p = x.run("enable", HOSTNAME, FAKE_NEXT="none")
    check("timer without a next run: INCOMPLETE (exit 3), HTTPS not enabled", incomplete(x, p, "has no next run"), (p.stdout + p.stderr).strip())
    p = x.run("disable")
    check("disable after INCOMPLETE stops the package timer (no state file)",
          p.returncode == 0 and "systemctl disable certbot-renew.timer" in x.calls(), (p.stdout + p.stderr).strip())
    x = fresh()
    p = x.run("enable", HOSTNAME, FAKE_NO_HOOK="1")
    check("renewal config without the nginx reload hook: INCOMPLETE", incomplete(x, p, "no nginx reload hook"), (p.stdout + p.stderr).strip())
    x = fresh(files={"etc/cron.d/certbot": "0 */12 * * * root certbot renew -q\n"})
    p = x.run("enable", HOSTNAME, FAKE_RENEWAL="cron")
    check("cron mechanism without crond: INCOMPLETE", incomplete(x, p, "needs crond"), (p.stdout + p.stderr).strip())
    x = fresh(files={"etc/cron.d/certbot": "0 */12 * * * root certbot renew -q\n"})
    p = x.run("enable", HOSTNAME, FAKE_RENEWAL="cron", FAKE_CROND="1")
    check("cron mechanism with crond running: enabled", p.returncode == 0
          and "RENEWAL=cron /etc/cron.d/certbot" in x.read("etc", "flh-demo", "public-https.env"), (p.stdout + p.stderr).strip())

    # enable refuses before touching anything when DNS is not cut over.
    x = fresh()
    dns(("answer", [OLD]), ("nodata",))
    p = x.run("enable", HOSTNAME)
    check("enable before the DNS cutover is refused by preflight", refused(x, p, f"expected only {EIP}") and "dnf -y" not in x.calls(), p.stderr.strip())
    dns(("answer", [EIP]), ("answer", ["2001:db8::1"]))
    p = x.run("enable", HOSTNAME)
    check("enable with an AAAA record is refused before installation", refused(x, p, "has AAAA") and "dnf -y" not in x.calls(), p.stderr.strip())

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if not ok and detail else ""))
print(f"public https tool test: {len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
