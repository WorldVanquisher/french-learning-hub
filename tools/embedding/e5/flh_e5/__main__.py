"""Command line: verify-files | manifest | serve. See README.md."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from pathlib import Path

from . import contract, manifest
from .service import EmbeddingHTTPServer, EmbeddingService, Limits, validate_bind_host

PACKAGE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("flh_e5")


def build_manifest_for(encoder_files: dict, runtime: dict, dtype: str, limits: Limits) -> dict:
    return manifest.build_manifest(
        files=encoder_files, code_hash=manifest.code_sha256(PACKAGE_DIR), convention=contract.CONVENTION,
        accepted_pairs=contract.ACCEPTED_PAIRS, prefixes=dict(contract.PREFIXES), dtype=dtype,
        microbatch=limits.microbatch, runtime=runtime, service=limits.public())


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m flh_e5", description="FLH-054 local E5 embedding service")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("verify-files", "manifest", "serve"):
        p = sub.add_parser(name)
        p.add_argument("--model-dir", required=True, type=Path, help="directory prepared with the pinned files only")
        if name != "verify-files":
            p.add_argument("--dtype", choices=("float16", "float32"), default="float16")
            p.add_argument("--microbatch", type=int, default=8)
            p.add_argument("--max-inputs", type=int, default=32)
            p.add_argument("--max-queue", type=int, default=4)
            p.add_argument("--queue-timeout", type=float, default=30.0)
        if name == "serve":
            p.add_argument("--host", default="127.0.0.1", help="loopback (default) or a private RFC 1918 / ULA IP literal")
            p.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    if args.command == "verify-files":
        try:
            files = manifest.verify_model_dir(args.model_dir)
        except manifest.ModelFilesError as e:
            print(f"verify-files: FAILED: {e}", file=sys.stderr)
            return 3
        print(json.dumps({"repository": manifest.REPOSITORY, "revision": manifest.REVISION, "files": files}, indent=2))
        return 0

    limits = Limits(max_inputs=args.max_inputs, microbatch=args.microbatch, max_queue=args.max_queue, queue_timeout_s=args.queue_timeout)
    try:
        limits.validate()
    except ValueError as e:
        print(f"configuration: {e}", file=sys.stderr)
        return 2
    from .encoder import E5CudaEncoder, EncoderStartupError, runtime_versions

    if args.command == "manifest":
        try:
            files = manifest.verify_model_dir(args.model_dir)
            m = build_manifest_for(files, runtime_versions(), args.dtype, limits)
        except (manifest.ModelFilesError, EncoderStartupError) as e:
            print(f"manifest: FAILED: {e}", file=sys.stderr)
            return 3
        print(json.dumps(m, indent=2, sort_keys=True))
        return 0

    try:
        host = validate_bind_host(args.host)
        if not 1024 <= args.port <= 65535:
            raise ValueError("--port must be 1024..65535")
    except ValueError as e:
        print(f"configuration: {e}", file=sys.stderr)
        return 2

    service = EmbeddingService(
        encoder_factory=lambda: E5CudaEncoder(args.model_dir, args.dtype),
        manifest_factory=lambda enc: build_manifest_for(enc.files, enc.runtime_versions(), args.dtype, limits),
        limits=limits)
    return serve(service, host, args.port)


def serve(service: EmbeddingService, host: str, port: int, stop: threading.Event | None = None, on_bound=None) -> int:
    """Bind, answer /readyz 503 while loading, load and warm up, then serve
    until SIGINT/SIGTERM/SIGBREAK (or `stop`). Returns the exit status."""
    stop = stop or threading.Event()
    try:
        server = EmbeddingHTTPServer((host, port), service)
    except OSError as e:
        print(f"bind {host}:{port} failed: {e}", file=sys.stderr)
        return 3
    if on_bound is not None:
        on_bound(server.server_address)
    thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    thread.start()
    log.info("listening on http://%s:%d (state %s)", host, server.server_address[1], service.state)

    def on_signal(signum, _frame):
        log.info("signal %s: stopping", signum)
        stop.set()

    if threading.current_thread() is threading.main_thread():
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), on_signal)
    code = 0
    try:
        try:
            service.load()
            log.info("gpu: %s", json.dumps(service.metrics()["gpu"], sort_keys=True))
        except Exception as e:  # noqa: BLE001 - reported, the process exits nonzero
            log.error("startup failed, not ready: %s", service.state_detail or e)
            code = 3
            stop.set()
        while not stop.wait(0.5):  # short waits keep Ctrl+C responsive on Windows
            pass
    except KeyboardInterrupt:
        pass
    finally:
        service.state = "stopping"
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        service.close()
        log.info("stopped; listener closed and model released (counters %s)", json.dumps(service.counters.snapshot(), sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
