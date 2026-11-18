#!/usr/bin/env python3
"""Build a synthetic, NAS-shaped backup for the staging restore (item 11).

  make_fixture_backup.py BUNDLE_DIR BASE_BACKUP CONTRACT_JSON SPEAKING_DIR FAKE_PROVIDER_PY OUT_DIR WORK_DIR

Starts the bundle's image in an isolated Compose project (loopback, data under
WORK_DIR) with the Speaking providers pointed at a local OpenAI-compatible
fake on the Compose network (no network, placeholder key, no cost), restores
BASE_BACKUP (an earlier synthetic backup: the contract entry, an old mistake
and workbook script revision 1), then adds through the normal HTTP API:
  - workbook revision 2 by the explicit, previewed script update (and a replay);
  - a new entry by POST /captures, then an identical replay (receipt);
  - retry marks on the old mistake (mark, unmark, mark: append-only rows);
  - Speaking: an exercise, three takes (metadata only), transcriptions with
    a provider 500 (stored failure) and an explicit retry, a lost response
    (outcome unknown, plain retry refused, confirmed retry), confirmed
    transcripts v1/v2 and one feedback.
Then `flh-daily.sh backup` (the NAS's supported path) and copies the backup to
OUT_DIR/nas-fixture-<run>/ with OUT_DIR/nas-fixture-<run>.json describing it:
table counts, ledger, logical dump SHA-256, sizes, and the IDs later checks
read back. Only synthetic data; the daily instance is never touched.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import standin_lib as L  # noqa: E402

BUNDLE, BASE, CONTRACT, SPK, FAKE_PY, OUT, WORK = (os.path.realpath(x) for x in sys.argv[1:8])
rec = L.Recorder(WORK)
manifest, build = L.bundle_identity(BUNDLE)
contract = json.load(open(CONTRACT))
fx = json.load(open(os.path.join(SPK, "speaking-fixture.json")))
audio = open(os.path.join(SPK, fx["take"]["file"]), "rb").read()
KEY = "fixture-placeholder-key-not-a-secret"
DATA = os.path.join(WORK, "data", "app")
os.makedirs(DATA)
os.chmod(os.path.dirname(DATA), 0o700)
os.chmod(DATA, 0o700)
FAKE = os.path.join(WORK, "fake")
os.makedirs(FAKE)
shutil.copyfile(FAKE_PY, os.path.join(FAKE, "fake_openai.py"))
shutil.copyfile(os.path.join(SPK, "speaking-fixture.json"), os.path.join(FAKE, "fixture.json"))
MODE = os.path.join(FAKE, "mode")
open(MODE, "w").write("ok")
open(os.path.join(FAKE, "calls.log"), "w").close()
for f in ("mode", "calls.log"):
    os.chmod(os.path.join(FAKE, f), 0o666)
PORT = L.free_port()
PROJECT = f"flh-stg-{L.RUN}-fixture"
ENV_FILE = os.path.join(WORK, "settings.env")
settings = {"FLH_DATA_DIR": DATA, "FLH_HOST_PORT": str(PORT), "FLH_UID": str(os.getuid()), "FLH_GID": str(os.getgid()),
            "AI_PROVIDER": "rule-based", "EXTRACTOR_PROVIDER": "disabled", "SUGGESTION_PROVIDER": "disabled",
            "LISTENING_PROVIDER": "disabled", "READING_PROVIDER": "disabled", "WRITING_PROVIDER": "disabled",
            "SPEAKING_TRANSCRIPTION_PROVIDER": "openai", "SPEAKING_TRANSCRIPTION_MODEL": "fixture-transcriber",
            "SPEAKING_PROVIDER": "openai", "OPENAI_MODEL": "fixture-feedback", "OPENAI_API_KEY": KEY,
            "OPENAI_BASE_URL": "http://fake-provider:19195", "OPENAI_TIMEOUT": "5", "HTTP_WRITE_TIMEOUT": "75",
            "LISTENING_PLAYLIST_SOURCE": "disabled", "LISTENING_AUTO_PREPARE": "disabled", "LISTENING_NOTIFY": "disabled"}
with open(ENV_FILE, "w") as fh:
    fh.writelines(f"{k}='{v}'\n" for k, v in settings.items())
os.chmod(ENV_FILE, 0o600)
OVERRIDE = os.path.join(WORK, "override.yaml")
with open(OVERRIDE, "w") as fh:
    fh.write(f"""services:
  app:
    image: {manifest['image']['tag']}
    build: !reset null
    pull_policy: never
  fake-provider:
    image: python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e
    pull_policy: never
    user: "{os.getuid()}:{os.getgid()}"
    restart: "no"
    command: ["python3", "-I", "-B", "/fake/fake_openai.py", "19195", "/fake/calls.log", "/fake/fixture.json", "/fake/mode", "0.0.0.0"]
    volumes:
      - {{type: bind, source: {FAKE}, target: /fake}}
""")
WRAPPER = os.path.join(BUNDLE, "repo", "scripts", "daily", "flh-daily.sh")
COMPOSE = os.path.join(BUNDLE, "repo", "compose.yaml")


def wrap(*args, log=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    env.update(FLH_DAILY_ENV=ENV_FILE, FLH_COMPOSE_PROJECT=PROJECT, FLH_COMPOSE_OVERRIDE=OVERRIDE)
    r = subprocess.run(["bash", WRAPPER, *args], env=env, capture_output=True, text=True)
    rec.save(f"fixture-{log or args[0]}.log", f"$ flh-daily.sh {' '.join(args)}\nexit {r.returncode}\n{r.stdout}{r.stderr}")
    return r.returncode, r.stdout + r.stderr


def call(method, path, body=None, headers=None):
    st, raw = L.call(PORT, method, path, body, headers)
    return st, L.js(raw)


def set_mode(m):
    open(MODE, "w").write(m)


def audio_for(n):
    if n == 1:
        return audio
    b = bytearray(audio)
    b[44 + 2 * n] ^= 0x01
    return bytes(b)


def add_take(ex_id, n):
    a = audio_for(n)
    body = {"audio_source": "file", "audio_mime": fx["take"]["type"], "audio_bytes": len(a),
            "audio_sha256": hashlib.sha256(a).hexdigest(), "duration_ms": int(fx["take"]["duration_seconds"] * 1000)}
    st, j = call("POST", f"/speaking/exercises/{ex_id}/takes", body)
    return st, (j.get("take") or {}).get("id") or j.get("take_id")


def transcribe(take_id, n, confirm=False):
    body = {"audio_base64": base64.b64encode(audio_for(n)).decode(), "audio_mime": fx["take"]["type"]}
    if confirm:
        body["confirm_unknown_retry"] = True
    return call("POST", f"/speaking/takes/{take_id}/transcriptions", body, {"Idempotency-Key": str(uuid.uuid4())})


def versions(view, take_id):
    out = []

    def walk(o):
        if isinstance(o, dict):
            if "origin" in o and "version" in o and o.get("take_id") == take_id:
                out.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(view)
    return sorted(out, key=lambda d: d["version"])


fp_before = L.daily_fingerprint()
facts = {}
try:
    have = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", manifest["image"]["tag"]], capture_output=True, text=True).stdout.strip()
    if have != build["image_id"]:
        subprocess.run(["docker", "load", "-q", "-i", os.path.join(BUNDLE, "image.tar")], check=True, capture_output=True)
    rc, _ = wrap("up")
    rec.record("F0", rc == 0 and L.wait_ready(PORT), "fixture instance up (bundle image, Speaking -> local fake)", f"exit {rc}")
    base_copy = os.path.join(WORK, "base-backup")
    shutil.copytree(BASE, base_copy)
    for f in os.listdir(base_copy):
        os.chmod(os.path.join(base_copy, f), 0o600)
    rc, out = wrap("restore", base_copy)
    rec.record("F1", rc == 0 and L.wait_ready(PORT), "restore the earlier synthetic backup (contract entry, old mistake, script rev 1)",
               f"exit {rc}")
    # --- workbook revision 2
    wb = contract["workbook"]
    st, scripts = call("GET", "/listening/scripts")
    row = next((x for x in scripts.get("scripts", []) if x.get("id") == wb["script_id"]), {})
    mat = row.get("imported_material_id")
    st_p, prev = call("GET", f"/listening/materials/{mat}/script-update")
    body = {"from_revision": prev.get("current_revision"), "pack_fingerprint": prev.get("pack_fingerprint")}
    st_u, upd = call("POST", f"/listening/materials/{mat}/script-update", body)
    st_ur, _ = call("POST", f"/listening/materials/{mat}/script-update", body)
    rec.record("F2", st_u == 201 and upd.get("revision") == 2 and st_ur == 200,
               "workbook script revision 1 -> 2 (previewed update 201, replay 200)", f"material {mat}: {st_u}, replay {st_ur}")
    facts["workbook"] = {"script_id": wb["script_id"], "material_id": mat, "revisions": 2}
    # --- a new entry and its replay
    cap = dict(contract["entry"]["capture"], capture_id="fixture-staging-entry-001",
               original_input="FIXTURE-PRIVATE-STAGING : « il faut que je parte » ou « il faut que je pars » ?")
    st1, j1 = call("POST", "/captures", cap)
    st2, _ = call("POST", "/captures", cap)
    rec.record("F3", st1 == 201 and st2 == 200, "new entry 201, identical replay 200 (receipt)", f"{st1}, {st2}")
    facts["entries"] = {"contract": contract["entry"]["capture"]["capture_id"], "old_mistake": contract["old_mistake"]["capture"]["capture_id"],
                        "fixture": cap["capture_id"], "fixture_entry_id": j1.get("entry_id")}
    # --- retry marks on the old mistake (append-only)
    st_i, items = call("GET", "/mistake-notebook/items")
    mistake_entry = call("GET", f"/captures/{contract['old_mistake']['capture']['capture_id']}")[1].get("entry_id")
    item = next((i for i in items.get("items", []) if i.get("entry_id") == mistake_entry or i.get("id") == mistake_entry), None)
    iid = (item or {}).get("id") or (item or {}).get("entry_id")
    marks = [call("PUT", f"/mistake-notebook/items/{iid}/retry", {"marked": m})[0] for m in (True, False, True)]
    rec.record("F4", st_i == 200 and iid and all(s in (200, 201) for s in marks), "retry marks on the old mistake: mark, unmark, mark",
               f"item {iid}, statuses {marks}")
    facts["retry_item"] = iid
    # --- Speaking: exercise, takes (metadata), transcriptions with failure + retries, transcripts, feedback
    st_e, ex = call("POST", f"/speaking/prompts/{fx['prompt_id']}")
    ex_id = (ex.get("exercise") or ex).get("id")
    st_t1, t1 = add_take(ex_id, 1)
    st_x1, x1 = transcribe(t1, 1)
    tr = x1.get("transcription") or {}
    st_v1, _ = call("POST", f"/speaking/takes/{t1}/transcripts", {"text": tr.get("text"), "transcription_id": tr.get("id")})
    st_v2, view = call("POST", f"/speaking/takes/{t1}/transcripts", {"text": fx["corrected_transcript_v2"], "transcription_id": None})
    vs = versions(view, t1)
    st_fb, _ = call("POST", f"/speaking/transcripts/{vs[-1]['id'] if vs else 0}/feedback", {}, {"Idempotency-Key": str(uuid.uuid4())})
    st_t2, t2 = add_take(ex_id, 2)
    set_mode("status500")
    st_f, _ = transcribe(t2, 2)
    set_mode("ok")
    st_ok, _ = transcribe(t2, 2)
    st_t3, t3 = add_take(ex_id, 3)
    set_mode("drop")
    st_d, _ = transcribe(t3, 3)
    set_mode("ok")
    st_plain, jp = transcribe(t3, 3)
    st_conf, _ = transcribe(t3, 3, confirm=True)
    rec.record("F5", st_e in (200, 201) and st_t1 == 201 and st_x1 == 201 and st_v1 == 201 and st_v2 == 201 and st_fb == 201,
               "Speaking: exercise, take 1 (metadata), transcription, confirmed v1 + corrected v2, feedback",
               f"exercise {ex_id} {st_e}; take {st_t1}; transcription {st_x1}; transcripts {st_v1}/{st_v2}; feedback {st_fb}")
    rec.record("F6", st_t2 == 201 and st_f == 502 and st_ok == 201 and st_t3 == 201 and st_d == 502 and st_plain == 409
               and jp.get("code") == "outcome_unknown" and st_conf == 201,
               "retries: provider 500 stored then explicit retry 201; lost response unknown, plain retry 409, confirmed retry 201",
               f"500 path {st_f}->{st_ok}; lost {st_d}, plain {st_plain} {jp.get('code')}, confirmed {st_conf}")
    facts["speaking"] = {"exercise_id": ex_id, "takes": [t1, t2, t3]}
    st_pr, practice = call("GET", "/speaking/practice")
    rec.save("fixture-speaking-practice.json", practice)
    # --- the NAS-shaped backup
    rc, out = wrap("backup")
    bpath = next((l.split("backup written to ", 1)[1].split(" (copy", 1)[0] for l in out.splitlines() if "backup written to" in l), None)
    rec.record("F7", rc == 0 and bpath and os.path.isfile(os.path.join(bpath, "SHA256SUMS")),
               "flh-daily.sh backup (the NAS's supported path) writes a verified copy", f"exit {rc}, {os.path.basename(str(bpath))}")
    name = f"nas-fixture-{L.RUN}"
    dest = os.path.join(OUT, name)
    shutil.copytree(bpath, dest, copy_function=shutil.copy2)
    db = os.path.join(dest, "app.db")
    counts = L.table_counts(db)
    dbbytes = open(db, "rb").read()
    audio_absent = all(audio_for(n)[44:4140] not in dbbytes for n in (1, 2, 3))
    size = sum(os.path.getsize(os.path.join(dest, f)) for f in os.listdir(dest))
    desc = {"name": name, "made_by": "flh-daily.sh backup (synthetic data only)", "bundle": manifest["name"],
            "tree_id": manifest["revision"]["tree_id"], "ledger": L.ledger(db), "dump_sha256": L.dump_hash(db),
            "app_db_bytes": os.path.getsize(db), "backup_bytes": size, "files": sorted(os.listdir(dest)),
            "modes": {f: oct(os.stat(os.path.join(dest, f)).st_mode & 0o777) for f in sorted(os.listdir(dest))},
            "tables": counts, "facts": facts, "audio_absent": audio_absent}
    with open(os.path.join(OUT, f"{name}.json"), "w") as fh:
        json.dump(desc, fh, indent=1, sort_keys=True)
    want = {"learning_entries": 3, "learning_captures": 3, "learning_capture_sources": 1, "listening_transcripts": 2,
            "listening_exercises": 2, "mistake_retry_marks": 3, "speaking_exercises": 1, "speaking_takes": 3,
            "speaking_transcription_requests": 5, "speaking_transcriptions": 5, "speaking_transcripts": 2,
            "speaking_feedback": 1}
    got = {k: counts.get(k) for k in want}
    rec.record("F8", audio_absent and got == want and desc["ledger"] == 21,
               "fixture holds entries, 2 script revisions, retry marks, Speaking metadata with failed/unknown/retried requests; no audio bytes",
               f"{got}; transcription requests {counts.get('speaking_transcription_requests')}; ledger {desc['ledger']}; "
               f"app.db {desc['app_db_bytes']} B, backup {size} B; audio absent {audio_absent}")
    rec.note("OUT", dest)
except Exception as e:  # an unexpected error is a failure, never a silent pass
    rec.record("ERR", False, "no unexpected error", repr(e)[:300])
finally:
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    subprocess.run(["docker", "compose", "-p", PROJECT, "-f", COMPOSE, "-f", OVERRIDE, "--env-file", ENV_FILE, "down",
                    "--remove-orphans"], env=env, capture_output=True)
    fp_after = L.daily_fingerprint()
    rec.record("C2", fp_after == fp_before, "daily container and image unchanged", "unchanged" if fp_after == fp_before else "CHANGED")
    rec.note("RESULT", f"{'PASSED' if rec.failed == 0 else 'FAILED'} ({rec.failed} failed)")
sys.exit(1 if rec.failed else 0)
