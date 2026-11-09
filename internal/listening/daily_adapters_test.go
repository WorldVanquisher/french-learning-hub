package listening_test

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening"
	"french-learning-app/internal/listening/listeningfake"
)

const (
	ytKey    = "yt-adapter-secret-key"
	tgToken  = "123456:tg-adapter-secret-token"
	chatID   = "-1009876543210"
	playlist = "PLflhAdapterTest01"
)

func videos(n int) []listeningfake.Video {
	out := make([]listeningfake.Video, n)
	for i := range out {
		out[i] = listeningfake.Video{ID: fmt.Sprintf("vid%08d", i), Title: fmt.Sprintf("Vidéo %d", i), PublishedAt: "2026-11-01T08:00:00Z"}
	}
	return out
}

func TestYouTubePlaylist_ReadsOfficialMetadataWithinBounds(t *testing.T) {
	fake := listeningfake.NewYouTube(t, ytKey, videos(130)...)
	src := listening.NewYouTubePlaylist(ytKey, playlist, fake.URL(), 120, time.Second)
	got, err := src.List(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Items) != 120 || got.Skipped != 0 || got.PlaylistID != playlist || fake.Calls() != 3 {
		t.Fatalf("items %d skipped %d calls %d", len(got.Items), got.Skipped, fake.Calls())
	}
	if got.Items[0].VideoID != "vid00000000" || got.Items[119].VideoID != "vid00000119" || got.Items[0].PublishedAt == nil {
		t.Fatalf("items = %+v … %+v", got.Items[0], got.Items[119])
	}
	q := fake.Queries()
	if q[0].Get("part") != "snippet,contentDetails,status" || q[0].Get("playlistId") != playlist || q[0].Get("maxResults") != "50" ||
		q[2].Get("maxResults") != "20" || q[1].Get("pageToken") != "page50" || q[0].Get("key") != "" || fake.KeyInURL() {
		t.Fatalf("queries = %v", q)
	}
}

func TestYouTubePlaylist_SkipsPrivateDeletedAndMalformedEntries(t *testing.T) {
	fake := listeningfake.NewYouTube(t, ytKey,
		listeningfake.Video{ID: "FLHpublic01", Title: "Public"},
		listeningfake.Video{ID: "FLHunlist01", Title: "Non répertoriée", Privacy: "unlisted"},
		listeningfake.Video{ID: "FLHprivat01", Title: "Private video", Privacy: "private"},
		listeningfake.Video{ID: "FLHdelete01", Title: "Deleted video", Privacy: "privacyStatusUnspecified"},
		listeningfake.Video{ID: "short", Title: "Bad ID"},
		listeningfake.Video{ID: "FLHnotitl01", Title: " \t "},
		listeningfake.Video{ID: "FLHcontrl01", Title: "Une\nligne\u0007 de trop"},
	)
	got, err := listening.NewYouTubePlaylist(ytKey, playlist, fake.URL(), 50, time.Second).List(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Items) != 3 || got.Skipped != 4 || got.Items[2].Title != "Une ligne de trop" {
		t.Fatalf("listing = %+v", got)
	}
}

func TestYouTubePlaylist_FailuresAreClassifiedWithoutSecrets(t *testing.T) {
	cases := []struct {
		name   string
		mode   string
		status int
		key    string
		want   error
	}{
		{"wrong key", listeningfake.ModeOK, 0, "another-key", domain.ErrPlaylistRefused},
		{"quota or forbidden", listeningfake.ModeStatus, http.StatusForbidden, ytKey, domain.ErrPlaylistRefused},
		{"unknown playlist", listeningfake.ModeStatus, http.StatusNotFound, ytKey, domain.ErrPlaylistRefused},
		{"server error", listeningfake.ModeStatus, http.StatusInternalServerError, ytKey, domain.ErrPlaylistUnavailable},
		{"malformed", listeningfake.ModeMalformed, 0, ytKey, domain.ErrPlaylistInvalid},
		{"dropped", listeningfake.ModeDrop, 0, ytKey, domain.ErrPlaylistUnavailable},
		{"timeout", listeningfake.ModeHang, 0, ytKey, domain.ErrPlaylistTimeout},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			fake := listeningfake.NewYouTube(t, ytKey, videos(3)...)
			fake.Set(c.mode, c.status, 2*time.Second)
			_, err := listening.NewYouTubePlaylist(c.key, playlist, fake.URL(), 50, 200*time.Millisecond).List(context.Background())
			if !errors.Is(err, c.want) {
				t.Fatalf("err = %v, want %v", err, c.want)
			}
			if msg := err.Error(); strings.Contains(msg, ytKey) || strings.Contains(msg, "another-key") || strings.Contains(msg, fake.URL()) {
				t.Fatalf("error leaks: %s", msg)
			}
		})
	}
}

func TestTelegram_SendsTheTitleOnlyAndClassifiesOutcomes(t *testing.T) {
	notice := domain.LessonReadyNotice{Title: "La minute du quartier"}
	fake := listeningfake.NewTelegram(t, tgToken)
	tg := listening.NewTelegram(tgToken, chatID, fake.URL(), 300*time.Millisecond)
	if err := tg.NotifyLessonReady(context.Background(), notice); err != nil {
		t.Fatal(err)
	}
	msgs := fake.Messages()
	if len(msgs) != 1 || msgs[0].ChatID != chatID || !strings.Contains(msgs[0].Text, "«La minute du quartier»") || strings.Contains(fake.Bodies()[0], tgToken) {
		t.Fatalf("messages = %+v body %s", msgs, fake.Bodies()[0])
	}

	closed, _ := net.Listen("tcp", "127.0.0.1:0")
	deadURL := "http://" + closed.Addr().String()
	closed.Close()
	cases := []struct {
		name    string
		mode    string
		status  int
		url     string
		outcome string
		code    string
	}{
		{"refused by the API", listeningfake.ModeStatus, http.StatusBadRequest, "", domain.ListeningOutcomeFailed, domain.NotificationRefused},
		{"rate limited", listeningfake.ModeStatus, http.StatusTooManyRequests, "", domain.ListeningOutcomeFailed, domain.NotificationRefused},
		{"never sent", listeningfake.ModeOK, 0, deadURL, domain.ListeningOutcomeFailed, domain.NotificationNotSent},
		{"lost answer", listeningfake.ModeDrop, 0, "", domain.ListeningOutcomeUnknown, domain.NotificationNoResponse},
		{"timeout after sending", listeningfake.ModeHang, 0, "", domain.ListeningOutcomeUnknown, domain.NotificationNoResponse},
		{"unreadable 200", listeningfake.ModeMalformed, 0, "", domain.ListeningOutcomeUnknown, domain.NotificationNoResponse},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			f := listeningfake.NewTelegram(t, tgToken)
			f.Set(c.mode, c.status, 2*time.Second)
			url := f.URL()
			if c.url != "" {
				url = c.url
			}
			err := listening.NewTelegram(tgToken, chatID, url, 300*time.Millisecond).NotifyLessonReady(context.Background(), notice)
			outcome, code := domain.NotificationResult(err)
			if outcome != c.outcome || code != c.code {
				t.Fatalf("err %v -> %s/%s, want %s/%s", err, outcome, code, c.outcome, c.code)
			}
			if msg := err.Error(); strings.Contains(msg, tgToken) || strings.Contains(msg, chatID) || strings.Contains(msg, "minute") {
				t.Fatalf("error leaks: %s", msg)
			}
		})
	}
}

func TestLessonReadyNotice_CarriesNoTranscriptOrLink(t *testing.T) {
	text := domain.LessonReadyNotice{Title: "Titre"}.Text()
	if !strings.Contains(text, "«Titre»") || strings.Contains(text, "http") || strings.Contains(text, "youtube") {
		t.Fatalf("text = %q", text)
	}
}

func TestOpenAI_LostResponseIsAnUnknownOutcome(t *testing.T) {
	fake := listeningfake.NewResponses(t, "sk-lost", "{}")
	fake.Set(listeningfake.ModeDrop, 0, 0)
	gen := listening.NewOpenAI("sk-lost", "m", fake.URL(), time.Second)
	_, err := gen.Generate(context.Background(), domain.ListeningGenerationRequest{Title: "t", Segments: []domain.TranscriptSegment{{Index: 1, Text: "Bonjour."}}})
	if !errors.Is(err, domain.ErrOutcomeUnknown) || domain.PreparationOutcome(err) != domain.ListeningOutcomeUnknown {
		t.Fatalf("err = %v", err)
	}
	closed, _ := net.Listen("tcp", "127.0.0.1:0")
	addr := closed.Addr().String()
	closed.Close()
	_, err = listening.NewOpenAI("sk-lost", "m", "http://"+addr, time.Second).Generate(context.Background(),
		domain.ListeningGenerationRequest{Title: "t", Segments: []domain.TranscriptSegment{{Index: 1, Text: "Bonjour."}}})
	if errors.Is(err, domain.ErrOutcomeUnknown) || domain.PreparationOutcome(err) != domain.ListeningOutcomeFailed {
		t.Fatalf("a request that never left is a definite failure: %v", err)
	}
}
