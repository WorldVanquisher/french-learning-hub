#!/usr/bin/env python3
"""Compare two staging bundles without extracting application data (standard library only).

  bundle_compare.py A.tar|A_DIR B.tar|B_DIR [--json]
  bundle_compare.py BUNDLE.tar|DIR --summary [--json]   # one bundle's identity, no local path

Reads MANIFEST.json, BUILD.json and SHA256SUMS of each bundle, and from image.tar (streamed in
memory, never written to disk) the server executable `app/server`, the frontend entry
`app/web/index.html` and the script it loads (`/assets/index-*.js`). Classifies every
difference:
  content     what runs: source tree and content digest, executable SHA-256, web files digest,
              frontend entry and entry-script SHA-256, migration ledger, every pinned file
  label       names derived from the revision: bundle name, image tag, revision labels
  build-only  this build's record: image ID, image.tar SHA-256, built_at, Docker version,
              no-cache flag, BUILD/MANIFEST digests and SHA256SUMS entries for those files
Exit 0 when the content is identical (build-only and label differences allowed), 1 when the
content differs, 2 on unreadable input.
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Bundle:
    def __init__(self, src):
        self.src = src
        if os.path.isdir(src):
            self.root, self.tf = src, None
        else:
            self.tf = tarfile.open(src)
            stem = os.path.basename(src)[:-4] if src.endswith(".tar") else None
            self.prefix = stem or self.tf.getmembers()[0].name.split("/")[0]

    def open(self, name):
        if self.tf is None:
            return open(os.path.join(self.root, name), "rb")
        return self.tf.extractfile(f"{self.prefix}/{name}")

    def json(self, name):
        with self.open(name) as fh:
            return json.load(fh)

    def sums(self):
        with self.open("SHA256SUMS") as fh:
            return dict(reversed(l.split(None, 1)) for l in fh.read().decode().splitlines() if l.strip())

    def image_files(self, wanted):
        """SHA-256 (and bytes for index.html) of the wanted paths, streamed from the image layers."""
        found = {}
        with self.open("image.tar") as raw:
            img = tarfile.open(fileobj=io.BytesIO(raw.read()))
        with img:
            man = json.load(img.extractfile("manifest.json"))[0]
            for layer in man["Layers"]:       # later layers win, as in the image
                with tarfile.open(fileobj=img.extractfile(layer), mode="r|*") as lt:
                    for m in lt:
                        n = m.name.lstrip("./")
                        if m.isfile() and (n in wanted or (wanted.get("@entry") and n == wanted["@entry"])):
                            data = lt.extractfile(m).read()
                            found[n] = {"sha256": sha(data), "bytes": len(data), "data": data if n.endswith(".html") else None}
        return found

    def facts(self):
        man, build, sums = self.json("MANIFEST.json"), self.json("BUILD.json"), self.sums()
        files = self.image_files({"app/server": 1, "app/web/index.html": 1})
        entry = None
        html = (files.get("app/web/index.html") or {}).get("data") or b""
        m = re.search(rb'src="/assets/(index-[^"]+\.js)"', html)
        if m:
            entry = "app/web/assets/" + m.group(1).decode()
            files.update(self.image_files({"@entry": entry}))
        content = {
            "tree_id": man["revision"]["tree_id"], "content_sha256": man["revision"].get("content_sha256"),
            "server_sha256 (manifest)": man["server_sha256"], "server_sha256 (image)": (files.get("app/server") or {}).get("sha256"),
            "web_files_sha256": man["web_files_sha256"],
            "frontend entry index.html": (files.get("app/web/index.html") or {}).get("sha256"),
            "frontend entry script": f"{entry.rsplit('/', 1)[-1]} {(files.get(entry) or {}).get('sha256')}" if entry else None,
            "migrations": f"{man['migrations']['count']} (last {man['migrations']['last']})",
        }
        for p, h in sorted(man.get("files", {}).items()):
            content[f"file {p}"] = h
        label = {"bundle name": man["name"], "image tag": man["image"]["tag"],
                 "label revision": man["image"]["labels"].get("org.opencontainers.image.revision"),
                 "label tree": man["image"]["labels"].get("org.flh.staging.tree-id"), "commit": man["revision"].get("commit")}
        buildonly = {"image_id": build.get("image_id"), "image_tar_sha256": build.get("image_tar_sha256"),
                     "built_at": build.get("built_at"), "docker_server": build.get("docker_server"), "no_cache": build.get("no_cache"),
                     "BUILD manifest_sha256": build.get("manifest_sha256"),
                     "SHA256SUMS BUILD.json": sums.get("BUILD.json"), "SHA256SUMS image.tar": sums.get("image.tar"),
                     "SHA256SUMS MANIFEST.json": sums.get("MANIFEST.json")}
        if not os.path.isdir(self.src) and os.path.isfile(self.src):
            h = hashlib.sha256()
            with open(self.src, "rb") as fh:
                for blk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(blk)
            buildonly["transfer tar sha256"] = h.hexdigest()
        if self.tf is not None:
            self.tf.close()
        return {"content": content, "label": label, "build-only": buildonly}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--summary", action="store_true", help="one bundle: its identity and pinned files, no local path")
    a = ap.parse_args()
    if a.summary:
        try:
            f = Bundle(a.a).facts()
        except (OSError, KeyError, ValueError, tarfile.TarError) as e:
            print(f"bundle_compare: unreadable input: {e}", file=sys.stderr)
            return 2
        summary = {"bundle": f["label"]["bundle name"], "commit": f["label"]["commit"], "tree_id": f["content"]["tree_id"],
                   "content_sha256": f["content"]["content_sha256"], "image_tag": f["label"]["image tag"],
                   "image_id": f["build-only"]["image_id"], "server_sha256": f["content"]["server_sha256 (manifest)"],
                   "server_in_image_matches": f["content"]["server_sha256 (manifest)"] == f["content"]["server_sha256 (image)"],
                   "web_files_sha256": f["content"]["web_files_sha256"], "frontend_entry": f["content"]["frontend entry script"],
                   "migrations": f["content"]["migrations"], "built_at": f["build-only"]["built_at"],
                   "transfer_sha256": f["build-only"].get("transfer tar sha256"),
                   "files": {k[5:]: v for k, v in sorted(f["content"].items()) if k.startswith("file ")}}
        if a.json:
            print(json.dumps(summary, indent=1, sort_keys=True))
        else:
            for k, v in summary.items():
                if k != "files":
                    print(f"{k:<24} {v}")
            print(f"pinned files ({len(summary['files'])}):")
            for p, h in summary["files"].items():
                print(f"  {h[:16]}  {p}")
        return 0
    if not a.b:
        ap.error("give two bundles, or one with --summary")
    try:
        fa, fb = Bundle(a.a).facts(), Bundle(a.b).facts()
    except (OSError, KeyError, ValueError, tarfile.TarError) as e:
        print(f"bundle_compare: unreadable input: {e}", file=sys.stderr)
        return 2
    diffs = {}
    for cat in ("content", "label", "build-only"):
        keys = sorted(set(fa[cat]) | set(fb[cat]))
        diffs[cat] = [{"field": k, "a": fa[cat].get(k), "b": fb[cat].get(k)} for k in keys if fa[cat].get(k) != fb[cat].get(k)]
    same = not diffs["content"]
    if a.json:
        print(json.dumps({"a": a.a, "b": a.b, "same_content": same, "differences": diffs, "a_facts": fa, "b_facts": fb}, indent=1))
    else:
        print(f"A {os.path.basename(a.a)}\nB {os.path.basename(a.b)}")
        print(f"content: {'IDENTICAL' if same else 'DIFFERENT'} ({len(diffs['content'])} field(s)); "
              f"label: {len(diffs['label'])} difference(s); build-only: {len(diffs['build-only'])} difference(s)")
        for cat in ("content", "label", "build-only"):
            for d in diffs[cat]:
                av, bv = (str(d["a"])[:40], str(d["b"])[:40])
                print(f"  {cat:<10} {d['field']:<46} {av:<40} -> {bv}")
        for k in ("migrations", "server_sha256 (image)", "frontend entry script"):
            print(f"  same      {k:<46} {fa['content'][k]}" if fa["content"][k] == fb["content"][k] else "", end="" if fa["content"][k] != fb["content"][k] else "\n")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
