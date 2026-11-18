package http_test

// Speaking practice overview, attempt states, take replay and export, end to
// end over the real handler, repository and provider clients against the
// local fakes (see speaking_integration_test.go).

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
	"french-learning-app/internal/speaking/speakingfake"
)

func (f *speakingFixture) practice(t *testing.T) map[string]any {
	t.Helper()
	status, out := doJSON(t, http.MethodGet, f.srv.URL+"/speaking/practice", "")
	if status != http.StatusOK || out["schema_version"] != domain.SpeakingPracticeVersion {
		t.Fatalf("practice: %d %v", status, out)
	}
	s := out["summary"].(map[string]any)
	sum := 0.0
	for _, k := range []string{"completed", "awaiting_transcript", "awaiting_feedback", "in_progress", "failed", "unknown"} {
		sum += s[k].(float64)
	}
	if sum != s["takes"].(float64) {
		t.Fatalf("summary counts do not add up to the takes: %v", s)
	}
	return out
}

// queueReasons lists "reason:prompt" in queue order.
func queueReasons(p map[string]any) []string {
	out := []string{}
	for _, q := range p["queue"].([]any) {
		out = append(out, fmt.Sprintf("%s:%s", path(q, "reason"), path(q, "prompt_id")))
	}
	return out
}

func takeState(view map[string]any, take int64) string {
	for _, k := range view["takes"].([]any) {
		if path(k, "id") == float64(take) {
			return path(k, "state").(string)
		}
	}
	return ""
}

func (f *speakingFixture) postTake(t *testing.T, ex int64, body map[string]any) (int, map[string]any, http.Header) {
	t.Helper()
	raw, _ := json.Marshal(body)
	status, out, hdr, err := keyed(t, http.DefaultClient, http.MethodPost, fmt.Sprintf("%s/speaking/exercises/%d/takes", f.srv.URL, ex), "", string(raw))
	if err != nil {
		t.Fatal(err)
	}
	return status, out, hdr
}

func TestSpeakingPractice_QueueStatesAndCountsFollowTheRecords(t *testing.T) {
	f := newSpeakingFixture(t, true, 0)
	p := f.practice(t)
	if got := strings.Join(queueReasons(p), " "); got != "not_started:sp-invitation-reponse not_started:sp-demande-renseignements not_started:sp-changement-programme" {
		t.Fatalf("empty history queue: %s", got)
	}
	if path(p, "summary", "prompts") != 3.0 || path(p, "summary", "takes") != 0.0 || path(p, "summary", "last_completed_at") != nil {
		t.Fatalf("empty summary: %v", p["summary"])
	}
	ex := f.start(t)
	if got := queueReasons(f.practice(t))[0]; got != "start_first_take:sp-invitation-reponse" {
		t.Fatalf("started, no take: %s", got)
	}

	// A take; the same save sent again names the same take.
	audio := synthAudio("practice", 4_000)
	body := map[string]any{"audio_source": "recording", "audio_mime": "audio/wav", "audio_bytes": len(audio), "audio_sha256": digest(audio), "duration_ms": 41_400}
	status, first, _ := f.postTake(t, ex, body)
	if status != http.StatusCreated || first["replayed"] != false {
		t.Fatalf("first save: %d %v", status, first)
	}
	take1 := int64(first["take_id"].(float64))
	status, again, hdr := f.postTake(t, ex, body)
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || again["take_id"] != float64(take1) || len(again["takes"].([]any)) != 1 {
		t.Fatalf("resent save: %d %v", status, again)
	}
	other := map[string]any{}
	for k, v := range body {
		other[k] = v
	}
	other["duration_ms"] = 12_000
	if status, out, _ := f.postTake(t, ex, other); status != http.StatusConflict || out["code"] != "take_conflict" {
		t.Fatalf("same audio, other details: %d %v", status, out)
	}
	if st := takeState(f.view(t, ex), take1); st != domain.SpeakingAwaitingTranscript {
		t.Fatalf("new take: %s", st)
	}
	if got := queueReasons(f.practice(t))[0]; got != "add_transcript:sp-invitation-reponse" {
		t.Fatalf("take without transcript: %s", got)
	}

	// Machine transcript → to confirm → confirmed → feedback.
	status, res, _ := f.transcribe(t, take1, skeyA, audio, "audio/wav", false)
	if status != http.StatusCreated {
		t.Fatalf("transcribe: %d %v", status, res)
	}
	if st := takeState(f.view(t, ex), take1); st != domain.SpeakingTranscriptToConfirm {
		t.Fatalf("machine transcript: %s", st)
	}
	status, view := f.confirm(t, take1, transcriptV1(t), path(res, "transcription", "id"))
	if status != http.StatusCreated || takeState(view, take1) != domain.SpeakingAwaitingFeedback {
		t.Fatalf("confirmed: %d %v", status, takeState(view, take1))
	}
	if got := queueReasons(f.practice(t))[0]; got != "request_feedback:sp-invitation-reponse" {
		t.Fatalf("awaiting feedback: %s", got)
	}
	v1 := transcriptID(view, take1, 1)
	f.model.Set(listeningfake.ModeStatus, http.StatusInternalServerError, 0)
	if status, out := f.feedback(t, v1, skeyB, ""); status != http.StatusBadGateway {
		t.Fatalf("failed feedback: %d %v", status, out)
	}
	p = f.practice(t)
	if takeState(f.view(t, ex), take1) != domain.SpeakingFeedbackFailed || queueReasons(p)[0] != "request_failed:sp-invitation-reponse" ||
		path(p, "summary", "failed") != 1.0 || path(p, "summary", "completed") != 0.0 {
		t.Fatalf("after a failed report: %v %v", queueReasons(p), p["summary"])
	}
	f.model.Set(listeningfake.ModeOK, 0, 0)
	if status, out := f.feedback(t, v1, skeyC, ""); status != http.StatusCreated {
		t.Fatalf("feedback: %d %v", status, out)
	}
	p = f.practice(t)
	q := p["queue"].([]any)[0]
	if path(q, "reason") != domain.SpeakingQueueAnswerAgain || path(q, "take_number") != 1.0 || path(q, "improvements").(float64) < 1 ||
		path(p, "summary", "completed") != 1.0 || path(p, "summary", "exercises_completed") != 1.0 || path(p, "summary", "last_completed_at") == nil {
		t.Fatalf("completed: %v %v", q, p["summary"])
	}

	// A second, typed take is the latest attempt: the queue follows it, and the
	// completed first take still counts.
	status, second, _ := f.postTake(t, ex, map[string]any{"audio_source": "none"})
	if status != http.StatusCreated {
		t.Fatalf("typed take: %d %v", status, second)
	}
	take2 := int64(second["take_id"].(float64))
	p = f.practice(t)
	if queueReasons(p)[0] != "add_transcript:sp-invitation-reponse" || path(p["queue"].([]any)[0], "take_id") != float64(take2) ||
		path(p, "summary", "takes") != 2.0 || path(p, "summary", "completed") != 1.0 || path(p, "summary", "awaiting_transcript") != 1.0 {
		t.Fatalf("second take: %v %v", queueReasons(p), p["summary"])
	}
	latest := path(p["exercises"].([]any)[0], "latest")
	if path(latest, "take_number") != 2.0 || path(latest, "audio_source") != "none" || path(p["exercises"].([]any)[0], "completed") != 1.0 {
		t.Fatalf("exercise row: %v", p["exercises"])
	}

	// A new version of take 1 has other words: the report on version 1 does
	// not complete it, so it leaves the completed count.
	if status, view = f.confirm(t, take1, transcriptV2(t), nil); status != http.StatusCreated || takeState(view, take1) != domain.SpeakingAwaitingFeedback {
		t.Fatalf("version 2: %d %s", status, takeState(view, take1))
	}
	if p = f.practice(t); path(p, "summary", "completed") != 0.0 || path(p, "summary", "awaiting_feedback") != 1.0 || path(p, "summary", "exercises_completed") != 0.0 {
		t.Fatalf("after version 2: %v", p["summary"])
	}

	// Export: one line per take, references and provenance kept, never audio.
	resp, err := http.Get(f.srv.URL + "/speaking/export")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusOK || !strings.HasPrefix(resp.Header.Get("Content-Type"), "application/x-ndjson") {
		t.Fatalf("export: %d %s", resp.StatusCode, resp.Header.Get("Content-Type"))
	}
	lines := []map[string]any{}
	sc := bufio.NewScanner(strings.NewReader(string(raw)))
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		var m map[string]any
		if err := json.Unmarshal(sc.Bytes(), &m); err != nil {
			t.Fatalf("export line: %v", err)
		}
		lines = append(lines, m)
	}
	if len(lines) != 2 || path(lines[0], "take", "id") != float64(take1) || path(lines[1], "take", "id") != float64(take2) {
		t.Fatalf("export lines: %s", raw)
	}
	l := lines[0]
	exJSON := path(f.view(t, ex), "exercise")
	if l["schema_version"] != domain.SpeakingExportVersion || path(l, "exercise", "prompt_set") != domain.SpeakingPromptsID ||
		path(l, "exercise", "content_fingerprint") != path(exJSON, "content_fingerprint") || path(l, "exercise", "pack_status") != "current" ||
		path(l, "take", "audio_sha256") != digest(audio) || path(l, "take", "state") != domain.SpeakingAwaitingFeedback ||
		len(l["transcripts"].([]any)) != 2 || len(l["transcriptions"].([]any)) != 1 || len(l["feedback"].([]any)) != 2 ||
		path(l["feedback"].([]any)[0], "status") != "failed" || path(l["feedback"].([]any)[1], "generator") != "openai:fake-model:speaking_feedback_v1" ||
		path(l["transcriptions"].([]any)[0], "transcriber") != "openai:fake-transcribe:speaking_transcription_v1" {
		t.Fatalf("export line 1: %v", l)
	}
	if strings.Contains(string(raw), "audio_base64") || strings.Contains(string(raw), speakingKey) {
		t.Fatal("the export carries audio or a key")
	}
}

func TestSpeakingPractice_UnknownOutcomeAndDisabledFeedback(t *testing.T) {
	f := newSpeakingFixture(t, true, 300*time.Millisecond)
	ex := f.start(t)
	audio := synthAudio("unknown", 4_000)
	take, _ := f.recordTake(t, ex, audio)
	f.stt.Set(speakingfake.ModeDrop, 0, 0)
	if status, res, _ := f.transcribe(t, take, skeyA, audio, "audio/wav", false); status != http.StatusBadGateway {
		t.Fatalf("dropped: %d %v", status, res)
	}
	p := f.practice(t)
	if takeState(f.view(t, ex), take) != domain.SpeakingTranscriptionUnknown || queueReasons(p)[0] != "check_unknown_outcome:sp-invitation-reponse" ||
		path(p, "summary", "unknown") != 1.0 {
		t.Fatalf("unknown outcome: %v %v", queueReasons(p), p["summary"])
	}
	// Restart without providers: the records are unchanged, a typed version
	// waits for feedback that cannot be requested, so no queue item asks for it.
	f.open(t, false, 0)
	status, view := f.confirm(t, take, transcriptV1(t), nil)
	if status != http.StatusCreated || takeState(view, take) != domain.SpeakingAwaitingFeedback {
		t.Fatalf("typed version: %d %v", status, takeState(view, take))
	}
	p = f.practice(t)
	for _, r := range queueReasons(p) {
		if strings.HasPrefix(r, "request_feedback") || strings.HasSuffix(r, ":sp-invitation-reponse") {
			t.Fatalf("feedback disabled, yet queued: %v", queueReasons(p))
		}
	}
	if path(p, "summary", "awaiting_feedback") != 1.0 || path(p, "providers", "feedback", "enabled") != false {
		t.Fatalf("disabled summary: %v", p["summary"])
	}
}

func TestSpeakingPractice_ChangedPromptKeepsTakesAndDropsTheNewExample(t *testing.T) {
	f := newSpeakingFixture(t, false, 0)
	ex := f.start(t)
	take, _ := f.recordTake(t, ex, synthAudio("changed", 4_000))
	before := f.view(t, ex)
	if path(before, "exercise", "pack_status") != "current" || before["example_transcript"] == nil {
		t.Fatalf("current prompt: %v %v", path(before, "exercise"), before["example_transcript"])
	}
	// The set is corrected after the learner started (simulated by the stored
	// wording differing from the embedded one).
	if _, err := f.db.Exec(`UPDATE speaking_exercises SET situation = situation || ' (ancienne version)' WHERE id = ?`, ex); err != nil {
		t.Fatal(err)
	}
	after := f.view(t, ex)
	if path(after, "exercise", "pack_status") != "changed" || after["example_transcript"] != nil ||
		path(after, "exercise", "content_fingerprint") == path(before, "exercise", "content_fingerprint") ||
		takeState(after, take) != domain.SpeakingAwaitingTranscript || !strings.HasSuffix(path(after, "exercise", "situation").(string), "(ancienne version)") {
		t.Fatalf("changed prompt: %v %v", path(after, "exercise"), after["example_transcript"])
	}
	_, prompts := doJSON(t, http.MethodGet, f.srv.URL+"/speaking/prompts", "")
	p0 := prompts["prompts"].([]any)[0]
	if path(p0, "started_exercise_id") != float64(ex) || path(p0, "started_pack_status") != "changed" || path(prompts["prompts"].([]any)[1], "started_pack_status") != nil {
		t.Fatalf("prompt list: %v", prompts["prompts"])
	}
	if status, out := doJSON(t, http.MethodPost, f.srv.URL+"/speaking/prompts/sp-invitation-reponse", ""); status != http.StatusConflict || out["code"] != "prompt_conflict" {
		t.Fatalf("restart: %d %v", status, out)
	}
	if p := f.practice(t); path(p["exercises"].([]any)[0], "exercise", "pack_status") != "changed" || path(p, "summary", "takes") != 1.0 {
		t.Fatalf("practice: %v", p["exercises"])
	}
}

func TestSpeakingPractice_ConcurrentSavesOfOneRecordingMakeOneTake(t *testing.T) {
	f := newSpeakingFixture(t, false, 0)
	ex := f.start(t)
	audio := synthAudio("concurrent", 4_000)
	body := map[string]any{"audio_source": "recording", "audio_mime": "audio/wav", "audio_bytes": len(audio), "audio_sha256": digest(audio), "duration_ms": 9_000}
	var wg sync.WaitGroup
	statuses := make([]int, 8)
	ids := make([]any, 8)
	for i := range statuses {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			raw, _ := json.Marshal(body)
			req, _ := http.NewRequest(http.MethodPost, fmt.Sprintf("%s/speaking/exercises/%d/takes", f.srv.URL, ex), strings.NewReader(string(raw)))
			req.Header.Set("Content-Type", "application/json")
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				return
			}
			defer resp.Body.Close()
			var out map[string]any
			_ = json.NewDecoder(resp.Body).Decode(&out)
			statuses[i], ids[i] = resp.StatusCode, out["take_id"]
		}(i)
	}
	wg.Wait()
	created := 0
	for i, s := range statuses {
		if s == http.StatusCreated {
			created++
		} else if s != http.StatusOK {
			t.Fatalf("save %d: %d", i, s)
		}
		if ids[i] != ids[0] {
			t.Fatalf("saves named different takes: %v", ids)
		}
	}
	if created != 1 || len(f.view(t, ex)["takes"].([]any)) != 1 {
		t.Fatalf("one recording, %d created: %v", created, statuses)
	}
	// Distinct recordings saved at once get distinct, consecutive numbers.
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			a := synthAudio(fmt.Sprintf("distinct-%d", i), 4_000)
			raw, _ := json.Marshal(map[string]any{"audio_source": "file", "audio_mime": "audio/wav", "audio_bytes": len(a), "audio_sha256": digest(a), "duration_ms": 9_000})
			resp, err := http.Post(fmt.Sprintf("%s/speaking/exercises/%d/takes", f.srv.URL, ex), "application/json", strings.NewReader(string(raw)))
			if err == nil {
				_ = resp.Body.Close()
			}
		}(i)
	}
	wg.Wait()
	takes := f.view(t, ex)["takes"].([]any)
	for i, k := range takes {
		if path(k, "number") != float64(i+1) {
			t.Fatalf("take numbers: %v", takes)
		}
	}
	if len(takes) != 7 {
		t.Fatalf("want 7 takes, got %d", len(takes))
	}
}
