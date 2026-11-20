package http

import (
	"context"
	"errors"
	"net/http"
	"strconv"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// ListeningRevisionStudio is the revision studio capability of the listening
// service (private workbench). A listening service without it answers 503 on
// these routes; the public demo never reaches them (allowlist).
type ListeningRevisionStudio interface {
	ListScriptRevisions(ctx context.Context, materialID int64) (*application.ListeningRevisionHistory, error)
	CompareScriptRevisions(ctx context.Context, materialID int64, from, to int) (*application.ListeningRevisionComparison, error)
	ScriptRestorePreview(ctx context.Context, materialID int64, target int) (*application.ListeningRestorePreview, error)
	RestoreScript(ctx context.Context, materialID int64, fromRevision, target int, targetFingerprint string) (*application.ListeningRestoreResult, bool, error)
}

func (h *Handler) registerRevisionStudioRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /listening/materials/{id}/revisions", h.handleListScriptRevisions)
	mux.HandleFunc("GET /listening/materials/{id}/revision-compare", h.handleCompareScriptRevisions)
	mux.HandleFunc("GET /listening/materials/{id}/restore", h.handleScriptRestorePreview)
	mux.HandleFunc("POST /listening/materials/{id}/restore", h.handleRestoreScript)
}

func (h *Handler) revisionStudio(w http.ResponseWriter) (ListeningRevisionStudio, bool) {
	if h.listeningUnavailable(w) {
		return nil, false
	}
	studio, ok := h.listening.(ListeningRevisionStudio)
	if !ok {
		writeError(w, http.StatusServiceUnavailable, "the revision studio is not available on this server")
		return nil, false
	}
	return studio, true
}

// linkedRecord is a Mistake Notebook record saved from one revision's exercise.
type linkedRecord struct {
	EntryID       int64 `json:"entry_id"`
	Item          int   `json:"item"`
	InReviewToday bool  `json:"in_review_today"`
}

// linkedRecords maps exercise ID → the notebook records saved from it. nil
// (JSON null) when this server has no notebook: unknown, not "none".
func (h *Handler) linkedRecords(ctx context.Context) (map[int64][]linkedRecord, error) {
	if h.notebook == nil {
		return nil, nil
	}
	items, err := h.notebook.ListItems(ctx, "listening", false)
	if err != nil {
		return nil, err
	}
	out := map[int64][]linkedRecord{}
	for _, it := range items {
		if it.Source.Ref.Type != domain.SourceListeningItem {
			continue
		}
		ex := it.Source.Ref.RecordID // the exercise the record was saved from, as stored
		out[ex] = append(out[ex], linkedRecord{EntryID: it.Source.EntryID, Item: it.Source.Ref.Item, InReviewToday: it.Mark != nil && it.Mark.Marked})
	}
	return out, nil
}

func recordsFor(all map[int64][]linkedRecord, exerciseID int64) []linkedRecord {
	if all == nil {
		return nil
	}
	if rows := all[exerciseID]; rows != nil {
		return rows
	}
	return []linkedRecord{}
}

type revisionRef struct {
	Revision    int    `json:"revision"`
	Fingerprint string `json:"fingerprint"`
	ExerciseID  int64  `json:"exercise_id"`
	CreatedAt   string `json:"created_at"`
}

func refOf(r domain.ListeningScriptRevision) revisionRef {
	return revisionRef{Revision: r.Revision, Fingerprint: r.Fingerprint, ExerciseID: r.Exercise.ID, CreatedAt: ts(r.Transcript.CreatedAt)}
}

// handleListScriptRevisions lists every stored revision of an imported
// script with what belongs to it: its lines (transcript version), its
// authored exercise and answer key (exercise and generator), its audio (an
// authored script has none) and the notebook records saved from it.
// Read-only. 200; 404 unknown lesson; 409 not_authored_script.
func (h *Handler) handleListScriptRevisions(w http.ResponseWriter, r *http.Request) {
	studio, ok := h.revisionStudio(w)
	if !ok {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	hist, err := studio.ListScriptRevisions(r.Context(), id)
	if err != nil {
		writeListeningError(w, err, "list the script revisions")
		return
	}
	linked, err := h.linkedRecords(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read the notebook records linked to the revisions")
		return
	}
	rows := make([]map[string]any, 0, len(hist.Revisions))
	for _, rev := range hist.Revisions {
		questions := 0
		if rev.Exercise.Content != nil {
			questions = len(rev.Exercise.Content.Items)
		}
		rows = append(rows, map[string]any{
			"revision": rev.Revision, "current": rev.Revision == hist.State.Revision, "created_at": ts(rev.Transcript.CreatedAt),
			"fingerprint": rev.Fingerprint, "transcript_id": rev.Transcript.ID, "lines": len(rev.Transcript.Segments),
			"exercise_id": rev.Exercise.ID, "generator": rev.Exercise.Generator, "questions": questions,
			"audio": "none", "linked_records": recordsFor(linked, rev.Exercise.ID),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"material_id": hist.MaterialID, "title": hist.Title, "script_id": hist.State.ScriptID, "current_revision": hist.State.Revision,
		"pack_status": hist.State.PackStatus, "pack_fingerprint": optionalString(hist.State.PackFingerprint), "revisions": rows,
	})
}

func revisionParam(w http.ResponseWriter, r *http.Request, name string) (int, bool) {
	n, err := strconv.Atoi(r.URL.Query().Get(name))
	if err != nil || n < 1 {
		writeError(w, http.StatusBadRequest, name+" must be a revision number (1 or more)")
		return 0, false
	}
	return n, true
}

func comparisonJSON(c *application.ListeningRevisionComparison) map[string]any {
	return map[string]any{"material_id": c.MaterialID, "current_revision": c.Current, "from": refOf(c.From), "to": refOf(c.To),
		"blocks": c.Blocks, "changes": c.Changes}
}

// handleCompareScriptRevisions compares two stored revisions block by block
// (every line in order, word edits on changed lines) plus the question
// changes. Read-only. 200; 400 bad from/to; 404 unknown lesson or revision.
func (h *Handler) handleCompareScriptRevisions(w http.ResponseWriter, r *http.Request) {
	studio, ok := h.revisionStudio(w)
	if !ok {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	from, ok := revisionParam(w, r, "from")
	if !ok {
		return
	}
	to, ok := revisionParam(w, r, "to")
	if !ok {
		return
	}
	c, err := studio.CompareScriptRevisions(r.Context(), id, from, to)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "listening script revision not found")
		return
	}
	if err != nil {
		writeListeningError(w, err, "compare the script revisions")
		return
	}
	writeJSON(w, http.StatusOK, comparisonJSON(c))
}

func (h *Handler) restorePreviewJSON(ctx context.Context, p *application.ListeningRestorePreview) (map[string]any, error) {
	linked, err := h.linkedRecords(ctx)
	if err != nil {
		return nil, err
	}
	out := comparisonJSON(p.Comparison)
	out["target_revision"] = p.Comparison.To.Revision
	out["target_fingerprint"] = p.Comparison.To.Fingerprint
	out["next_revision"] = positiveInt(p.NextRevision)
	out["blocked"] = optionalString(p.Blocked)
	// What adopting the target changes outside the script: the lesson's
	// current exercise moves to a new one; records saved from the current
	// revision keep its wording and are then shown as from an older revision.
	out["current_exercise_id"] = p.Comparison.From.Exercise.ID
	out["records_on_current"] = recordsFor(linked, p.Comparison.From.Exercise.ID)
	return out, nil
}

// handleScriptRestorePreview reads what restoring revision ?revision=N would
// change: the current revision against N, the revision a restore would
// append, and the records saved from the current revision. Read-only.
func (h *Handler) handleScriptRestorePreview(w http.ResponseWriter, r *http.Request) {
	studio, ok := h.revisionStudio(w)
	if !ok {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	n, ok := revisionParam(w, r, "revision")
	if !ok {
		return
	}
	p, err := studio.ScriptRestorePreview(r.Context(), id, n)
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "listening script revision not found")
		return
	}
	if err != nil {
		writeListeningError(w, err, "preview the restore")
		return
	}
	out, err := h.restorePreviewJSON(r.Context(), p)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not read the notebook records linked to the revisions")
		return
	}
	writeJSON(w, http.StatusOK, out)
}

type restoreScriptRequest struct {
	FromRevision int    `json:"from_revision"`
	Revision     int    `json:"revision"`
	Fingerprint  string `json:"fingerprint"`
}

// handleRestoreScript is the explicit, confirmed restore: revision N's lines
// and authored exercise appended as the next revision. 201 restored; 200 the
// current revision already has N's content (nothing written;
// Idempotency-Replayed: true); 404 unknown lesson or revision; 409
// stale_preview (the lesson changed since the preview; the body carries a
// fresh one) or not_authored_script; 422 malformed confirmation or N is
// current. Every refusal writes nothing.
func (h *Handler) handleRestoreScript(w http.ResponseWriter, r *http.Request) {
	studio, ok := h.revisionStudio(w)
	if !ok {
		return
	}
	id, ok := parseID(w, r)
	if !ok {
		return
	}
	var req restoreScriptRequest
	if !decodeListening(w, r, &req) {
		return
	}
	res, replay, err := studio.RestoreScript(r.Context(), id, req.FromRevision, req.Revision, req.Fingerprint)
	var stale *application.ListeningRestoreStaleError
	if errors.As(err, &stale) {
		preview, perr := h.restorePreviewJSON(r.Context(), stale.Preview)
		if perr != nil {
			writeError(w, http.StatusInternalServerError, "could not read the notebook records linked to the revisions")
			return
		}
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "stale_preview", "preview": preview})
		return
	}
	if errors.Is(err, domain.ErrNotFound) {
		writeError(w, http.StatusNotFound, "listening script revision not found")
		return
	}
	if err != nil {
		writeListeningError(w, err, "restore the script revision")
		return
	}
	status := http.StatusCreated
	if replay {
		status = http.StatusOK
		w.Header().Set("Idempotency-Replayed", "true")
	}
	writeJSON(w, status, map[string]any{"revision": res.Revision, "restored_from": res.RestoredFrom, "replayed": replay, "lesson": h.toListeningLesson(res.Lesson)})
}
