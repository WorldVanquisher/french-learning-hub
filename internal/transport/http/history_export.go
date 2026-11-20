package http

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strings"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// HistoryExportService is the portable learning history capability
// (learning_history_export_v1, private workbench).
type HistoryExportService interface {
	Export(ctx context.Context, opts application.HistoryExportOptions) (*application.HistoryExport, error)
	PreviewImport(ctx context.Context, data []byte) (*application.HistoryImportPreview, error)
}

// WithHistoryExport enables the /learning-history routes. Without it they
// answer 503; the public demo never reaches them (allowlist).
func WithHistoryExport(service HistoryExportService) HandlerOption {
	return func(handler *Handler) { handler.history = service }
}

func (h *Handler) registerHistoryExportRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /learning-history/export-preview", h.handleHistoryExportPreview)
	mux.HandleFunc("GET /learning-history/export", h.handleHistoryExport)
	mux.HandleFunc("POST /learning-history/import-preview", h.handleHistoryImportPreview)
}

// historyOptions reads ?transcripts= and ?notes= (true/false). Audio and
// credentials are never exported, so asking for them is a 400, not a no-op.
func historyOptions(w http.ResponseWriter, r *http.Request) (application.HistoryExportOptions, bool) {
	q := r.URL.Query()
	var opts application.HistoryExportOptions
	for _, never := range []string{"audio", "credentials"} {
		if q.Has(never) {
			writeError(w, http.StatusBadRequest, never+" is never exported: audio is never stored, and credentials are never read")
			return opts, false
		}
	}
	for name, into := range map[string]*bool{"transcripts": &opts.Transcripts, "notes": &opts.Notes} {
		switch q.Get(name) {
		case "", "false":
		case "true":
			*into = true
		default:
			writeError(w, http.StatusBadRequest, name+" must be true or false")
			return opts, false
		}
	}
	return opts, true
}

func (h *Handler) historyUnavailable(w http.ResponseWriter) bool {
	if h.history == nil {
		writeError(w, http.StatusServiceUnavailable, "the learning history export is not available on this server")
		return true
	}
	return false
}

// historyFiles names what a download produces and how each file opens.
func historyFiles() []map[string]any {
	return []map[string]any{
		{"format": "ndjson", "extension": ".ndjson", "opens_as_text": true, "app_import": "preview_only",
			"description": "one JSON record per line, with a header and a checksummed footer; the app's import preview reads it"},
		{"format": "text", "extension": ".txt", "opens_as_text": true, "app_import": "none",
			"description": "a readable copy for any text editor; not importable"},
	}
}

// handleHistoryExportPreview says what an export with these options holds:
// the header (included, omitted, counts) and the footer. Read-only.
func (h *Handler) handleHistoryExportPreview(w http.ResponseWriter, r *http.Request) {
	if h.historyUnavailable(w) {
		return
	}
	opts, ok := historyOptions(w, r)
	if !ok {
		return
	}
	x, err := h.history.Export(r.Context(), opts)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not build the export")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"header": x.Header, "footer": x.Footer, "bytes": len(x.Body), "files": historyFiles()})
}

// handleHistoryExport downloads the export: NDJSON (default) or a readable
// text copy (?format=text). Read-only.
func (h *Handler) handleHistoryExport(w http.ResponseWriter, r *http.Request) {
	if h.historyUnavailable(w) {
		return
	}
	opts, ok := historyOptions(w, r)
	if !ok {
		return
	}
	format := r.URL.Query().Get("format")
	if format != "" && format != "ndjson" && format != "text" {
		writeError(w, http.StatusBadRequest, "format must be ndjson or text")
		return
	}
	x, err := h.history.Export(r.Context(), opts)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not build the export")
		return
	}
	if format == "text" {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.Header().Set("Content-Disposition", `attachment; filename="learning-history.txt"`)
		_, _ = io.WriteString(w, application.HistoryText(x))
		return
	}
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.Header().Set("Content-Disposition", `attachment; filename="learning-history.ndjson"`)
	_, _ = w.Write(x.Body)
}

// handleHistoryImportPreview reads an export file (the request body, at most
// HistoryPreviewMaxBytes) and compares it with the stored records. It never
// writes: there is no import.
func (h *Handler) handleHistoryImportPreview(w http.ResponseWriter, r *http.Request) {
	if h.historyUnavailable(w) {
		return
	}
	data, err := io.ReadAll(io.LimitReader(r.Body, application.HistoryPreviewMaxBytes+1))
	if err != nil {
		writeError(w, http.StatusBadRequest, "could not read the file")
		return
	}
	p, err := h.history.PreviewImport(r.Context(), data)
	if errors.Is(err, domain.ErrValidation) {
		writeError(w, http.StatusRequestEntityTooLarge, strings.TrimPrefix(err.Error(), domain.ErrValidation.Error()+": "))
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not compare the file with the stored records")
		return
	}
	rows := make([]map[string]any, 0, len(p.Rows))
	for _, row := range p.Rows {
		fields := row.Fields
		if fields == nil {
			fields = []string{}
		}
		rows = append(rows, map[string]any{"line": row.Line, "kind": row.Kind, "key": row.Key, "status": row.Status, "fields": fields, "resolution": row.Resolution})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"format": optionalString(p.Format), "integrity": p.Integrity, "problems": p.Problems, "counts": p.Counts, "missing_fields": p.Missing,
		"included": p.Included, "rows": rows, "new": p.New, "same": p.Same, "conflicts": p.Conflicts, "writes": false,
	})
}
