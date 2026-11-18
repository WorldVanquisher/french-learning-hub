package http

import (
	"encoding/json"
	"net/http"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// Speaking practice overview and attempt export: read-only, no provider call,
// derived from the stored records on every request.

type speakingAttemptJSON struct {
	TakeID           int64   `json:"take_id"`
	TakeNumber       int     `json:"take_number"`
	State            string  `json:"state"`
	Versions         int     `json:"transcript_versions"`
	LatestVersion    *int    `json:"latest_version"`
	FeedbackID       *int64  `json:"feedback_id"`
	FeedbackRating   *string `json:"feedback_rating"`
	Improvements     int     `json:"improvements"`
	ActivityAt       string  `json:"activity_at"`
	TakeCreatedAt    string  `json:"take_created_at"`
	AudioSource      string  `json:"audio_source"`
	TranscriptOrigin *string `json:"transcript_origin"`
}

func toSpeakingAttempt(a application.SpeakingAttempt) speakingAttemptJSON {
	out := speakingAttemptJSON{TakeID: a.Take.ID, TakeNumber: a.Take.Number, State: a.State, Versions: a.Versions,
		Improvements: a.Improvements, ActivityAt: ts(a.ActivityAt), TakeCreatedAt: ts(a.Take.CreatedAt), AudioSource: a.Take.AudioSource}
	if t := a.LatestTranscript; t != nil {
		v, origin := t.Version, t.Origin
		out.LatestVersion, out.TranscriptOrigin = &v, &origin
	}
	if f := a.Feedback; f != nil {
		id := f.ID
		out.FeedbackID = &id
		if f.Content != nil {
			rating := f.Content.TaskFulfilment.Rating
			out.FeedbackRating = &rating
		}
	}
	return out
}

// handleSpeakingPractice answers the practice overview: summary, queue and
// per-exercise progress.
func (h *Handler) handleSpeakingPractice(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	p, err := h.speaking.Practice(r.Context())
	if err != nil {
		writeSpeakingError(w, err, "read the practice overview")
		return
	}
	queue := make([]map[string]any, 0, len(p.Queue))
	for _, q := range p.Queue {
		queue = append(queue, toSpeakingQueueItem(q))
	}
	var resume any
	if p.Resume != nil {
		resume = toSpeakingQueueItem(*p.Resume)
	}
	exercises := make([]map[string]any, 0, len(p.Exercises))
	for _, e := range p.Exercises {
		var latest any
		if e.Latest != nil {
			latest = toSpeakingAttempt(*e.Latest)
		}
		exercises = append(exercises, map[string]any{"exercise": toSpeakingExercise(e.Exercise, e.PackStatus), "takes": e.Takes,
			"completed": e.Completed, "latest": latest, "last_activity_at": ts(e.LastActivity)})
	}
	s := p.Summary
	var last any
	if s.LastCompletedAt != nil {
		last = ts(*s.LastCompletedAt)
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"schema_version": domain.SpeakingPracticeVersion,
		"generated_at":   ts(p.Now),
		"summary": map[string]any{"prompts": s.Prompts, "started": s.Started, "takes": s.Takes, "completed": s.Completed,
			"exercises_completed": s.ExercisesCompleted, "awaiting_transcript": s.AwaitingTranscript, "awaiting_feedback": s.AwaitingFeedback,
			"in_progress": s.InProgress, "failed": s.Failed, "unknown": s.Unknown, "last_completed_at": last},
		"queue":     queue,
		"resume":    resume,
		"exercises": exercises,
		"providers": h.speakingProviders(),
	})
}

// toSpeakingQueueItem is one queue step. request/request_enabled say which
// provider request the step concerns and whether it can be sent now;
// pack_status is the started exercise's (null for a prompt not started).
func toSpeakingQueueItem(q application.SpeakingQueueItem) map[string]any {
	item := map[string]any{"reason": q.Reason, "priority": domain.SpeakingQueuePriority(q.Reason), "prompt_id": q.PromptID,
		"title": q.Title, "exercise_id": q.ExerciseID, "take_id": q.TakeID, "take_number": nil, "state": optString(q.State),
		"improvements": q.Improvements, "since": nil, "request": optString(q.Request), "request_enabled": q.RequestEnabled,
		"pack_status": optString(q.PackStatus)}
	if q.TakeID != nil {
		item["take_number"] = q.TakeNumber
	}
	if q.Since != nil {
		item["since"] = ts(*q.Since)
	}
	return item
}

// handleSpeakingExport streams one JSON object per attempt (take), oldest
// exercise first: the exercise reference, the take's audio METADATA (audio is
// never stored, so never exported), its machine transcriptions, confirmed
// transcript versions and feedback with their provenance. Same NDJSON
// conventions as the learning-record export.
func (h *Handler) handleSpeakingExport(w http.ResponseWriter, r *http.Request) {
	if h.speakingUnavailable(w) {
		return
	}
	rows, err := h.speaking.Export(r.Context())
	if err != nil {
		writeSpeakingError(w, err, "export speaking attempts")
		return
	}
	w.Header().Set("Content-Type", "application/x-ndjson; charset=utf-8")
	w.Header().Set("Content-Disposition", `attachment; filename="speaking-attempts.ndjson"`)
	w.WriteHeader(http.StatusOK)
	enc := json.NewEncoder(w)
	for _, row := range rows {
		take := toSpeakingTake(row.Attempt.Take)
		take.State = row.Attempt.State
		trs := make([]speakingTranscriptionJSON, 0, len(row.Transcriptions))
		for _, t := range row.Transcriptions {
			trs = append(trs, toSpeakingTranscription(t))
		}
		scripts := make([]speakingTranscriptJSON, 0, len(row.Transcripts))
		for _, t := range row.Transcripts {
			scripts = append(scripts, toSpeakingTranscript(t))
		}
		fb := make([]speakingFeedbackJSON, 0, len(row.Feedback))
		for _, f := range row.Feedback {
			fb = append(fb, toSpeakingFeedback(f))
		}
		e := row.Exercise
		line := map[string]any{
			"schema_version": domain.SpeakingExportVersion,
			"exercise": map[string]any{"id": e.ID, "prompt_id": e.PromptID, "prompt_set": domain.SpeakingPromptsID,
				"content_fingerprint": e.Fingerprint(), "pack_status": row.PackStatus, "title": e.Title},
			"take": take, "transcriptions": trs, "transcripts": scripts, "feedback": fb,
		}
		if err := enc.Encode(line); err != nil {
			return // the connection is broken; nothing more can be signalled
		}
	}
}
