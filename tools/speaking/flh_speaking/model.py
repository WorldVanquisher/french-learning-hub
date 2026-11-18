"""Whisper transcription with explicit abstention (``flh_speaking_transcribe_v1``).

Decoding policy (part of the deployment identity):
* French is forced (``<|fr|><|transcribe|><|notimestamps|>``), greedy, no
  sampling, no prompt, no previous-text conditioning.
* Audio longer than 30 s is cut into windows of at most 30 s at the quietest
  30 ms frame of each window's last 5 s, and the window texts are joined.
* Abstention, never a fabricated transcript:
  - ``no_speech``: under ``MIN_SOUND_SECONDS`` of sound above -70 dBFS (the
    model is not run), or every window judged silent by Whisper's own rule
    (P(no-speech) > 0.6 and mean log-probability < -1.0), or only known
    phantom phrases (subtitle credits and similar) remain;
  - ``not_french``: language identification puts French under 0.2 while
    another language is above 0.6 (forced French would otherwise translate).
* Loop cut-off: when the last n tokens (1 <= n <= 10) have just occurred four
  times in a row, decoding of that window stops and three copies are removed
  (one is kept); the window gets ``repetitive_output``.
* Warnings (the transcript is still returned for the learner to check):
  ``low_confidence`` (mean log-probability < -1.0 in a kept window),
  ``repetitive_output`` (gzip compression ratio > 2.4), ``possibly_not_french``
  (P(French) < 0.5), ``phantom_phrase_removed``.
"""

from __future__ import annotations

import gzip
import os
import re
import time
from dataclasses import dataclass, field

import numpy as np

from . import audio, textnorm

DECODING = "flh_speaking_transcribe_v1"
WINDOW_SECONDS = 30.0
SEARCH_SECONDS = 5.0
MIN_SOUND_SECONDS = 0.3
NO_SPEECH_PROB = 0.6
LOGPROB_THRESHOLD = -1.0
COMPRESSION_THRESHOLD = 2.4
NOT_FRENCH_FR_MAX = 0.2
NOT_FRENCH_OTHER_MIN = 0.6
POSSIBLY_NOT_FRENCH = 0.5
MAX_NEW_TOKENS = 220
LOOP_REPEATS = 4
LOOP_MAX_NGRAM = 10

# Normalized (flh_fr_asr_norm_v1) phrases Whisper is known to emit on silence or
# music in French: subtitle credits and channel sign-offs from its training data.
PHANTOM = [
    re.compile(p)
    for p in (
        r"sous titres? (?:r[ée]alis[ée]s? |fait )?(?:par|pour) .*",
        r".*\bamara org\b.*",
        r"merci d' avoir regard[ée] .*",
        r"abonnez vous .*",
        r"sous titrage .*",
        r".*\bst' 501\b.*",
    )
]


@dataclass
class Result:
    status: str  # transcribed | no_speech | not_french
    text: str
    warnings: list[str] = field(default_factory=list)
    windows: list[dict] = field(default_factory=list)
    language: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    seconds_model: float = 0.0


def phantom(text: str) -> bool:
    n = textnorm.normalize_fr(text)
    return bool(n) and any(p.fullmatch(n) for p in PHANTOM)


def loop_cut(toks: list[int]) -> int:
    """Number of tokens to drop when the sequence just ended in LOOP_REPEATS
    consecutive copies of an n-gram (n <= LOOP_MAX_NGRAM); 0 otherwise."""
    for n in range(1, LOOP_MAX_NGRAM + 1):
        if len(toks) < LOOP_REPEATS * n:
            break
        tail = toks[-n:]
        if all(toks[-(k + 1) * n:len(toks) - k * n] == tail for k in range(1, LOOP_REPEATS)):
            return (LOOP_REPEATS - 1) * n
    return 0


def compression_ratio(text: str) -> float:
    b = text.encode("utf-8")
    return len(b) / max(1, len(gzip.compress(b, mtime=0))) if b else 0.0


def windows(samples: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) sample ranges of at most WINDOW_SECONDS, cut at quiet frames."""
    sr, n = audio.SAMPLE_RATE, len(samples)
    win, search = int(WINDOW_SECONDS * sr), int(SEARCH_SECONDS * sr)
    out, start = [], 0
    while n - start > win:
        lo = start + win - search
        db = audio.frame_db(samples[lo:start + win])
        cut = lo + int(np.argmin(db)) * audio.FRAME + audio.FRAME // 2
        out.append((start, cut))
        start = cut
    out.append((start, n))
    return out


class Transcriber:
    def __init__(self, model_dir: str, *, threads: int = 4):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        torch.set_num_threads(threads)
        self.torch = torch
        t0 = time.monotonic()
        self.processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=True)
        self.model = WhisperForConditionalGeneration.from_pretrained(
            model_dir, local_files_only=True, use_safetensors=True, torch_dtype=torch.float32)
        self.model.eval()
        self.load_seconds = time.monotonic() - t0
        tok = self.processor.tokenizer
        ids = tok.convert_tokens_to_ids
        self.sot, self.fr, self.eot = ids("<|startoftranscript|>"), ids("<|fr|>"), tok.eos_token_id
        self.transcribe_id, self.notimestamps = ids("<|transcribe|>"), ids("<|notimestamps|>")
        nospeech = [t for t in ("<|nospeech|>", "<|nocaptions|>") if t in tok.get_vocab()]
        self.nospeech = ids(nospeech[0])
        self.lang_ids = {t[2:-2]: i for t, i in tok.get_vocab().items()
                         if re.fullmatch(r"<\|[a-z]{2,3}\|>", t)}
        self.lang_ids = {k: v for k, v in self.lang_ids.items() if self.sot < v < self.transcribe_id - 1}

    # -- one batch of <= 30 s windows --------------------------------------
    def _suppressed(self):
        if not hasattr(self, "_supp"):
            torch = self.torch
            gc = self.model.generation_config
            v = self.model.config.vocab_size
            always = set(getattr(gc, "suppress_tokens", None) or [])
            always |= set(range(self.eot + 1, v))  # every special and timestamp token; EOT stays allowed
            begin = set(getattr(gc, "begin_suppress_tokens", None) or []) | {self.eot}
            self._supp = (torch.tensor(sorted(t for t in always if t < v)), torch.tensor(sorted(t for t in begin if t < v)))
        return self._supp

    def _batch(self, chunks: list[np.ndarray], deadline: float | None = None) -> list[dict]:
        """Greedy decoding with KV cache: one encoder pass; language and no-speech
        probabilities are read at the start-of-transcript position (as in OpenAI's
        reference decoder); then the forced French prompt; then greedy tokens."""
        torch = self.torch
        feats = self.processor.feature_extractor(chunks, sampling_rate=audio.SAMPLE_RATE, return_tensors="pt").input_features
        n = len(chunks)
        always, begin = self._suppressed()
        names = [k for k, _ in sorted(self.lang_ids.items(), key=lambda kv: kv[1])]
        lang_idx = torch.tensor([self.lang_ids[k] for k in names])
        with torch.inference_mode():
            enc = (self.model.model.encoder(feats).last_hidden_state,)
            out = self.model(encoder_outputs=enc, decoder_input_ids=torch.full((n, 1), self.sot), use_cache=True)
            first = out.logits[:, -1, :].float()
            p_nospeech = torch.softmax(first, dim=-1)[:, self.nospeech]
            lang_p = torch.softmax(first[:, lang_idx], dim=-1)
            prompt = torch.tensor([[self.fr, self.transcribe_id, self.notimestamps]] * n)
            out = self.model(encoder_outputs=enc, decoder_input_ids=prompt, past_key_values=out.past_key_values, use_cache=True)
            past, logits = out.past_key_values, out.logits[:, -1, :].float()
            toks = [[] for _ in range(n)]
            lps = [[] for _ in range(n)]
            looped = [False] * n
            done = torch.zeros(n, dtype=torch.bool)
            for step in range(MAX_NEW_TOKENS + 1):
                if deadline is not None and time.monotonic() > deadline:
                    raise TimeoutError("transcription exceeded its time limit")
                logits[:, always] = -float("inf")
                if step == 0:
                    logits[:, begin] = -float("inf")
                logp = torch.log_softmax(logits, dim=-1)
                if step == MAX_NEW_TOKENS:
                    nxt = torch.full((n,), self.eot)
                else:
                    nxt = torch.argmax(logp, dim=-1)
                for i in range(n):
                    if not done[i]:
                        lps[i].append(float(logp[i, nxt[i]]))
                        if int(nxt[i]) == self.eot:
                            done[i] = True
                        else:
                            toks[i].append(int(nxt[i]))
                            cut = loop_cut(toks[i])
                            if cut:
                                del toks[i][-cut:]
                                looped[i] = True
                                done[i] = True
                if bool(done.all()):
                    break
                nxt = torch.where(done, torch.full_like(nxt, self.eot), nxt)
                out = self.model(encoder_outputs=enc, decoder_input_ids=nxt[:, None], past_key_values=past, use_cache=True)
                past, logits = out.past_key_values, out.logits[:, -1, :].float()
        fr_i = names.index("fr")
        res = []
        for b in range(n):
            text = self.processor.tokenizer.decode(toks[b], skip_special_tokens=True, clean_up_tokenization_spaces=False).strip()
            top = int(torch.argmax(lang_p[b]))
            res.append({
                "text": text,
                "tokens": len(toks[b]),
                "avg_logprob": round(sum(lps[b]) / len(lps[b]), 4) if lps[b] else 0.0,
                "no_speech_prob": round(float(p_nospeech[b]), 4),
                "p_fr": round(float(lang_p[b, fr_i]), 4),
                "top_language": names[top],
                "p_top_language": round(float(lang_p[b, top]), 4),
                "compression_ratio": round(compression_ratio(text), 3),
                "hit_token_limit": len(toks[b]) >= MAX_NEW_TOKENS,
                "loop_cut": looped[b],
            })
        return res

    # -- public -------------------------------------------------------------
    def raw(self, batch: list[np.ndarray]) -> list[dict]:
        """Model output only (no abstention), for <= 30 s clips; used by evaluation."""
        return self._batch(batch)

    def transcribe(self, samples: np.ndarray, *, quality: dict | None = None, deadline: float | None = None) -> Result:
        q = quality or audio.quality(samples)
        if q["sound_seconds"] < MIN_SOUND_SECONDS:
            return Result("no_speech", "", ["no_sound"], [], {}, q, 0.0)
        t0 = time.monotonic()
        spans = windows(samples)
        outs = []
        for i in range(0, len(spans), 4):
            outs += self._batch([samples[a:b] for a, b in spans[i:i + 4]], deadline)
        for (a, b), o in zip(spans, outs):
            o["start_s"], o["end_s"] = round(a / audio.SAMPLE_RATE, 3), round(b / audio.SAMPLE_RATE, 3)
        return decide(outs, q, time.monotonic() - t0)


def decide(outs: list[dict], q: dict, secs: float = 0.0) -> Result:
    """Apply the abstention and warning rules to the model output of each window."""
    if q["sound_seconds"] < MIN_SOUND_SECONDS:
        return Result("no_speech", "", ["no_sound"], [], {}, q, secs)
    warnings: list[str] = []
    first = outs[0]
    lang = {"p_fr": first["p_fr"], "top": first["top_language"], "p_top": first["p_top_language"]}
    if first["p_fr"] < NOT_FRENCH_FR_MAX and first["top_language"] != "fr" and first["p_top_language"] > NOT_FRENCH_OTHER_MIN:
        return Result("not_french", "", [f"detected_{first['top_language']}"], outs, lang, q, secs)
    if first["p_fr"] < POSSIBLY_NOT_FRENCH:
        warnings.append("possibly_not_french")
    kept = []
    for o in outs:
        silent = o["no_speech_prob"] > NO_SPEECH_PROB and o["avg_logprob"] < LOGPROB_THRESHOLD
        o["kept"] = False
        if silent or not o["text"]:
            continue
        if phantom(o["text"]):
            warnings.append("phantom_phrase_removed")
            continue
        if o["avg_logprob"] < LOGPROB_THRESHOLD:
            warnings.append("low_confidence")
        if o["compression_ratio"] > COMPRESSION_THRESHOLD or o["hit_token_limit"] or o.get("loop_cut"):
            warnings.append("repetitive_output")
        o["kept"] = True
        kept.append(o["text"])
    if not kept:
        return Result("no_speech", "", sorted(set(warnings)) or ["model_heard_no_speech"], outs, lang, q, secs)
    return Result("transcribed", " ".join(kept).strip(), sorted(set(warnings)), outs, lang, q, secs)
