package http

import (
	"errors"
	"net/http"
	"strconv"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// Revisions of an imported authored script (ARCHITECTURE.md §4.3, A.15). A
// pack correction is never applied silently: the learner reads a preview and
// confirms it, and the update appends the next revision. Earlier revisions and
// the Mistake Notebook records saved from them are never changed. No route
// here calls a provider; only the confirmation writes.

// listeningScriptStateResponse: pack_fingerprint is null when the server's
// pack no longer has the script.
type listeningScriptStateResponse struct {
	ScriptID        string  `json:"script_id"`
	Revision        int     `json:"revision"`
	Fingerprint     string  `json:"fingerprint"`
	PackStatus      string  `json:"pack_status"`
	PackFingerprint *string `json:"pack_fingerprint"`
}

func toListeningScriptState(s application.ListeningScriptState) listeningScriptStateResponse {
	return listeningScriptStateResponse{ScriptID: s.ScriptID, Revision: s.Revision, Fingerprint: s.Fingerprint, PackStatus: s.PackStatus,
		PackFingerprint: optionalString(s.PackFingerprint)}
}

type listeningScriptPreviewResponse struct {
	MaterialID         int64                         `json:"material_id"`
	ScriptID           string                        `json:"script_id"`
	CurrentRevision    int                           `json:"current_revision"`
	CurrentFingerprint string                        `json:"current_fingerprint"`
	PackStatus         string                        `json:"pack_status"`
	PackFingerprint    string                        `json:"pack_fingerprint"`
	NextRevision       *int                          `json:"next_revision"`
	Changes            domain.ListeningScriptChanges `json:"changes"`
}

func toListeningScriptPreview(p *application.ListeningScriptUpdatePreview) listeningScriptPreviewResponse {
	out := listeningScriptPreviewResponse{MaterialID: p.MaterialID, ScriptID: p.State.ScriptID, CurrentRevision: p.State.Revision,
		CurrentFingerprint: p.State.Fingerprint, PackStatus: p.State.PackStatus, PackFingerprint: p.State.PackFingerprint, Changes: p.Changes}
	if p.State.PackStatus == domain.ListeningScriptUpdateAvailable {
		out.NextRevision = positiveInt(p.State.Revision + 1)
	}
	return out
}

func positiveInt(n int) *int {
	if n <= 0 {
		return nil
	}
	return &n
}

// handleListeningScriptUpdatePreview compares an imported script's current
// revision with the server's pack, line by line and question by question.
// Read-only. 200 (pack_status up_to_date, update_available or title_changed);
// 400 invalid id; 404 unknown lesson; 409 not_authored_script (YouTube) or
// script_not_in_pack.
func (h *Handler) handleListeningScriptUpdatePreview(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	preview, err := h.listening.ScriptUpdatePreview(r.Context(), id)
	if err != nil {
		writeListeningError(w, err, "compare the script with the pack")
		return
	}
	writeJSON(w, http.StatusOK, toListeningScriptPreview(preview))
}

// updateListeningScriptRequest is the preview the learner confirmed.
type updateListeningScriptRequest struct {
	FromRevision    int    `json:"from_revision"`
	PackFingerprint string `json:"pack_fingerprint"`
}

// handleListeningScriptUpdate is the explicit, confirmed update. It appends
// the next revision (lines and authored exercise, one transaction) and
// returns the lesson. 201 updated; 200 the lesson already has the pack's
// content (repeated, concurrent or resent confirmation; nothing written;
// Idempotency-Replayed: true); 400 invalid JSON; 404 unknown lesson; 409
// stale_preview (the lesson or the pack changed since the preview; the body
// carries a fresh preview), not_authored_script, script_not_in_pack or
// script_title_changed; 422 malformed confirmation. Every refusal writes
// nothing.
func (h *Handler) handleListeningScriptUpdate(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	var req updateListeningScriptRequest
	if !decodeListening(w, r, &req) {
		return
	}
	res, replay, err := h.listening.UpdateScript(r.Context(), id, req.FromRevision, req.PackFingerprint)
	var stale *application.ListeningScriptStaleError
	if errors.As(err, &stale) {
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "stale_preview", "preview": toListeningScriptPreview(stale.Preview)})
		return
	}
	if err != nil {
		writeListeningError(w, err, "update the listening script")
		return
	}
	status := http.StatusCreated
	if replay {
		status = http.StatusOK
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, status, map[string]any{"revision": res.Revision, "replayed": replay, "lesson": h.toListeningLesson(res.Lesson)})
}

// handleGetListeningScriptRevision reads one revision of an imported script:
// its lines and its authored exercise (with the key, like a lesson read), e.g.
// the revision a Mistake Notebook record was saved from. Read-only. 200; 400
// invalid id or revision; 404 unknown lesson or revision; 409
// not_authored_script.
func (h *Handler) handleGetListeningScriptRevision(w http.ResponseWriter, r *http.Request) {
	if h.listeningUnavailable(w) {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	n, err := strconv.Atoi(r.PathValue("revision"))
	if err != nil || n < 1 {
		writeError(w, http.StatusBadRequest, "invalid revision")
		return
	}
	rev, current, err := h.listening.GetScriptRevision(r.Context(), id, n)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "listening script revision not found")
		return
	}
	if err != nil {
		writeListeningError(w, err, "read the listening script revision")
		return
	}
	t := rev.Transcript
	writeJSON(w, http.StatusOK, map[string]any{
		"material_id": id, "revision": rev.Revision, "current_revision": current, "fingerprint": rev.Fingerprint,
		"transcript": listeningTranscriptResponse{ID: t.ID, Version: t.Version, HasTimestamps: t.HasTimestamps, Segments: t.Segments, CreatedAt: ts(t.CreatedAt)},
		"exercise":   toListeningExercise(rev.Exercise, true),
	})
}
