"""Tests that need NumPy and PyAV (run in the image): audio decoding, the
abstention rules and the HTTP service with a fake model.

  docker run --rm --network none -v $PWD/tools/speaking:/src:ro -w /src --entrypoint python3 \
      flh-speaking:cpu-dev -B -m unittest discover -s tests -t tests
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import av  # noqa: F401
    import numpy as np
    HAVE = True
except ImportError:  # host without the image's libraries
    HAVE = False

if HAVE:
    from flh_speaking import audio, model, probes, service

SR = 16000


def tone(seconds, freq=220.0, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


@unittest.skipUnless(HAVE, "needs numpy and av (run in the image)")
class Audio(unittest.TestCase):
    def test_wav_round_trip_and_convention(self):
        x = tone(1.0)
        d = audio.decode(audio.to_wav_pcm16(x), max_seconds=5, allowed=audio.SERVICE_FAMILIES)
        self.assertEqual((d.family, d.source_rate, d.source_channels), ("wav", SR, 1))
        self.assertEqual(len(d.samples), SR)
        self.assertLess(float(np.max(np.abs(d.samples - x))), 1e-3)
        self.assertEqual(audio.read_wav_pcm16(audio.to_wav_pcm16(x)).dtype, np.float32)

    def test_stereo_44k_is_downmixed_and_resampled(self):
        n = 44100
        t = np.arange(n) / 44100
        st = np.stack([0.4 * np.sin(2 * np.pi * 300 * t), 0.4 * np.sin(2 * np.pi * 300 * t)]).T
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes((st * 32767).astype("<i2").tobytes())
        d = audio.decode(buf.getvalue(), max_seconds=5, allowed=audio.SERVICE_FAMILIES)
        self.assertEqual((d.source_rate, d.source_channels), (44100, 2))
        self.assertAlmostEqual(len(d.samples) / SR, 1.0, delta=0.01)
        # FFmpeg's mono layout sums the channels with 1/sqrt(2) weights: identical channels gain 3 dB.
        self.assertAlmostEqual(float(np.max(np.abs(d.samples))), 0.4 * 2 / np.sqrt(2), delta=0.03)

    def test_browser_codecs_decode_in_memory(self):
        x = tone(2.0)
        for fmt, codec, family in (("webm", "libopus", "webm"), ("mp4", "aac", "mp4"), ("mp3", "libmp3lame", "mp3")):
            blob = probes.encode(x, fmt, codec, rate=48000 if codec == "libopus" else (44100 if codec == "libmp3lame" else SR))
            d = audio.decode(blob, max_seconds=5, allowed=audio.SERVICE_FAMILIES)
            self.assertEqual(d.family, family)
            self.assertAlmostEqual(d.seconds, 2.0, delta=0.15)

    def test_refusals_have_stable_codes(self):
        cases = [(b"", "empty_audio"), (os.urandom(2048), "unsupported_audio"),
                 (b"fLaC" + b"\0" * 64, "unsupported_audio"), (audio.to_wav_pcm16(tone(1))[:30], "undecodable_audio")]
        for data, code in cases:
            with self.assertRaises(audio.AudioError) as cm:
                audio.decode(data, max_seconds=5, allowed=audio.SERVICE_FAMILIES)
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(audio.AudioError) as cm:
            audio.decode(audio.to_wav_pcm16(np.zeros(6 * SR, np.float32)), max_seconds=5, allowed=audio.SERVICE_FAMILIES)
        self.assertEqual(cm.exception.code, "audio_too_long")

    def test_quality_separates_silence_from_signal(self):
        self.assertEqual(audio.quality(np.zeros(SR, np.float32))["sound_seconds"], 0.0)
        x = np.concatenate([np.zeros(SR, np.float32), tone(1.0)])
        self.assertAlmostEqual(audio.quality(x)["sound_seconds"], 1.0, delta=0.1)
        quiet = np.concatenate([np.zeros(SR, np.float32), tone(1.0, amp=0.001)])  # about -63 dBFS: still sound
        self.assertAlmostEqual(audio.quality(quiet)["sound_seconds"], 1.0, delta=0.1)
        noisy = np.concatenate([tone(1.0, amp=0.03), tone(1.0, amp=0.05)])  # steady background, no quiet floor
        self.assertGreater(audio.quality(noisy)["sound_seconds"], 1.9)


def win(text="Bonjour à tous.", nsp=0.01, lp=-0.3, pfr=0.95, top="fr", ptop=0.95, cr=1.2, limit=False):
    return {"text": text, "no_speech_prob": nsp, "avg_logprob": lp, "p_fr": pfr, "top_language": top,
            "p_top_language": ptop, "compression_ratio": cr, "hit_token_limit": limit}


@unittest.skipUnless(HAVE, "needs numpy")
class Rules(unittest.TestCase):
    Q = {"sound_seconds": 2.0, "seconds": 2.0}

    def test_transcribed_and_warnings(self):
        r = model.decide([win()], self.Q)
        self.assertEqual((r.status, r.text, r.warnings), ("transcribed", "Bonjour à tous.", []))
        r = model.decide([win(lp=-1.4, cr=3.0, pfr=0.4, top="en", ptop=0.5)], self.Q)
        self.assertEqual(r.warnings, ["low_confidence", "possibly_not_french", "repetitive_output"])

    def test_abstentions(self):
        self.assertEqual(model.decide([win()], {"sound_seconds": 0.1}).status, "no_speech")
        self.assertEqual(model.decide([win(nsp=0.9, lp=-1.5)], self.Q).status, "no_speech")
        r = model.decide([win(pfr=0.05, top="en", ptop=0.9)], self.Q)
        self.assertEqual((r.status, r.warnings), ("not_french", ["detected_en"]))
        r = model.decide([win("Sous-titres réalisés par la communauté d'Amara.org")], self.Q)
        self.assertEqual((r.status, r.warnings), ("no_speech", ["phantom_phrase_removed"]))

    def test_silent_windows_add_no_text(self):
        r = model.decide([win("Merci."), win("Sous-titrage ST' 501"), win(nsp=0.95, lp=-2.0, text="...")], self.Q)
        self.assertEqual((r.status, r.text), ("transcribed", "Merci."))
        self.assertIn("phantom_phrase_removed", r.warnings)

    def test_loop_cut(self):
        self.assertEqual(model.loop_cut([1, 2, 3, 5, 5, 5]), 0)
        self.assertEqual(model.loop_cut([1, 5, 5, 5, 5]), 3)  # "très très très très" -> one kept
        self.assertEqual(model.loop_cut([9, 7, 8, 7, 8, 7, 8, 7, 8]), 6)
        self.assertEqual(model.loop_cut([7, 8] * 3), 0)  # three copies are allowed
        r = model.decide([dict(win(), loop_cut=True)], self.Q)
        self.assertEqual(r.warnings, ["repetitive_output"])

    def test_phantom_does_not_eat_real_sentences(self):
        self.assertFalse(model.phantom("Je me suis abonné au journal."))
        self.assertFalse(model.phantom("Merci beaucoup pour votre aide."))
        self.assertTrue(model.phantom("Merci d'avoir regardé cette vidéo !"))

    def test_long_audio_windows_cut_at_quiet_frames(self):
        x = np.concatenate([tone(27), np.zeros(SR // 2, np.float32), tone(20), np.zeros(SR // 3, np.float32), tone(20)])
        spans = model.windows(x)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(x))
        self.assertTrue(all(b - a <= model.WINDOW_SECONDS * SR for a, b in spans))
        self.assertTrue(all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1)))
        self.assertAlmostEqual(spans[0][1] / SR, 27.25, delta=0.3)  # inside the first pause


class FakeTranscriber:
    def __init__(self, delay=0.0, result=None, raise_timeout=False):
        self.delay, self.result, self.raise_timeout, self.calls = delay, result, raise_timeout, 0

    def raw(self, batch):
        return [win()]

    def transcribe(self, samples, deadline=None, quality=None):
        self.calls += 1
        time.sleep(self.delay)
        if self.raise_timeout:
            raise TimeoutError()
        q = audio.quality(samples)
        if self.result:
            return model.Result(self.result, "", [], [], {}, q, self.delay)
        return model.decide([win(text=f"Texte {len(samples)}.")], q, self.delay)


MANIFEST = {"deployment_id": "fake@0/flh_speaking_transcribe_v1/cpu-fp32/0000", "limits": {}}


def multipart(fields):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{b}\r\n".encode())
        if k == "file":
            out.write(b'Content-Disposition: form-data; name="file"; filename="take.wav"\r\nContent-Type: audio/wav\r\n\r\n')
        else:
            out.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        out.write(v if isinstance(v, bytes) else v.encode())
        out.write(b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


@unittest.skipUnless(HAVE, "needs numpy and av")
class Service(unittest.TestCase):
    def start(self, fake, limits=None, max_waiting=2, delay_load=0.0):
        def loader(d, t):
            time.sleep(delay_load)
            return fake
        lim = dict(service.deployment.LIMITS)
        lim.update(limits or {})
        srv, st = service.make_server("unused", "127.0.0.1", 0, loader=loader, manifest_fn=lambda d: MANIFEST, limits=lim, max_waiting=max_waiting)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        loading = threading.Thread(target=st.load, daemon=True)
        loading.start()
        return f"http://127.0.0.1:{srv.server_address[1]}", st, loading

    def call(self, url, path, fields=None, raw=None, ctype=None):
        if fields is not None:
            body, ct = multipart(fields)
        else:
            body, ct = raw, ctype
        req = urllib.request.Request(url + path, data=body, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": ct, "Authorization": "Bearer not-a-secret"} if body is not None else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def ok_fields(self, seconds=1.0):
        x = np.concatenate([np.zeros(SR // 2, np.float32), tone(seconds - 0.5)])  # a pause, then signal
        return {"file": audio.to_wav_pcm16(x), "model": MANIFEST["deployment_id"], "response_format": "json"}

    def test_readiness_distinguishes_loading_from_ready(self):
        url, st, loading = self.start(FakeTranscriber(), delay_load=0.5)
        self.assertEqual(self.call(url, "/healthz")[0], 200)
        code, doc = self.call(url, "/readyz")
        self.assertEqual((code, doc["status"]), (503, "loading"))
        self.assertEqual(self.call(url, "/v1/audio/transcriptions", self.ok_fields())[1]["error"]["type"], "not_ready")
        loading.join()
        code, doc = self.call(url, "/readyz")
        self.assertEqual((code, doc["status"], doc["deployment_id"]), (200, "ready", MANIFEST["deployment_id"]))

    def test_transcription_contract_and_determinism(self):
        url, st, loading = self.start(FakeTranscriber())
        loading.join()
        code, doc = self.call(url, "/v1/audio/transcriptions", self.ok_fields())
        self.assertEqual(code, 200)
        self.assertEqual(doc["text"], f"Texte {SR}.")
        self.assertEqual(doc["flh"]["schema"], "flh_speaking_transcription_v1")
        self.assertEqual(doc["flh"]["status"], "transcribed")
        self.assertEqual(len(doc["flh"]["audio_sha256"]), 64)
        again = self.call(url, "/v1/audio/transcriptions", self.ok_fields())[1]
        self.assertEqual((again["text"], again["flh"]["audio_sha256"]), (doc["text"], doc["flh"]["audio_sha256"]))
        self.assertEqual(self.call(url, "/audio/transcriptions", self.ok_fields())[0], 200)  # base URL without /v1

    def test_abstention_is_200_with_empty_text(self):
        url, st, loading = self.start(FakeTranscriber(result="no_speech"))
        loading.join()
        code, doc = self.call(url, "/v1/audio/transcriptions", self.ok_fields())
        self.assertEqual((code, doc["text"], doc["flh"]["status"]), (200, "", "no_speech"))

    def test_request_refusals(self):
        url, st, loading = self.start(FakeTranscriber(), limits={"max_request_bytes": 200_000, "max_audio_seconds": 3.0})
        loading.join()
        f = self.ok_fields()
        cases = [
            ({**f, "model": "whisper-1"}, 400, "unknown_model"),
            ({k: v for k, v in f.items() if k != "file"}, 400, "invalid_request"),
            ({**f, "response_format": "verbose_json"}, 400, "invalid_request"),
            ({**f, "language": "en"}, 400, "invalid_request"),
            ({**f, "prompt": "Bonjour"}, 400, "invalid_request"),
            ({**f, "file": b"not audio at all"}, 415, "unsupported_audio"),
            ({**f, "file": audio.to_wav_pcm16(tone(4.0))}, 422, "audio_too_long"),
            ({**f, "file": audio.to_wav_pcm16(tone(7.0))}, 413, "request_too_large"),
        ]
        for fields, code, kind in cases:
            got = self.call(url, "/v1/audio/transcriptions", fields)
            self.assertEqual((got[0], got[1]["error"]["type"]), (code, kind), kind)
        self.assertEqual(self.call(url, "/v1/audio/transcriptions", raw=b"{}", ctype="application/json")[0], 415)
        self.assertEqual(self.call(url, "/v1/other", self.ok_fields())[0], 404)
        self.assertGreaterEqual(st.counters["refused"], 8)

    def test_busy_and_timeout(self):
        url, st, loading = self.start(FakeTranscriber(delay=0.6), max_waiting=0)
        loading.join()
        results = []
        ts = [threading.Thread(target=lambda: results.append(self.call(url, "/v1/audio/transcriptions", self.ok_fields()))) for _ in range(3)]
        for t in ts:
            t.start()
            time.sleep(0.05)
        for t in ts:
            t.join()
        codes = sorted(c for c, _ in results)
        self.assertEqual(codes.count(200), 1)
        self.assertEqual(codes.count(429), 2)
        url2, st2, l2 = self.start(FakeTranscriber(raise_timeout=True))
        l2.join()
        code, doc = self.call(url2, "/v1/audio/transcriptions", self.ok_fields())
        self.assertEqual((code, doc["error"]["type"]), (504, "timeout"))

    def test_deadline_counts_from_arrival_and_is_published(self):
        # A queued request's wait counts: it answers 504 when its time runs out
        # waiting, without ever reaching the model.
        fake = FakeTranscriber(delay=0.8)
        url, st, loading = self.start(fake, limits={"inference_timeout_s": 0.4}, max_waiting=1)
        loading.join()
        self.assertEqual(st.manifest["limits"]["inference_timeout_s"], 0.4)  # /manifest shows the limit in force
        results = []
        ts = [threading.Thread(target=lambda: results.append(self.call(url, "/v1/audio/transcriptions", self.ok_fields()))) for _ in range(2)]
        for t in ts:
            t.start()
            time.sleep(0.1)
        for t in ts:
            t.join()
        self.assertEqual(sorted(c for c, _ in results), [200, 504])
        self.assertEqual(fake.calls, 1)
        self.assertEqual(next(d for c, d in results if c == 504)["error"]["type"], "timeout")
        self.assertEqual(st.counters["timeouts"], 1)
        with self.assertRaises(ValueError):
            service.serve("unused", "127.0.0.1", 0, inference_timeout=0)

    def test_no_temporary_files_and_no_content_in_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("TMPDIR")
            os.environ["TMPDIR"] = tmp
            tempfile.tempdir = None
            r, w = os.pipe()
            saved = os.dup(2)
            os.dup2(w, 2)
            try:
                url, st, loading = self.start(FakeTranscriber())
                loading.join()
                self.call(url, "/v1/audio/transcriptions", self.ok_fields())
                self.call(url, "/v1/audio/transcriptions", {**self.ok_fields(), "file": b"RIFF....WAVEbroken"})
                self.call(url, "/v1/audio/transcriptions", {**self.ok_fields(), "model": "x"})
                sys.stderr.flush()
            finally:
                os.dup2(saved, 2)
                os.close(w)
                os.close(saved)
                if old is None:
                    os.environ.pop("TMPDIR", None)
                else:
                    os.environ["TMPDIR"] = old
                tempfile.tempdir = None
            logs = os.read(r, 1 << 20).decode()
            os.close(r)
            self.assertEqual(os.listdir(tmp), [])
        self.assertIn('"status": 200', logs)
        self.assertNotIn("Texte", logs)  # no transcript text
        self.assertNotIn("not-a-secret", logs)  # no Authorization header
        self.assertNotIn("RIFF", logs)

    def test_bind_policy(self):
        for host in ("8.8.8.8", "0.0.0.0", "::"):
            with self.assertRaises(ValueError):
                service.check_host(host, container=False)
        service.check_host("0.0.0.0", container=True)
        with self.assertRaises(ValueError):
            service.check_host("8.8.8.8", container=True)
        service.check_host("127.0.0.1")
        service.check_host("192.168.1.10")


if __name__ == "__main__":
    unittest.main()
