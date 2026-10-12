package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"french-learning-app/internal/application"
)

// FLH-052 F1: the overall deadline governs offline retrievers.

// delayedRetriever is a controlled offline retriever: it sleeps for delay on
// every call and then returns the existing weighted-lexical result. With
// honorContext it returns early on ctx.Done(); without it, it behaves like the
// existing synchronous retrievers and ignores the context.
type delayedRetriever struct {
	mu           sync.Mutex
	delay        time.Duration
	honorContext bool
	calls        int
}

func (d *delayedRetriever) Name() string { return "delayed_test_retriever" }
func (d *delayedRetriever) Retrieve(ctx context.Context, q application.ConceptRetrievalQuery, docs []application.ConceptRetrievalDocument, limit int) ([]application.ConceptRetrievalCandidate, error) {
	d.mu.Lock()
	d.calls++
	d.mu.Unlock()
	if d.honorContext {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(d.delay):
		}
	} else {
		time.Sleep(d.delay)
	}
	return application.NewWeightedLexicalConceptRetriever().Retrieve(ctx, q, docs, limit)
}

func assertDeadlineFailure(t *testing.T, run RetrieverRun, ev *Evaluation, errorAt int, want string) {
	t.Helper()
	if run.State != stateFailed {
		t.Fatalf("state %s, want failed", run.State)
	}
	for i, q := range run.Queries {
		switch {
		case i < errorAt && q.Status != "ok":
			t.Fatalf("query %d status %s, want ok", i, q.Status)
		case i == errorAt && (q.Status != "error" || !strings.Contains(q.Error, want) || len(q.Hits) != 0):
			t.Fatalf("query %d: %+v, want error containing %q and no hits", i, q, want)
		case i > errorAt && q.Status != "not_run_after_error":
			t.Fatalf("query %d status %s, want not_run_after_error", i, q.Status)
		}
	}
	if e := Evaluate(run, ev); e.Overall != nil || e.BySplit != nil || e.ByLanguage != nil || e.ByGroup != nil {
		t.Fatalf("a deadline failure must publish no metrics: %+v", e.Overall)
	}
}

func TestRunRetriever_ExpiredDeadlineRunsNothing(t *testing.T) {
	in, ev := load(t, encode(t, smallFixture()))
	ctx, cancel := context.WithTimeout(context.Background(), time.Nanosecond)
	defer cancel()
	<-ctx.Done()
	r := &delayedRetriever{}
	run := RunRetriever(ctx, r, in)
	assertDeadlineFailure(t, run, ev, 0, "overall run timeout (-timeout) expired before Retrieve")
	if r.calls != 0 {
		t.Fatalf("Retrieve called %d time(s) after the deadline", r.calls)
	}

	canceled, stop := context.WithCancel(context.Background())
	stop()
	run = RunRetriever(canceled, r, in)
	assertDeadlineFailure(t, run, ev, 0, "run canceled before Retrieve")
}

// A synchronous retriever that ignores its context runs to completion; the
// check afterwards discards its late result and stops the retriever.
func TestRunRetriever_DelayedRetrieverMissesDeadline(t *testing.T) {
	in, ev := load(t, encode(t, smallFixture()))
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	r := &delayedRetriever{delay: 100 * time.Millisecond}
	run := RunRetriever(ctx, r, in)
	// Call 1 ends at ~100ms (ok); call 2 ends at ~200ms, after the deadline.
	assertDeadlineFailure(t, run, ev, 1, "expired during Retrieve; its result is discarded")
	if r.calls != 2 {
		t.Fatalf("Retrieve called %d times, want 2 (no work after the deadline)", r.calls)
	}
	if run.Queries[1].DurationNS < (90 * time.Millisecond).Nanoseconds() {
		t.Fatalf("the ignoring retriever was not left to finish: %dns", run.Queries[1].DurationNS)
	}
}

func TestRunRetriever_ContextHonoringRetrieverStopsAtDeadline(t *testing.T) {
	in, ev := load(t, encode(t, smallFixture()))
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	r := &delayedRetriever{delay: time.Hour, honorContext: true}
	run := RunRetriever(ctx, r, in)
	assertDeadlineFailure(t, run, ev, 0, "context deadline exceeded")
	if r.calls != 1 || run.Queries[0].DurationNS > (10*time.Second).Nanoseconds() {
		t.Fatalf("calls %d, duration %dns", r.calls, run.Queries[0].DurationNS)
	}
}

// With nothing left to run, completion is still refused after the deadline.
func TestRunRetriever_NeverCompletesAfterDeadline(t *testing.T) {
	in, _ := load(t, encode(t, smallFixture()))
	in.Queries = nil
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	run := RunRetriever(ctx, &delayedRetriever{}, in)
	if run.State != stateFailed || !strings.Contains(run.Note, "before the retriever was declared completed") {
		t.Fatalf("state %s note %q", run.State, run.Note)
	}
	if run = RunRetriever(context.Background(), &delayedRetriever{}, in); run.State != stateCompleted {
		t.Fatalf("live context: state %s", run.State)
	}
}

func TestCLI_ExpiredOverallTimeoutFailsEveryRetrieverWithoutMetrics(t *testing.T) {
	f := newFakeEmbeddings(t, "ok")
	out := outDir(t)
	code, stdout, stderr := runCLI(t, "-out", out, "-timeout", "1ns",
		"-embedding", "http", "-embedding-base-url", f.server.URL, "-embedding-model", "m", "-embedding-max-inputs", "1400")
	if code != 1 {
		t.Fatalf("exit %d, want 1: %s", code, stderr)
	}
	r := readReport(t, out)
	all := append(append([]any(nil), r["offline_baselines"].([]any)...), r["embedding"])
	for _, x := range all {
		rr := x.(map[string]any)
		qs := rr["queries"].([]any)
		first := qs[0].(map[string]any)
		if rr["state"] != stateFailed || rr["evaluation"].(map[string]any)["overall"] != nil ||
			first["status"] != "error" || !strings.Contains(first["error"].(string), "overall run timeout (-timeout) expired before Retrieve") {
			t.Fatalf("%v: state %v first %v", rr["name"], rr["state"], first)
		}
		for _, q := range qs[1:] {
			if q.(map[string]any)["status"] != "not_run_after_error" {
				t.Fatalf("%v kept running after the deadline", rr["name"])
			}
		}
	}
	if reqs, _ := f.counts(); reqs != 0 {
		t.Fatalf("provider contacted %d time(s) after the deadline", reqs)
	}
	run := r["run"].(map[string]any)
	if run["timeout"] != "1ns" || !strings.Contains(run["deadline"].(string), "overall run timeout (-timeout) expired") {
		t.Fatalf("run %v", run)
	}
	if !strings.Contains(stdout, "Overall timeout 1ns: overall run timeout (-timeout) expired") || strings.Contains(stdout, "| all single-target |") {
		t.Fatalf("summary:\n%s", stdout)
	}
}

func TestCLI_TimeoutMustBePositive(t *testing.T) {
	for _, v := range []string{"0", "0s", "-1s", "-1ns"} {
		out := outDir(t)
		code, _, stderr := runCLI(t, "-out", out, "-timeout", v)
		if code != 2 || !strings.Contains(stderr, "-timeout must be positive") {
			t.Fatalf("-timeout %s: exit %d %s", v, code, stderr)
		}
		if _, err := os.Stat(out); err == nil {
			t.Fatalf("-timeout %s: output created", v)
		}
	}
}

// FLH-052 F2: the frozen reference is the compiled FLH-045 constant.

// FLH-051's reproduction: one rationale changed, then the copy's own hash
// supplied as the expectation.
func TestCLI_ModifiedFixtureWithItsOwnHashIsRefused(t *testing.T) {
	var data map[string]any
	if err := json.Unmarshal(frozenFixture(t), &data); err != nil {
		t.Fatal(err)
	}
	data["judgments"].([]any)[0].(map[string]any)["rationale"] = "changed by FLH-052 test"
	modified := encode(t, data)
	fixture := filepath.Join(t.TempDir(), "fixture.json")
	if err := os.WriteFile(fixture, modified, 0o644); err != nil {
		t.Fatal(err)
	}
	own := sha256Hex(modified)
	cases := []struct {
		args []string
		code int
		want string
	}{
		{[]string{"-expect-fixture-sha256", own}, 2, "is not the frozen FLH-045 SHA-256"},
		{nil, 3, "refusing to run on a modified fixture"},
		{[]string{"-expect-fixture-sha256", flh045FixtureSHA256}, 3, "refusing to run on a modified fixture"},
	}
	for _, c := range cases {
		out := outDir(t)
		code, _, stderr := runCLI(t, append([]string{"-fixture", fixture, "-out", out}, c.args...)...)
		if code != c.code || !strings.Contains(stderr, c.want) {
			t.Fatalf("%v: exit %d, want %d: %s", c.args, code, c.code, stderr)
		}
		if _, err := os.Stat(out); err == nil {
			t.Fatalf("%v: output created", c.args)
		}
	}
	// A wrong expectation is refused even for the frozen fixture itself.
	if code, _, _ := runCLI(t, "-out", outDir(t), "-expect-fixture-sha256", own); code != 2 {
		t.Fatalf("frozen fixture with a foreign expectation: exit %d", code)
	}
}

func TestCLI_FreezeStatusNamesTheCompiledReference(t *testing.T) {
	out := outDir(t)
	code, stdout, stderr := runCLI(t, "-out", out, "-expect-fixture-sha256", flh045FixtureSHA256)
	if code != 0 {
		t.Fatalf("exit %d: %s", code, stderr)
	}
	in := readReport(t, out)["inputs"].(map[string]any)
	if in["fixture_sha256"] != flh045FixtureSHA256 || in["frozen_reference_sha256"] != flh045FixtureSHA256 ||
		in["fixture_matches_frozen"] != true || in["caller_asserted_sha256"] != flh045FixtureSHA256 ||
		!strings.Contains(in["frozen_reference"].(string), "compiled into this runner") {
		t.Fatalf("inputs %v", in)
	}
	if _, ok := in["expected_fixture_sha256"]; ok {
		t.Fatal("caller-defined expectation field still present")
	}
	if !strings.Contains(stdout, "frozen reference (FLH-045 scripts/validation/flh045/fixture.json, SHA-256 compiled into this runner) `"+flh045FixtureSHA256+"`; matches the frozen reference: true") {
		t.Fatalf("summary freeze line:\n%s", stdout)
	}
	if !strings.Contains(stdout, "Overall timeout 10m0s: not reached.") {
		t.Fatalf("summary timeout line:\n%s", stdout)
	}
}

// FLH-051 R2: the standalone summary explains the exact baseline's zeros.

func TestExactStructure(t *testing.T) {
	in, _ := load(t, frozenFixture(t))
	st := ExactStructure(in)
	if st.Documents != 24 || st.DocumentsWithScopeOrFeature != 24 || st.Queries != 56 || st.QueriesWithScopeOrFeature != 0 ||
		st.ExactMatchPossible || !strings.HasPrefix(st.Note, "Structural: all 24 fixture Concepts") {
		t.Fatalf("frozen structure %+v", st)
	}
	// smallFixture's C001 has no scope or features, so exact can match.
	small, _ := load(t, encode(t, smallFixture()))
	if st := ExactStructure(small); !st.ExactMatchPossible || st.DocumentsWithScopeOrFeature != 2 {
		t.Fatalf("small structure %+v", st)
	}
	// Ranking inputs are untouched: no target identity copied into queries.
	for _, q := range in.Queries {
		if q.CandidateIdentity.Scope != "" || len(q.CandidateIdentity.IdentityFeatures) != 0 {
			t.Fatalf("query %d has a scope or features", q.UnitID)
		}
	}
}

func TestCLI_SummaryExplainsStructuralExactZeros(t *testing.T) {
	out := outDir(t)
	if code, _, stderr := runCLI(t, "-out", out); code != 0 {
		t.Fatalf("exit %d: %s", code, stderr)
	}
	summary, _ := os.ReadFile(filepath.Join(out, "summary.md"))
	s := string(summary)
	exact := strings.Index(s, "### `exact_signature_retriever_v1`")
	lexical := strings.Index(s, "### `weighted_lexical_retriever_v1`")
	note := strings.Index(s, "Structural: all 24 fixture Concepts have a non-empty scope or identity features")
	if exact < 0 || note < exact || note > lexical || strings.Count(s, "Structural:") != 1 {
		t.Fatalf("structural note missing or misplaced:\n%s", s)
	}
	base := readReport(t, out)["offline_baselines"].([]any)
	st := base[0].(map[string]any)["structure"].(map[string]any)
	if st["exact_match_possible"] != false || base[1].(map[string]any)["structure"] != nil {
		t.Fatalf("structure %v", st)
	}
	// Exact's zeros stay measured zeros, not nulls.
	if base[0].(map[string]any)["evaluation"].(map[string]any)["overall"].(map[string]any)["recall_at_1"] != 0.0 {
		t.Fatal("exact zeros became null")
	}
}
