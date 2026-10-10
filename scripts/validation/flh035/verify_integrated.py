#!/usr/bin/env python3
"""Run the unchanged FLH-034 demo; independently check its integrated contract."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEMO = ROOT / "scripts/demo/flh034/demo.sh"
sys.path.insert(0, str(HERE.parent / "flh026"))
from run import clean_env, owns_listener, snapshot  # noqa: E402
from integrated_checks import check_detail, check_search, require
from linux_demo_checks import verify_identity, safety_probes  # noqa: E402

# Observe the unchanged author's stub at its stdlib request-dispatch boundary.
# No request body, headers, credentials, learning text or response is intercepted.
OBSERVER = '''import os, sys
if sys.argv[0].endswith("stub_extractor.py"):
    from http.server import BaseHTTPRequestHandler
    original = BaseHTTPRequestHandler.handle_one_request
    def observe(self):
        try:
            return original(self)
        finally:
            if getattr(self, "command", None) == "POST":
                with open(os.environ["FLH035_COUNTER"], "a") as output:
                    output.write("POST\\n")
    BaseHTTPRequestHandler.handle_one_request = observe
'''


RELATION_UI_PROBE = r'''import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { writeFileSync } from "node:fs";
import App from "./App";
it("preserves both legal relations without duplicate React keys", async () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  const c = { id: 3, target: "relation probe", pedagogical_intent: "grammar", scope: "",
    identity_features: {}, signature: "{}", preferred_unit_id: null, state: "orphaned",
    lifecycle_state: "normal", support_state: "orphaned", created_at: "t", updated_at: "t" };
  const u = { unit_id: 9, kind: "grammar", canonical: "demo unit", statement: "Synthetic statement",
    example: null, entry_id: 1, extraction_id: 5, extraction_version: 2,
    in_current_extraction: true, admission: "active" };
  globalThis.fetch = vi.fn(async (input) => {
    const path = new URL(String(input), "http://localhost").pathname;
    const body = path === "/api/knowledge-library/concepts/3" ? {
      schema_version: "knowledge_library_concept_v1", concept: c, preferred_unit: null,
      supporting_units: [], non_supporting_members: [], historical_units: [], history_event_count: 2,
      current_relations: ["related", "broader"].map((relation, index) => ({
        relation, link_id: index + 1, decision_source: "human", decided_at: "t", unit: u }))
    } : path === "/api/knowledge-library/concepts" ? {
      schema_version: "knowledge_library_search_v1", query: "", tokens: [], state: "all", limit: 20,
      total_matches: 1, truncated: false, results: [{ concept: c, match_tier: "browse", matched_fields: [],
        current_member_count: 0, supporting_unit_count: 0 }]
    } : { concepts: [], reviewable_units: [] };
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  });
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Knowledge Library" }));
  fireEvent.click(await screen.findByRole("button", { name: "relation probe" }));
  const rows = await screen.findAllByRole("article", { name: "Unit #9" });
  const messages = errors.mock.calls.map((args) => args.map(String).join(" "));
  const duplicate = messages.some((message) => message.includes("same key"));
  writeFileSync(process.env.FLH035_WARNING_REPORT!, JSON.stringify({
    evidence_type: "mocked API + real React/jsdom component", duplicate_key_warning: duplicate,
    rendered_unit_cards: rows.length, console_messages: messages }));
  expect(duplicate).toBe(false);
  expect(rows[0]).toHaveTextContent("RELATED");
  expect(rows[1]).toHaveTextContent("BROADER");
  expect(rows).toHaveLength(2);
  errors.mockRestore();
});'''


def listener_alive(_pid, port):
    # After author stop, /proc/PID/fd can become unreadable during process exit.
    # Require the reserved port to have NO listener at all (a stronger stop check).
    # Live claim/request guards still attribute socket inodes to the recorded PID.
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        for row in Path(name).read_text().splitlines()[1:]:
            fields = row.split()
            if int(fields[1].split(":")[1], 16) == port and fields[3] == "0A":
                return True
    return False


class Acceptance:
    def __init__(self):
        self.parent = Path(tempfile.mkdtemp(prefix="flh035-integrated-"))
        self.work = self.parent / "flh034-demo"
        self.web = self.parent / "web"
        self.home = self.parent / "home"
        self.home.mkdir()
        self.env = clean_env(self.home)
        for name in ("npm-user.conf", "npm-global.conf"):
            (self.parent / name).write_text("")
        self.env.update(GOCACHE=str(self.parent / "gocache"),
                        NODE_OPTIONS="--no-experimental-webstorage",
                        NPM_CONFIG_USERCONFIG=str(self.parent / "npm-user.conf"),
                        NPM_CONFIG_GLOBALCONFIG=str(self.parent / "npm-global.conf"))
        cache_env = {"PATH": self.env["PATH"], "HOME": str(Path.home()),
                     "GOENV": "off", "GOTOOLCHAIN": "local"}
        self.env["GOMODCACHE"] = subprocess.check_output(
            ["go", "env", "GOMODCACHE"], env=cache_env, text=True).strip()
        self.commands = []
        self.cases = []
        self.defects = []
        self.observations = {}
        self.pid = None
        self.stub_pid = None
        self.owned_processes = []
        self.counter = self.parent / "stub-posts.txt"
        self.counter.write_text("")
        hook = self.parent / "observer"
        hook.mkdir()
        (hook / "sitecustomize.py").write_text(OBSERVER)
        self.env.update(PYTHONPATH=str(hook), FLH035_COUNTER=str(self.counter))
        self.sockets = []
        try:
            for name in ("DEMO_PORT", "STUB_PORT"):
                sock = socket.socket()
                self.sockets.append(sock)
                sock.bind(("127.0.0.1", 0))
                self.env[name] = str(sock.getsockname()[1])
        except BaseException:
            for sock in self.sockets:
                sock.close()
            shutil.rmtree(self.parent)
            raise
        self.port = int(self.env["DEMO_PORT"])
        self.stub_port = int(self.env["STUB_PORT"])
        self.demo_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(DEMO.parent.iterdir()) if p.is_file()}
        self.phase_a_hashes = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                               for name in ("expectations.py", "test_expectations.py", "verify_existing.py")}

    def command(self, args, expected=0, timeout=240):
        started = time.monotonic()
        completed = subprocess.run(args, cwd=ROOT, env=self.env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, timeout=timeout)
        self.commands.append({"argv": [str(a) for a in args], "exit": completed.returncode,
                              "seconds": time.monotonic() - started, "output": completed.stdout})
        require(completed.returncode == expected, f"command expected {expected}: {args}: {completed.stdout[-3000:]}")
        return completed

    def counts(self):
        return {"stub_received_posts": len(self.counter.read_text().splitlines())}

    def claim(self):
        self.pid = int((self.work / "server.pid").read_text())
        self.stub_pid = int((self.work / "stub.pid").read_text())
        deadline = time.monotonic() + 4
        while not (owns_listener(self.pid, self.port) and owns_listener(self.stub_pid, self.stub_port)):
            require(time.monotonic() < deadline, "author server/stub did not acquire owned listeners")
            time.sleep(0.02)  # start waits for app readyz; Python stub can still be starting.

        self.owned_processes.extend([(self.pid, self.port), (self.stub_pid, self.stub_port)])
        for pid, executable in ((self.pid, str(self.work / "server")),
                                (self.stub_pid, str(DEMO.parent / "stub_extractor.py"))):
            require(executable in Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0"),
                    "demo PID attribution mismatch")

    def request(self, method, path, body=None, expected=200, raw=False):
        require(self.pid is not None and owns_listener(self.pid, self.port), "refuse unowned API listener")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            data = response.read()
            require(response.status == expected, f"{method} {path}: {response.status}, expected {expected}: {data[:300]!r}")
            return (response.getheaders(), data) if raw else json.loads(data)
        finally:
            conn.close()

    def get(self, path, expected=200):
        root = self.request("GET", path, expected=expected)
        prefixed = self.request("GET", "/api" + path, expected=expected)
        require(root == prefixed, "root /api parity: " + path)
        return root

    def passed(self, name, actual=None):
        self.cases.append({"case": name, "result": "PASS", "actual": actual})
        print("PASS " + name, flush=True)

    def build_and_setup(self):
        started = time.monotonic()
        self.web.mkdir()
        shutil.copytree(ROOT / "web/src", self.web / "src")
        for name in ("index.html", "package.json", "package-lock.json", "vite.config.ts",
                     "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json"):
            shutil.copy2(ROOT / "web" / name, self.web / name)
        # Documented npm ci/build in a private source copy; cache contains public packages.
        cache = self.parent / "npm-cache"
        shutil.copytree(Path("/tmp/flh029-npm-cache/_cacache"), cache / "_cacache")
        self.command(["npm", "--prefix", str(self.web), "ci", "--offline", "--ignore-scripts",
                      "--no-audit", "--no-fund", "--cache", str(cache)])
        self.command(["npm", "--prefix", str(self.web), "run", "build"])
        self.observations["frontend_setup_seconds"] = time.monotonic() - started
        self.command(["npm", "--prefix", str(self.web), "test", "--",
                      "src/pages/KnowledgeLibrary.test.tsx", "--reporter=json",
                      "--outputFile=" + str(self.parent / "library-vitest.json")])
        self.observations["mocked_ui_tests"] = json.loads((self.parent / "library-vitest.json").read_text())
        (self.web / "src/library-relations-probe.test.tsx").write_text(RELATION_UI_PROBE)
        self.env["FLH035_WARNING_REPORT"] = str(self.parent / "react-warning.json")
        self.command(["npm", "--prefix", str(self.web), "test", "--",
                      "src/library-relations-probe.test.tsx", "--reporter=json",
                      "--outputFile=" + str(self.parent / "relation-vitest.json")])
        self.observations["relation_ui_probe"] = json.loads((self.parent / "react-warning.json").read_text())
        self.observations["relation_ui_tests"] = json.loads((self.parent / "relation-vitest.json").read_text())
        self.observations["node"] = self.command(["node", "--version"]).stdout.strip()
        self.observations["npm"] = self.command(["npm", "--version"]).stdout.strip()
        for sock in self.sockets:
            sock.close()
        self.sockets = []
        started = time.monotonic()
        self.command(["sh", str(DEMO), "setup", str(self.work), str(self.web / "dist")])
        self.observations["demo_build_start_seed_seconds"] = time.monotonic() - started
        self.claim()
        verify_identity(self)
        self.observations["fixture_receipt"] = json.loads((self.work / "seed.json").read_text())
        self.observations["compiler"] = self.command(["go", "version"]).stdout.strip()
        compiler = Path(shutil.which("go", path=self.env["PATH"])).resolve()
        self.observations["compiler_sha256"] = hashlib.sha256(compiler.read_bytes()).hexdigest()
        self.observations["binary_sha256"] = hashlib.sha256((self.work / "server").read_bytes()).hexdigest()
        self.observations["python"] = sys.version
        self.observations["platform"] = list(os.uname())
        self.observations["binary_metadata"] = self.command(["go", "version", "-m", str(self.work / "server")]).stdout
        self.passed("documented author setup with production workbench", self.observations["fixture_receipt"])

    def search(self, q="", ids=None, tokens=None, tiers=None, **params):
        data = self.get("/knowledge-library/concepts?" + urlencode({"q": q, **params}))
        if ids is not None:
            check_search(data, ids, tokens, tiers, limit=int(params.get("limit", 20)))
        return data

    def walkthrough(self):
        started = time.monotonic()
        before, counters = snapshot(self.work / "demo.db"), self.counts()
        browse = self.search(ids=[6, 5, 3, 1, 7, 4, 2], tokens=[], tiers=["browse"] * 7)
        self.search("subjonctif", [3, 1, 4, 2], ["subjonctif"], ["identity"] * 4)
        faut = self.get("/knowledge-library/concepts/1")
        check_detail(faut, [9], [1], [3], preferred=9)
        old = self.get("/knowledge-library/units/1/source")
        require(old["entry"]["id"] == 1 and "il faut que je fasse" in old["entry"]["original_input"], "demo source entry")
        require(not old["unit"]["in_current_extraction"] and old["extraction"]["version"] == 1, "historical source")
        require(old["source_interpretation"]["analysis"]["version"] == 1 and old["latest_analysis"]["version"] == 2,
                "source versus latest analysis")
        self.search("fasse", [1, 2], ["fasse"], ["unit_evidence"] * 2)
        faire = self.get("/knowledge-library/concepts/2")
        check_detail(faire, [], [2])
        require(faire["concept"]["state"] == "orphaned", "historical-member orphaned Concept")
        pc = self.get("/knowledge-library/concepts/5")
        check_detail(pc, [5], historical=[6])
        require(pc["historical_units"][0]["current_concept_id"] == 6, "reassigned history")
        manque = self.get("/knowledge-library/concepts/7")
        check_detail(manque, [7], historical=[8])
        require(manque["historical_units"][0]["effective_status"] == "invalid", "INVALID history")
        bien = self.get("/knowledge-library/concepts/3")
        check_detail(bien, [3], [4], preferred=3)
        source = self.get("/knowledge-library/units/3/source")
        interp = source["source_interpretation"]
        require(interp["effective"]["resolution"] == "corrected"
                and "Concession" in interp["effective"]["effective"]["explanation"], "corrected source interpretation")
        require(source["extraction"]["source_feedback_id"] == interp["feedback"]["id"], "feedback provenance")
        require(snapshot(self.work / "demo.db") == before and self.counts() == counters, "walkthrough read-only")
        self.observations["http_presentation_seconds"] = time.monotonic() - started
        self.observations["walkthrough"] = {"browse": browse, "faut": faut, "historical_source": old,
                                            "faire": faire, "reassigned": pc, "invalid": manque,
                                            "bien": bien, "corrected_source": source,
                                            "sqlite_snapshot_sha256": hashlib.sha256(
                                                json.dumps(before, sort_keys=True).encode()).hexdigest(),
                                            "snapshot_equal_after": True, "provider_counters": counters}
        self.passed("documented walkthrough content through real HTTP; no browser interaction", counters)
        self.passed("historical CURRENT SAME search retains orphaned membership without support")

    def search_checks(self):
        before, counters = snapshot(self.work / "demo.db"), self.counts()
        cases = [
            ("SUBJONCTIF", [3, 1, 4, 2], ["subjonctif"]),
            ("  ÊTRE—COMPOSÉ  ", [5], ["etre", "compose"]),
            ("E\u0302TRE COMPOSE\u0301", [5], ["etre", "compose"]),
            ("subj bie", [3], ["subj", "bie"]),
            ("jonctif", [], ["jonctif"]), ("fasse introuvable", [], ["fasse", "introuvable"]),
            ("à y être", [6, 5], ["etre"]),
            ("subj subj", [3, 1, 4, 2], ["subj"]),
            ("mardi", [], ["mardi"]), ("déclencheur", [3, 1], ["declencheur"]),
            ("irreg", [2], ["irreg"]),  # historical member statement; CURRENT SAME retained
            ("malgre", [3], ["malgre"]),  # suppressed current member is searchable
            ("manquer", [7], ["manquer"]),
            ("allee", [6], ["allee"]),  # reassigned evidence searched only under new concept
            ("ensemble", [4], ["ensemble"]),  # identity scope
            ("", [6, 5, 3, 1, 7, 4, 2], []),
        ]
        for q, ids, tokens in cases:
            data = self.search(q, ids, tokens)
            self.passed("search " + repr(q), data)
        for state, ids in [("all", [6, 5, 3, 1, 7, 4, 2]), ("active", [6, 5, 3, 1, 7]),
                           ("orphaned", [4, 2]), ("retired", [])]:
            self.search(ids=ids, tokens=[], state=state)
            self.passed("state filter " + state)
        for limit in (1, 7, 20, 50):
            data = self.search(limit=limit)
            ids = [6, 5, 3, 1, 7, 4, 2][:limit]
            check_search(data, ids, limit=limit, total=7)
            self.passed("limit " + str(limit), data)
        invalid = [{"limit": value} for value in ("0", "51", "-1", "abc", "1.5")]
        invalid += [{"state": "unsupported"}, {"q": "!!!"}, {"q": "à y"},
                    {"q": "x" * 201}, {"q": "é" * 101},
                    {"q": "aa bb cc dd ee ff gg hh ii"}]
        for query in invalid:
            self.get("/knowledge-library/concepts?" + urlencode(query), expected=400)
            self.passed("invalid query " + repr(query))
        for q in ("x" * 200, "é" * 100, "aa bb cc dd ee ff gg hh", "aa " * 9):
            self.search(q, [], list(dict.fromkeys(q.strip().split())) if q.startswith("aa") else None)
            self.passed("accepted query bound " + repr(q))
        self.get("/knowledge-library/concepts?q=%FF", expected=400)
        self.passed("invalid UTF-8 query")
        for suffix, status in [("concepts/999999", 404), ("units/999999/source", 404),
                               ("concepts/0", 400), ("units/0/source", 400)]:
            self.get("/knowledge-library/" + suffix, expected=status)
            self.passed("missing/invalid resource " + suffix)
        require(snapshot(self.work / "demo.db") == before and self.counts() == counters, "search reads changed state/counters")
        self.passed("entire search/error matrix read-only", counters)

    def assets_and_sources(self):
        before, counters = snapshot(self.work / "demo.db"), self.counts()
        headers, index = self.request("GET", "/", raw=True)
        require(index == (self.web / "dist/index.html").read_bytes(), "real production index")
        assets = re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', index)
        require(bool(assets), "index contains production assets")
        for path in assets:
            path = path.decode()
            headers, body = self.request("GET", path, raw=True)
            require(body == (self.web / "dist" / path.lstrip("/")).read_bytes(), "asset content mismatch")
            self.passed("production asset " + path, {"bytes": len(body), "headers": headers})
        for uid in range(1, 11):
            source = self.get(f"/knowledge-library/units/{uid}/source")
            unit = source["unit"]
            extraction = self.get(f"/extractions/{unit['extraction_id']}")
            entry = self.get(f"/entries/{unit['entry_id']}")
            require(source["entry"] == entry, "original source record parity")
            require(source["extraction"]["source_analysis_id"] == extraction["source_analysis_id"], "analysis source attribution")
            interpretation = source["source_interpretation"]
            require(interpretation["analysis"]["id"] == extraction["source_analysis_id"], "analysis source ID")
            fid = interpretation["feedback"]["id"] if interpretation["feedback"] else None
            require(fid == extraction["source_feedback_id"], "feedback source ID")
            membership = self.get(f"/knowledge-units/{uid}/concept-membership")["current_membership"]
            require(source["annotation"]["current_concept_id"] == (membership["concept_id"] if membership else None), "membership source authority")
            self.passed("source chain unit " + str(uid), source)
        require(snapshot(self.work / "demo.db") == before and self.counts() == counters, "assets/source reads changed state")
        self.passed("assets and provenance sequence read-only", counters)

    def safety_and_restart(self):
        before, counters = snapshot(self.work / "demo.db"), self.counts()
        self.command(["sh", str(DEMO), "setup", str(self.work), str(self.web / "dist")], expected=2)
        self.command(["python3", "-B", str(DEMO.parent / "seed.py"), f"http://127.0.0.1:{self.port}"], expected=1)
        occupied = self.parent / "nonempty"
        occupied.mkdir()
        (occupied / "sentinel").write_text("preserve")
        self.command(["sh", str(DEMO), "setup", str(occupied)], expected=2)
        require((occupied / "sentinel").read_text() == "preserve", "nonempty directory mutated")
        require(snapshot(self.work / "demo.db") == before and self.counts() == counters, "repeat setup/seed changed state")
        self.command(["sh", str(DEMO), "setup", "relative-demo"], expected=2)
        self.command(["sh", str(DEMO), "setup", str(ROOT / "flh035-refused-demo")], expected=2)
        self.command(["python3", "-B", str(DEMO.parent / "seed.py"), "http://example.invalid:18934"], expected=1)
        for action in ("start", "stop", "cleanup"):
            self.command(["sh", str(DEMO), action, str(occupied)], expected=2)
        require((occupied / "sentinel").read_text() == "preserve", "unmarked directory changed")
        self.passed("repeat setup/seed, nonempty/relative/repository directories, non-loopback seed, and unmarked lifecycle refusal")
        search = self.search("fasse")
        self.claim()  # Only invoke author stop on attributed, live owned PIDs.
        self.command(["sh", str(DEMO), "stop", str(self.work)])
        for _ in range(100):
            if not listener_alive(self.pid, self.port) and not listener_alive(self.stub_pid, self.stub_port):
                break
            time.sleep(0.02)
        require(not listener_alive(self.pid, self.port) and not listener_alive(self.stub_pid, self.stub_port), "stop left listeners")
        self.command(["sh", str(DEMO), "start", str(self.work), str(self.web / "dist")])
        self.claim()
        require(self.search("fasse") == search, "restart search changed")
        require(snapshot(self.work / "demo.db") == before and self.counts() == counters, "restart changed data/provider calls")
        self.passed("documented stop/start persists database/search; no provider calls", counters)
        verify_identity(self)

    def edges(self):
        # Supported API mutations only, after unchanged demo walkthrough/restart.
        tiers = []
        for intent in ("usage", "grammar"):
            result = self.request("POST", "/concepts", {"identity": {
                "target": "fasse", "pedagogical_intent": intent, "scope": "flh035-tier"}}, expected=201)
            tiers.append(result["concept"]["id"])
        self.search("fasse", tiers + [1, 2], ["fasse"], ["identity"] * 2 + ["unit_evidence"] * 2)
        self.passed("identity orphaned tier precedes active evidence; equal-target ID tie-break")
        self.request("PUT", "/knowledge-units/2/concept-membership", {"concept_id": 1})
        historical = self.search("irreg", [1], ["irreg"], ["unit_evidence"])
        require(historical["results"][0]["current_member_count"] == 3
                and historical["results"][0]["supporting_unit_count"] == 1, "historical reassignment counts")
        self.request("POST", "/concepts/1/preferred-unit", {"unit_id": 2})
        detail = self.get("/knowledge-library/concepts/1")
        check_detail(detail, [9], [1, 2], [3], preferred=2)
        self.passed("historical CURRENT SAME is searchable and preferred, but not support", detail)
        self.request("POST", "/knowledge-units/2/invalid", {}, expected=200)
        self.search("irreg", [], ["irreg"])
        detail = self.get("/knowledge-library/concepts/1")
        check_detail(detail, [9], [1], [3], [2])
        self.passed("INVALID removes historical search membership and preferred", detail)
        self.request("POST", "/knowledge-units/1/invalid", {}, expected=200)
        self.search("fasse", tiers, ["fasse"], ["identity"] * 2)
        self.passed("old extraction wording is excluded after CURRENT SAME is removed")
        self.request("PUT", "/knowledge-units/3/concept-membership", {"concept_id": 1})
        self.request("POST", "/concepts/1/preferred-unit", {"unit_id": 3})
        detail = self.get("/knowledge-library/concepts/1")
        check_detail(detail, [3, 9], historical=[1, 2], preferred=3)
        require({u["entry_id"] for u in detail["supporting_units"]} == {1, 2}, "multiple independent sources")
        self.passed("multiple supporting source entries and explicit preferred; section priority", detail)
        old_source = self.observations["walkthrough"]["corrected_source"]
        aid = old_source["source_interpretation"]["analysis"]["id"]
        self.request("POST", f"/analyses/{aid}/feedback",
                     {"status": "rejected", "user_note": "FLH-035 later feedback"}, expected=201)
        self.request("POST", "/entries/2/analysis", expected=201)
        source = self.get("/knowledge-library/units/3/source")
        require(source["source_interpretation"] == old_source["source_interpretation"],
                "later feedback replaced interpretation used at extraction")
        require(source["latest_analysis"]["version"] == 2, "latest analysis indicator")
        self.passed("later feedback/analysis preserve exact extracted interpretation", source)
        # Unit 9 remains a CURRENT SAME member of concept 1.
        self.request("POST", "/knowledge-units/9/concept-links/relation",
                     {"concept_id": 3, "relation": "related"}, expected=201)
        self.request("POST", "/knowledge-units/9/concept-links/relation",
                     {"concept_id": 3, "relation": "broader"}, expected=201)
        detail = self.get("/knowledge-library/concepts/3")
        relation_ids = [r["unit"]["unit_id"] for r in detail["current_relations"]]
        self.observations["multi_relation_detail"] = detail
        require(relation_ids == [9, 9], "both legal relation rows retained")
        require({r["relation"] for r in detail["current_relations"]} == {"broader", "related"},
                "relation types preserved")
        require(len({r["link_id"] for r in detail["current_relations"]}) == 2,
                "distinct immutable relation events")
        check_detail(detail, [], [4], [9, 9], [3])
        self.passed("multiple legal relations preserved; mocked UI has no duplicate-key warning", detail)

    def additional_safety(self):
        safety_probes(self)

    def run(self):
        self.build_and_setup()
        self.walkthrough()
        self.search_checks()
        self.assets_and_sources()
        self.safety_and_restart()
        self.edges()
        before, counters = snapshot(self.work / "demo.db"), self.counts()
        for cid in range(1, 10):
            self.get(f"/knowledge-library/concepts/{cid}")
        for uid in range(1, 11):
            self.get(f"/knowledge-library/units/{uid}/source")
        self.search("fasse")
        require(snapshot(self.work / "demo.db") == before and self.counts() == counters,
                "post-edge browsing changed data or provider counters")
        self.passed("post-edge browsing remains read-only", counters)
        self.additional_safety()
        require(self.demo_hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(DEMO.parent.iterdir()) if p.is_file()}, "author demo changed")
        require(self.phase_a_hashes == {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                                        for name in self.phase_a_hashes}, "Phase A helpers changed")

    def cleanup(self):
        errors = []
        for sock in self.sockets:
            sock.close()
        if self.work.exists() and (self.work / ".flh034-demo").exists():
            try:
                # Independently validate records before author cleanup.
                for name, executable in (("server.pid", str(self.work / "server")),
                                         ("stub.pid", str(DEMO.parent / "stub_extractor.py"))):
                    path = self.work / name
                    if path.exists():
                        pid = int(path.read_text())
                        proc = Path(f"/proc/{pid}/cmdline")
                        require(not proc.exists() or not proc.read_bytes()
                                or executable in proc.read_bytes().decode().split("\0"), "unsafe cleanup PID")
                self.command(["sh", str(DEMO), "cleanup", str(self.work)])
            except BaseException as exc:
                errors.append(str(exc))
        for _ in range(100):
            if all(not listener_alive(pid, port) for pid, port in self.owned_processes):
                break
            time.sleep(0.02)
        remaining = [(pid, port) for pid, port in self.owned_processes if listener_alive(pid, port)]
        if remaining:
            errors.append("owned listeners remain: " + repr(remaining))
        self.observations["owned_listeners_stopped"] = not remaining
        self.observations["demo_directory_removed"] = not self.work.exists()
        if not errors:
            shutil.rmtree(self.parent)
        return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    destination = args.report.resolve()
    require(not destination.exists() and ROOT not in destination.parents and destination.parent.is_dir(), "unsafe report destination")
    os.umask(0o077)
    run = Acceptance()
    error = None
    try:
        run.run()
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        print("FAIL " + error, flush=True)
    finally:
        counters = run.counts()
        cleanup = run.cleanup()
        report = {"phase": "B", "status": "FAIL" if error or cleanup or run.defects else "PASS",
                  "error": error, "cases": run.cases, "defects": run.defects,
                  "commands": run.commands, "observations": run.observations,
                  "acceptance_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                          for p in sorted(HERE.glob("*.py"))},
                  "demo_sha256": run.demo_hashes, "phase_a_sha256": run.phase_a_hashes,
                  "stub_observer": OBSERVER, "provider_counters": counters,
                  "cleanup_errors": cleanup, "temporary_directory_removed": not run.parent.exists(),
                  "browser": {"state": "NOT_RUN", "reason": "No browser executable or tool available"}}
        with destination.open("x") as output:
            json.dump(report, output, indent=2, ensure_ascii=False)
        print(f"RESULT={report['status']} CASES={len(run.cases)} DEFECTS={len(run.defects)} CLEANUP={cleanup}", flush=True)
    return 1 if error or cleanup or run.defects else 0


if __name__ == "__main__":
    raise SystemExit(main())
