package application

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"french-learning-app/internal/domain"
)

// Portable learning history (learning_history_export_v1, private workbench).
//
// An export is NDJSON: a header line, one line per record, and a footer that
// counts the records and carries the SHA-256 of their lines, so a reader can
// tell a complete file from a truncated or edited one. It is built from the
// stored records on request; nothing is stored about it.
//
//   - Audio bytes are never exported (none are stored) and no credential or
//     configuration value is ever read. Neither can be requested.
//   - Transcript texts and notes (Mistake Notebook record text and Writing
//     draft text) are included only when asked; otherwise each record says
//     "omitted", which is different from a record that has none ("absent").
//   - Each record has the server's own `ref` and a portable `key` built from
//     stable identities (prompt IDs, take and draft numbers, capture IDs,
//     pack script IDs), which the import preview matches on.
//
// The import preview reads a file and compares it with the stored records.
// It never writes. There is no import yet.

const (
	HistoryExportFormat        = "learning_history_export_v1"
	historySpeakingOlderFormat = "speaking_attempt_export_v1"
	// HistoryPreviewMaxBytes bounds an import preview's input.
	HistoryPreviewMaxBytes = 8 << 20
)

// Text states of a record's optional text.
const (
	TextIncluded = "included"
	TextOmitted  = "omitted" // exists, not selected for this export
	TextAbsent   = "absent"  // the record has no such text
)

// HistoryExportOptions selects the optional texts.
type HistoryExportOptions struct {
	Transcripts bool
	Notes       bool
}

type historyEntryReader interface {
	GetByID(ctx context.Context, id int64) (*domain.Entry, error)
}

type historyListeningReader interface {
	ListMaterials(ctx context.Context) ([]domain.ListeningMaterial, error)
	LatestTranscript(ctx context.Context, materialID int64) (*domain.ListeningTranscript, error)
}

// HistoryExportService builds exports and import previews. Any reader may be
// nil; that part is then absent and the header says so.
type HistoryExportService struct {
	speaking  weekSpeakingReader
	writing   weekWritingReader
	notebook  weekNotebookReader
	entries   historyEntryReader
	listening historyListeningReader
	now       func() time.Time
}

// NewHistoryExportService builds the service.
func NewHistoryExportService(s weekSpeakingReader, w weekWritingReader, n weekNotebookReader, e historyEntryReader, l historyListeningReader) *HistoryExportService {
	return &HistoryExportService{speaking: s, writing: w, notebook: n, entries: e, listening: l, now: func() time.Time { return time.Now().UTC() }}
}

// HistoryRecord is one exported record (one NDJSON line).
type HistoryRecord map[string]any

func (r HistoryRecord) str(k string) string { s, _ := r[k].(string); return s }

// HistoryExport is a built export.
type HistoryExport struct {
	Header  map[string]any
	Records []HistoryRecord
	Footer  map[string]any
	Body    []byte // the NDJSON file
}

func rfc(t time.Time) string {
	if t.IsZero() {
		return ""
	}
	return t.UTC().Format(time.RFC3339Nano)
}

func textField(rec HistoryRecord, field, text string, include bool) {
	switch {
	case text == "":
		rec[field+"_state"] = TextAbsent
	case include:
		rec[field], rec[field+"_state"] = text, TextIncluded
	default:
		rec[field+"_state"] = TextOmitted
	}
}

// records reads every record from the stored rows, in a stable order.
func (s *HistoryExportService) records(ctx context.Context, opts HistoryExportOptions) ([]HistoryRecord, map[string]any, error) {
	var out []HistoryRecord
	parts := map[string]any{"speaking": s.speaking != nil, "writing": s.writing != nil, "notebook": s.notebook != nil && s.entries != nil, "listening": s.listening != nil}
	if s.listening != nil {
		ms, err := s.listening.ListMaterials(ctx)
		if err != nil {
			return nil, nil, err
		}
		for _, m := range ms {
			rec := HistoryRecord{"kind": "listening_material", "ref": fmt.Sprintf("listening:material:%d", m.ID), "source_kind": m.SourceKind, "title": m.Title, "created_at": rfc(m.CreatedAt)}
			switch {
			case m.PackScriptID != "":
				rec["key"], rec["pack_script_id"] = "listening:script:"+m.PackScriptID, m.PackScriptID
			case m.VideoID != "":
				rec["key"], rec["video_id"] = "listening:video:"+m.VideoID, m.VideoID
			default:
				rec["key"] = "listening:material-created:" + rfc(m.CreatedAt)
			}
			tr, err := s.listening.LatestTranscript(ctx, m.ID)
			if err != nil {
				return nil, nil, err
			}
			rec["transcript_versions"] = 0
			if tr != nil {
				rec["transcript_versions"] = tr.Version
			}
			out = append(out, rec)
		}
	}
	if s.speaking != nil {
		exs, err := s.speaking.ListExercises(ctx)
		if err != nil {
			return nil, nil, err
		}
		for _, ex := range exs {
			takes, err := s.speaking.ListTakes(ctx, ex.ID)
			if err != nil {
				return nil, nil, err
			}
			transcripts, err := s.speaking.ListTranscripts(ctx, ex.ID)
			if err != nil {
				return nil, nil, err
			}
			for _, k := range takes {
				rec := HistoryRecord{"kind": "speaking_take", "ref": fmt.Sprintf("speaking:take:%d", k.ID),
					"key":      fmt.Sprintf("speaking:prompt:%s:take:%d", ex.PromptID, k.Number),
					"exercise": map[string]any{"ref": fmt.Sprintf("speaking:exercise:%d", ex.ID), "prompt_id": ex.PromptID, "title": ex.Title},
					"number":   k.Number, "audio_source": k.AudioSource, "audio_bytes_exported": false, "created_at": rfc(k.CreatedAt)}
				if k.AudioSource != domain.SpeakingAudioNone {
					rec["audio_mime"], rec["audio_size"], rec["audio_sha256"], rec["duration_ms"] = k.AudioMIME, k.AudioBytes, k.AudioSHA256, k.DurationMS
				}
				versions := []map[string]any{}
				for _, tr := range transcripts {
					if tr.TakeID != k.ID {
						continue
					}
					v := map[string]any{"version": tr.Version, "origin": tr.Origin, "word_count": tr.WordCount, "created_at": rfc(tr.CreatedAt)}
					if opts.Transcripts {
						v["text"] = tr.Text
					}
					versions = append(versions, v)
				}
				rec["transcripts"] = versions
				switch {
				case len(versions) == 0:
					rec["transcripts_state"] = TextAbsent
				case opts.Transcripts:
					rec["transcripts_state"] = TextIncluded
				default:
					rec["transcripts_state"] = TextOmitted
				}
				out = append(out, rec)
			}
		}
	}
	if s.writing != nil {
		tasks, err := s.writing.ListTasks(ctx)
		if err != nil {
			return nil, nil, err
		}
		for _, task := range tasks {
			drafts, err := s.writing.ListDrafts(ctx, task.ID)
			if err != nil {
				return nil, nil, err
			}
			taskKey := "writing:prompt:" + task.PromptID
			if task.PromptID == "" {
				taskKey = "writing:learner-task:" + rfc(task.CreatedAt)
			}
			for _, d := range drafts {
				rec := HistoryRecord{"kind": "writing_draft", "ref": fmt.Sprintf("writing:draft:%d", d.ID), "key": fmt.Sprintf("%s:draft:%d", taskKey, d.Version),
					"task":    map[string]any{"ref": fmt.Sprintf("writing:task:%d", task.ID), "title": task.Title, "origin": task.Origin, "prompt_id": task.PromptID},
					"version": d.Version, "word_count": d.WordCount, "created_at": rfc(d.CreatedAt)}
				textField(rec, "text", d.Text, opts.Notes)
				out = append(out, rec)
			}
		}
	}
	if s.notebook != nil && s.entries != nil {
		srcs, err := s.notebook.ListSources(ctx)
		if err != nil {
			return nil, nil, err
		}
		marks, err := s.notebook.CurrentMarks(ctx)
		if err != nil {
			return nil, nil, err
		}
		for _, src := range srcs {
			rec := HistoryRecord{"kind": "notebook_record", "ref": fmt.Sprintf("notebook:entry:%d", src.EntryID), "key": "notebook:capture:" + src.CaptureID,
				"capture_id": src.CaptureID, "saved_at": rfc(src.CreatedAt),
				"source_ref": map[string]any{"type": src.Ref.Type, "record_id": src.Ref.RecordID, "item": src.Ref.Item}}
			retry := map[string]any{"marked": false, "since": nil}
			if m, ok := marks[src.EntryID]; ok {
				retry["marked"], retry["since"] = m.Marked, rfc(m.At)
			}
			rec["retry"] = retry
			e, err := s.entries.GetByID(ctx, src.EntryID)
			if err != nil {
				return nil, nil, err
			}
			textField(rec, "original_input", e.OriginalInput, opts.Notes)
			textField(rec, "original_context", e.OriginalContext, opts.Notes)
			textField(rec, "attempt", src.Ref.Attempt, opts.Notes)
			out = append(out, rec)
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].str("kind") != out[j].str("kind") {
			return out[i].str("kind") < out[j].str("kind")
		}
		return out[i].str("key") < out[j].str("key")
	})
	return out, parts, nil
}

// Export builds the NDJSON export.
func (s *HistoryExportService) Export(ctx context.Context, opts HistoryExportOptions) (*HistoryExport, error) {
	recs, parts, err := s.records(ctx, opts)
	if err != nil {
		return nil, err
	}
	counts := map[string]int{}
	omitted := map[string]int{}
	for _, r := range recs {
		counts[r.str("kind")]++
		for _, f := range []string{"transcripts_state", "text_state", "original_input_state", "original_context_state", "attempt_state"} {
			if r.str(f) == TextOmitted {
				omitted[strings.TrimSuffix(f, "_state")]++
			}
		}
	}
	header := map[string]any{"kind": "header", "format": HistoryExportFormat, "exported_at": rfc(s.now()),
		"included":       map[string]any{"transcripts": opts.Transcripts, "notes": opts.Notes, "audio": false, "credentials": false},
		"never_exported": []string{"audio bytes (never stored)", "credentials and configuration (never read)"},
		"parts":          parts, "counts": counts, "omitted_texts": omitted}
	var body bytes.Buffer
	line := func(v any) []byte {
		b, _ := json.Marshal(v)
		return b
	}
	body.Write(line(header))
	body.WriteByte('\n')
	h := sha256.New()
	for i, r := range recs {
		b := line(r)
		if i > 0 {
			h.Write([]byte("\n"))
		}
		h.Write(b)
		body.Write(b)
		body.WriteByte('\n')
	}
	footer := map[string]any{"kind": "footer", "format": HistoryExportFormat, "records": len(recs), "sha256": hex.EncodeToString(h.Sum(nil))}
	body.Write(line(footer))
	body.WriteByte('\n')
	return &HistoryExport{Header: header, Records: recs, Footer: footer, Body: body.Bytes()}, nil
}

// HistoryText renders an export as plain text a person can read in any
// editor. It is not importable.
func HistoryText(x *HistoryExport) string {
	var b strings.Builder
	fmt.Fprintf(&b, "Learning history (%s), exported %v\n", HistoryExportFormat, x.Header["exported_at"])
	fmt.Fprintf(&b, "This text copy is for reading. The .ndjson file is the one the app's import preview reads.\n")
	fmt.Fprintf(&b, "Never exported: audio bytes (never stored), credentials and configuration.\n\n")
	for _, r := range x.Records {
		switch r.str("kind") {
		case "speaking_take":
			ex, _ := r["exercise"].(map[string]any)
			fmt.Fprintf(&b, "Speaking · %v · take %v (%v) · %v\n", ex["title"], r["number"], r["audio_source"], r["created_at"])
			for _, v := range r["transcripts"].([]map[string]any) {
				if t, ok := v["text"].(string); ok {
					fmt.Fprintf(&b, "  v%v (%v): %s\n", v["version"], v["origin"], t)
				} else {
					fmt.Fprintf(&b, "  v%v (%v): [text omitted]\n", v["version"], v["origin"])
				}
			}
		case "writing_draft":
			task, _ := r["task"].(map[string]any)
			fmt.Fprintf(&b, "Writing · %v · draft %v · %v\n", task["title"], r["version"], r["created_at"])
			if t, ok := r["text"].(string); ok {
				fmt.Fprintf(&b, "  %s\n", t)
			} else {
				fmt.Fprintf(&b, "  [text %s]\n", r.str("text_state"))
			}
		case "notebook_record":
			fmt.Fprintf(&b, "Mistake Notebook · %s · saved %v\n", r.str("capture_id"), r["saved_at"])
			if t, ok := r["original_input"].(string); ok {
				fmt.Fprintf(&b, "  %s\n", t)
			} else {
				fmt.Fprintf(&b, "  [note %s]\n", r.str("original_input_state"))
			}
		case "listening_material":
			fmt.Fprintf(&b, "Listening · %v · %v transcript version(s)\n", r["title"], r["transcript_versions"])
		}
	}
	fmt.Fprintf(&b, "\n%v records; SHA-256 of the record lines %v\n", x.Footer["records"], x.Footer["sha256"])
	return b.String()
}

// Import preview statuses.
const (
	PreviewNew      = "new"      // no stored record has this key
	PreviewSame     = "same"     // a stored record with this key matches
	PreviewConflict = "conflict" // a stored record with this key differs
)

// HistoryPreviewRow is one record of the file, compared with the store.
type HistoryPreviewRow struct {
	Line       int
	Kind       string
	Key        string
	Status     string
	Fields     []string // differing fields (conflict)
	Resolution string
}

// HistoryImportPreview is what the file holds and how it compares. It is a
// report only: nothing is written.
type HistoryImportPreview struct {
	Format      string // learning_history_export_v1, speaking_attempt_export_v1 (older), or ""
	Integrity   string // complete, truncated, corrupted, unchecked (older format), unreadable
	Problems    []string
	Counts      map[string]int
	Missing     []string // optional fields the file does not have (an older export)
	Rows        []HistoryPreviewRow
	New, Same   int
	Conflicts   int
	Included    map[string]any
	WritesNever bool
}

var comparedFields = map[string][]string{
	"listening_material": {"source_kind", "title", "pack_script_id", "video_id"},
	"speaking_take":      {"number", "audio_source", "audio_sha256", "audio_size", "duration_ms", "transcripts"},
	"writing_draft":      {"version", "word_count", "text"},
	"notebook_record":    {"capture_id", "source_ref", "original_input", "original_context", "attempt", "retry"},
}

func canon(v any) string {
	b, _ := json.Marshal(v)
	var x any
	_ = json.Unmarshal(b, &x)
	b, _ = json.Marshal(x)
	return string(b)
}

// diff compares the fields both sides carry. A text omitted on either side
// is not compared (it is reported as omitted, not as a difference).
func diff(kind string, in, stored HistoryRecord) []string {
	var out []string
	for _, f := range comparedFields[kind] {
		a, okA := in[f]
		b, okB := stored[f]
		if !okA || !okB {
			continue
		}
		if f == "transcripts" {
			a, b = stripTexts(a, b)
		}
		if canon(a) != canon(b) {
			out = append(out, f)
		}
	}
	return out
}

// stripTexts drops transcript texts unless both sides have them.
func stripTexts(a, b any) (any, any) {
	list := func(v any) []map[string]any {
		out := []map[string]any{} // null and [] are both "no version"
		raw, _ := json.Marshal(v)
		_ = json.Unmarshal(raw, &out)
		if out == nil {
			out = []map[string]any{}
		}
		return out
	}
	x, y := list(a), list(b)
	has := func(l []map[string]any) bool {
		for _, v := range l {
			if _, ok := v["text"]; ok {
				return true
			}
		}
		return false
	}
	both := has(x) && has(y)
	for _, l := range [][]map[string]any{x, y} {
		for _, v := range l {
			delete(v, "created_at") // formats differ between export versions; version numbers identify
			if !both {
				delete(v, "text")
			}
		}
	}
	return x, y
}

// PreviewImport reads an export file and compares it with the stored records.
func (s *HistoryExportService) PreviewImport(ctx context.Context, data []byte) (*HistoryImportPreview, error) {
	p := &HistoryImportPreview{Counts: map[string]int{}, Rows: []HistoryPreviewRow{}, Problems: []string{}, Missing: []string{}, WritesNever: true}
	if len(data) > HistoryPreviewMaxBytes {
		return nil, fmt.Errorf("%w: the file is larger than %d bytes", domain.ErrValidation, HistoryPreviewMaxBytes)
	}
	type line struct {
		n   int
		raw []byte
		rec HistoryRecord
	}
	var lines []line
	sc := bufio.NewScanner(bytes.NewReader(data))
	sc.Buffer(make([]byte, 0, 1<<20), HistoryPreviewMaxBytes)
	n := 0
	for sc.Scan() {
		n++
		raw := bytes.TrimSpace(sc.Bytes())
		if len(raw) == 0 {
			continue
		}
		var rec HistoryRecord
		if err := json.Unmarshal(raw, &rec); err != nil {
			p.Problems = append(p.Problems, fmt.Sprintf("line %d is not complete JSON", n))
			continue
		}
		lines = append(lines, line{n, append([]byte(nil), raw...), rec})
	}
	if err := sc.Err(); err != nil {
		p.Problems = append(p.Problems, "the file could not be read to the end: "+err.Error())
	}
	if len(lines) == 0 {
		p.Integrity = "unreadable"
		p.Problems = append(p.Problems, "no JSON line found")
		return p, nil
	}
	var records []line
	switch {
	case lines[0].rec.str("kind") == "header" && lines[0].rec.str("format") == HistoryExportFormat:
		p.Format = HistoryExportFormat
		p.Included, _ = lines[0].rec["included"].(map[string]any)
		last := lines[len(lines)-1]
		body := lines[1:]
		if last.rec.str("kind") == "footer" {
			body = lines[1 : len(lines)-1]
		}
		records = body
		h := sha256.New()
		for i, l := range body {
			if i > 0 {
				h.Write([]byte("\n"))
			}
			h.Write(l.raw)
		}
		switch {
		case last.rec.str("kind") != "footer":
			p.Integrity = "truncated"
			p.Problems = append(p.Problems, "the footer is missing: the file ends early")
		case int(toFloat(last.rec["records"])) != len(body) || len(p.Problems) > 0:
			p.Integrity = "truncated"
			p.Problems = append(p.Problems, fmt.Sprintf("the footer counts %v records; %d were read", last.rec["records"], len(body)))
		case last.rec.str("sha256") != hex.EncodeToString(h.Sum(nil)):
			p.Integrity = "corrupted"
			p.Problems = append(p.Problems, "the records do not match the footer's SHA-256: the file was changed after export")
		default:
			p.Integrity = "complete"
		}
	case lines[0].rec.str("schema_version") == historySpeakingOlderFormat:
		// An older Speaking export (GET /speaking/export): no header, footer
		// or checksum, and no notebook, writing or listening records.
		p.Format, p.Integrity = historySpeakingOlderFormat, "unchecked"
		if len(p.Problems) > 0 {
			p.Integrity = "truncated"
		}
		p.Missing = append(p.Missing, "header and checksum", "notebook records", "writing drafts", "listening material")
		for _, l := range lines {
			records = append(records, line{l.n, l.raw, olderSpeakingRecord(l.rec)})
		}
	default:
		p.Integrity = "unreadable"
		p.Problems = append(p.Problems, "the first line is not a learning_history_export_v1 header or a speaking_attempt_export_v1 line")
		return p, nil
	}
	current, _, err := s.records(ctx, HistoryExportOptions{Transcripts: true, Notes: true})
	if err != nil {
		return nil, err
	}
	byKey := map[string]HistoryRecord{}
	for _, r := range current {
		byKey[r.str("key")] = r
	}
	missing := map[string]bool{}
	for _, l := range records {
		kind, key := l.rec.str("kind"), l.rec.str("key")
		if kind == "" || key == "" {
			p.Problems = append(p.Problems, fmt.Sprintf("line %d has no kind or key", l.n))
			continue
		}
		p.Counts[kind]++
		for _, f := range comparedFields[kind] {
			if _, ok := l.rec[f]; !ok && !strings.HasSuffix(f, "text") && f != "original_input" && f != "original_context" && f != "attempt" {
				missing[kind+"."+f] = true
			}
		}
		row := HistoryPreviewRow{Line: l.n, Kind: kind, Key: key}
		stored, ok := byKey[key]
		switch {
		case !ok:
			row.Status, row.Resolution, p.New = PreviewNew, "not on this server; an import would add it (there is no import yet: nothing is written)", p.New+1
		default:
			if fields := diff(kind, l.rec, stored); len(fields) > 0 {
				row.Status, row.Fields, p.Conflicts = PreviewConflict, fields, p.Conflicts+1
				row.Resolution = "keep the stored record: stored records are append-only and are never overwritten; the file's version would be skipped"
			} else {
				row.Status, row.Resolution, p.Same = PreviewSame, "already stored; nothing to do", p.Same+1
			}
		}
		p.Rows = append(p.Rows, row)
	}
	fields := make([]string, 0, len(missing))
	for k := range missing {
		fields = append(fields, k)
	}
	sort.Strings(fields)
	p.Missing = append(p.Missing, fields...)
	return p, nil
}

func toFloat(v any) float64 { f, _ := v.(float64); return f }

// olderSpeakingRecord maps one speaking_attempt_export_v1 line onto a
// speaking_take record. Fields the older format lacks stay absent.
func olderSpeakingRecord(in HistoryRecord) HistoryRecord {
	ex, _ := in["exercise"].(map[string]any)
	take, _ := in["take"].(map[string]any)
	out := HistoryRecord{"kind": "speaking_take"}
	if ex == nil || take == nil {
		return out
	}
	out["key"] = fmt.Sprintf("speaking:prompt:%v:take:%v", ex["prompt_id"], take["number"])
	out["number"], out["audio_source"] = take["number"], take["audio_source"]
	if v, ok := take["audio_sha256"]; ok && v != nil {
		out["audio_sha256"] = v
	}
	if trs, ok := in["transcripts"].([]any); ok {
		versions := []map[string]any{}
		for _, t := range trs {
			m, _ := t.(map[string]any)
			v := map[string]any{"version": m["version"], "origin": m["origin"], "word_count": m["word_count"], "created_at": m["created_at"]}
			if txt, ok := m["text"]; ok {
				v["text"] = txt
			}
			versions = append(versions, v)
		}
		out["transcripts"] = versions
	}
	return out
}
