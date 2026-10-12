"""Pinned files, file verification and deployment identity (no model files
are present in tests; the real weights are verified only on the prepared
Windows machine)."""

import shutil
import tempfile
import unittest
from pathlib import Path

from flh_e5 import contract, manifest

PKG = Path(manifest.__file__).resolve().parent


def build(**over):
    args = dict(files={"model.safetensors": {"sha256": "a" * 64}}, code_hash="c" * 64, convention=contract.CONVENTION,
                accepted_pairs=contract.ACCEPTED_PAIRS, prefixes=dict(contract.PREFIXES), dtype="float16", microbatch=8,
                runtime={"torch": "2.13.0+cu126"}, service={"max_inputs": 32})
    args.update(over)
    return manifest.build_manifest(**args)


class Identity(unittest.TestCase):
    def test_pins_are_immutable_digests(self):
        self.assertRegex(manifest.REVISION, r"^[0-9a-f]{40}$")
        self.assertEqual(manifest.DIMENSIONS, 768)
        self.assertEqual(manifest.MAX_TOKENS, 512)
        for name, (size, kind, digest) in manifest.PINNED_FILES.items():
            self.assertGreater(size, 0, name)
            self.assertRegex(digest, {"sha256": r"^[0-9a-f]{64}$", "git-blob-sha1": r"^[0-9a-f]{40}$"}[kind], name)
        self.assertIn("model.safetensors", manifest.PINNED_FILES)
        self.assertFalse(any(n.endswith((".bin", ".py", ".onnx")) for n in manifest.PINNED_FILES))

    def test_identity_is_bounded_and_derived_from_vector_defining_fields(self):
        base = build()
        ident = base["deployment_id"]
        self.assertLessEqual(len(ident.encode()), 200)
        self.assertTrue(ident.startswith(f"multilingual-e5-base@{manifest.REVISION}/flh_e5_role_prefix_v1/float16/"))
        self.assertEqual(build()["deployment_id"], ident)  # deterministic
        for change in ({"dtype": "float32"}, {"code_hash": "d" * 64}, {"microbatch": 4},
                       {"runtime": {"torch": "2.14.0"}}, {"files": {"model.safetensors": {"sha256": "b" * 64}}},
                       {"prefixes": {"query": "query: ", "passage": "query: "}}):
            with self.subTest(change):
                self.assertNotEqual(build(**change)["deployment_id"], ident)
        # Service limits do not change vectors, so they do not change identity.
        self.assertEqual(build(service={"max_inputs": 16})["deployment_id"], ident)

    def test_code_hash_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in manifest.VECTOR_CODE_FILES:
                data = (PKG / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                (Path(tmp) / name).write_bytes(data)
            self.assertEqual(manifest.code_sha256(Path(tmp)), manifest.code_sha256(PKG))
            (Path(tmp) / "contract.py").write_bytes(b"# changed\r\n" + (Path(tmp) / "contract.py").read_bytes())
            self.assertNotEqual(manifest.code_sha256(Path(tmp)), manifest.code_sha256(PKG))


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="flh054-model-"))
        self.addCleanup(shutil.rmtree, self.dir)

    def test_git_blob_sha1(self):
        self.assertEqual(manifest.git_blob_sha1(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")

    def test_missing_directory_and_files(self):
        with self.assertRaisesRegex(manifest.ModelFilesError, "not found"):
            manifest.verify_model_dir(self.dir / "absent")
        with self.assertRaisesRegex(manifest.ModelFilesError, "missing pinned file"):
            manifest.verify_model_dir(self.dir)

    def test_unexpected_files_are_refused(self):
        for name in ("pytorch_model.bin", "modeling_custom.py", "model.onnx"):
            with self.subTest(name):
                (self.dir / name).write_bytes(b"x")
                with self.assertRaisesRegex(manifest.ModelFilesError, "unexpected entries"):
                    manifest.verify_model_dir(self.dir)
                (self.dir / name).unlink()

    def test_wrong_size_or_digest_is_refused(self):
        (self.dir / ".cache").mkdir()  # tolerated download metadata
        for name in manifest.PINNED_FILES:
            (self.dir / name).write_bytes(b"")
        with self.assertRaisesRegex(manifest.ModelFilesError, "size 0, pinned"):
            manifest.verify_model_dir(self.dir)


if __name__ == "__main__":
    unittest.main()
