"""FLH-089 read-path measurements against a seeded fixture backend (GET only).

Usage: python3 -B measure.py http://127.0.0.1:PORT

Reports, per endpoint: item count, response bytes and the median of five
request times. It also walks the learning-record cursor from the first page
to the end for each filter, and checks direct cursor jumps. Loopback only.
Timings describe this machine and fixture only.

FLH-090 additions: learning-record text search (?q=) walks and bounds, and the
paged review queue (limit/after/from_unit_id) compared with the legacy list.
"""
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1].rstrip("/")
if urllib.parse.urlparse(BASE).hostname not in ("127.0.0.1", "localhost", "::1"):
    sys.exit("refusing non-loopback backend")


def get(path):
    t = time.perf_counter()
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        body = r.read()
    return json.loads(body), len(body), (time.perf_counter() - t) * 1000


def timed(path, key):
    runs = [get(path) for _ in range(5)]
    data, size, _ = runs[-1]
    items = data[key] if key else data
    return {"path": path, "items": len(items) if isinstance(items, list) else None, "bytes": size,
            "median_ms": round(statistics.median(r[2] for r in runs), 1)}


out = {"endpoints": [], "walks": [], "jumps": []}
for path, key in [
    ("/learning-records?limit=20", "records"),
    ("/learning-records?limit=200", "records"),
    ("/learning-records?limit=1&before_entry_id=2", "records"),
    ("/learning-records?state=corrected&limit=20", "records"),
    ("/learning-records?category=translation&limit=20", "records"),
    ("/learning-records/summary", None),
    ("/reviewable-units", "reviewable_units"),
    ("/concepts", "concepts"),
    ("/effective-annotations", "effective_annotations"),
    ("/knowledge-library/concepts?q=synthetic", "results"),
    ("/knowledge-library/concepts?q=concept%200499", "results"),
    ("/learning-records?limit=20&q=" + urllib.parse.quote("Synthetic question 5:"), "records"),
    ("/learning-records?limit=20&q=" + urllib.parse.quote("est-ce que"), "records"),
    ("/learning-records?limit=20&q=journal", "records"),
    ("/reviewable-units?limit=50", "reviewable_units"),
    ("/reviewable-units?limit=200", "reviewable_units"),
]:
    try:
        out["endpoints"].append(timed(path, key))
    except Exception as e:  # report, do not hide
        out["endpoints"].append({"path": path, "error": repr(e)})

for label, query in [("all", ""), ("unanalyzed", "&state=unanalyzed"), ("rejected", "&state=rejected"),
                     ("category=grammar", "&category=grammar")]:
    pages, total, cursor, ms, ids = 0, 0, None, 0.0, []
    while True:
        path = f"/learning-records?limit=20{query}" + (f"&before_entry_id={cursor}" if cursor else "")
        data, _, t = get(path)
        pages += 1
        ms += t
        total += len(data["records"])
        ids += [r["entry_id"] for r in data["records"]]
        cursor = data["next_before_entry_id"]
        if cursor is None:
            break
    out["walks"].append({"filter": label, "pages_of_20": pages, "records": total, "first_id": ids[0] if ids else None,
                         "last_id": ids[-1] if ids else None, "strictly_descending": ids == sorted(ids, reverse=True),
                         "unique": len(ids) == len(set(ids)), "total_ms": round(ms, 1)})

for target in (1, 500, 1000):
    data, _, t = get(f"/learning-records?limit=20&before_entry_id={target + 1}")
    out["jumps"].append({"jump_to": target, "first_id": data["records"][0]["entry_id"] if data["records"] else None,
                         "ms": round(t, 1)})
# FLH-090: text search walks, literal wildcards, case, bounds.
def walk_q(q, extra="", start=None):
    # start is the initial exclusive cursor (a jump); later pages use the returned one.
    pages, ids, cursor, ms = 0, [], start, 0.0
    while True:
        path = f"/learning-records?limit=20&q={urllib.parse.quote(q)}{extra}" + (f"&before_entry_id={cursor}" if cursor else "")
        if pages > 1000:
            raise RuntimeError(f"text-search walk for {q!r} did not terminate")
        data, _, t = get(path)
        pages, ms = pages + 1, ms + t
        ids += [r["entry_id"] for r in data["records"]]
        cursor = data["next_before_entry_id"]
        if cursor is None:
            return {"q": q, "extra": extra, "start": start, "pages_of_20": pages, "records": len(ids), "first_id": ids[0] if ids else None,
                    "last_id": ids[-1] if ids else None, "strictly_descending": ids == sorted(ids, reverse=True),
                    "unique": len(ids) == len(set(ids)), "total_ms": round(ms, 1)}

out["text_search"] = [
    walk_q("est-ce que"),                      # every record's input
    walk_q("Synthetic context"),               # context only (n % 4 != 0)
    walk_q("SYNTHETIC CONTEXT"),               # case-insensitive
    walk_q("journal"),                         # the 20 long inputs
    walk_q("Synthetic question 5:"),           # one old record, found in one request
    walk_q("%"),                               # literal: no record contains %
    walk_q("_"),                               # literal: no record contains _
    walk_q("est-ce que", "&state=corrected&category=translation"),
    walk_q("est-ce que", start=501),
    walk_q("Synthetic correction"),            # feedback text only: must not match
]
try:
    get("/learning-records?limit=20&q=" + "a" * 201)
    out["text_search_201_chars"] = "accepted (unexpected)"
except urllib.error.HTTPError as e:
    out["text_search_201_chars"] = e.code
out["text_search_200_chars_status"] = 200 if get("/learning-records?limit=20&q=" + urllib.parse.quote("é" * 200)) else None

# FLH-090: the paged queue walk equals the legacy list, each unit once.
legacy, legacy_bytes, legacy_ms = get("/reviewable-units")
legacy_ids = [u["unit_id"] for u in legacy["reviewable_units"]]
for limit in (50, 200):
    ids, pages, cursor, total_bytes, total_ms, max_bytes = [], 0, None, 0, 0.0, 0
    while True:
        path = f"/reviewable-units?limit={limit}" + (f"&after={urllib.parse.quote(cursor)}" if cursor else "")
        data, size, t = get(path)
        pages += 1
        total_bytes += size
        max_bytes = max(max_bytes, size)
        total_ms += t
        ids += [u["unit_id"] for u in data["reviewable_units"]]
        cursor = data["next_cursor"]
        if cursor is None:
            break
    out.setdefault("queue_walks", []).append({
        "limit": limit, "pages": pages, "units": len(ids), "legacy_units": len(legacy_ids),
        "equals_legacy_order": ids == legacy_ids, "unique": len(ids) == len(set(ids)),
        "max_page_bytes": max_bytes, "total_bytes": total_bytes,
        "legacy_bytes": legacy_bytes, "total_ms": round(total_ms, 1), "legacy_ms": round(legacy_ms, 1)})
mid = legacy_ids[len(legacy_ids) // 2]
data, size, t = get(f"/reviewable-units?limit=50&from_unit_id={mid}")
out["queue_from_unit"] = {"from_unit_id": mid, "first": data["reviewable_units"][0]["unit_id"],
                          "equals_legacy_slice": [u["unit_id"] for u in data["reviewable_units"]] == legacy_ids[legacy_ids.index(mid):legacy_ids.index(mid) + 50],
                          "bytes": size, "ms": round(t, 1)}
scoped_ok = True
entries = sorted({u["entry_id"] for u in get("/reviewable-units?limit=200")[0]["reviewable_units"]})[:25]
for e in entries:
    paged = [u["unit_id"] for u in get(f"/reviewable-units?entry_id={e}&limit=200")[0]["reviewable_units"]]
    leg = [u["unit_id"] for u in get(f"/reviewable-units?entry_id={e}")[0]["reviewable_units"]]
    scoped_ok &= paged == leg
out["queue_entry_scoped_equal_legacy"] = {"entries_checked": len(entries), "all_equal": scoped_ok}
print(json.dumps(out, indent=1))
