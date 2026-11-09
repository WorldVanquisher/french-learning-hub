// Command listening-pull runs the Daily Listening pull: the same operation as
// the workbench's "Pull now" button, built from the same configuration as the
// server (environment plus optional .env in the working directory) and the same
// database. A systemd timer runs it with -trigger scheduled; see
// scripts/daily/systemd/.
//
//	listening-pull [-json] [-trigger manual|scheduled]   run one pull now
//	listening-pull [-json] status                        settings, today's cap use and the last pull (read-only)
//
// A pull reads the configured playlist's official metadata (new video IDs wait
// for the learner's transcript), prepares at most one lesson per local day when
// LISTENING_AUTO_PREPARE=daily, and announces that lesson when
// LISTENING_NOTIFY=telegram. Runs never overlap: while another pull (button or
// command) holds its lease, nothing starts. Nothing is retried: a failed or
// unknown step is reported and waits for an explicit action in the workbench.
//
// Exit status: 0 finished and nothing needs attention; 3 finished, but a step
// failed or its outcome is unknown; 4 another pull is running (nothing
// started); 5 daily listening is not configured; 1 error (configuration,
// database, interrupted run); 2 usage.
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/config"
	"french-learning-app/internal/domain"
	"french-learning-app/internal/listening"
	"french-learning-app/internal/storage/sqlite"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	code := run(ctx, os.Args[1:], os.Stdout, os.Stderr)
	stop()
	os.Exit(code)
}

const (
	exitOK         = 0
	exitError      = 1
	exitUsage      = 2
	exitAttention  = 3
	exitBusy       = 4
	exitNotEnabled = 5
)

func run(ctx context.Context, args []string, stdout, stderr io.Writer) int {
	flags := flag.NewFlagSet("listening-pull", flag.ContinueOnError)
	flags.SetOutput(stderr)
	asJSON := flags.Bool("json", false, "print the result as JSON")
	trigger := flags.String("trigger", domain.ListeningPullManual, "manual (run by hand) or scheduled (run by a timer)")
	if err := flags.Parse(args); err != nil {
		return exitUsage
	}
	status := false
	switch {
	case flags.NArg() == 0:
	case flags.NArg() == 1 && flags.Arg(0) == "status":
		status = true
	default:
		fmt.Fprintln(stderr, "usage: listening-pull [-json] [-trigger manual|scheduled] | listening-pull [-json] status")
		return exitUsage
	}
	if *trigger != domain.ListeningPullManual && *trigger != domain.ListeningPullScheduled {
		fmt.Fprintln(stderr, "-trigger must be manual or scheduled")
		return exitUsage
	}

	cfg, err := config.Load()
	if err != nil {
		fmt.Fprintf(stderr, "configuration: %v\n", err)
		return exitError
	}
	db, err := sqlite.Open(cfg.DBPath)
	if err != nil {
		fmt.Fprintf(stderr, "open database: %v\n", err)
		return exitError
	}
	defer db.Close()
	_, daily, err := listening.NewServices(cfg, sqlite.NewListeningRepository(db))
	if err != nil {
		fmt.Fprintf(stderr, "configuration: %v\n", err)
		return exitError
	}

	if status {
		st, err := daily.Status(ctx)
		if err != nil {
			fmt.Fprintf(stderr, "status: %v\n", err)
			return exitError
		}
		if *asJSON {
			return printJSON(stdout, stderr, statusJSON(st), exitOK)
		}
		printStatus(stdout, st)
		return exitOK
	}

	key, err := newKey()
	if err != nil {
		fmt.Fprintf(stderr, "%v\n", err)
		return exitError
	}
	run, _, err := daily.Pull(ctx, key, *trigger)
	now := daily.Now()
	switch {
	case errors.Is(err, domain.ErrListeningPullNotConfigured):
		fmt.Fprintln(stderr, "daily listening is not configured: set LISTENING_PLAYLIST_SOURCE=youtube and/or LISTENING_AUTO_PREPARE=daily")
		return exitNotEnabled
	case errors.Is(err, domain.ErrListeningPullBusy):
		fmt.Fprintf(stderr, "another pull is running (run %d, %s, started %s); nothing was started\n",
			run.ID, run.Trigger, run.StartedAt.Format(time.RFC3339))
		return exitBusy
	case err != nil:
		fmt.Fprintf(stderr, "pull %s did not finish: %v\n", key, err)
		return exitError
	}
	code := exitOK
	if needsAttention(run) {
		code = exitAttention
	}
	if *asJSON {
		return printJSON(stdout, stderr, runJSON(run, now), code)
	}
	printRun(stdout, run, now)
	return code
}

// needsAttention: a step failed or its outcome is unknown.
func needsAttention(r domain.ListeningPullRun) bool {
	return r.SourceOutcome == domain.ListeningSourceFailed ||
		r.PrepareOutcome == domain.ListeningOutcomeFailed || r.PrepareOutcome == domain.ListeningOutcomeUnknown ||
		r.NotifyOutcome == domain.ListeningOutcomeFailed || r.NotifyOutcome == domain.ListeningOutcomeUnknown
}

func newKey() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("generate pull key: %w", err)
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	h := hex.EncodeToString(b[:])
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32], nil
}

func printRun(w io.Writer, r domain.ListeningPullRun, now time.Time) {
	fmt.Fprintf(w, "pull run %d (%s) %s, key %s\n", r.ID, r.Trigger, r.EffectiveStatus(now), r.OperationID)
	switch r.SourceOutcome {
	case domain.ListeningSourceFailed:
		fmt.Fprintf(w, "playlist:     failed (%s); nothing new was recorded\n", r.SourceFailure)
	case domain.ListeningSourceOK:
		fmt.Fprintf(w, "playlist:     ok — %d new (waiting for a transcript), %d already known, %d skipped\n",
			r.MaterialsCreated, r.ItemsKnown, r.ItemsSkipped)
	default:
		fmt.Fprintf(w, "playlist:     %s\n", r.SourceOutcome)
	}
	prep := r.PrepareOutcome
	if r.Preparation != nil {
		prep += fmt.Sprintf(" (material %d, attempt %s)", r.Preparation.MaterialID, r.Preparation.OperationID)
	}
	if r.PrepareOutcome == domain.ListeningOutcomeUnknown {
		prep += " — the provider may have finished and billed; open the lesson and retry explicitly if needed"
	}
	fmt.Fprintf(w, "preparation:  %s\n", prep)
	note := ""
	if r.NotifyOutcome == domain.ListeningOutcomeUnknown {
		note = " — the message may have arrived; send again only explicitly from the lesson"
	} else if r.NotifyOutcome == domain.ListeningOutcomeFailed && r.Notification != nil {
		note = fmt.Sprintf(" (%s); send again explicitly from the lesson", r.Notification.FailureCode)
	}
	fmt.Fprintf(w, "notification: %s%s\n", r.NotifyOutcome, note)
}

func printStatus(w io.Writer, st application.ListeningDailyStatus) {
	onOff := func(b bool, on string) string {
		if b {
			return on
		}
		return "disabled"
	}
	fmt.Fprintf(w, "playlist:     %s\n", onOff(st.SourceEnabled, st.SourceName))
	fmt.Fprintf(w, "preparation:  %s\n", onOff(st.PrepareEnabled, fmt.Sprintf("daily, at most %d per day (%s); today %s: %d used", st.DailyCap, st.Timezone, st.Today, st.UsedToday)))
	fmt.Fprintf(w, "notification: %s\n", onOff(st.NotifyEnabled, st.Channel))
	if st.LastRun == nil {
		fmt.Fprintln(w, "last pull:    none")
		return
	}
	fmt.Fprint(w, "last pull:    ")
	printRun(w, *st.LastRun, st.Now)
}

type runOut struct {
	ID               int64   `json:"id"`
	OperationID      string  `json:"operation_id"`
	Trigger          string  `json:"trigger"`
	Status           string  `json:"status"`
	StartedAt        string  `json:"started_at"`
	FinishedAt       *string `json:"finished_at"`
	SourceOutcome    string  `json:"source_outcome"`
	SourceFailure    string  `json:"source_failure,omitempty"`
	MaterialsCreated int     `json:"materials_created"`
	ItemsKnown       int     `json:"items_known"`
	ItemsSkipped     int     `json:"items_skipped"`
	PrepareOutcome   string  `json:"prepare_outcome"`
	NotifyOutcome    string  `json:"notify_outcome"`
	NeedsAttention   bool    `json:"needs_attention"`
}

func runJSON(r domain.ListeningPullRun, now time.Time) runOut {
	out := runOut{
		ID: r.ID, OperationID: r.OperationID, Trigger: r.Trigger, Status: r.EffectiveStatus(now),
		StartedAt: r.StartedAt.Format(time.RFC3339), SourceOutcome: r.SourceOutcome, SourceFailure: r.SourceFailure,
		MaterialsCreated: r.MaterialsCreated, ItemsKnown: r.ItemsKnown, ItemsSkipped: r.ItemsSkipped,
		PrepareOutcome: r.PrepareOutcome, NotifyOutcome: r.NotifyOutcome, NeedsAttention: needsAttention(r),
	}
	if r.FinishedAt != nil {
		f := r.FinishedAt.Format(time.RFC3339)
		out.FinishedAt = &f
	}
	return out
}

func statusJSON(st application.ListeningDailyStatus) map[string]any {
	var last any
	if st.LastRun != nil {
		last = runJSON(*st.LastRun, st.Now)
	}
	return map[string]any{
		"pull_enabled": st.PullEnabled, "source_enabled": st.SourceEnabled, "prepare_enabled": st.PrepareEnabled,
		"daily_cap": st.DailyCap, "timezone": st.Timezone, "today": st.Today, "used_today": st.UsedToday,
		"notify_enabled": st.NotifyEnabled, "channel": st.Channel, "last_run": last,
	}
}

func printJSON(stdout, stderr io.Writer, v any, code int) int {
	enc := json.NewEncoder(stdout)
	enc.SetIndent("", "  ")
	if err := enc.Encode(v); err != nil {
		fmt.Fprintf(stderr, "encode: %v\n", err)
		return exitError
	}
	return code
}
