package http_test

// Speaking practice queue when feedback is off, unavailable or missing: every
// started exercise whose latest take is not complete keeps one step whose
// reason follows from the take's state, and each step says which request it
// concerns and whether that request can be sent now. Pending, failed and
// unknown stay apart, and only feedback on the latest confirmed version counts
// as completed. End to end over the real handler against the local fakes.

import (
	"fmt"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/speaking/speakingfake"
)

func (f *speakingFixture) startPrompt(t *testing.T, prompt string) int64 {
	t.Helper()
	status, out := doJSON(t, http.MethodPost, f.srv.URL+"/speaking/prompts/"+prompt, "")
	if status != http.StatusCreated && status != http.StatusOK {
		t.Fatalf("start %s: %d %v", prompt, status, out)
	}
	return int64(path(out, "exercise", "id").(float64))
}

// queueItem is the queue step of one started exercise (nil if it has none).
func queueItem(p map[string]any, ex int64) map[string]any {
	for _, q := range p["queue"].([]any) {
		if path(q, "exercise_id") == float64(ex) {
			return q.(map[string]any)
		}
	}
	return nil
}

// step is "reason/request/enabled" for one exercise ("-" when it has none).
func step(p map[string]any, ex int64) string {
	q := queueItem(p, ex)
	if q == nil {
		return "-"
	}
	return fmt.Sprintf("%v/%v/%v", q["reason"], q["request"], q["request_enabled"])
}

func summaryOf(p map[string]any, keys ...string) string {
	out := []string{}
	for _, k := range keys {
		out = append(out, fmt.Sprintf("%s=%v", k, path(p, "summary", k)))
	}
	return strings.Join(out, " ")
}

// confirmedV1 confirms a typed version 1 for a take and returns its ID.
func (f *speakingFixture) confirmedV1(t *testing.T, ex, take int64) int64 {
	t.Helper()
	status, view := f.confirm(t, take, transcriptV1(t), nil)
	if status != http.StatusCreated {
		t.Fatalf("confirm: %d %v", status, view)
	}
	return transcriptID(view, take, 1)
}

func TestSpeakingQueue_FeedbackOffOrUnavailableKeepsEveryExerciseActionable(t *testing.T) {
	f := newSpeakingFixture(t, true, 0)
	// A: feedback unavailable (the model answers 500): a failed request.
	exA := f.startPrompt(t, "sp-invitation-reponse")
	takeA, _ := f.recordTake(t, exA, synthAudio("queue-a", 4_000))
	vA := f.confirmedV1(t, exA, takeA)
	f.model.Set(listeningfake.ModeStatus, http.StatusInternalServerError, 0)
	if status, out := f.feedback(t, vA, skeyA, ""); status != http.StatusBadGateway {
		t.Fatalf("A failed: %d %v", status, out)
	}
	// B: the answer is lost after sending: outcome unknown.
	exB := f.startPrompt(t, "sp-demande-renseignements")
	takeB, _ := f.recordTake(t, exB, nil)
	vB := f.confirmedV1(t, exB, takeB)
	f.model.Set(listeningfake.ModeDrop, 0, 0)
	if status, out := f.feedback(t, vB, skeyB, ""); status != http.StatusBadGateway {
		t.Fatalf("B unknown: %d %v", status, out)
	}
	// C: transcription unavailable: a failed transcription.
	exC := f.startPrompt(t, "sp-changement-programme")
	audioC := synthAudio("queue-c", 4_000)
	takeC, _ := f.recordTake(t, exC, audioC)
	f.stt.Set(speakingfake.ModeStatus, http.StatusInternalServerError, 0)
	if status, res, _ := f.transcribe(t, takeC, skeyC, audioC, "audio/wav", false); status != http.StatusBadGateway {
		t.Fatalf("C failed: %d %v", status, res)
	}
	p := f.practice(t)
	if got := []string{step(p, exA), step(p, exB), step(p, exC)}; strings.Join(got, " ") !=
		"request_failed/feedback/true check_unknown_outcome/feedback/true request_failed/transcription/true" {
		t.Fatalf("providers on: %v", got)
	}
	if got := summaryOf(p, "takes", "completed", "failed", "unknown", "awaiting_feedback"); got != "takes=3 completed=0 failed=2 unknown=1 awaiting_feedback=0" {
		t.Fatalf("providers on: %s", got)
	}

	// Both providers turned off (a restart): the same records, the same
	// reasons, failed and unknown still apart; each step now says its request
	// cannot be sent. No exercise leaves the queue.
	f.openProviders(t, false, false, 0)
	p = f.practice(t)
	if got := []string{step(p, exA), step(p, exB), step(p, exC)}; strings.Join(got, " ") !=
		"request_failed/feedback/false check_unknown_outcome/feedback/false request_failed/transcription/false" {
		t.Fatalf("providers off: %v", got)
	}
	if got := summaryOf(p, "takes", "completed", "failed", "unknown"); got != "takes=3 completed=0 failed=2 unknown=1" {
		t.Fatalf("providers off: %s", got)
	}
	// C gets a typed transcript: it waits for feedback that is off, so its step
	// is a review, not a request (this exercise used to vanish here).
	f.confirmedV1(t, exC, takeC)
	p = f.practice(t)
	if step(p, exC) != "review_without_feedback/feedback/false" || path(queueItem(p, exC), "state") != domain.SpeakingAwaitingFeedback ||
		path(p, "resume", "exercise_id") != float64(exC) {
		t.Fatalf("typed after a failed transcription, feedback off: %s %v", step(p, exC), p["resume"])
	}
	if got := summaryOf(p, "completed", "failed", "unknown", "awaiting_feedback"); got != "completed=0 failed=1 unknown=1 awaiting_feedback=1" {
		t.Fatalf("after typing: %s", got)
	}
	// A reload reads the same thing: nothing is stored about the queue.
	if again := f.practice(t); fmt.Sprint(again["queue"]) != fmt.Sprint(p["queue"]) {
		t.Fatalf("reload changed the queue:\n%v\n%v", p["queue"], again["queue"])
	}

	// Feedback back on: C asks for feedback; retries complete A and B (B only
	// with the explicit confirmation an unknown outcome needs).
	f.openProviders(t, false, true, 0)
	f.model.Set(listeningfake.ModeOK, 0, 0)
	p = f.practice(t)
	if step(p, exC) != "request_feedback/feedback/true" || step(p, exA) != "request_failed/feedback/true" {
		t.Fatalf("feedback back on: %s %s", step(p, exC), step(p, exA))
	}
	if status, out := f.feedback(t, vA, skeyD, ""); status != http.StatusCreated {
		t.Fatalf("A retry: %d %v", status, out)
	}
	if status, out := f.feedback(t, vB, "c5555555-5555-4555-8555-555555555555", ""); status != http.StatusConflict {
		t.Fatalf("B retry without confirmation: %d %v", status, out)
	}
	if status, out := f.feedback(t, vB, "c6666666-6666-4666-8666-666666666666", `{"confirm_unknown_retry": true}`); status != http.StatusCreated {
		t.Fatalf("B confirmed retry: %d %v", status, out)
	}
	p = f.practice(t)
	if step(p, exA) != "answer_again/<nil>/false" || step(p, exB) != "answer_again/<nil>/false" || path(queueItem(p, exA), "improvements").(float64) < 1 {
		t.Fatalf("after retries: %s %s", step(p, exA), step(p, exB))
	}
	if got := summaryOf(p, "takes", "completed", "exercises_completed", "failed", "unknown", "awaiting_feedback"); got !=
		"takes=3 completed=2 exercises_completed=2 failed=0 unknown=0 awaiting_feedback=1" {
		t.Fatalf("after retries: %s", got)
	}
	// The resume pointer skips complete exercises: C is the incomplete one.
	if path(p, "resume", "exercise_id") != float64(exC) {
		t.Fatalf("resume: %v", p["resume"])
	}
}

func TestSpeakingQueue_TypedAndUntranscribedTakesNameTheRightStep(t *testing.T) {
	f := newSpeakingFixture(t, false, 0)
	exA := f.startPrompt(t, "sp-invitation-reponse")
	f.recordTake(t, exA, nil) // typed: no audio, no transcription possible
	exB := f.startPrompt(t, "sp-demande-renseignements")
	f.recordTake(t, exB, synthAudio("queue-untranscribed", 4_000))
	p := f.practice(t)
	if step(p, exA) != "add_transcript/<nil>/false" || step(p, exB) != "add_transcript/transcription/false" {
		t.Fatalf("transcription off: %s %s", step(p, exA), step(p, exB))
	}
	f.openProviders(t, true, false, 0)
	p = f.practice(t)
	if step(p, exA) != "add_transcript/<nil>/false" || step(p, exB) != "add_transcript/transcription/true" {
		t.Fatalf("transcription on: %s %s", step(p, exA), step(p, exB))
	}
	if got := summaryOf(p, "takes", "awaiting_transcript", "completed"); got != "takes=2 awaiting_transcript=2 completed=0" {
		t.Fatalf("summary: %s", got)
	}
}

func TestSpeakingQueue_RunningRequestsStayVisibleAndCompletedWins(t *testing.T) {
	f := newSpeakingFixture(t, true, 5*time.Second)
	ex := f.start(t)
	take, _ := f.recordTake(t, ex, nil)
	v1 := f.confirmedV1(t, ex, take)
	// A request that is still running: the exercise stays in the queue as
	// "check again", and the resume pointer names it.
	f.model.Set(listeningfake.ModeHang, 0, 1500*time.Millisecond)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		if status, out := f.feedback(t, v1, skeyA, ""); status != http.StatusCreated {
			t.Errorf("hung request: %d %v", status, out)
		}
	}()
	<-f.model.Arrived
	p := f.practice(t)
	if step(p, ex) != "request_in_progress/feedback/true" || path(p, "summary", "in_progress") != 1.0 || path(p, "resume", "exercise_id") != float64(ex) {
		t.Fatalf("running: %s %v %v", step(p, ex), p["summary"], p["resume"])
	}
	wg.Wait()
	p = f.practice(t)
	if step(p, ex) != "answer_again/<nil>/false" || path(p, "summary", "completed") != 1.0 || p["resume"] != nil {
		t.Fatalf("finished: %s %v %v", step(p, ex), p["summary"], p["resume"])
	}
	// A second request about the same version runs: the take stays completed
	// (it used to dip to "in progress" and drop out of the completed count).
	wg.Add(1)
	go func() {
		defer wg.Done()
		if status, out := f.feedback(t, v1, skeyB, ""); status != http.StatusCreated {
			t.Errorf("second request: %d %v", status, out)
		}
	}()
	<-f.model.Arrived
	p = f.practice(t)
	if takeState(f.view(t, ex), take) != domain.SpeakingFeedbackReady || path(p, "summary", "completed") != 1.0 ||
		path(p, "summary", "in_progress") != 0.0 || step(p, ex) != "answer_again/<nil>/false" {
		t.Fatalf("second request running: %s %v", step(p, ex), p["summary"])
	}
	wg.Wait()
}

func TestSpeakingQueue_ChangedPromptStaysActionableWithoutFeedback(t *testing.T) {
	f := newSpeakingFixture(t, false, 0)
	ex := f.start(t)
	take, _ := f.recordTake(t, ex, nil)
	f.confirmedV1(t, ex, take)
	if _, err := f.db.Exec(`UPDATE speaking_exercises SET situation = situation || ' (ancienne version)' WHERE id = ?`, ex); err != nil {
		t.Fatal(err)
	}
	p := f.practice(t)
	q := queueItem(p, ex)
	if step(p, ex) != "review_without_feedback/feedback/false" || q["pack_status"] != "changed" || path(p, "resume", "pack_status") != "changed" {
		t.Fatalf("changed prompt, feedback off: %s %v", step(p, ex), q)
	}
	if got := summaryOf(p, "takes", "completed", "awaiting_feedback"); got != "takes=1 completed=0 awaiting_feedback=1" {
		t.Fatalf("changed prompt: %s", got)
	}
	// Prompts not started carry no pack status and no request.
	for _, item := range p["queue"].([]any) {
		if path(item, "reason") == "not_started" && (path(item, "pack_status") != nil || path(item, "request") != nil) {
			t.Fatalf("not started: %v", item)
		}
	}
}

// A mixed history: counts follow each take's own state, and each exercise's
// step follows its latest take only.
func TestSpeakingQueue_MixedHistoryCountsAndNextActions(t *testing.T) {
	f := newSpeakingFixture(t, true, 0)
	exC := f.startPrompt(t, "sp-changement-programme") // started, no take
	exA := f.startPrompt(t, "sp-invitation-reponse")
	a1, _ := f.recordTake(t, exA, nil)
	if status, out := f.feedback(t, f.confirmedV1(t, exA, a1), skeyA, ""); status != http.StatusCreated {
		t.Fatalf("A1 feedback: %d %v", status, out)
	}
	a2, _ := f.recordTake(t, exA, nil) // pending: no transcript yet
	exB := f.startPrompt(t, "sp-demande-renseignements")
	b1, _ := f.recordTake(t, exB, nil)
	f.model.Set(listeningfake.ModeStatus, http.StatusInternalServerError, 0)
	if status, _ := f.feedback(t, f.confirmedV1(t, exB, b1), skeyB, ""); status != http.StatusBadGateway {
		t.Fatalf("B1 should fail: %d", status)
	}
	b2, _ := f.recordTake(t, exB, nil)
	f.model.Set(listeningfake.ModeDrop, 0, 0)
	if status, _ := f.feedback(t, f.confirmedV1(t, exB, b2), skeyC, ""); status != http.StatusBadGateway {
		t.Fatalf("B2 should be unknown: %d", status)
	}
	p := f.practice(t)
	if got := summaryOf(p, "started", "takes", "completed", "exercises_completed", "awaiting_transcript", "awaiting_feedback", "in_progress", "failed", "unknown"); got !=
		"started=3 takes=4 completed=1 exercises_completed=1 awaiting_transcript=1 awaiting_feedback=0 in_progress=0 failed=1 unknown=1" {
		t.Fatalf("mixed: %s", got)
	}
	if path(p, "summary", "last_completed_at") == nil {
		t.Fatal("a completed take has a completion time")
	}
	if got := strings.Join([]string{step(p, exA), step(p, exB), step(p, exC)}, " "); got !=
		"add_transcript/<nil>/false check_unknown_outcome/feedback/true start_first_take/<nil>/false" {
		t.Fatalf("mixed steps: %s", got)
	}
	if got := strings.Join(queueReasons(p), " "); got != "check_unknown_outcome:sp-demande-renseignements add_transcript:sp-invitation-reponse start_first_take:sp-changement-programme" {
		t.Fatalf("mixed order: %s", got)
	}
	if path(queueItem(p, exA), "take_id") != float64(a2) || path(p, "resume", "exercise_id") != float64(exB) {
		t.Fatalf("latest take and resume: %v %v", queueItem(p, exA), p["resume"])
	}
	// Typing A2's transcript makes A the most recent incomplete exercise.
	f.openProviders(t, true, false, 0)
	f.confirmedV1(t, exA, a2)
	p = f.practice(t)
	if step(p, exA) != "review_without_feedback/feedback/false" || path(p, "resume", "exercise_id") != float64(exA) ||
		path(p, "summary", "completed") != 1.0 || path(p, "summary", "awaiting_feedback") != 1.0 {
		t.Fatalf("after typing A2: %s %v %v", step(p, exA), p["resume"], p["summary"])
	}
}
