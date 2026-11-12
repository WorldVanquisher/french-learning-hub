package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"time"

	"french-learning-app/internal/domain"
)

// SpeakingRepository stores Speaking v1 records (migration 018). It never
// stores audio: a take keeps only its metadata. Exercises, takes,
// transcriptions, transcripts and feedback are inserted once and never
// updated; a request is inserted before the provider call and finished once,
// with its start rules applied inside one write transaction. It writes nothing
// to entries, analyses, Concepts, annotations or admission.
type SpeakingRepository struct {
	db *sql.DB
}

var _ domain.SpeakingRepository = (*SpeakingRepository)(nil)

// NewSpeakingRepository builds a repository over an open database.
func NewSpeakingRepository(db *sql.DB) *SpeakingRepository { return &SpeakingRepository{db: db} }

func (r *SpeakingRepository) beginWrite(ctx context.Context, table string) (*sql.Tx, error) {
	tx, err := r.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `UPDATE `+table+` SET rowid = rowid WHERE 0`); err != nil {
		_ = tx.Rollback()
		return nil, fmt.Errorf("take write lock: %w", err)
	}
	return tx, nil
}

func listIDs(ctx context.Context, q *sql.DB, query string, args ...any) ([]int64, error) {
	rows, err := q.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	return scanIDs(rows)
}

// ---- exercises ----

func readSpeakingExercise(ctx context.Context, q queryer, where string, args ...any) (domain.SpeakingExercise, error) {
	var e domain.SpeakingExercise
	var reqs, created string
	err := q.QueryRowContext(ctx, `SELECT id, prompt_id, title, situation, requirements, seconds_min, seconds_max, created_at FROM speaking_exercises WHERE `+where, args...).
		Scan(&e.ID, &e.PromptID, &e.Title, &e.Situation, &reqs, &e.SecondsMin, &e.SecondsMax, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return e, fmt.Errorf("%w: speaking exercise", domain.ErrNotFound)
	}
	if err != nil {
		return e, err
	}
	if err := json.Unmarshal([]byte(reqs), &e.Requirements); err != nil {
		return e, fmt.Errorf("decode exercise %d: %w", e.ID, err)
	}
	e.CreatedAt = parseTime(created)
	return e, nil
}

func (r *SpeakingRepository) StartExercise(ctx context.Context, e domain.SpeakingExercise, now time.Time) (domain.SpeakingExercise, bool, error) {
	tx, err := r.beginWrite(ctx, "speaking_exercises")
	if err != nil {
		return domain.SpeakingExercise{}, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if existing, err := readSpeakingExercise(ctx, tx, `prompt_id = ?`, e.PromptID); err == nil {
		if existing.Title != e.Title || existing.Situation != e.Situation || existing.SecondsMin != e.SecondsMin || existing.SecondsMax != e.SecondsMax ||
			!reflect.DeepEqual(existing.Requirements, e.Requirements) {
			return existing, false, domain.ErrSpeakingPromptConflict
		}
		return existing, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return domain.SpeakingExercise{}, false, err
	}
	reqs, err := json.Marshal(e.Requirements)
	if err != nil {
		return domain.SpeakingExercise{}, false, err
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO speaking_exercises (prompt_id, title, situation, requirements, seconds_min, seconds_max, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		e.PromptID, e.Title, e.Situation, string(reqs), e.SecondsMin, e.SecondsMax, fmtTime(now))
	if err != nil {
		return domain.SpeakingExercise{}, false, fmt.Errorf("insert speaking exercise: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return domain.SpeakingExercise{}, false, err
	}
	saved, err := readSpeakingExercise(ctx, tx, `id = ?`, id)
	if err != nil {
		return saved, false, err
	}
	return saved, false, tx.Commit()
}

func (r *SpeakingRepository) GetExercise(ctx context.Context, id int64) (domain.SpeakingExercise, error) {
	return readSpeakingExercise(ctx, r.db, `id = ?`, id)
}

func (r *SpeakingRepository) ListExercises(ctx context.Context) ([]domain.SpeakingExercise, error) {
	ids, err := listIDs(ctx, r.db, `SELECT id FROM speaking_exercises ORDER BY id DESC`)
	if err != nil {
		return nil, err
	}
	out := []domain.SpeakingExercise{}
	for _, id := range ids {
		e, err := r.GetExercise(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, nil
}

// ---- takes ----

func readSpeakingTake(ctx context.Context, q queryer, where string, args ...any) (domain.SpeakingTake, error) {
	var t domain.SpeakingTake
	var mimeType, sha, created string
	var mimeNull, shaNull sql.NullString
	var size, duration sql.NullInt64
	err := q.QueryRowContext(ctx, `SELECT id, exercise_id, take_number, audio_source, audio_mime, audio_bytes, audio_sha256, duration_ms, created_at FROM speaking_takes WHERE `+where, args...).
		Scan(&t.ID, &t.ExerciseID, &t.Number, &t.AudioSource, &mimeNull, &size, &shaNull, &duration, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return t, fmt.Errorf("%w: speaking take", domain.ErrNotFound)
	}
	if err != nil {
		return t, err
	}
	mimeType, sha = mimeNull.String, shaNull.String
	t.AudioMIME, t.AudioSHA256, t.AudioBytes, t.DurationMS, t.CreatedAt = mimeType, sha, size.Int64, int(duration.Int64), parseTime(created)
	return t, nil
}

func (r *SpeakingRepository) AddTake(ctx context.Context, exerciseID int64, t domain.SpeakingTake, now time.Time) (domain.SpeakingTake, error) {
	tx, err := r.beginWrite(ctx, "speaking_takes")
	if err != nil {
		return domain.SpeakingTake{}, err
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := readSpeakingExercise(ctx, tx, `id = ?`, exerciseID); err != nil {
		return domain.SpeakingTake{}, err
	}
	var n int
	if err := tx.QueryRowContext(ctx, `SELECT COALESCE(MAX(take_number), 0) FROM speaking_takes WHERE exercise_id = ?`, exerciseID).Scan(&n); err != nil {
		return domain.SpeakingTake{}, err
	}
	if n >= domain.MaxSpeakingTakes {
		return domain.SpeakingTake{}, domain.ErrSpeakingTooManyTakes
	}
	var mimeType, size, sha, duration any
	if t.AudioSource != domain.SpeakingAudioNone {
		mimeType, size, sha, duration = t.AudioMIME, t.AudioBytes, t.AudioSHA256, t.DurationMS
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO speaking_takes (exercise_id, take_number, audio_source, audio_mime, audio_bytes, audio_sha256, duration_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		exerciseID, n+1, t.AudioSource, mimeType, size, sha, duration, fmtTime(now))
	if err != nil {
		return domain.SpeakingTake{}, fmt.Errorf("insert speaking take: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return domain.SpeakingTake{}, err
	}
	saved, err := readSpeakingTake(ctx, tx, `id = ?`, id)
	if err != nil {
		return saved, err
	}
	return saved, tx.Commit()
}

func (r *SpeakingRepository) GetTake(ctx context.Context, id int64) (domain.SpeakingTake, error) {
	return readSpeakingTake(ctx, r.db, `id = ?`, id)
}

func (r *SpeakingRepository) ListTakes(ctx context.Context, exerciseID int64) ([]domain.SpeakingTake, error) {
	ids, err := listIDs(ctx, r.db, `SELECT id FROM speaking_takes WHERE exercise_id = ? ORDER BY take_number`, exerciseID)
	if err != nil {
		return nil, err
	}
	out := []domain.SpeakingTake{}
	for _, id := range ids {
		t, err := r.GetTake(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, nil
}

// ---- transcriptions ----

func readSpeakingTranscription(ctx context.Context, q queryer, where string, args ...any) (domain.SpeakingTranscription, error) {
	var t domain.SpeakingTranscription
	var failure, text sql.NullString
	var created string
	err := q.QueryRowContext(ctx, `SELECT id, take_id, status, failure_code, transcriber, text, created_at FROM speaking_transcriptions WHERE `+where, args...).
		Scan(&t.ID, &t.TakeID, &t.Status, &failure, &t.Transcriber, &text, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return t, fmt.Errorf("%w: speaking transcription", domain.ErrNotFound)
	}
	t.FailureCode, t.Text, t.CreatedAt = failure.String, text.String, parseTime(created)
	return t, err
}

const speakingTranscriptionRequestColumns = `id, operation_id, exercise_id, take_id, audio_sha256, after_unknown, started_at, deadline_at, finished_at, outcome, transcription_id`

func readSpeakingTranscriptionRequest(ctx context.Context, q queryer, where string, args ...any) (domain.SpeakingTranscriptionRequest, error) {
	var w domain.SpeakingTranscriptionRequest
	var after int
	var started, deadline string
	var finished, outcome sql.NullString
	var result sql.NullInt64
	err := q.QueryRowContext(ctx, `SELECT `+speakingTranscriptionRequestColumns+` FROM speaking_transcription_requests WHERE `+where, args...).
		Scan(&w.ID, &w.OperationID, &w.ExerciseID, &w.TakeID, &w.AudioSHA256, &after, &started, &deadline, &finished, &outcome, &result)
	if errors.Is(err, sql.ErrNoRows) {
		return w, fmt.Errorf("%w: speaking transcription request", domain.ErrNotFound)
	}
	if err != nil {
		return w, err
	}
	w.AfterUnknown, w.StartedAt, w.DeadlineAt, w.FinishedAt = after == 1, parseTime(started), parseTime(deadline), parseNullTime(finished)
	w.Outcome, w.TranscriptionID = outcome.String, nullInt(result)
	return w, nil
}

// StartTranscriptionRequest: the take must have audio, and the audio sent must
// be the audio recorded for it (same SHA-256). A request still in progress for
// the same exercise blocks any new one; an unknown outcome for the same take
// needs the learner's acknowledgement.
func (r *SpeakingRepository) StartTranscriptionRequest(ctx context.Context, in domain.NewSpeakingTranscriptionRequest) (domain.SpeakingTranscriptionRequest, *domain.SpeakingTake, bool, error) {
	var none domain.SpeakingTranscriptionRequest
	tx, err := r.beginWrite(ctx, "speaking_transcription_requests")
	if err != nil {
		return none, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if w, err := readSpeakingTranscriptionRequest(ctx, tx, `operation_id = ?`, in.OperationID); err == nil {
		if w.TakeID != in.TakeID || w.AudioSHA256 != in.AudioSHA256 {
			return none, nil, false, domain.ErrSpeakingOperationConflict
		}
		t, err := readSpeakingTake(ctx, tx, `id = ?`, w.TakeID)
		if err != nil {
			return none, nil, false, err
		}
		return w, &t, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	t, err := readSpeakingTake(ctx, tx, `id = ?`, in.TakeID)
	if err != nil {
		return none, nil, false, err
	}
	if t.AudioSource == domain.SpeakingAudioNone {
		return none, nil, false, domain.ErrSpeakingNoAudio
	}
	if t.AudioSHA256 != in.AudioSHA256 || t.AudioMIME != in.AudioMIME {
		return none, nil, false, fmt.Errorf("%w: the audio sent is not the audio recorded for take %d", domain.ErrValidation, t.Number)
	}
	if latest, err := readSpeakingTranscriptionRequest(ctx, tx, `exercise_id = ? ORDER BY id DESC LIMIT 1`, t.ExerciseID); err == nil && latest.State(in.Now) == domain.ListeningStateInProgress {
		return latest, nil, false, domain.ErrSpeakingRequestInProgress
	} else if err != nil && !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	afterUnknown := false
	if latest, err := readSpeakingTranscriptionRequest(ctx, tx, `take_id = ? ORDER BY id DESC LIMIT 1`, t.ID); err == nil && latest.State(in.Now) == domain.ListeningOutcomeUnknown {
		if !in.ConfirmUnknownRetry {
			return latest, nil, false, domain.ErrSpeakingOutcomeUnknown
		}
		afterUnknown = true
	} else if err != nil && !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO speaking_transcription_requests (operation_id, exercise_id, take_id, audio_sha256, after_unknown, started_at, deadline_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		in.OperationID, t.ExerciseID, t.ID, in.AudioSHA256, boolInt(afterUnknown), fmtTime(in.Now), fmtTime(in.Deadline))
	if err != nil {
		return none, nil, false, fmt.Errorf("insert speaking transcription request: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return none, nil, false, err
	}
	w, err := readSpeakingTranscriptionRequest(ctx, tx, `id = ?`, id)
	if err != nil {
		return none, nil, false, err
	}
	return w, &t, false, tx.Commit()
}

func (r *SpeakingRepository) FinishTranscriptionRequest(ctx context.Context, id int64, outcome string, t domain.SpeakingTranscription, now time.Time) (domain.SpeakingTranscriptionRequest, domain.SpeakingTranscription, error) {
	var noneReq domain.SpeakingTranscriptionRequest
	var noneT domain.SpeakingTranscription
	tx, err := r.beginWrite(ctx, "speaking_transcription_requests")
	if err != nil {
		return noneReq, noneT, err
	}
	defer func() { _ = tx.Rollback() }()
	var text, failure any
	if t.Status == domain.ListeningExerciseCompleted {
		text = t.Text
	}
	if t.FailureCode != "" {
		failure = t.FailureCode
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO speaking_transcriptions (take_id, status, failure_code, transcriber, text, created_at) VALUES (?, ?, ?, ?, ?, ?)`,
		t.TakeID, t.Status, failure, t.Transcriber, text, fmtTime(now))
	if err != nil {
		return noneReq, noneT, fmt.Errorf("insert speaking transcription: %w", err)
	}
	tid, err := res.LastInsertId()
	if err != nil {
		return noneReq, noneT, err
	}
	upd, err := tx.ExecContext(ctx, `UPDATE speaking_transcription_requests SET outcome = ?, finished_at = ?, transcription_id = ? WHERE id = ? AND finished_at IS NULL`,
		outcome, fmtTime(now), tid, id)
	if err != nil {
		return noneReq, noneT, fmt.Errorf("finish speaking transcription request: %w", err)
	}
	if n, _ := upd.RowsAffected(); n != 1 {
		return noneReq, noneT, fmt.Errorf("speaking transcription request %d is not pending", id)
	}
	w, err := readSpeakingTranscriptionRequest(ctx, tx, `id = ?`, id)
	if err != nil {
		return w, noneT, err
	}
	stored, err := readSpeakingTranscription(ctx, tx, `id = ?`, tid)
	if err != nil {
		return w, stored, err
	}
	return w, stored, tx.Commit()
}

func (r *SpeakingRepository) GetTranscriptionRequestByOperation(ctx context.Context, operationID string) (domain.SpeakingTranscriptionRequest, error) {
	return readSpeakingTranscriptionRequest(ctx, r.db, `operation_id = ?`, operationID)
}

func (r *SpeakingRepository) GetTranscription(ctx context.Context, id int64) (domain.SpeakingTranscription, error) {
	return readSpeakingTranscription(ctx, r.db, `id = ?`, id)
}

func (r *SpeakingRepository) ListTranscriptions(ctx context.Context, exerciseID int64) ([]domain.SpeakingTranscription, error) {
	ids, err := listIDs(ctx, r.db, `SELECT t.id FROM speaking_transcriptions t JOIN speaking_takes k ON k.id = t.take_id WHERE k.exercise_id = ? ORDER BY t.id DESC`, exerciseID)
	if err != nil {
		return nil, err
	}
	out := []domain.SpeakingTranscription{}
	for _, id := range ids {
		t, err := r.GetTranscription(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, nil
}

func (r *SpeakingRepository) ListTranscriptionRequests(ctx context.Context, exerciseID int64) ([]domain.SpeakingTranscriptionRequest, error) {
	ids, err := listIDs(ctx, r.db, `SELECT id FROM speaking_transcription_requests WHERE exercise_id = ? ORDER BY id DESC`, exerciseID)
	if err != nil {
		return nil, err
	}
	out := []domain.SpeakingTranscriptionRequest{}
	for _, id := range ids {
		w, err := readSpeakingTranscriptionRequest(ctx, r.db, `id = ?`, id)
		if err != nil {
			return nil, err
		}
		out = append(out, w)
	}
	return out, nil
}

// ---- confirmed transcripts ----

func readSpeakingTranscript(ctx context.Context, q queryer, where string, args ...any) (domain.SpeakingTranscript, error) {
	var t domain.SpeakingTranscript
	var created string
	var from sql.NullInt64
	err := q.QueryRowContext(ctx, `SELECT id, take_id, version, text, word_count, origin, transcription_id, created_at FROM speaking_transcripts WHERE `+where, args...).
		Scan(&t.ID, &t.TakeID, &t.Version, &t.Text, &t.WordCount, &t.Origin, &from, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return t, fmt.Errorf("%w: speaking transcript", domain.ErrNotFound)
	}
	t.TranscriptionID, t.CreatedAt = nullInt(from), parseTime(created)
	return t, err
}

func (r *SpeakingRepository) AddTranscript(ctx context.Context, takeID int64, text string, words int, transcriptionID *int64, now time.Time) (domain.SpeakingTranscript, error) {
	var none domain.SpeakingTranscript
	tx, err := r.beginWrite(ctx, "speaking_transcripts")
	if err != nil {
		return none, err
	}
	defer func() { _ = tx.Rollback() }()
	take, err := readSpeakingTake(ctx, tx, `id = ?`, takeID)
	if err != nil {
		return none, err
	}
	var version int
	if err := tx.QueryRowContext(ctx, `SELECT COALESCE(MAX(version), 0) FROM speaking_transcripts WHERE take_id = ?`, take.ID).Scan(&version); err != nil {
		return none, err
	}
	if version >= domain.MaxSpeakingTranscriptVersions {
		return none, domain.ErrSpeakingTooManyVersions
	}
	if version > 0 {
		latest, err := readSpeakingTranscript(ctx, tx, `take_id = ? AND version = ?`, take.ID, version)
		if err != nil {
			return none, err
		}
		if latest.Text == text {
			return latest, domain.ErrSpeakingTranscriptUnchanged
		}
	}
	origin := domain.SpeakingTranscriptTyped
	var from any
	if transcriptionID != nil {
		mt, err := readSpeakingTranscription(ctx, tx, `id = ?`, *transcriptionID)
		if err != nil {
			return none, err
		}
		if mt.TakeID != take.ID || mt.Status != domain.ListeningExerciseCompleted {
			return none, fmt.Errorf("%w: transcription %d is not a completed transcription of take %d", domain.ErrValidation, mt.ID, take.Number)
		}
		from = mt.ID
		origin = domain.SpeakingTranscriptCorrected
		if mt.Text == text {
			origin = domain.SpeakingTranscriptFromTranscription
		}
	} else if version > 0 {
		origin = domain.SpeakingTranscriptCorrected
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO speaking_transcripts (take_id, version, text, word_count, origin, transcription_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		take.ID, version+1, text, words, origin, from, fmtTime(now))
	if err != nil {
		return none, fmt.Errorf("insert speaking transcript: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return none, err
	}
	saved, err := readSpeakingTranscript(ctx, tx, `id = ?`, id)
	if err != nil {
		return saved, err
	}
	return saved, tx.Commit()
}

func (r *SpeakingRepository) GetTranscript(ctx context.Context, id int64) (domain.SpeakingTranscript, error) {
	return readSpeakingTranscript(ctx, r.db, `id = ?`, id)
}

func (r *SpeakingRepository) ListTranscripts(ctx context.Context, exerciseID int64) ([]domain.SpeakingTranscript, error) {
	ids, err := listIDs(ctx, r.db, `SELECT s.id FROM speaking_transcripts s JOIN speaking_takes k ON k.id = s.take_id WHERE k.exercise_id = ? ORDER BY k.take_number, s.version`, exerciseID)
	if err != nil {
		return nil, err
	}
	out := []domain.SpeakingTranscript{}
	for _, id := range ids {
		t, err := r.GetTranscript(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, nil
}

// ---- feedback ----

func readSpeakingFeedback(ctx context.Context, q queryer, where string, args ...any) (domain.SpeakingFeedback, error) {
	var f domain.SpeakingFeedback
	var failure, content sql.NullString
	var created string
	err := q.QueryRowContext(ctx, `SELECT id, exercise_id, transcript_id, status, failure_code, generator, content, created_at FROM speaking_feedback WHERE `+where, args...).
		Scan(&f.ID, &f.ExerciseID, &f.TranscriptID, &f.Status, &failure, &f.Generator, &content, &created)
	if errors.Is(err, sql.ErrNoRows) {
		return f, fmt.Errorf("%w: speaking feedback", domain.ErrNotFound)
	}
	if err != nil {
		return f, err
	}
	f.FailureCode, f.CreatedAt = failure.String, parseTime(created)
	if content.Valid {
		var c domain.SpeakingFeedbackContent
		if err := json.Unmarshal([]byte(content.String), &c); err != nil {
			return f, fmt.Errorf("decode speaking feedback %d: %w", f.ID, err)
		}
		f.Content = &c
	}
	return f, nil
}

const speakingFeedbackRequestColumns = `id, operation_id, exercise_id, transcript_id, after_unknown, started_at, deadline_at, finished_at, outcome, feedback_id`

func readSpeakingFeedbackRequest(ctx context.Context, q queryer, where string, args ...any) (domain.SpeakingFeedbackRequest, error) {
	var w domain.SpeakingFeedbackRequest
	var after int
	var started, deadline string
	var finished, outcome sql.NullString
	var feedback sql.NullInt64
	err := q.QueryRowContext(ctx, `SELECT `+speakingFeedbackRequestColumns+` FROM speaking_feedback_requests WHERE `+where, args...).
		Scan(&w.ID, &w.OperationID, &w.ExerciseID, &w.TranscriptID, &after, &started, &deadline, &finished, &outcome, &feedback)
	if errors.Is(err, sql.ErrNoRows) {
		return w, fmt.Errorf("%w: speaking feedback request", domain.ErrNotFound)
	}
	if err != nil {
		return w, err
	}
	w.AfterUnknown, w.StartedAt, w.DeadlineAt, w.FinishedAt = after == 1, parseTime(started), parseTime(deadline), parseNullTime(finished)
	w.Outcome, w.FeedbackID = outcome.String, nullInt(feedback)
	return w, nil
}

// StartFeedbackRequest: a request still in progress for the same exercise
// blocks any new one; an unknown outcome for the same transcript version needs
// the learner's acknowledgement. A new version is a new input.
func (r *SpeakingRepository) StartFeedbackRequest(ctx context.Context, in domain.NewSpeakingFeedbackRequest) (domain.SpeakingFeedbackRequest, *domain.SpeakingTranscript, bool, error) {
	var none domain.SpeakingFeedbackRequest
	tx, err := r.beginWrite(ctx, "speaking_feedback_requests")
	if err != nil {
		return none, nil, false, err
	}
	defer func() { _ = tx.Rollback() }()
	if w, err := readSpeakingFeedbackRequest(ctx, tx, `operation_id = ?`, in.OperationID); err == nil {
		if w.TranscriptID != in.TranscriptID {
			return none, nil, false, domain.ErrSpeakingOperationConflict
		}
		s, err := readSpeakingTranscript(ctx, tx, `id = ?`, w.TranscriptID)
		if err != nil {
			return none, nil, false, err
		}
		return w, &s, true, tx.Commit()
	} else if !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	s, err := readSpeakingTranscript(ctx, tx, `id = ?`, in.TranscriptID)
	if err != nil {
		return none, nil, false, err
	}
	take, err := readSpeakingTake(ctx, tx, `id = ?`, s.TakeID)
	if err != nil {
		return none, nil, false, err
	}
	if latest, err := readSpeakingFeedbackRequest(ctx, tx, `exercise_id = ? ORDER BY id DESC LIMIT 1`, take.ExerciseID); err == nil && latest.State(in.Now) == domain.ListeningStateInProgress {
		return latest, nil, false, domain.ErrSpeakingRequestInProgress
	} else if err != nil && !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	afterUnknown := false
	if latest, err := readSpeakingFeedbackRequest(ctx, tx, `transcript_id = ? ORDER BY id DESC LIMIT 1`, s.ID); err == nil && latest.State(in.Now) == domain.ListeningOutcomeUnknown {
		if !in.ConfirmUnknownRetry {
			return latest, nil, false, domain.ErrSpeakingOutcomeUnknown
		}
		afterUnknown = true
	} else if err != nil && !errors.Is(err, domain.ErrNotFound) {
		return none, nil, false, err
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO speaking_feedback_requests (operation_id, exercise_id, transcript_id, after_unknown, started_at, deadline_at) VALUES (?, ?, ?, ?, ?, ?)`,
		in.OperationID, take.ExerciseID, s.ID, boolInt(afterUnknown), fmtTime(in.Now), fmtTime(in.Deadline))
	if err != nil {
		return none, nil, false, fmt.Errorf("insert speaking feedback request: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return none, nil, false, err
	}
	w, err := readSpeakingFeedbackRequest(ctx, tx, `id = ?`, id)
	if err != nil {
		return none, nil, false, err
	}
	return w, &s, false, tx.Commit()
}

func (r *SpeakingRepository) FinishFeedbackRequest(ctx context.Context, id int64, outcome string, f domain.SpeakingFeedback, now time.Time) (domain.SpeakingFeedbackRequest, domain.SpeakingFeedback, error) {
	var noneReq domain.SpeakingFeedbackRequest
	var noneF domain.SpeakingFeedback
	tx, err := r.beginWrite(ctx, "speaking_feedback_requests")
	if err != nil {
		return noneReq, noneF, err
	}
	defer func() { _ = tx.Rollback() }()
	var content, failure any
	if f.Content != nil {
		raw, err := json.Marshal(f.Content)
		if err != nil {
			return noneReq, noneF, err
		}
		content = string(raw)
	}
	if f.FailureCode != "" {
		failure = f.FailureCode
	}
	res, err := tx.ExecContext(ctx, `INSERT INTO speaking_feedback (exercise_id, transcript_id, status, failure_code, generator, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		f.ExerciseID, f.TranscriptID, f.Status, failure, f.Generator, content, fmtTime(now))
	if err != nil {
		return noneReq, noneF, fmt.Errorf("insert speaking feedback: %w", err)
	}
	fid, err := res.LastInsertId()
	if err != nil {
		return noneReq, noneF, err
	}
	upd, err := tx.ExecContext(ctx, `UPDATE speaking_feedback_requests SET outcome = ?, finished_at = ?, feedback_id = ? WHERE id = ? AND finished_at IS NULL`,
		outcome, fmtTime(now), fid, id)
	if err != nil {
		return noneReq, noneF, fmt.Errorf("finish speaking feedback request: %w", err)
	}
	if n, _ := upd.RowsAffected(); n != 1 {
		return noneReq, noneF, fmt.Errorf("speaking feedback request %d is not pending", id)
	}
	w, err := readSpeakingFeedbackRequest(ctx, tx, `id = ?`, id)
	if err != nil {
		return w, noneF, err
	}
	stored, err := readSpeakingFeedback(ctx, tx, `id = ?`, fid)
	if err != nil {
		return w, stored, err
	}
	return w, stored, tx.Commit()
}

func (r *SpeakingRepository) GetFeedbackRequestByOperation(ctx context.Context, operationID string) (domain.SpeakingFeedbackRequest, error) {
	return readSpeakingFeedbackRequest(ctx, r.db, `operation_id = ?`, operationID)
}

func (r *SpeakingRepository) GetFeedback(ctx context.Context, id int64) (domain.SpeakingFeedback, error) {
	return readSpeakingFeedback(ctx, r.db, `id = ?`, id)
}

func (r *SpeakingRepository) ListFeedback(ctx context.Context, exerciseID int64) ([]domain.SpeakingFeedback, error) {
	ids, err := listIDs(ctx, r.db, `SELECT id FROM speaking_feedback WHERE exercise_id = ? ORDER BY id DESC`, exerciseID)
	if err != nil {
		return nil, err
	}
	out := []domain.SpeakingFeedback{}
	for _, id := range ids {
		f, err := r.GetFeedback(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, nil
}

func (r *SpeakingRepository) ListFeedbackRequests(ctx context.Context, exerciseID int64) ([]domain.SpeakingFeedbackRequest, error) {
	ids, err := listIDs(ctx, r.db, `SELECT id FROM speaking_feedback_requests WHERE exercise_id = ? ORDER BY id DESC`, exerciseID)
	if err != nil {
		return nil, err
	}
	out := []domain.SpeakingFeedbackRequest{}
	for _, id := range ids {
		w, err := readSpeakingFeedbackRequest(ctx, r.db, `id = ?`, id)
		if err != nil {
			return nil, err
		}
		out = append(out, w)
	}
	return out, nil
}
