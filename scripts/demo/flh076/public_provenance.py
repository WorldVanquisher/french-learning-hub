#!/usr/bin/env python3
"""Public provenance for the FLH public-demo package: only explicitly public fields leave the machine.

  public_provenance.py project ARTIFACT_DIR    # in place, on package.sh's staged copy of the artifact
  public_provenance.py check PACKAGE_DIR        # RELEASE.json and artifact/provenance.json of a package

The preparation records the embedding service's address (`base_url`) in the artifact's
provenance.json, and package.sh used to copy it into RELEASE.json. That address is private.

project rewrites ARTIFACT_DIR/provenance.json with the allowlisted fields below (unknown fields are
dropped, a post's error text is emptied) and updates manifest.json's files["provenance.json"] to the
new SHA-256. It refuses first if any file differs from manifest.json, so only an intact artifact is
projected. The artifact identity stays: artifact_version (derived from the fixtures, the vectors and
the domain fingerprint), the database, vectors and fixtures, the vector identity and the domain
fingerprint. Only the manifest's provenance entry changes, so the manifest digest differs from the
private artifact's.

check requires every key of RELEASE.json and artifact/provenance.json, at every depth, to be in its
allowlist; a post's error to be empty; no string value to look like an address, URL, local path or
e-mail; and RELEASE.json's artifact block to match the package's manifest (version, manifest digest,
model, dimensions, fingerprint). It prints file, key path and rule, never a value.
Exit 0 public; 1 a check failed; 2 usage or unreadable input. Standard library, Python 3.9.
"""
import hashlib
import json
import os
import re
import sys

T = True                                    # any scalar value
EMPTY = "empty"                             # the value must be "" (or is emptied by project)
PROBE = {"utc": T, "ready_status": T, "manifest_deployment_id": T, "manifest_sha256": T, "outcome": T}
PROVENANCE = {
    "schema": T, "generator": T, "deployment_id": T, "dimensions": T, "plan_sha256": T, "fixtures_sha256": T,
    "probes": [PROBE],
    "posts": [{"seq": T, "positions": T, "outcome": T, "reserved_utc": T, "finished_utc": T, "error": EMPTY}],
    "accounting": {"max_positions": T, "max_posts": T, "max_probes": T, "used_positions": T, "used_posts": T, "used_probes": T},
    "positions": [{"key": T, "kind": T, "representation": T, "role": T, "text_sha256": T, "vector_sha256": T,
                   "post_seq": T, "received_utc": T}],
    "note": T,
}
RELEASE = {
    "schema": T, "label": T, "source_revision": T, "source_revision_note": T, "built_utc": T, "go": T, "targets": [T],
    "release_status": T,
    "web": {"build_id": T, "api_base": T, "entry": T, "index_sha256": T},
    "artifact": {"version": T, "manifest_sha256": T, "vector_source": T, "real_model": T, "model_id": T, "dimensions": T,
                 "release_status": T, "domain_fingerprint": T, "fingerprint_version": T},
    "model_provenance": {"deployment_id": T, "plan_sha256": T, "positions": T, "posts": T, "probes": T, "readiness": [PROBE]},
    "runtime_requirements": {"os": T, "needs": [T], "does_not_need": [T]},
    "not_included": [T],
}
# String values that must never appear in a public file (classes only are reported).
PRIVATE = [
    ("url", re.compile(r"\b[a-z][a-z0-9+.-]*://", re.I)),
    ("private-address", re.compile(r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}"
                                   r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})\b")),
    ("private-host", re.compile(r"\.(?:ts\.net|internal|local|lan|home)\b", re.I)),
    ("local-path", re.compile(r"(?:^|[\s\"'])/(?:home|Users|root|srv|mnt|var|tmp)/")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def project_value(value, schema, path, dropped):
    """The allowlisted part of value; dropped key paths are recorded (names only)."""
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            return value
        out = {}
        for k, v in value.items():
            if k in schema:
                out[k] = project_value(v, schema[k], f"{path}.{k}", dropped)
            else:
                dropped.append(f"{path}.{k}")
        return out
    if isinstance(schema, list):
        return [project_value(v, schema[0], f"{path}[]", dropped) for v in value] if isinstance(value, list) else value
    if schema == EMPTY and value not in ("", None):
        dropped.append(f"{path} (text emptied)")
        return ""
    return value


def check_value(value, schema, path, problems):
    if value is None and isinstance(schema, dict):
        return                                   # e.g. model_provenance: null for a mechanical artifact
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            problems.append(f"{path}: expected an object")
            return
        for k, v in value.items():
            if k not in schema:
                problems.append(f"{path}.{k}: not a public field")
            else:
                check_value(v, schema[k], f"{path}.{k}", problems)
        return
    if isinstance(schema, list):
        if not isinstance(value, list):
            problems.append(f"{path}: expected a list")
            return
        for v in value:
            check_value(v, schema[0], f"{path}[]", problems)
        return
    if isinstance(value, (dict, list)):
        problems.append(f"{path}: expected a scalar")
        return
    if schema == EMPTY and value not in ("", None):
        problems.append(f"{path}: must be empty in a public file")
    if isinstance(value, str):
        for name, rx in PRIVATE:
            if rx.search(value):
                problems.append(f"{path}: value looks like a {name}")


def project(artifact):
    man_path, prov_path = os.path.join(artifact, "manifest.json"), os.path.join(artifact, "provenance.json")
    with open(man_path) as fh:
        manifest = json.load(fh)
    files = manifest.get("files") or {}
    for name, want in sorted(files.items()):
        if sha256_file(os.path.join(artifact, name)) != want:
            raise SystemExit(f"refused: {name} differs from manifest.json; the artifact is not intact")
    if not os.path.isfile(prov_path):
        print("no provenance.json (mechanical artifact): nothing to project")
        return 0
    if "provenance.json" not in files:
        raise SystemExit("refused: provenance.json is present but manifest.json does not list it")
    with open(prov_path) as fh:
        prov = json.load(fh)
    dropped = []
    public = project_value(prov, PROVENANCE, "provenance", dropped)
    with open(prov_path, "w") as fh:
        json.dump(public, fh, indent=2)
        fh.write("\n")
    files["provenance.json"] = sha256_file(prov_path)
    with open(man_path, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"public provenance: {len(dropped)} field(s) removed ({', '.join(dropped) or 'none'}); "
          f"artifact_version {manifest.get('artifact_version')} unchanged; manifest provenance entry updated")
    return 0


def check(package):
    problems = []
    targets = (("RELEASE.json", RELEASE, "release"), (os.path.join("artifact", "provenance.json"), PROVENANCE, "provenance"))
    loaded = {}
    for rel, schema, root in targets:
        p = os.path.join(package, rel)
        if not os.path.isfile(p):
            if rel == "RELEASE.json":
                problems.append(f"{rel}: missing")
            continue
        try:
            with open(p) as fh:
                loaded[rel] = json.load(fh)
        except ValueError:
            problems.append(f"{rel}: not JSON")
            continue
        found = []
        check_value(loaded[rel], schema, root, found)
        problems += [f"{rel}: {x}" for x in found]
    rel = loaded.get("RELEASE.json") or {}
    man_path = os.path.join(package, "artifact", "manifest.json")
    if rel and os.path.isfile(man_path):
        with open(man_path) as fh:
            m = json.load(fh)
        art = rel.get("artifact") or {}
        want = {"version": m.get("artifact_version"), "manifest_sha256": sha256_file(man_path),
                "model_id": (m.get("vectors") or {}).get("model_id"), "dimensions": (m.get("vectors") or {}).get("dimensions"),
                "domain_fingerprint": (m.get("domain_fingerprint") or {}).get("sha256")}
        for k, v in want.items():
            if art.get(k) != v:
                problems.append(f"RELEASE.json: release.artifact.{k} does not match the package's artifact")
        prov = loaded.get(os.path.join("artifact", "provenance.json"))
        if prov is not None:
            if prov.get("deployment_id") != want["model_id"]:
                problems.append("artifact/provenance.json: provenance.deployment_id does not match the vector identity")
            if (m.get("files") or {}).get("provenance.json") != sha256_file(os.path.join(package, "artifact", "provenance.json")):
                problems.append("artifact/provenance.json: does not match manifest.json")
    for p in problems:
        print(f"FAIL {p}")
    print(("PUBLIC FIELDS CHECK FAILED" if problems else "PUBLIC FIELDS CHECK PASSED")
          + f": RELEASE.json and artifact/provenance.json ({len(problems)} problem(s))")
    return 1 if problems else 0


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 2 or a[0] not in ("project", "check") or not os.path.isdir(a[1]):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        return project(a[1]) if a[0] == "project" else check(a[1])
    except (OSError, ValueError) as e:
        print(f"public_provenance: unreadable input: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
