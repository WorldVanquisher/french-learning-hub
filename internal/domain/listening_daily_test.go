package domain

import (
	"fmt"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

func TestAttemptStates(t *testing.T) {
	now := time.Date(2026, 11, 9, 8, 0, 0, 0, time.UTC)
	p := ListeningPreparation{DeadlineAt: now.Add(time.Minute)}
	if p.State(now) != ListeningStateInProgress || p.State(now.Add(time.Minute)) != ListeningOutcomeUnknown {
		t.Fatal("an unfinished attempt is in progress before its deadline and unknown from it on")
	}
	p.Outcome = ListeningOutcomeFailed
	if p.State(now.Add(time.Hour)) != ListeningOutcomeFailed {
		t.Fatal("a finished attempt keeps its outcome")
	}
	run := ListeningPullRun{Status: ListeningPullRunning, LeaseExpiresAt: now}
	if run.EffectiveStatus(now.Add(-time.Second)) != ListeningPullRunning || run.EffectiveStatus(now) != ListeningPullInterrupted {
		t.Fatal("a running run past its lease reads as interrupted")
	}
}

func TestOutcomeClassification(t *testing.T) {
	cases := []struct {
		err  error
		want string
	}{
		{nil, ListeningOutcomeCompleted},
		{fmt.Errorf("%w: x", ErrProviderTimeout), ListeningOutcomeUnknown},
		{fmt.Errorf("%w: %w: x", ErrProviderUnavailable, ErrOutcomeUnknown), ListeningOutcomeUnknown},
		{fmt.Errorf("%w: HTTP 500", ErrProviderUnavailable), ListeningOutcomeFailed},
		{fmt.Errorf("%w: bad", ErrValidation), ListeningOutcomeFailed},
	}
	for _, c := range cases {
		if got := PreparationOutcome(c.err); got != c.want {
			t.Errorf("PreparationOutcome(%v) = %s, want %s", c.err, got, c.want)
		}
	}
	for err, want := range map[error]string{
		nil:                       "sent/",
		ErrNotificationNotSent:    "failed/not_sent",
		ErrNotificationRefused:    "failed/refused",
		ErrNotificationNoResponse: "unknown/no_response",
		fmt.Errorf("other"):       "unknown/no_response",
	} {
		if o, c := NotificationResult(err); o+"/"+c != want {
			t.Errorf("NotificationResult(%v) = %s/%s, want %s", err, o, c, want)
		}
	}
	for err, want := range map[error]string{
		ErrPlaylistTimeout: ListeningSourceTimeout, ErrPlaylistRefused: ListeningSourceRefused,
		ErrPlaylistInvalid: ListeningSourceInvalidResponse, ErrPlaylistUnavailable: ListeningSourceUnavailable,
	} {
		if got := PlaylistFailureCode(fmt.Errorf("%w: x", err)); got != want {
			t.Errorf("PlaylistFailureCode(%v) = %s", err, got)
		}
	}
}

func TestNormalizePlaylistTitle(t *testing.T) {
	if got := NormalizePlaylistTitle("  Le\tmarché\n du\u0007 samedi "); got != "Le marché du samedi" {
		t.Fatalf("got %q", got)
	}
	long := NormalizePlaylistTitle(strings.Repeat("é", 300))
	if utf8.RuneCountInString(long) != MaxListeningTitleRunes || !strings.HasSuffix(long, "…") {
		t.Fatalf("long title has %d runes", utf8.RuneCountInString(long))
	}
	if _, err := NormalizeListeningTitle(long); err != nil {
		t.Fatalf("a normalized title must be a valid material title: %v", err)
	}
}

func TestListeningDayFollowsTheTimezone(t *testing.T) {
	paris, _ := time.LoadLocation("Europe/Paris")
	at := time.Date(2026, 11, 9, 23, 30, 0, 0, time.UTC)
	if ListeningDay(at, time.UTC) != "2026-11-09" || ListeningDay(at, paris) != "2026-11-10" {
		t.Fatal("the local day follows LISTENING_TIMEZONE")
	}
}
