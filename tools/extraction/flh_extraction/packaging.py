"""Compare the installed training stack with requirements-train.txt.

  python3 -m flh_extraction.packaging [--requirements FILE] [--out REPORT.json]
      exit 0 when every pinned package is installed at its pinned version, 4 otherwise

The SageMaker entry point runs the same check before training or prediction and
refuses a mismatched stack (a stale image) unless FLH_ALLOW_STACK_MISMATCH=1,
which is meant only for tiny offline fixtures; the report is then written next
to the job's outputs (`stack-check.json`) so the mismatch is never silent.
Standard library only.
"""

import argparse
import json
import os
import re
import sys
from importlib import metadata
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements-train.txt"
ALLOW_ENV = "FLH_ALLOW_STACK_MISMATCH"
PIN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(?:==\s*([^\s#;]+))?")


def pins(path=None):
    out = {}
    for line in Path(path or REQUIREMENTS).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        m = PIN.match(line)
        if line and m:
            out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


def installed(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def qwen3_5_supported():
    """Whether the installed transformers knows model_type qwen3_5 (None: not installed)."""
    try:
        from transformers.models.auto.configuration_auto import CONFIG_MAPPING_NAMES
    except Exception:  # noqa: BLE001 - absent or broken transformers
        return None
    return "qwen3_5" in CONFIG_MAPPING_NAMES


def check(path=None, probe_transformers=True):
    path = path or REQUIREMENTS
    rows = {}
    for name, want in pins(path).items():
        have = installed(name)
        # PEP 440: a pin without a local label (==2.15.0) accepts a local variant (2.15.0+cpu), as pip does.
        same = have is not None and want is not None and (have == want or ("+" not in want and have.split("+")[0] == want))
        st = "MISSING" if have is None else "UNPINNED" if want is None else "OK" if same else "MISMATCH"
        rows[name] = {"pinned": want, "installed": have, "status": st}
        if same and have != want:
            rows[name]["local_variant"] = have.split("+", 1)[1]
    bad = {k: v for k, v in rows.items() if v["status"] in ("MISSING", "MISMATCH")}
    rep = {"schema": "flh_extractor_stack_check_v1", "requirements": Path(path).name, "packages": rows,
           "stack_matches_requirements": not bad, "mismatches": sorted(bad)}
    if probe_transformers:
        rep["transformers_knows_qwen3_5"] = qwen3_5_supported()
    if bad:
        rep["verdict"] = "STALE_OR_INCOMPLETE: rebuild the image from requirements-train.txt; " + ", ".join(
            f"{k} {v['installed'] or 'absent'} != {v['pinned'] or 'any version'}" for k, v in sorted(bad.items()))
    else:
        rep["verdict"] = "MATCHES_PINNED_REQUIREMENTS"
    return rep


def allowed_mismatch():
    return os.environ.get(ALLOW_ENV) == "1"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--requirements")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rep = check(a.requirements)
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"verdict": rep["verdict"], "transformers_knows_qwen3_5": rep.get("transformers_knows_qwen3_5"),
                      "packages": {k: f"{v['installed']} (pinned {v['pinned']})" for k, v in rep["packages"].items()}}))
    return 0 if rep["stack_matches_requirements"] else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
