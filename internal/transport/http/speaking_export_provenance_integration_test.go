package http_test

// The attempt export carries each take's prompt revision, transcript and
// feedback provenance exactly as stored, including after the set corrected the
// prompt: the stored wording's fingerprint (not the set's), every confirmed
// version with its origin and machine transcript, and every report on its own
// version with its generator, oldest first.

import (
	"bufio"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening/listeningfake"
)

func TestSpeakingExport_CarriesRevisionTranscriptAndFeedbackProvenance(t *testing.T) {
	f := newSpeakingFixture(t, true, 0)
	ex := f.start(t)
	audio := synthAudio("export-provenance", 4_000)
	take1, _ := f.recordTake(t, ex, audio)
	status, res, _ := f.transcribe(t, take1, skeyA, audio, "audio/wav", false)
	if status != http.StatusCreated {
		t.Fatalf("transcribe: %d %v", status, res)
	}
	machineID := path(res, "transcription", "id")
	_, view := f.confirm(t, take1, transcriptV1(t), machineID) // corrected from the machine transcript
	v1 := transcriptID(view, take1, 1)
	if status, out := f.feedback(t, v1, skeyB, ""); status != http.StatusCreated {
		t.Fatalf("feedback v1: %d %v", status, out)
	}
	_, view = f.confirm(t, take1, transcriptV2(t), nil) // a correction of v1
	v2 := transcriptID(view, take1, 2)
	f.model.Set(listeningfake.ModeStatus, http.StatusInternalServerError, 0)
	if status, _ := f.feedback(t, v2, skeyC, ""); status != http.StatusBadGateway {
		t.Fatal("v2 feedback should fail")
	}
	f.model.Set(listeningfake.ModeOK, 0, 0)
	if status, out := f.feedback(t, v2, skeyD, ""); status != http.StatusCreated {
		t.Fatalf("v2 retry: %d %v", status, out)
	}
	take2, _ := f.recordTake(t, ex, nil)
	f.confirmedV1(t, ex, take2)
	before := path(f.view(t, ex), "exercise", "content_fingerprint")
	// The set corrects the prompt after the learner answered it.
	if _, err := f.db.Exec(`UPDATE speaking_exercises SET requirements = '["Remerciez Léa pour l''invitation."]' WHERE id = ?`, ex); err != nil {
		t.Fatal(err)
	}
	answered := path(f.view(t, ex), "exercise", "content_fingerprint")
	setPrompt := path(f.view(t, ex), "current_prompt", "content_fingerprint")
	if answered == before || setPrompt != before {
		t.Fatalf("fixture: before %v, answered %v, set %v", before, answered, setPrompt)
	}

	resp, err := http.Get(f.srv.URL + "/speaking/export")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	var lines []map[string]any
	sc := bufio.NewScanner(strings.NewReader(string(raw)))
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		var m map[string]any
		if err := json.Unmarshal(sc.Bytes(), &m); err != nil {
			t.Fatal(err)
		}
		lines = append(lines, m)
	}
	if len(lines) != 2 {
		t.Fatalf("export lines: %d", len(lines))
	}
	for _, l := range lines {
		if path(l, "exercise", "content_fingerprint") != answered || path(l, "exercise", "pack_status") != domain.SpeakingPackChanged ||
			path(l, "exercise", "prompt_set") != domain.SpeakingPromptsID {
			t.Fatalf("revision provenance: %v", l["exercise"])
		}
	}
	// Take 1: two versions (corrected from the machine transcript, then corrected
	// again), one machine transcription, three reports on their own versions.
	l := lines[0]
	trs, scripts, fb := l["transcriptions"].([]any), l["transcripts"].([]any), l["feedback"].([]any)
	if path(l, "take", "id") != float64(take1) || path(l, "take", "state") != domain.SpeakingFeedbackReady || len(trs) != 1 ||
		path(trs[0], "id") != machineID || path(trs[0], "transcriber") != "openai:fake-transcribe:speaking_transcription_v1" {
		t.Fatalf("take 1 transcriptions: %v", l)
	}
	if len(scripts) != 2 || path(scripts[0], "id") != float64(v1) || path(scripts[0], "origin") != "corrected" ||
		path(scripts[0], "transcription_id") != machineID || path(scripts[1], "id") != float64(v2) || path(scripts[1], "version") != 2.0 ||
		path(scripts[1], "origin") != "corrected" || path(scripts[1], "transcription_id") != nil {
		t.Fatalf("take 1 transcripts: %v", scripts)
	}
	wantFB := []struct {
		transcript int64
		status     string
	}{{v1, "completed"}, {v2, "failed"}, {v2, "completed"}}
	if len(fb) != len(wantFB) {
		t.Fatalf("take 1 feedback: %v", fb)
	}
	for i, w := range wantFB {
		if path(fb[i], "transcript_id") != float64(w.transcript) || path(fb[i], "status") != w.status ||
			path(fb[i], "generator") != "openai:fake-model:speaking_feedback_v1" {
			t.Fatalf("take 1 feedback %d: %v", i, fb[i])
		}
	}
	if path(fb[1], "failure_code") != "provider_unavailable" || path(fb[1], "content") != nil || path(fb[2], "content") == nil {
		t.Fatalf("failed report: %v", fb[1])
	}
	// Take 2: typed, one version, no machine transcript, no report.
	l = lines[1]
	if path(l, "take", "id") != float64(take2) || path(l, "take", "audio_source") != "none" || path(l, "take", "state") != domain.SpeakingAwaitingFeedback ||
		len(l["transcriptions"].([]any)) != 0 || len(l["feedback"].([]any)) != 0 || path(l["transcripts"].([]any)[0], "origin") != "typed" {
		t.Fatalf("take 2: %v", l)
	}
}
