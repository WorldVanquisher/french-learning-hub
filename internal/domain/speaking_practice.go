package domain

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
)

// Speaking practice: derived, read-only views over the stored Speaking
// records. Nothing here is stored: an attempt's state, the practice queue and
// the summary are recomputed on every read, so they can never disagree with
// the records they describe.

// ErrSpeakingTakeConflict: the same audio (SHA-256) was already saved as a take
// of this exercise with different metadata.
var ErrSpeakingTakeConflict = errors.New("this audio is already a take of this exercise with different details")

// SpeakingPracticeVersion and SpeakingExportVersion name the read contracts.
const (
	SpeakingPracticeVersion = "speaking_practice_v1"
	SpeakingExportVersion   = "speaking_attempt_export_v1"
)

// Where an exercise's stored prompt stands against the embedded prompt set.
// An exercise keeps the prompt it was started with; the set may later be
// corrected (changed) or drop the prompt (removed). Takes always belong to the
// stored prompt.
const (
	SpeakingPackCurrent = "current"
	SpeakingPackChanged = "changed"
	SpeakingPackRemoved = "removed"
)

// Attempt (take) states, derived from the take's requests and records.
const (
	SpeakingAwaitingTranscript   = "awaiting_transcript"   // no confirmed transcript, no machine transcript
	SpeakingTranscribing         = "transcribing"          // a transcription request is in progress
	SpeakingTranscriptionFailed  = "transcription_failed"  // the latest transcription failed
	SpeakingTranscriptionUnknown = "transcription_unknown" // the latest transcription request's outcome is unknown
	SpeakingTranscriptToConfirm  = "transcript_to_confirm" // a machine transcript waits for the learner's check
	SpeakingAwaitingFeedback     = "awaiting_feedback"     // the latest confirmed version has no feedback
	SpeakingFeedbackInProgress   = "feedback_in_progress"  // a feedback request is in progress
	SpeakingFeedbackFailed       = "feedback_failed"       // the latest feedback on the latest version failed
	SpeakingFeedbackUnknown      = "feedback_unknown"      // the latest feedback request's outcome is unknown
	SpeakingFeedbackReady        = "feedback_ready"        // completed feedback on the latest confirmed version
)

// Practice queue reasons, in priority order (first = most urgent).
const (
	SpeakingQueueCheckUnknown      = "check_unknown_outcome"
	SpeakingQueueRequestFailed     = "request_failed"
	SpeakingQueueConfirmTranscript = "confirm_transcript"
	SpeakingQueueAddTranscript     = "add_transcript"
	SpeakingQueueRequestFeedback   = "request_feedback"
	SpeakingQueueAnswerAgain       = "answer_again"
	SpeakingQueueFirstTake         = "start_first_take"
	SpeakingQueueNotStarted        = "not_started"
)

// SpeakingQueuePriority orders the reasons; unknown reasons sort last.
func SpeakingQueuePriority(reason string) int {
	for i, r := range []string{SpeakingQueueCheckUnknown, SpeakingQueueRequestFailed, SpeakingQueueConfirmTranscript,
		SpeakingQueueAddTranscript, SpeakingQueueRequestFeedback, SpeakingQueueAnswerAgain, SpeakingQueueFirstTake,
		SpeakingQueueNotStarted} {
		if r == reason {
			return i
		}
	}
	return 99
}

// SpeakingContentFingerprint identifies a prompt's content: SHA-256 of the
// canonical JSON of the fields an exercise stores. The same function serves a
// stored exercise and an embedded prompt, so equal fingerprints mean the
// learner answered exactly the prompt the set holds now.
func SpeakingContentFingerprint(title, situation string, requirements []string, secondsMin, secondsMax int) string {
	if requirements == nil {
		requirements = []string{}
	}
	raw, _ := json.Marshal(struct {
		Title        string   `json:"title"`
		Situation    string   `json:"situation"`
		Requirements []string `json:"requirements"`
		SecondsMin   int      `json:"seconds_min"`
		SecondsMax   int      `json:"seconds_max"`
	}{title, situation, requirements, secondsMin, secondsMax})
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// Fingerprint is the content fingerprint of the stored prompt.
func (e SpeakingExercise) Fingerprint() string {
	return SpeakingContentFingerprint(e.Title, e.Situation, e.Requirements, e.SecondsMin, e.SecondsMax)
}

// Fingerprint is the content fingerprint of the authored prompt.
func (p SpeakingPrompt) Fingerprint() string {
	return SpeakingContentFingerprint(p.Title, p.Situation, p.Requirements, p.SecondsMin, p.SecondsMax)
}

// SameTakeMetadata reports whether a resent take describes the stored one.
func SameTakeMetadata(a, b SpeakingTake) bool {
	return a.AudioSource == b.AudioSource && a.AudioMIME == b.AudioMIME && a.AudioBytes == b.AudioBytes &&
		a.AudioSHA256 == b.AudioSHA256 && a.DurationMS == b.DurationMS
}
