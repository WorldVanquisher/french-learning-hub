#!/usr/bin/env python3
"""One bounded CPU experiment for the Speaking Lab (EXPERIMENT, not a promotion).

Question: on a small slice of the frozen MLS-fr test split, how do two pinned
public models (whisper-base vs whisper-small) differ? And does seeded white
noise at 20 dB SNR change that difference?

  python3 -I -B scripts/lab_experiment.py prepare --data DATA_V1 --work WORK [--per-speaker 5]
  python3 -I -B scripts/lab_experiment.py run     --work WORK --sources SOURCES --image IMG [--lock CPU.LOCK]
  python3 -I -B scripts/lab_experiment.py report  --work WORK
  python3 -I -B scripts/lab_experiment.py rerun   --work WORK --sources SOURCES --image IMG [--model M --condition C] [--lock CPU.LOCK]
  python3 -I -B scripts/lab_experiment.py reproduce --work WORK --sources SOURCES --image IMG [--condition C] [--lock CPU.LOCK]

* **prepare** (stdlib, host) selects the first ``--per-speaker`` clips of each
  test speaker in id order. It copies the clean clips unchanged and writes
  their noise copies (``variants.white_noise``, 20 dB, seed 7). The manifest
  records the hashes.
* **run** makes four ``evaluate`` calls (two models, two conditions) in the
  lock-built image. Each call runs with no network, ``--cpus 2``, 2 GB, batch
  1 and 2 threads, and holds the CPU lock if one is given. This tree's
  ``flh_speaking`` is mounted read-only, so the code that runs is the code
  under review. The lock file inside the image must equal this tree's lock.
* **report** (stdlib) compares base and small per condition with
  ``lab.batch``; speakers are the groups, intervals come from a group
  bootstrap, and candidate manifests are checked. It also compares clean vs
  noise per model, and writes ``experiment-result.json``: the experiment
  identity, the inputs, the outputs with their sizes and SHA-256, and the
  tradeoffs.
* **rerun** re-evaluates the smallest slice (the speaker with the least audio)
  with one model and one condition, then compares every served text and status
  with the first run (``rerun.json``).
* **reproduce** repeats the smallest comparison (base vs small on that slice,
  one condition) with the code packaged in the image: nothing from this tree
  is mounted. It first checks that every file of the image's
  ``/opt/program/flh_speaking`` equals this tree's, and refuses (exit 1) on any
  difference. It then compares texts and statuses with the first run, compares
  the paired comparison with the one computed from the first run's outputs for
  the same ids, and renders the candidate review inside the image
  (``reproduce.json``, ``reproduce/``).

Everything is written under WORK, outside Git, and no machine path is
written. The serving default is unchanged by any of this.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

from flh_speaking import candidates, lab, pins, variants  # noqa: E402

SCHEMA = "flh_speaking_lab_experiment_v1"
MODELS = ("whisper-base", "whisper-small")
CONDITIONS = {"clean": None, "noise20": ("noise", 20.0, 7)}
LIMITS = {"cpus": "2", "memory": "2g", "threads": 2, "batch": 1, "timeout_s": 1800}
CODE = ("flh_speaking/evaluate.py", "flh_speaking/model.py", "flh_speaking/audio.py", "flh_speaking/textnorm.py", "flh_speaking/lab.py")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: str) -> str:
    with open(p, "rb") as fh:
        return sha(fh.read())


def dump(obj, path: str) -> None:
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(path + ".tmp", path)


def select(rows: list[dict], per_speaker: int) -> list[dict]:
    by: dict = {}
    for r in sorted((r for r in rows if r["split"] == "test"), key=lambda r: r["id"]):
        by.setdefault(r["speaker"], []).append(r)
    return [r for spk in sorted(by) for r in by[spk][:per_speaker]]


def prepare(a) -> int:
    man_path = os.path.join(a.data, "manifest.jsonl")
    with open(man_path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    chosen = select(rows, a.per_speaker)
    out_rows = []
    for cond, plan in CONDITIONS.items():
        os.makedirs(os.path.join(a.work, "data", "audio", cond), exist_ok=True)
        for r in chosen:
            with open(os.path.join(a.data, r["file"]), "rb") as fh:
                b = fh.read()
            if sha(b[44:]) != r["pcm_sha256"]:
                raise SystemExit(f"source clip changed: {r['id']}")
            if plan:
                rate, x = variants.read_pcm16(b)
                b = variants.write_pcm16(rate, variants.white_noise(x, plan[1], plan[2]))
            rel = f"audio/{cond}/{r['id']}.wav"
            with open(os.path.join(a.work, "data", rel), "wb") as fh:
                fh.write(b)
            out_rows.append({**{k: r[k] for k in ("id", "speaker", "gender", "group", "text", "seconds", "corpus")},
                             "split": cond, "file": rel, "pcm_sha256": sha(b[44:]),
                             "variant": None if not plan else {"kind": plan[0], "snr_db": plan[1], "seed": plan[2]}})
    with open(os.path.join(a.work, "data", "manifest.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in out_rows))
    ids = [r["id"] for r in chosen]
    dump({"schema": SCHEMA + "/prepare", "source_manifest_sha256": sha_file(man_path), "source_split": "test",
          "selection": f"first {a.per_speaker} clips per test speaker in id order", "per_speaker": a.per_speaker,
          "ids": ids, "ids_sha256": sha("\n".join(ids).encode()), "speakers": sorted({r["speaker"] for r in chosen}),
          "audio_seconds": round(sum(r["seconds"] for r in chosen), 1), "conditions": {k: v and list(v) for k, v in CONDITIONS.items()},
          "prepared_manifest_sha256": sha_file(os.path.join(a.work, "data", "manifest.jsonl")),
          "licence": "MLS French (facebook/multilingual_librispeech @2e83e618), CC-BY-4.0; audio kept outside Git"},
         os.path.join(a.work, "prepare.json"))
    print(json.dumps({"clips": len(chosen), "speakers": len({r['speaker'] for r in chosen}), "conditions": list(CONDITIONS)}))
    return 0


def check_image(image: str) -> tuple[str, str]:
    img_lock = subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "python3", image, "-c",
                               "import hashlib;print(hashlib.sha256(open('/opt/program/requirements-cpu.lock','rb').read()).hexdigest())"],
                              capture_output=True, text=True, check=True).stdout.strip()
    tree_lock = sha_file(candidates.LOCK)
    if img_lock != tree_lock:
        raise SystemExit(f"the image was built from another lock ({img_lock[:12]} vs this tree's {tree_lock[:12]})")
    image_id = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", image], capture_output=True, text=True, check=True).stdout.strip()
    return image_id, img_lock


def docker_base(out_dir: str) -> list[str]:
    return ["docker", "run", "--rm", "--oom-score-adj", "1000", "--network", "none", "--cpus", LIMITS["cpus"],
            "--memory", LIMITS["memory"], "--memory-swap", LIMITS["memory"], "--user", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/tmp", "-v", f"{out_dir}:/out"]


def evaluate_in_image(a, m: str, cond: str, out_dir: str, name: str, ids_file: str | None = None, mount_code: bool = True) -> dict:
    """One bounded ``evaluate`` call; ``out_dir`` and ``ids_file`` sit under WORK. ``mount_code=False`` runs
    the code packaged in the image (nothing from this tree is mounted)."""
    rev = pins.MODELS[m]["revision"]
    code = ["-v", f"{os.path.join(PKG, 'flh_speaking')}:/opt/program/flh_speaking:ro"] if mount_code else []
    cmd = docker_base(out_dir) + ["-v", f"{a.sources}:/sources:ro", "-v", f"{os.path.join(a.work, 'data')}:/data:ro"] + code + [
           a.image, "evaluate", "--model", f"/sources/openai/{m}/{rev}", "--data", "/data", "--split", cond,
           "--out", f"/out/{name}", "--batch", str(LIMITS["batch"]), "--threads", str(LIMITS["threads"]), "--label", f"{m} {cond}"]
    if ids_file:
        cmd += ["--ids", "/out/" + os.path.basename(ids_file)]
    t0 = time.monotonic()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=LIMITS["timeout_s"])
    return {"model": m, "condition": cond, "exit": p.returncode, "wall_s": round(time.monotonic() - t0, 1),
            "stderr_tail": p.stderr[-400:] if p.returncode else ""}


def run(a) -> int:
    lock = open(a.lock, "a+") if a.lock else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        image_id, img_lock = check_image(a.image)
        os.makedirs(os.path.join(a.work, "evals"), exist_ok=True)
        runs = []
        for m in MODELS:
            for cond in CONDITIONS:
                runs.append(evaluate_in_image(a, m, cond, os.path.join(a.work, "evals"), f"{m}-{cond}.json"))
                print(json.dumps(runs[-1]), flush=True)
                if runs[-1]["exit"]:
                    break
        dump({"schema": SCHEMA + "/run", "image_id": image_id, "image_lock_sha256": img_lock, "limits": LIMITS, "runs": runs,
              "code_sha256": {c: sha_file(os.path.join(PKG, c)) for c in CODE}, "network": "none"},
             os.path.join(a.work, "run.json"))
        return 0 if all(r["exit"] == 0 for r in runs) and len(runs) == len(MODELS) * len(CONDITIONS) else 1
    finally:
        if lock:
            lock.close()


def smallest_speaker(work: str) -> tuple[str, list[str]]:
    with open(os.path.join(work, "data", "manifest.jsonl"), encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if json.loads(line)["split"] == "clean"]
    secs: dict = {}
    for r in rows:
        secs[r["speaker"]] = secs.get(r["speaker"], 0.0) + r["seconds"]
    spk = min(sorted(secs), key=lambda k: secs[k])
    return spk, sorted(r["id"] for r in rows if r["speaker"] == spk)


def compare_rerun(first: dict, second: dict) -> dict:
    a = {i["id"]: i["served"] for i in first["items"]}
    rows = [{"id": i["id"], "same_text": a[i["id"]]["text"] == i["served"]["text"], "same_status": a[i["id"]]["status"] == i["served"]["status"]}
            for i in second["items"]]
    return {"samples": len(rows), "identical": sum(1 for r in rows if r["same_text"] and r["same_status"]), "per_sample": rows}


def rerun(a) -> int:
    lock = open(a.lock, "a+") if a.lock else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        image_id, _ = check_image(a.image)
        spk, ids = smallest_speaker(a.work)
        d = os.path.join(a.work, "rerun")
        os.makedirs(d, exist_ok=True)
        ids_file = os.path.join(d, "ids.json")
        with open(ids_file, "w", encoding="utf-8") as fh:
            json.dump(ids, fh)
        name = f"{a.model}-{a.condition}-{spk}.json"
        r = evaluate_in_image(a, a.model, a.condition, d, name, ids_file)
        if r["exit"]:
            print(json.dumps(r))
            return 1
        with open(os.path.join(a.work, "evals", f"{a.model}-{a.condition}.json"), encoding="utf-8") as fh:
            first = json.load(fh)
        with open(os.path.join(d, name), encoding="utf-8") as fh:
            second = json.load(fh)
        cmp = compare_rerun(first, second)
        doc = {"schema": SCHEMA + "/rerun", "speaker": spk, "model": a.model, "condition": a.condition, "image_id": image_id,
               "selection": "the speaker with the least audio in the slice (ties: lowest id)", "wall_s": r["wall_s"], **cmp,
               "output": {"file": f"rerun/{name}", "bytes": os.path.getsize(os.path.join(d, name)), "sha256": sha_file(os.path.join(d, name))}}
        dump(doc, os.path.join(a.work, "rerun.json"))
        print(json.dumps({k: doc[k] for k in ("speaker", "model", "condition", "samples", "identical", "wall_s")}))
        return 0 if cmp["identical"] == cmp["samples"] else 1
    finally:
        if lock:
            lock.close()


PACKAGED_HASHES = ("import hashlib, json, os\n"
                   "root = '/opt/program/flh_speaking'\n"
                   "out = {}\n"
                   "for dp, dns, fns in os.walk(root):\n"
                   "    dns[:] = sorted(d for d in dns if d != '__pycache__')\n"
                   "    for f in fns:\n"
                   "        if not f.endswith('.pyc'):\n"
                   "            p = os.path.join(dp, f)\n"
                   "            out[os.path.relpath(p, root)] = hashlib.sha256(open(p, 'rb').read()).hexdigest()\n"
                   "print(json.dumps(out, sort_keys=True))\n")


def code_hashes(root: str) -> dict:
    """{relative path: sha256} of a package directory, ignoring bytecode caches (the image's view of the code)."""
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d != "__pycache__")
        for f in fns:
            if not f.endswith(".pyc"):
                p = os.path.join(dp, f)
                out[os.path.relpath(p, root)] = sha_file(p)
    return out


def code_differences(image: dict, tree: dict) -> list[dict]:
    """Every path whose content differs, or that exists on one side only."""
    return [{"path": k, "image": image.get(k, "absent")[:12], "tree": tree.get(k, "absent")[:12]}
            for k in sorted(set(image) | set(tree)) if image.get(k) != tree.get(k)]


def packaged_code(image: str) -> dict:
    p = subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "python3", image, "-c", PACKAGED_HASHES],
                       capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def restrict(doc: dict, ids: list[str]) -> dict:
    """The same evaluation limited to ``ids`` (summary kept: only texts and statuses are compared)."""
    keep = set(ids)
    return {**doc, "items": [i for i in doc["items"] if i["id"] in keep]}


def without_resources(obj):
    """A comparison with the measured resources removed: they differ between any two runs."""
    if isinstance(obj, dict):
        return {k: without_resources(v) for k, v in obj.items() if k != "resources"}
    if isinstance(obj, list):
        return [without_resources(v) for v in obj]
    return obj


def pair_from_docs(da: dict, db: dict, ma: str, mb: str, la: str, lb: str) -> dict:
    out = {}
    for doc, m, label in ((da, ma, la), (db, mb, lb)):
        if doc["model_dir_name"] != pins.MODELS[m]["revision"]:
            raise SystemExit(f"the {label} evaluation was not produced by the pinned {m} revision")
        refs, rows = candidates.from_eval(doc, label, group="speaker")
        rows[0]["header"]["candidate_id"] = candidates.manifest(m)["candidate_id"]
        out[label] = (refs, rows)
    (ra, rows_a), (rb, rows_b) = out[la], out[lb]
    if {r["id"]: r["reference"] for r in ra} != {r["id"]: r["reference"] for r in rb}:
        raise SystemExit("the two evaluations do not share one reference set")
    res = lambda rows: {r["id"]: {"text": r["text"], "status": r["status"]} for r in rows[1:]}  # noqa: E731
    return lab.batch({r["id"]: r for r in ra}, rows_a[0]["header"], res(rows_a), rows_b[0]["header"], res(rows_b),
                     manifests={la: candidates.manifest(ma), lb: candidates.manifest(mb)})


def reproduce(a) -> int:
    lock = open(a.lock, "a+") if a.lock else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        image_id, img_lock = check_image(a.image)
        d = os.path.join(a.work, "reproduce")
        os.makedirs(d, exist_ok=True)
        tree = code_hashes(os.path.join(PKG, "flh_speaking"))
        diff = code_differences(packaged_code(a.image), tree)
        doc = {"schema": SCHEMA + "/reproduce", "image_id": image_id, "image_lock_sha256": img_lock, "condition": a.condition,
               "code": {"mounted": False, "files": len(tree), "tree_sha256": sha(json.dumps(tree, sort_keys=True).encode()),
                        "differences": diff}}
        if diff:
            doc["status"] = "refused: the image's packaged flh_speaking differs from this tree; rebuild the image"
            dump(doc, os.path.join(a.work, "reproduce.json"))
            print(json.dumps({"status": doc["status"], "differences": diff}))
            return 1
        spk, ids = smallest_speaker(a.work)
        ids_file = os.path.join(d, "ids.json")
        with open(ids_file, "w", encoding="utf-8") as fh:
            json.dump(ids, fh)
        names, runs, same = {}, [], {}
        for m in MODELS:
            names[m] = f"{m}-{a.condition}-{spk}.json"
            r = evaluate_in_image(a, m, a.condition, d, names[m], ids_file, mount_code=False)
            runs.append(r)
            print(json.dumps(r), flush=True)
            if r["exit"]:
                doc |= {"status": f"failed: evaluate {m} exited {r['exit']}", "runs": runs}
                dump(doc, os.path.join(a.work, "reproduce.json"))
                return 1
        first, second = {}, {}
        for m in MODELS:
            with open(os.path.join(a.work, "evals", f"{m}-{a.condition}.json"), encoding="utf-8") as fh:
                first[m] = restrict(json.load(fh), ids)
            with open(os.path.join(d, names[m]), encoding="utf-8") as fh:
                second[m] = json.load(fh)
            cmp = compare_rerun(first[m], second[m])
            same[m] = {k: cmp[k] for k in ("samples", "identical")}
        ma, mb = MODELS
        cmp_first = pair_from_docs(first[ma], first[mb], ma, mb, "base", "small")
        cmp_packaged = pair_from_docs(second[ma], second[mb], ma, mb, "base", "small")
        dump(cmp_packaged, os.path.join(d, "comparison.json"))
        with open(os.path.join(d, "comparison.txt"), "w", encoding="utf-8") as fh:
            fh.write(lab.render_batch_text(cmp_packaged))
        review_cmd = docker_base(d) + [a.image, "lab", "candidate-review", "--baseline", "/out/" + names[ma],
                                       "--candidate", "/out/" + names[mb], "--json", "/out/review-packaged.json",
                                       "--text", "/out/review-packaged.txt"]
        rv = subprocess.run(review_cmd, capture_output=True, text=True, timeout=600)
        from flh_speaking import candidate_review as cr  # this tree's code, for the byte comparison only
        host = cr.from_files(os.path.join(d, names[ma]), os.path.join(d, names[mb]))
        with open(os.path.join(d, "review-tree.json"), "w", encoding="utf-8") as fh:
            fh.write(lab.to_json(host))
        packaged_bytes = b""
        if rv.returncode in cr.EXIT.values():
            with open(os.path.join(d, "review-packaged.json"), "rb") as fh:
                packaged_bytes = fh.read()
        u = cmp_packaged["uncertainty"]
        doc |= {
            "status": "reproduced" if all(v["identical"] == v["samples"] for v in same.values())
            and without_resources(cmp_first) == without_resources(cmp_packaged) else "differs",
            "speaker": spk, "ids": ids, "selection": "the speaker with the least audio in the slice (ties: lowest id)",
            "runs": [{k: r[k] for k in ("model", "condition", "exit", "wall_s")} for r in runs],
            "texts_and_statuses_vs_first_run": same,
            "comparison": {"same_as_first_run_outputs": without_resources(cmp_first) == without_resources(cmp_packaged),
                           "compared": "the paired comparison without measured resources",
                           "samples": cmp_packaged["paired"]["samples"], "groups": cmp_packaged["paired"]["groups"],
                           "wer": {k: v["wer"] for k, v in cmp_packaged["models"].items()},
                           "wer_difference_b_minus_a": u.get("wer_difference_b_minus_a"), "interval_95": u.get("interval_95"),
                           "ranking": cmp_packaged["ranking"]["status"], "standing": cmp_packaged["ranking"].get("standing")},
            "review": {"ran_in": "image (packaged code)", "exit": rv.returncode,
                       "outcome": host["outcome"], "expected_exit": host["exit_code"],
                       "same_bytes_as_tree_code": packaged_bytes == lab.to_json(host).encode("utf-8"),
                       "stderr_tail": rv.stderr[-400:]},
            "outputs": {f"reproduce/{f}": {"bytes": os.path.getsize(os.path.join(d, f)), "sha256": sha_file(os.path.join(d, f))}
                        for f in sorted(os.listdir(d))}}
        dump(doc, os.path.join(a.work, "reproduce.json"))
        print(json.dumps({k: doc[k] for k in ("status", "speaker", "texts_and_statuses_vs_first_run")} | {
            "comparison": {k: doc["comparison"][k] for k in ("same_as_first_run_outputs", "samples", "groups", "standing")},
            "review": {k: doc["review"][k] for k in ("exit", "outcome", "same_bytes_as_tree_code")}}))
        ok = doc["status"] == "reproduced" and doc["review"]["same_bytes_as_tree_code"] and rv.returncode == host["exit_code"]
        return 0 if ok else 1
    finally:
        if lock:
            lock.close()


def load_pair(work: str, ma: str, ca: str, mb: str, cb: str, la: str, lb: str):
    docs = {}
    for m, c, label in ((ma, ca, la), (mb, cb, lb)):
        with open(os.path.join(work, "evals", f"{m}-{c}.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc["model_dir_name"] != pins.MODELS[m]["revision"]:
            raise SystemExit(f"{m}-{c}.json was not produced by the pinned {m} revision")
        refs, rows = candidates.from_eval(doc, label, group="speaker")
        rows[0]["header"]["candidate_id"] = candidates.manifest(m)["candidate_id"]
        docs[label] = (refs, rows, doc)
    (ra, rows_a, da), (rb, rows_b, db) = docs[la], docs[lb]
    refs = {r["id"]: r for r in ra}
    if {r["id"]: r["reference"] for r in ra} != {r["id"]: r["reference"] for r in rb}:
        raise SystemExit("the two evaluations do not share one reference set")
    res = lambda rows: {r["id"]: {"text": r["text"], "status": r["status"]} for r in rows[1:]}  # noqa: E731
    manifests = {la: candidates.manifest(ma), lb: candidates.manifest(mb)}
    return lab.batch(refs, rows_a[0]["header"], res(rows_a), rows_b[0]["header"], res(rows_b), manifests=manifests), da, db


def report(a) -> int:
    rep_dir = os.path.join(a.work, "report")
    os.makedirs(rep_dir, exist_ok=True)
    with open(os.path.join(a.work, "prepare.json"), encoding="utf-8") as fh:
        prep = json.load(fh)
    with open(os.path.join(a.work, "run.json"), encoding="utf-8") as fh:
        run_doc = json.load(fh)
    comparisons, timing = {}, {}
    plan = [("base-vs-small-clean", "whisper-base", "clean", "whisper-small", "clean", "base", "small"),
            ("base-vs-small-noise20", "whisper-base", "noise20", "whisper-small", "noise20", "base", "small"),
            ("base-clean-vs-noise20", "whisper-base", "clean", "whisper-base", "noise20", "clean", "noise20"),
            ("small-clean-vs-noise20", "whisper-small", "clean", "whisper-small", "noise20", "clean", "noise20")]
    for name, ma, ca, mb, cb, la, lb in plan:
        res, da, db = load_pair(a.work, ma, ca, mb, cb, la, lb)
        dump(res, os.path.join(rep_dir, name + ".json"))
        with open(os.path.join(rep_dir, name + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(lab.render_batch_text(res))
        for d, m, c in ((da, ma, ca), (db, mb, cb)):
            t = d["summary"]["timing"]
            timing[f"{m}/{c}"] = {k: t[k] for k in ("real_time_factor", "peak_rss_mb", "compute_s", "audio_s", "model_load_s")}
        u, p = res["uncertainty"], res["paired"]
        comparisons[name] = {
            "a": la, "b": lb, "samples": p["samples"], "groups": p["groups"], "sample_order_sha256": res["sample_order_sha256"],
            "wer": {la: res["models"][la]["wer"], lb: res["models"][lb]["wer"]},
            "wer_difference_b_minus_a": u["wer_difference_b_minus_a"], "interval_95": u["interval_95"], "excludes_zero": u.get("excludes_zero"),
            "reliability": u.get("reliability"), "b_fewer_errors_samples": p[f"{lb}_fewer_errors"], "b_more_errors_samples": p[f"{lb}_more_errors"],
            "b_fewer_errors_groups": p[f"{lb}_fewer_errors_groups"], "b_more_errors_groups": p[f"{lb}_more_errors_groups"],
            "abstentions": res["abstentions"]["samples"], "ranking": res["ranking"]["status"],
            "standing": "observation" if p["groups"] < lab.MIN_RANK_GROUPS or res["ranking"]["status"] != "ranked" else "ranked",
            "ranking_note": res["ranking"].get("note") or res["ranking"].get("reason"), "invalidated": res["validity"]["invalidated"]}
    cands = {m: candidates.manifest(m)["candidate_id"] for m in MODELS}
    defining = {"prepare": {k: prep[k] for k in ("source_manifest_sha256", "ids_sha256", "conditions", "prepared_manifest_sha256")},
                "candidates": cands, "image_id": run_doc["image_id"], "image_lock_sha256": run_doc["image_lock_sha256"],
                "code_sha256": run_doc["code_sha256"], "limits": run_doc["limits"], "bootstrap": lab.BOOTSTRAP,
                "normalization": lab.textnorm.policy_fingerprint()}
    outputs = {}
    for root, sub in ((a.work, "evals"), (a.work, "report")):
        for f in sorted(os.listdir(os.path.join(root, sub))):
            p = os.path.join(root, sub, f)
            outputs[f"{sub}/{f}"] = {"bytes": os.path.getsize(p), "sha256": sha_file(p)}
    audio_bytes = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(os.path.join(a.work, "data", "audio")) for f in fs)
    doc = {"schema": SCHEMA, "experiment_id": "lab-exp-" + sha(json.dumps(defining, sort_keys=True).encode())[:16], "defining": defining,
           "status": "experimented", "serving_default": "unchanged (RUNBOOK.md decides what is served)",
           "slice": {k: prep[k] for k in ("selection", "speakers", "audio_seconds", "licence")} | {"clips": len(prep["ids"])},
           "comparisons": comparisons, "tradeoffs": timing, "runs": [{k: r[k] for k in ("model", "condition", "exit", "wall_s")} for r in run_doc["runs"]],
           "sizes": {"outputs": outputs, "outputs_bytes": sum(o["bytes"] for o in outputs.values()), "prepared_audio_bytes": audio_bytes,
                     "where": "WORK only; nothing here belongs in Git"},
           "limits_of_evidence": [
               f"{len(prep['speakers'])} speakers: below the {lab.MIN_RANK_GROUPS}-group minimum, so every comparison is an observation, not a ranking",
               "read audiobook speech by native speakers (MLS): says nothing about learners, accents or phone microphones",
               "white noise is synthetic; real rooms have other noise",
               "word error rate under flh_fr_asr_norm_v1 only; homophones are counted as errors"]}
    dump(doc, os.path.join(a.work, "experiment-result.json"))
    print(json.dumps({"experiment_id": doc["experiment_id"], **{k: {kk: v[kk] for kk in ("wer", "wer_difference_b_minus_a", "interval_95", "standing")}
                                                                   for k, v in comparisons.items()}}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--data", required=True); p.add_argument("--work", required=True)
    p.add_argument("--per-speaker", type=int, default=5)
    r = sub.add_parser("run"); r.add_argument("--work", required=True); r.add_argument("--sources", required=True)
    r.add_argument("--image", required=True); r.add_argument("--lock")
    q = sub.add_parser("report"); q.add_argument("--work", required=True)
    rr = sub.add_parser("rerun"); rr.add_argument("--work", required=True); rr.add_argument("--sources", required=True)
    rr.add_argument("--image", required=True); rr.add_argument("--lock")
    rr.add_argument("--model", choices=MODELS, default="whisper-base"); rr.add_argument("--condition", choices=tuple(CONDITIONS), default="noise20")
    rp = sub.add_parser("reproduce"); rp.add_argument("--work", required=True); rp.add_argument("--sources", required=True)
    rp.add_argument("--image", required=True); rp.add_argument("--lock")
    rp.add_argument("--condition", choices=tuple(CONDITIONS), default="clean")
    a = ap.parse_args(argv)
    return {"prepare": prepare, "run": run, "report": report, "rerun": rerun, "reproduce": reproduce}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
