"""Offline tests for the FLH-059 diagnostic (no torch, no model, no socket).

The fake backend makes a vector depend on its forward-pass shape, so that the
analysis can be checked to detect such drift and to report its absence. This
tests the diagnostic's plumbing and arithmetic only; it says nothing about
real CUDA numerics.
"""

import hashlib
import json
import math
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "tools" / "embedding" / "e5"))

import diagnose  # noqa: E402
from flh_e5 import contract  # noqa: E402


def f32(values):
    return list(array("f", values))


def unit(seed: bytes) -> list[float]:
    raw = []
    k = 0
    while len(raw) < diagnose.DIMENSIONS:
        for byte in hashlib.sha256(seed + k.to_bytes(4, "big")).digest():
            raw.append(byte / 255.0 - 0.5)
        k += 1
    raw = raw[: diagnose.DIMENSIONS]
    n = math.sqrt(sum(x * x for x in raw))
    return [x / n for x in raw]


class FakeBackend:
    """Shape-dependent fake: drift = f(rows, width) of the forward pass."""

    def __init__(self, dtype: str, drift: float = 2e-3):
        self.dtype = dtype
        self.drift = drift
        self.files = {"fake": True}
        self.closed = False
        self.calls = []

    def count_tokens(self, texts):
        return [len(t.encode()) // 4 + 2 for t in texts]

    def _vec(self, text, rows, width):
        base = unit(text.encode())
        noise = unit(f"{rows}x{width}".encode())
        v = [b + self.drift * n for b, n in zip(base, noise)]
        n = math.sqrt(sum(x * x for x in v))
        return f32([x / n for x in v])

    def encode_dynamic(self, texts):
        width = max(self.count_tokens(texts))
        self.calls.append(("dynamic", len(texts), width))
        return [self._vec(t, len(texts), width) for t in texts]

    def encode_fixed(self, texts, rows, width):
        self.calls.append(("fixed", rows, width))
        return [self._vec(t, rows, width) for t in texts]

    def evidence(self):
        return {"fake": self.dtype}

    def close(self):
        self.closed = True


class InputsTests(unittest.TestCase):
    def test_inputs_are_contract_inputs_without_labels(self):
        data = diagnose.load_inputs()
        self.assertEqual(data["schema"], "flh059_model_inputs_v1")
        for d in data["documents"]:
            self.assertEqual(set(d), {"id", "text"})
            self.assertEqual(contract.adapt(d["text"]).role, "passage")
        for q in data["queries"]:
            self.assertEqual(set(q), {"id", "text"})
            self.assertEqual(contract.adapt(q["text"]).role, "query")
        raw = diagnose.INPUTS.read_text(encoding="utf-8")
        for word in ('"split"', '"language"', '"expected', '"label', '"judgment', '"reason"'):
            self.assertNotIn(word, raw)

    def test_query_sample_uses_token_counts_only(self):
        data = diagnose.load_inputs()
        counts = {q["text"]: (i * 7) % 31 for i, q in enumerate(data["queries"])}
        picks = diagnose.select_queries(data["queries"], counts)
        self.assertEqual(len(picks), diagnose.QUERY_SAMPLE)
        lengths = [counts[q["text"]] for q in picks]
        self.assertEqual(min(lengths), min(counts.values()))
        self.assertEqual(max(lengths), max(counts.values()))
        self.assertEqual(picks, diagnose.select_queries(data["queries"], counts))


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.data = diagnose.load_inputs()
        self.tokens = {x["text"]: len(x["text"].encode()) // 4 for x in self.data["documents"] + self.data["queries"]}
        self.reqs = diagnose.build_matrix(self.data, self.tokens)

    def test_bounded_and_identical_texts(self):
        s = diagnose.plan_summary(self.reqs)
        self.assertLessEqual(s["positions_per_config"], diagnose.MAX_POSITIONS_PER_CONFIG)
        self.assertEqual(s["positions_total"], s["positions_per_config"] * 6)
        conds = {r["condition"] for r in self.reqs}
        self.assertEqual(conds, {"singleton_a", "singleton_b", "ordered", "reversed", "rotated",
                                 "short_companion", "long_companion", "partial3", "flh058_shape"})
        ids = {x["id"] for x in self.data["documents"] + self.data["queries"]}
        for r in self.reqs:
            self.assertTrue(set(r["items"]) <= ids)
            self.assertEqual(len(r["items"]), len(set(r["items"])))

    def test_shapes_cover_full_partial_and_flh058(self):
        sizes = {r["condition"]: [len(m) for m in diagnose.microbatches(r["items"])] for r in self.reqs}
        self.assertEqual(sizes["ordered"], [8, 8, 8])
        self.assertEqual(sizes["partial3"], [3])
        self.assertEqual(sizes["flh058_shape"], [8, 8, 8, 1])
        docs = [d["id"] for d in self.data["documents"]]
        flh058 = [r for r in self.reqs if r["condition"] == "flh058_shape"]
        self.assertTrue(all(r["items"][1:] == docs for r in flh058))


class RunAnalyzeTests(unittest.TestCase):
    def run_fake(self, out, drift=2e-3):
        backends = []

        def factory(dtype):
            b = FakeBackend(dtype, drift)
            backends.append(b)
            return b
        code = diagnose.run(out, None, diagnose.DTYPES, diagnose.POLICIES, backend_factory=factory)
        return code, backends

    def test_detects_shape_drift_and_its_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            code, backends = self.run_fake(out)
            self.assertEqual(code, 0)
            self.assertTrue(all(b.closed for b in backends))
            a = json.loads((out / "analysis.json").read_text())
            dyn = a["configs"]["float16-dynamic_v1"]
            self.assertGreater(dyn["tolerance_failures"], 0)
            self.assertGreater(dyn["conditions"]["flh058_shape"]["tolerance_failures"], 0)
            self.assertEqual(dyn["conditions"]["singleton_b"]["tolerance_failures"], 0)
            self.assertEqual(dyn["same_shape_rows"]["groups_with_repeats"], dyn["same_shape_rows"]["groups_all_bitwise_equal"])
            self.assertEqual(dyn["shape_vs_reference"]["different_shape"]["bitwise"], 0)
            for name in ("float16-singleton_v1", "float16-fixed_v1", "float32-singleton_v1"):
                c = a["configs"][name]
                self.assertEqual(c["tolerance_failures"], 0, name)
                self.assertEqual(c["bitwise_equal"], c["compared_positions"], name)
                self.assertEqual(c["ranking"]["top5_order_changed"], 0, name)
            self.assertNotIn("float16-dynamic_v1", a["passing"])
            self.assertEqual(a["candidate"], "float16-singleton_v1")
            self.assertIn("float16-dynamic_v1", a["cross_config"])
            self.assertEqual(a["tolerance"], {"abs": 1e-5, "rel": 1e-4, "source": "FLH-056, unchanged"})
            env = json.loads((out / "environment.json").read_text())
            self.assertEqual(env["flh_e5_code_sha256_v1"], "96ab7c27ec6e18ec98cbafd3c8f3aac39c72f317110b98887d24d95d5e466bc0")
            rec = json.loads((out / "records-float16-fixed_v1.json").read_text())
            self.assertTrue(all((r["forward_rows"], r["forward_width"]) == (8, 512) for r in rec["records"]))
            fixed_calls = {c for c in backends[0].calls if c[0] == "fixed"}
            self.assertEqual(fixed_calls, {("fixed", 8, 512)})

    def test_zero_drift_passes_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            self.run_fake(out, drift=0.0)
            a = json.loads((out / "analysis.json").read_text())
            self.assertEqual(sorted(a["passing"]), sorted(a["configs"]))
            self.assertEqual(a["candidate"], "float16-dynamic_v1")  # no change preferred when nothing fails

    def test_analyze_detects_tampering_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            self.run_fake(out)
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.analyze(out)  # analysis.json exists
            (out / "analysis.json").unlink()
            v = out / "vectors-float32-fixed_v1.f32"
            data = bytearray(v.read_bytes())
            data[0] ^= 1
            v.write_bytes(bytes(data))
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.analyze(out)

    def test_out_guard(self):
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.guard_out(diagnose.ROOT / "scratch-flh059")
        self.assertFalse((diagnose.ROOT / "scratch-flh059").exists())
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x").write_text("keep")
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.guard_out(Path(tmp))
            self.assertEqual((Path(tmp) / "x").read_text(), "keep")

    def test_cli_rejects_unknown_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = diagnose.main(["run", "--model-dir", tmp, "--out", str(Path(tmp) / "o"), "--dtypes", "bfloat16"])
            self.assertEqual(code, 2)


class ArithmeticTests(unittest.TestCase):
    def test_tolerance_and_compare(self):
        a = [0.5, -0.25, 0.0]
        self.assertTrue(diagnose.compare(a, a)["bitwise"])
        b = [0.5 + 1e-5 + 0.5e-4, -0.25, 0.0]
        self.assertTrue(diagnose.within_tolerance(a, b))
        c = [0.5 + 1e-5 + 0.5e-4 + 1e-6, -0.25, 0.0]
        self.assertFalse(diagnose.within_tolerance(a, c))

    def test_f32_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            vals = f32([0.1, -1e-8, 3.0e-4, 1.0])
            p = Path(tmp) / "v.f32"
            digest = diagnose.write_f32(p, vals)
            self.assertEqual(digest, hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(list(diagnose.read_f32(p)), vals)


if __name__ == "__main__":
    unittest.main()
