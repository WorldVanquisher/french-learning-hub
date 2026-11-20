#!/usr/bin/env python3
"""check_examples.py BASE SPEC OUT_DIR: check the public demo's example data
against a running package (demo-candidate lane).

SPEC is web/src/demo/discovery.json: the guided examples, the comparisons and
the suggested keyword searches the page offers. Each entry names only how to
find its evidence through the read API (a keyword query, wording from exactly
one unit), so a package built from another catalog, or an artifact rebuilt
after the catalog changed, can leave an entry stale: the page then shows its
"not in this demo build" fallback. This check finds that before release, the
same way the page resolves each entry (web/src/demo/examples.ts,
comparisons.ts, queries.ts):

  example     its query's Concepts hold exactly one supporting unit whose
              canonical wording contains the seed; that unit's source reads,
              and its question is the one the start page quotes verbatim
  comparison  each side: a CURRENT member unit with the seed wording, among
              the Concepts its query matches; its source reads
  query       the search behaves as the page says (expect: min/max results,
              a tier, a matched field, the token count, a normalized token, a
              prefix-only match); a follow-up search finds something and its
              example exists

Read-only: GETs on /knowledge-library/... only. Writes OUT_DIR/examples.json
(every entry, with the IDs it resolved to and, for a failure, why) and
OUT_DIR/examples-matrix.md (the support matrix for this package's artifact).
Exit 0 when every entry resolves, 1 otherwise (each failure is printed as one
readable line), 2 on usage or an unreachable server.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    if len(sys.argv) != 4:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    base, spec_path, out = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
    spec = json.load(open(spec_path, encoding="utf-8"))
    if spec.get("schema") != "flh_public_demo_discovery_v1":
        print(f"refused: {spec_path} is not flh_public_demo_discovery_v1", file=sys.stderr)
        return 2

    def get(path):
        try:
            with urllib.request.urlopen(base + path, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    try:
        status, info = get("/knowledge-library/demo")
    except (urllib.error.URLError, OSError) as e:
        print(f"refused: no demo server at {base} ({e})", file=sys.stderr)
        return 2
    if status != 200 or not info:
        print(f"refused: {base}/knowledge-library/demo answered {status}", file=sys.stderr)
        return 2
    artifact = info["artifact"]

    def search(q):
        status, d = get("/knowledge-library/concepts?" + urllib.parse.urlencode({"q": q, "limit": 50}))
        if status != 200:
            raise Stale(f"the search for “{q}” answered HTTP {status}")
        return d

    concepts = {}

    def concept(cid):
        if cid not in concepts:
            status, d = get(f"/knowledge-library/concepts/{cid}")
            if status != 200:
                raise Stale(f"Concept #{cid} answered HTTP {status}")
            concepts[cid] = d
        return concepts[cid]

    def source(uid):
        status, d = get(f"/knowledge-library/units/{uid}/source")
        if status != 200:
            raise Stale(f"the source of unit #{uid} answered HTTP {status}")
        return d

    rows = []

    def record(kind, key, fn):
        try:
            got = fn()
            rows.append({"kind": kind, "key": key, "ok": True, **got})
        except Stale as e:
            rows.append({"kind": kind, "key": key, "ok": False, "why": str(e)})

    def example(e):
        d = search(e["query"])
        details = [concept(r["concept"]["id"]) for r in d["results"]]
        seeds = {u["unit_id"]: (u, c["concept"]) for c in details for u in c["supporting_units"] if e["seed"] in u["canonical"].lower()}
        if len(seeds) != 1:
            ids = [r["concept"]["id"] for r in d["results"]]
            raise Stale(f"“{e['query']}” matches Concepts {ids or 'none'}, whose supporting units include {len(seeds)} with “{e['seed']}” in their wording (the page needs exactly 1)")
        (u, c), = seeds.values()
        s = source(u["unit_id"])
        if s["entry"]["original_input"] != e["question"]:
            raise Stale(f"unit #{u['unit_id']}'s question (record #{s['entry']['id']}) differs from the one the start page quotes")
        return {"unit": u["unit_id"], "concept": c["id"], "record": s["entry"]["id"]}

    def side(sd):
        d = search(sd["query"])
        for r in d["results"]:
            c = concept(r["concept"]["id"])
            for u in c["supporting_units"] + c["non_supporting_members"]:
                if sd["seed"] in u["canonical"].lower():
                    s = source(u["unit_id"])
                    return {"unit": u["unit_id"], "concept": c["concept"]["id"], "record": s["entry"]["id"],
                            "supporting": any(x["unit_id"] == u["unit_id"] for x in c["supporting_units"]),
                            "example": u.get("example") or ""}
        ids = [r["concept"]["id"] for r in d["results"]]
        raise Stale(f"no unit with “{sd['seed']}” in its wording among the Concepts “{sd['query']}” matches ({ids or 'none'})")

    def comparison(cmp):
        sides = [side(sd) for sd in cmp["sides"]]
        # R2 practice: each choice's form occurs exactly once in its side's
        # example, or the page cannot blank it (the item would not be offered).
        practice = cmp.get("practice")
        if practice:
            for i, ch in enumerate(practice["choices"]):
                n = sides[i]["example"].count(ch["form"])
                if n != 1:
                    raise Stale(f"practice form “{ch['form']}” occurs {n} times in the example of unit #{sides[i]['unit']} (the page needs exactly 1)")
        for sd in sides:
            sd.pop("example")
        return {"sides": sides, **({"practice_items": len(practice["items"])} if practice else {})}

    examples_by_key = {e["key"] for e in spec["examples"]}

    def query(x):
        d = search(x["q"])
        n, res, ex = d["total_matches"], d["results"], x.get("expect", {})
        problems = []
        if "min" in ex and n < ex["min"]:
            problems.append(f"{n} results, the page says at least {ex['min']}")
        if "max" in ex and n > ex["max"]:
            problems.append(f"{n} results, the page says at most {ex['max']}")
        if "tier" in ex and not any(r["match_tier"] == ex["tier"] for r in res):
            problems.append(f"no result of tier {ex['tier']}")
        if "field" in ex and sum(ex["field"] in r["matched_fields"] for r in res) < ex.get("min", 1):
            problems.append(f"fewer than {ex.get('min', 1)} results matched in {ex['field']}")
        if "tokens" in ex and len(d["tokens"]) != ex["tokens"]:
            problems.append(f"{len(d['tokens'])} search words, the page says {ex['tokens']}")
        if "token" in ex and ex["token"] not in d["tokens"]:
            problems.append(f"the search words are {d['tokens']}, without {ex['token']}")
        if ex.get("prefix"):
            # Only longer words begin with the token: no Concept field holds it whole.
            whole = [r["concept"]["id"] for r in res if any(t in words(r["concept"]) for t in d["tokens"])]
            if whole:
                problems.append(f"Concepts {whole} hold the search word whole, not only as a beginning")
        f = x.get("follow_up")
        follow = None
        if f:
            fd = search(f["q"])
            follow = {"q": f["q"], "results": fd["total_matches"]}
            if fd["total_matches"] == 0:
                problems.append(f"its follow-up search “{f['q']}” finds nothing")
            if f.get("example") and f["example"] not in examples_by_key:
                problems.append(f"its follow-up example {f['example']} is not one of the guided examples")
        if problems:
            raise Stale("; ".join(problems))
        return {"results": n, "tokens": d["tokens"], "concepts": [r["concept"]["id"] for r in res][:5], **({"follow_up": follow} if follow else {})}

    for e in spec["examples"]:
        record("example", e["key"], lambda e=e: example(e))
    for c in spec["comparisons"]:
        record("comparison", c["key"], lambda c=c: comparison(c))
    for x in spec["queries"]:
        record("query", x["q"], lambda x=x: query(x))

    os.makedirs(out, exist_ok=True)
    summary = {"schema": "demo_candidate_examples_check_v1", "artifact": {k: artifact[k] for k in ("version", "manifest_sha256", "domain_fingerprint_sha256", "real_model")},
               "spec": os.path.basename(spec_path), "entries": rows, "result": "PASS" if all(r["ok"] for r in rows) else "FAIL"}
    json.dump(summary, open(os.path.join(out, "examples.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(out, "examples-matrix.md"), "w", encoding="utf-8") as m:
        m.write(f"# Public example support: artifact {artifact['version']}\n\n")
        m.write(f"Manifest `{artifact['manifest_sha256']}`, domain fingerprint `{artifact['domain_fingerprint_sha256']}`, real model: {artifact['real_model']}.\n\n")
        m.write("| Feature | Entry | Supported | Resolves to |\n|---|---|---|---|\n")
        for r in rows:
            if not r["ok"]:
                got = r["why"]
            elif r["kind"] == "example":
                got = f"unit #{r['unit']} → Concept #{r['concept']}, record #{r['record']}"
            elif r["kind"] == "comparison":
                got = " · ".join(f"unit #{s['unit']} → Concept #{s['concept']}, record #{s['record']}" for s in r["sides"])
            else:
                got = f"{r['results']} results {r['concepts']}" + (f"; follow-up “{r['follow_up']['q']}”: {r['follow_up']['results']}" if r.get("follow_up") else "")
            m.write(f"| {r['kind']} | `{r['key']}` | {'yes' if r['ok'] else '**no**'} | {got} |\n")
    for r in rows:
        print(("PASS" if r["ok"] else "FAIL"), r["kind"], r["key"] + ("" if r["ok"] else f": {r['why']}"))
    print(f"{sum(r['ok'] for r in rows)}/{len(rows)} example entries resolve against artifact {artifact['version']}")
    return 0 if summary["result"] == "PASS" else 1


class Stale(Exception):
    pass


def words(c):
    """The accent-free lower-case words of a Concept's identity fields (display check only)."""
    import unicodedata
    text = " ".join([c["target"], c["pedagogical_intent"], c.get("scope") or "", json.dumps(c.get("identity_features") or {}, ensure_ascii=False)])
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    out, cur = set(), []
    for ch in text + " ":
        if ch.isalnum():
            cur.append(ch)
        else:
            if len(cur) > 1:
                out.add("".join(cur))
            cur = []
    return out


if __name__ == "__main__":
    sys.exit(main())
