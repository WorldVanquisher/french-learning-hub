// Browser-side recording for Speaking v1. Everything here stays in the
// browser: a take is a Blob in memory, played back from an object URL. Nothing
// is uploaded while recording or playing back, and nothing is written to
// browser storage. Only an explicit "Send audio for transcription" reads the
// Blob as base64 for that one request.

// The audio types a take may have for transcription: formats both of the
// provider's pages list (see the backend's SpeakingAudioType). A browser that
// records only another type (e.g. ogg) can still record and play back.
const CANONICAL: Record<string, string> = {
  "audio/webm": "audio/webm",
  "audio/mp4": "audio/mp4",
  "audio/x-m4a": "audio/mp4",
  "audio/m4a": "audio/mp4",
  "audio/mpeg": "audio/mpeg",
  "audio/mp3": "audio/mpeg",
  "audio/wav": "audio/wav",
  "audio/x-wav": "audio/wav",
  "audio/wave": "audio/wav",
  "audio/vnd.wave": "audio/wav",
};

// canonicalAudioType maps a declared type (codec parameters ignored) to the
// accepted type, or null.
export function canonicalAudioType(declared: string): string | null {
  const media = declared.split(";")[0].trim().toLowerCase();
  return CANONICAL[media] ?? null;
}

export type RecordingSupport = "supported" | "unsupported";

// recordingSupport reports whether this browser can record here: it needs
// getUserMedia (only on a secure origin such as localhost) and MediaRecorder.
export function recordingSupport(): RecordingSupport {
  const nav = typeof navigator === "undefined" ? undefined : navigator;
  const hasMedia = !!nav?.mediaDevices && typeof nav.mediaDevices.getUserMedia === "function";
  const hasRecorder = typeof window !== "undefined" && typeof (window as { MediaRecorder?: unknown }).MediaRecorder === "function";
  return hasMedia && hasRecorder ? "supported" : "unsupported";
}

// preferredRecordingType picks the first accepted type this browser records.
export function preferredRecordingType(): string | undefined {
  const MR = (window as { MediaRecorder?: { isTypeSupported?: (t: string) => boolean } }).MediaRecorder;
  for (const t of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]) {
    if (MR?.isTypeSupported?.(t)) return t;
  }
  return undefined;
}

export type RecordingError = "denied" | "no_device" | "failed";

// classifyRecordingError separates a refused permission from a missing device
// and anything else, so each gets an honest message.
export function classifyRecordingError(e: unknown): RecordingError {
  const name = e && typeof e === "object" && "name" in e ? String((e as { name: unknown }).name) : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "denied";
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") return "no_device";
  return "failed";
}

export interface RecordedAudio {
  blob: Blob;
  mime: string; // as reported by the recorder or the file
  durationMs: number;
}

export interface ActiveRecording {
  stop: () => void;
  done: Promise<RecordedAudio>;
}

// startRecording asks for the microphone and records until stop() or maxMs.
// It rejects with the getUserMedia error (see classifyRecordingError).
export async function startRecording(maxMs: number, onTick?: (elapsedMs: number) => void): Promise<ActiveRecording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const type = preferredRecordingType();
  const recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream);
  const chunks: Blob[] = [];
  const started = performance.now();
  let timer: ReturnType<typeof setInterval> | undefined;
  const done = new Promise<RecordedAudio>((resolve, reject) => {
    recorder.ondataavailable = (ev: BlobEvent) => {
      if (ev.data && ev.data.size > 0) chunks.push(ev.data);
    };
    recorder.onerror = () => reject(new Error("recording failed"));
    recorder.onstop = () => {
      if (timer) clearInterval(timer);
      stream.getTracks().forEach((t) => t.stop());
      const mime = recorder.mimeType || type || chunks[0]?.type || "audio/webm";
      const durationMs = Math.min(Math.max(1, Math.round(performance.now() - started)), maxMs);
      resolve({ blob: new Blob(chunks, { type: mime }), mime, durationMs });
    };
  });
  recorder.start(250);
  timer = setInterval(() => {
    const elapsed = performance.now() - started;
    onTick?.(Math.min(elapsed, maxMs));
    if (elapsed >= maxMs && recorder.state === "recording") recorder.stop();
  }, 200);
  return {
    stop: () => {
      if (recorder.state === "recording") recorder.stop();
    },
    done,
  };
}

// measureDuration reads a file's duration from its metadata (null when the
// browser cannot tell).
export function measureDuration(blob: Blob): Promise<number | null> {
  return new Promise((resolve) => {
    if (typeof URL.createObjectURL !== "function" || typeof Audio === "undefined") {
      resolve(null);
      return;
    }
    const url = URL.createObjectURL(blob);
    const audio = new Audio();
    const finish = (ms: number | null) => {
      URL.revokeObjectURL(url);
      resolve(ms);
    };
    audio.preload = "metadata";
    audio.onloadedmetadata = () => finish(Number.isFinite(audio.duration) && audio.duration > 0 ? Math.round(audio.duration * 1000) : null);
    audio.onerror = () => finish(null);
    audio.src = url;
  });
}

// buffer reads a Blob's bytes. Blob.arrayBuffer is missing in some browsers
// (and in jsdom); FileReader exists everywhere and never stringifies the Blob.
function buffer(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error("could not read the audio"));
    reader.readAsArrayBuffer(blob);
  });
}

// sha256Hex is the take's audio digest; the server checks that the audio sent
// for transcription is this take's.
export async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await buffer(blob));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// base64Of encodes the audio for the one transcription request.
export async function base64Of(blob: Blob): Promise<string> {
  const data = new Uint8Array(await buffer(blob));
  let binary = "";
  for (let i = 0; i < data.length; i += 0x8000) binary += String.fromCharCode(...data.subarray(i, i + 0x8000));
  return btoa(binary);
}

// formatDuration shows m:ss.
export function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// formatBytes shows a size in KB or MB.
export function formatBytes(n: number): string {
  return n >= 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}
