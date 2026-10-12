"""FLH-059 batching policies and the v1/v2 manifest split (no torch, no
model). These check shapes requested and identities derived; they say nothing
about real CUDA numerics."""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from flh_e5 import __main__ as cli
from flh_e5 import batching, contract, manifest
from flh_e5.service import Limits

PKG = Path(manifest.__file__).resolve().parent
# The FLH-054 deployment observed by FLH-056/058 hashed exactly these bytes.
FLH054_CODE_SHA256 = "96ab7c27ec6e18ec98cbafd3c8f3aac39c72f317110b98887d24d95d5e466bc0"
NUMERICS = {"attn_implementation": "sdpa", "matmul_allow_tf32": False}
FILES = {"model.safetensors": {"sha256": "a" * 64}}
RUNTIME = {"torch": "2.13.0+cu126"}


class Recorder:
    def __init__(self):
        self.calls = []

    def dynamic(self, texts):
        self.calls.append(("dynamic", list(texts)))
        return [[float(len(t))] for t in texts]

    def fixed(self, texts, rows, width):
        self.calls.append(("fixed", list(texts), rows, width))
        return [[float(len(t))] for t in texts]


class Policies(unittest.TestCase):
    def apply(self, policy, texts, rows=8):
        rec = Recorder()
        out = batching.apply_policy(policy, texts, rows=rows, encode_dynamic=rec.dynamic, encode_fixed=rec.fixed)
        return out, rec.calls

    def test_dynamic_is_one_legacy_call(self):
        out, calls = self.apply("dynamic_v1", ["a", "bb", "ccc"])
        self.assertEqual(calls, [("dynamic", ["a", "bb", "ccc"])])
        self.assertEqual(out, [[1.0], [2.0], [3.0]])

    def test_singleton_is_one_unpadded_call_per_input_in_order(self):
        out, calls = self.apply("singleton_v1", ["a", "bb", "ccc"])
        self.assertEqual(calls, [("dynamic", ["a"]), ("dynamic", ["bb"]), ("dynamic", ["ccc"])])
        self.assertEqual(out, [[1.0], [2.0], [3.0]])

    def test_fixed_requests_the_fixed_shape_even_for_partial_batches(self):
        out, calls = self.apply("fixed_v1", ["a", "bb"], rows=8)
        self.assertEqual(calls, [("fixed", ["a", "bb"], 8, 512)])
        self.assertEqual(out, [[1.0], [2.0]])
        with self.assertRaises(ValueError):
            self.apply("fixed_v1", ["x"] * 9, rows=8)

    def test_empty_and_unknown(self):
        self.assertEqual(self.apply("singleton_v1", [])[0], [])
        with self.assertRaises(ValueError):
            self.apply("bucketed", ["a"])


class Identities(unittest.TestCase):
    def test_legacy_vector_code_is_byte_identical_to_flh054(self):
        self.assertEqual(manifest.code_sha256(PKG), FLH054_CODE_SHA256,
                         "contract.py/encoder.py/manifest.py changed: the FLH-054 deployment identity can no longer be reproduced")

    def test_dynamic_keeps_the_v1_manifest_and_identity(self):
        limits = Limits()
        legacy = cli.build_manifest_for(FILES, RUNTIME, "float16", limits)
        direct = manifest.build_manifest(files=FILES, code_hash=FLH054_CODE_SHA256, convention=contract.CONVENTION,
                                         accepted_pairs=contract.ACCEPTED_PAIRS, prefixes=dict(contract.PREFIXES),
                                         dtype="float16", microbatch=8, runtime=RUNTIME, service=limits.public())
        self.assertEqual(legacy, direct)
        self.assertEqual(legacy["vector_defining"]["schema"], manifest.MANIFEST_SCHEMA)
        self.assertNotIn("batching", legacy["vector_defining"]["inference"])
        with self.assertRaises(ValueError):
            batching.build_manifest_v2(files=FILES, code_hash="c" * 64, convention=contract.CONVENTION,
                                       accepted_pairs=contract.ACCEPTED_PAIRS, prefixes=dict(contract.PREFIXES),
                                       dtype="float16", microbatch=8, policy="dynamic_v1", numerics=NUMERICS,
                                       runtime=RUNTIME, service={})

    def test_every_other_policy_gets_a_distinct_explicit_identity(self):
        limits = Limits()
        legacy = cli.build_manifest_for(FILES, RUNTIME, "float16", limits)["deployment_id"]
        seen = {legacy}
        for dtype in ("float16", "float32"):
            for policy in ("singleton_v1", "fixed_v1"):
                m = cli.build_manifest_for(FILES, RUNTIME, dtype, limits, policy, NUMERICS)
                ident = m["deployment_id"]
                self.assertNotIn(ident, seen)
                seen.add(ident)
                self.assertLessEqual(len(ident.encode()), manifest.MAX_IDENTITY_BYTES)
                self.assertIn(f"/flh_e5_role_prefix_v1/{dtype}/{policy}/", ident)
                vd = m["vector_defining"]
                self.assertEqual(vd["schema"], batching.MANIFEST_SCHEMA_V2)
                self.assertEqual(vd["inference"]["batching"]["policy"], policy)
                self.assertEqual(vd["inference"]["numerics"], NUMERICS)
                self.assertEqual(vd["adapter"]["code_files"], list(batching.VECTOR_CODE_FILES_V2))
                self.assertEqual(vd["adapter"]["code_sha256"], batching.code_sha256_v2(PKG))
        with self.assertRaises(ValueError):
            cli.build_manifest_for(FILES, RUNTIME, "float16", limits, "singleton_v1", None)

    def test_v2_identity_changes_with_numerics_microbatch_and_code(self):
        def v2(**over):
            args = dict(files=FILES, code_hash="c" * 64, convention=contract.CONVENTION,
                        accepted_pairs=contract.ACCEPTED_PAIRS, prefixes=dict(contract.PREFIXES), dtype="float16",
                        microbatch=8, policy="fixed_v1", numerics=NUMERICS, runtime=RUNTIME, service={"max_inputs": 32})
            args.update(over)
            return batching.build_manifest_v2(**args)["deployment_id"]
        base = v2()
        self.assertEqual(v2(), base)
        self.assertEqual(v2(service={"max_inputs": 16}), base)  # limits do not define vectors
        for change in ({"numerics": {**NUMERICS, "matmul_allow_tf32": True}}, {"microbatch": 4},
                       {"code_hash": "d" * 64}, {"policy": "singleton_v1"}, {"dtype": "float32"}):
            self.assertNotEqual(v2(**change), base, change)

    def test_v2_code_hash_covers_batching_and_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "flh_e5"
            shutil.copytree(PKG, pkg, ignore=shutil.ignore_patterns("__pycache__"))
            before = batching.code_sha256_v2(pkg)
            self.assertNotEqual(before, manifest.code_sha256(pkg))
            path = pkg / "batching.py"
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            self.assertEqual(batching.code_sha256_v2(pkg), before)
            path.write_bytes(path.read_bytes() + b"# changed\r\n")
            self.assertNotEqual(batching.code_sha256_v2(pkg), before)
            self.assertEqual(manifest.code_sha256(pkg), FLH054_CODE_SHA256)


class Cli(unittest.TestCase):
    def test_batching_flag_validated_before_any_model_work(self):
        for command in ("manifest", "serve"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                cli.main([command, "--model-dir", "unused", "--batching", "bucketed"])
            self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
