"""Owned loopback fixture for the existing HTTP embedding contract, not an index."""
from collections import Counter
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading


ROLES = {"document", "query"}
FAULTS = {"status", "malformed", "short", "duplicate-index", "wrong-dimension",
          "zero", "nonfinite", "reverse", "disconnect"}


def text_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def deterministic_vector(text, model, dimensions):
    """Exact-input mechanical vector; no tokenization or semantic similarity."""
    if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions < 1:
        raise ValueError("positive integer dimensions required")
    seed = json.dumps([model, text], ensure_ascii=False, separators=(",", ":")).encode()
    raw = hashlib.shake_256(seed).digest(dimensions)
    vector = [(byte - 127) / 128 for byte in raw]
    if not any(vector):
        vector[0] = 1.0
    return vector


@dataclass(frozen=True)
class Fault:
    kind: str = "status"
    status: int = 503
    gate: threading.Event | None = None

    def __post_init__(self):
        if self.kind not in FAULTS and self.kind != "none":
            raise ValueError("unknown fixture fault")
        if self.kind == "status" and not 400 <= self.status <= 599:
            raise ValueError("failure HTTP status required")


class FakeEmbeddings:
    """In-process controls; no HTTP admin endpoint, target URL or credentials.

    Register exact provider inputs with their role, then arm faults by 1-based
    request number. A gate holds that request after counters record receipt.
    Context exit releases gates and joins owned request/server threads.
    """

    def __init__(self, dimensions=8, gate_timeout=5):
        deterministic_vector("validation", "fixture", dimensions)
        if gate_timeout <= 0:
            raise ValueError("positive gate timeout required")
        self.dimensions = dimensions
        self.gate_timeout = gate_timeout
        self._condition = threading.Condition()
        self._roles = {}
        self._faults = {}
        self._events = []
        self._active = 0
        self._max_active = 0
        self._rejected = 0
        self._server = None
        self._thread = None
        self._started = False

    def register(self, text, role):
        if not isinstance(text, str) or role not in ROLES:
            raise ValueError("exact text and document/query role required")
        digest = text_digest(text)
        with self._condition:
            if digest in self._roles and self._roles[digest] != role:
                raise ValueError("input cannot have conflicting fixture roles")
            self._roles[digest] = role

    def arm(self, call, fault):
        if not isinstance(call, int) or isinstance(call, bool) or call < 1 or not isinstance(fault, Fault):
            raise ValueError("positive request ordinal and Fault required")
        with self._condition:
            if call <= len(self._events):
                raise ValueError("cannot change a received request")
            self._faults[call] = fault

    def wait_received(self, count, timeout=2):
        with self._condition:
            return self._condition.wait_for(lambda: len(self._events) >= count, timeout)

    def wait_idle(self, timeout=2):
        with self._condition:
            return self._condition.wait_for(lambda: self._active == 0, timeout)

    def snapshot(self):
        with self._condition:
            events = json.loads(json.dumps(self._events))
            return {"events": events, "requests": len(events), "active": self._active,
                    "max_active": self._max_active, "rejected_requests": self._rejected,
                    "attempted_texts": dict(Counter(role for event in events for role in event["roles"])),
                    "valid_response_texts": dict(Counter(
                        role for event in events if event["outcome"] == "valid-response"
                        for role in event["roles"]))}

    def _begin(self, model, texts):
        with self._condition:
            call = len(self._events) + 1
            fault = self._faults.get(call, Fault(kind="none"))
            digests = [text_digest(text) for text in texts]
            event = {"call": call, "model": model, "input_sha256": digests,
                     "roles": [self._roles.get(digest, "unclassified") for digest in digests],
                     "batch_size": len(texts), "fault": fault.kind, "outcome": "active",
                     "http_status": None, "reply_written": False}
            self._events.append(event)
            self._active += 1
            self._max_active = max(self._max_active, self._active)
            self._condition.notify_all()
            return event, fault

    def _update(self, event, **values):
        with self._condition:
            event.update(values)

    def _end(self, event):
        with self._condition:
            self._active -= 1
            self._condition.notify_all()

    @property
    def base_url(self):
        if self._server is None:
            raise RuntimeError("fixture is not running")
        return f"http://127.0.0.1:{self._server.server_port}"

    def __enter__(self):
        if self._started:
            raise RuntimeError("fixture contexts cannot be reused")
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, *_):
                pass  # Do not log headers, credentials, request bodies or caller URLs.

            def reply(self, status, body):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.path != "/embeddings" or not 0 < length <= 1 << 20:
                        raise ValueError("invalid request boundary")
                    request = json.loads(self.rfile.read(length))
                    model, texts = request["model"], request["input"]
                    if not isinstance(model, str) or not model or not isinstance(texts, list):
                        raise ValueError("invalid request types")
                    if not texts or not all(isinstance(text, str) for text in texts):
                        raise ValueError("nonempty string batch required")
                except (ValueError, KeyError, TypeError, OSError):
                    with fixture._condition:
                        fixture._rejected += 1
                    self.reply(400, b'{"error":{"type":"fixture_invalid_request"}}')
                    return
                event, fault = fixture._begin(model, texts)
                try:
                    if fault.gate is not None and not fault.gate.wait(fixture.gate_timeout):
                        fixture._update(event, http_status=504)
                        fixture._update(event, outcome="gate-timeout")
                        self.reply(504, b'{"error":{"type":"fixture_gate_timeout"}}')
                        return
                    if fault.kind == "disconnect":
                        fixture._update(event, outcome="injected-disconnect")
                        self.close_connection = True
                        return
                    status = fault.status if fault.kind == "status" else 200
                    items = [{"index": index, "embedding": deterministic_vector(text, model, fixture.dimensions)}
                             for index, text in enumerate(texts)]
                    if fault.kind == "short":
                        items = items[:-1]
                    elif fault.kind == "duplicate-index":
                        items[-1]["index"] = -1 if len(items) == 1 else items[0]["index"]
                    elif fault.kind == "wrong-dimension":
                        items[-1]["embedding"].append(1.0)
                    elif fault.kind == "zero":
                        items[-1]["embedding"] = [0.0] * fixture.dimensions
                    elif fault.kind == "nonfinite":
                        items[-1]["embedding"][0] = float("nan")
                    elif fault.kind == "reverse":
                        items.reverse()
                    value = {"data": items} if status == 200 else {"error": {"type": "fixture_failure"}}
                    body = b"{broken" if fault.kind == "malformed" else json.dumps(value).encode()
                    fixture._update(event, http_status=status)
                    fixture._update(event, outcome="valid-response" if fault.kind in ("none", "reverse") else "injected-failure")
                    self.reply(status, body)
                    fixture._update(event, reply_written=True)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    fixture._update(event, outcome="client-disconnected")
                finally:
                    fixture._end(event)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.02})
        self._thread.start()
        self._started = True
        return self

    def __exit__(self, *_):
        with self._condition:
            for fault in self._faults.values():
                if fault.gate is not None:
                    fault.gate.set()
        self._server.shutdown()
        self._server.server_close()  # Joins non-daemon request handlers.
        self._thread.join(timeout=3)
        if self._thread.is_alive() or not self.wait_idle():
            raise RuntimeError("owned fixture thread did not exit")
        self._server = None
