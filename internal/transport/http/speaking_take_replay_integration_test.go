package http_test

// A resent take save never creates a second attempt: the same audio names the
// existing take (speaking_practice_integration_test.go), and so does a typed
// save while the exercise's latest take is a typed take with no transcript yet.
// Decided inside the write transaction, so concurrent saves agree.

import (
	"net/http"
	"sync"
	"testing"
)

func TestSpeakingTakes_TypedSaveNamesTheEmptyTypedTake(t *testing.T) {
	f := newSpeakingFixture(t, false, 0)
	ex := f.start(t)
	typed := map[string]any{"audio_source": "none"}
	status, first, _ := f.postTake(t, ex, typed)
	if status != http.StatusCreated || first["replayed"] != false {
		t.Fatalf("first typed save: %d %v", status, first)
	}
	take1 := first["take_id"]
	// The answer was lost and the save is sent again: the same, still empty take.
	status, again, hdr := f.postTake(t, ex, typed)
	if status != http.StatusOK || hdr.Get("Idempotency-Replayed") != "true" || again["take_id"] != take1 || again["replayed"] != true ||
		len(again["takes"].([]any)) != 1 {
		t.Fatalf("resent typed save: %d %v", status, again)
	}
	// Once take 1 has a transcript, a typed save is a new attempt.
	f.confirmedV1(t, ex, int64(take1.(float64)))
	status, second, _ := f.postTake(t, ex, typed)
	if status != http.StatusCreated || second["take_id"] == take1 {
		t.Fatalf("typed save after a transcript: %d %v", status, second)
	}
	// A recording in between: the next typed save is new, then replays.
	audio := synthAudio("replay-typed", 4_000)
	body := map[string]any{"audio_source": "recording", "audio_mime": "audio/wav", "audio_bytes": len(audio), "audio_sha256": digest(audio), "duration_ms": 30_000}
	if status, out, _ := f.postTake(t, ex, body); status != http.StatusCreated {
		t.Fatalf("recording: %d %v", status, out)
	}
	status, fourth, _ := f.postTake(t, ex, typed)
	if status != http.StatusCreated {
		t.Fatalf("typed after a recording: %d %v", status, fourth)
	}
	if status, out, _ := f.postTake(t, ex, typed); status != http.StatusOK || out["take_id"] != fourth["take_id"] {
		t.Fatalf("typed resent after a recording: %d %v", status, out)
	}
	if n := len(f.view(t, ex)["takes"].([]any)); n != 4 {
		t.Fatalf("takes: %d, want 4", n)
	}
}

func TestSpeakingTakes_ConcurrentTypedSavesMakeOneTake(t *testing.T) {
	f := newSpeakingFixture(t, false, 0)
	ex := f.start(t)
	const n = 8
	var wg sync.WaitGroup
	statuses := make([]int, n)
	ids := make([]any, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			status, out, _ := f.postTake(t, ex, map[string]any{"audio_source": "none"})
			statuses[i], ids[i] = status, out["take_id"]
		}(i)
	}
	wg.Wait()
	created := 0
	for i := range statuses {
		if statuses[i] == http.StatusCreated {
			created++
		} else if statuses[i] != http.StatusOK {
			t.Fatalf("save %d: %d", i, statuses[i])
		}
		if ids[i] != ids[0] {
			t.Fatalf("saves named different takes: %v", ids)
		}
	}
	if created != 1 || len(f.view(t, ex)["takes"].([]any)) != 1 {
		t.Fatalf("created %d, takes %d", created, len(f.view(t, ex)["takes"].([]any)))
	}
}
