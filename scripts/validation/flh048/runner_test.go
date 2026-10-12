package main

import (
	"context"
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"french-learning-app/internal/application"
	"french-learning-app/internal/domain"
)

// ---------------------------------------------------------------- fixtures

type fx map[string]any

func concept(id, group, target, intent, scope string, features map[string]string) fx {
	if features == nil {
		features = map[string]string{}
	}
	return fx{"id": id, "group_id": group, "identity": fx{"target": target, "pedagogical_intent": intent, "scope": scope, "identity_features": features}}
}

func query(id, group, split, lang, bucket, kind, canonical, statement string) fx {
	return fx{"id": id, "group_id": group, "split": split, "language": lang, "bucket": bucket, "tags": []string{"t"},
		"unit_evidence": fx{"kind": kind, "canonical": canonical, "statement": statement, "example": nil}, "free_text": statement}
}

func judgment(id, qid string, relevant, possible []string, rationale string) fx {
	if relevant == nil {
		relevant = []string{}
	}
	if possible == nil {
		possible = []string{}
	}
	return fx{"id": id, "query_id": qid, "review_status": "awaiting_human_review", "proposed_relevant_concept_ids": relevant,
		"possible_concept_ids": possible, "rationale": rationale, "hard_negatives": []any{}}
}

// smallFixture: C001 matches Q001 exactly by derived identity; C002/C003 are
// lexical neighbours; Q003 ambiguous, Q004 no-match.
func smallFixture() fx {
	return fx{
		"schema_version": flh045SchemaVersion, "label_status": "author_proposed_synthetic_awaiting_human_review",
		"groups": []fx{{"id": "F01", "split": "development", "name": "a", "rationale": "r"}, {"id": "F02", "split": "held_out", "name": "b", "rationale": "r"}},
		"concepts": []fx{
			concept("C001", "F01", "Passé composé avec être", "grammar", "", nil),
			concept("C002", "F01", "imparfait de description", "grammar", "arrière-plan passé", map[string]string{"aspect": "background"}),
			concept("C003", "F02", "pronom en de quantité", "grammar", "quantité", nil),
		},
		"queries": []fx{
			query("Q001", "F01", "development", "fr", "single_target", "grammar", "passé composé avec être", "Quel auxiliaire avec aller ?"),
			query("Q002", "F02", "held_out", "en", "single_target", "grammar", "quantity pronoun en", "How do I replace a quantity?"),
			query("Q003", "F01", "development", "en", "ambiguous", "grammar", "a past tense", "Which past tense?"),
			query("Q004", "F02", "held_out", "fr", "no_match", "vocabulary", "la température du four", "À quelle température cuire ?"),
		},
		"judgments": []fx{
			judgment("J001", "Q001", []string{"C001"}, nil, "RATIONALE-ONE"),
			judgment("J002", "Q002", []string{"C003"}, nil, "RATIONALE-TWO"),
			judgment("J003", "Q003", nil, []string{"C001", "C002"}, "RATIONALE-THREE"),
			judgment("J004", "Q004", nil, nil, "RATIONALE-FOUR"),
		},
	}
}

func encode(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func load(t *testing.T, raw []byte) (*RankingInputs, *Evaluation) {
	t.Helper()
	in, err := LoadRankingInputs(raw)
	if err != nil {
		t.Fatal(err)
	}
	ev, err := LoadEvaluation(raw, in)
	if err != nil {
		t.Fatal(err)
	}
	return in, ev
}

func frozenFixture(t *testing.T) []byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "flh045", "fixture.json"))
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

// ---------------------------------------------------------------- metrics

func approx(t *testing.T, name string, got *float64, want float64) {
	t.Helper()
	if got == nil || math.Abs(*got-want) > 1e-12 {
		t.Fatalf("%s = %v, want %v", name, got, want)
	}
}

func TestMetrics_HandCalculated(t *testing.T) {
	// Target ranks 1, 3, 4, miss, 5 (rank 4 sits just outside K=3):
	// R@1 1/5, R@3 2/5, R@5 4/5,
	// MRR@5 (1 + 1/3 + 1/4 + 0 + 1/5) / 5 = (107/60) / 5 = 107/300.
	m := &Metrics{}
	for _, r := range []int{1, 3, 4, 0, 5} {
		m.add(r)
	}
	m.finish()
	if m.N != 5 || m.Hits1 != 1 || m.Hits3 != 2 || m.Hits5 != 4 {
		t.Fatalf("counts %+v", m)
	}
	approx(t, "R@1", m.Recall1, 0.2)
	approx(t, "R@3", m.Recall3, 0.4)
	approx(t, "R@5", m.Recall5, 0.8)
	approx(t, "MRR@5", m.MRR5, 107.0/300.0)

	empty := &Metrics{}
	empty.finish()
	if empty.Recall1 != nil || empty.MRR5 != nil {
		t.Fatal("N = 0 must give null metrics, not zero")
	}
}

func TestEvaluate_RanksMissesAndSeparateDenominators(t *testing.T) {
	_, ev := load(t, encode(t, smallFixture()))
	run := RetrieverRun{Name: "x", State: stateCompleted, Queries: []QueryRun{
		{Status: "ok", Hits: []Hit{{ConceptFixtureID: "C002", ConceptID: 2, Rank: 1}, {ConceptFixtureID: "C001", ConceptID: 1, Rank: 2}}}, // target rank 2
		{Status: "ok", Hits: []Hit{{ConceptFixtureID: "C001", ConceptID: 1, Rank: 1}}},                                                    // miss
		{Status: "ok", Hits: []Hit{{ConceptFixtureID: "C002", ConceptID: 2, Rank: 1}}},                                                    // ambiguous
		{Status: "ok", Hits: []Hit{{ConceptFixtureID: "C003", ConceptID: 3, Rank: 1}}},                                                    // no-match
	}}
	e := Evaluate(run, ev)
	if e.Overall.N != 2 || e.Overall.Hits1 != 0 || e.Overall.Hits3 != 1 {
		t.Fatalf("overall %+v", e.Overall)
	}
	approx(t, "MRR@5", e.Overall.MRR5, 0.25) // (1/2 + 0) / 2
	if e.BySplit["development"].N != 1 || e.BySplit["held_out"].N != 1 || e.ByLanguage["fr"].N != 1 || e.ByLanguage["en"].N != 1 {
		t.Fatalf("slices %+v %+v", e.BySplit, e.ByLanguage)
	}
	approx(t, "dev R@3", e.BySplit["development"].Recall3, 1)
	approx(t, "held-out R@5", e.BySplit["held_out"].Recall5, 0)
	if *e.Cases[0].TargetRank != 2 || e.Cases[1].TargetRank != nil {
		t.Fatalf("case ranks %+v", e.Cases)
	}
	// Ambiguous and no-match never enter N.
	if len(e.Ambiguous) != 1 || *e.Ambiguous[0].AlternativeRanks["C002"] != 1 || e.Ambiguous[0].AlternativeRanks["C001"] != nil {
		t.Fatalf("ambiguous %+v", e.Ambiguous)
	}
	if len(e.NoMatch) != 1 || e.NoMatchWithAnyResult != 1 {
		t.Fatalf("no-match %+v", e.NoMatch)
	}
	d := CountDenominators(ev, 3)
	if d.SingleTarget != 2 || d.Ambiguous != 1 || d.NoMatch != 1 || d.SingleTargetBySplit["held_out"] != 1 {
		t.Fatalf("denominators %+v", d)
	}
}

func TestEvaluate_FailedOrUnavailableRunHasNoMetrics(t *testing.T) {
	_, ev := load(t, encode(t, smallFixture()))
	for _, state := range []string{stateFailed, stateUnavailable} {
		e := Evaluate(RetrieverRun{State: state, Queries: []QueryRun{{Status: "ok", Hits: []Hit{{ConceptID: 1, Rank: 1}}}}}, ev)
		if e.Overall != nil || e.BySplit != nil {
			t.Fatalf("%s run must not be scored: %+v", state, e.Overall)
		}
	}
}

// ---------------------------------------------------------------- inputs

func TestInputs_DeterministicMappingIndependentOfFileOrder(t *testing.T) {
	f := smallFixture()
	in1, _ := load(t, encode(t, f))
	// Reverse concepts and queries in the file.
	cs, qs := f["concepts"].([]fx), f["queries"].([]fx)
	rev := func(xs []fx) []fx {
		out := make([]fx, len(xs))
		for i, x := range xs {
			out[len(xs)-1-i] = x
		}
		return out
	}
	f["concepts"], f["queries"] = rev(cs), rev(qs)
	in2, _ := load(t, encode(t, f))
	d1, _ := Digests(encode(t, smallFixture()), in1)
	d2, _ := Digests(encode(t, f), in2)
	if d1.RankingInputsSHA256 != d2.RankingInputsSHA256 || strings.Join(in1.ConceptFixtureIDs, ",") != "C001,C002,C003" {
		t.Fatalf("mapping must depend on fixture IDs only: %v vs %v", in1.ConceptFixtureIDs, in2.ConceptFixtureIDs)
	}
	for i, d := range in2.Documents {
		if d.ConceptID != int64(i+1) {
			t.Fatalf("document %d has runtime id %d", i, d.ConceptID)
		}
	}
	// Ties break by ascending runtime ID, i.e. fixture-ID order.
	run := RunRetriever(context.Background(), application.NewWeightedLexicalConceptRetriever(), in2)
	if rankingDigest(run) != rankingDigest(RunRetriever(context.Background(), application.NewWeightedLexicalConceptRetriever(), in1)) {
		t.Fatal("rankings differ with file order")
	}
}

func TestInputs_CandidateIdentityComesFromDomainOnly(t *testing.T) {
	in, ev := load(t, encode(t, smallFixture()))
	q := in.Queries[0]
	want := domain.DeriveCandidateIdentity(domain.KnowledgeUnit{Kind: "grammar", Canonical: "passé composé avec être"})
	if q.CandidateIdentity.Signature() != want.Signature() || q.CandidateIdentity.Scope != "" || len(q.CandidateIdentity.IdentityFeatures) != 0 {
		t.Fatalf("candidate identity %+v", q.CandidateIdentity)
	}
	// The derived identity happens to equal C001's: the exact retriever finds it.
	run := RunRetriever(context.Background(), application.NewExactSignatureConceptRetriever(), in)
	if len(run.Queries[0].Hits) != 1 || run.Queries[0].Hits[0].ConceptFixtureID != "C001" {
		t.Fatalf("exact hits %+v", run.Queries[0].Hits)
	}
	if e := Evaluate(run, ev); e.Overall.Hits1 != 1 || e.Overall.N != 2 {
		t.Fatalf("exact evaluation %+v", e.Overall)
	}
}

// Evaluator data must not influence ranking inputs or provider inputs.
func TestInputs_LabelsNeverReachRetrieversOrProvider(t *testing.T) {
	base := smallFixture()
	perturbed := smallFixture()
	perturbed["judgments"] = []fx{
		judgment("J001", "Q001", []string{"C003"}, nil, "DIFFERENT-RATIONALE"),
		judgment("J002", "Q002", []string{"C001"}, nil, "x"),
		judgment("J003", "Q003", nil, []string{"C003"}, "y"),
		judgment("J004", "Q004", nil, nil, "z"),
	}
	for _, q := range perturbed["queries"].([]fx) {
		q["language"], q["tags"], q["free_text"] = "xx", []string{"changed"}, "FREE-TEXT-CHANGED"
	}
	perturbed["label_status"] = "changed"

	inA, _ := load(t, encode(t, base))
	inB, _ := load(t, encode(t, perturbed))
	dA, _ := Digests(encode(t, base), inA)
	dB, _ := Digests(encode(t, perturbed), inB)
	if dA.RankingInputsSHA256 != dB.RankingInputsSHA256 {
		t.Fatal("judgments/metadata changed the ranking inputs")
	}
	if dA.JudgmentsSHA256 == dB.JudgmentsSHA256 {
		t.Fatal("the judgments hash must see the change")
	}

	rendered := string(encode(t, inA.Documents)) + string(encode(t, inA.Queries))
	pA := NewProviderCounter(&bagProvider{dims: 16}, 1000, 16)
	RunRetriever(context.Background(), application.NewEmbeddingConceptRetriever(pA), inA)
	pB := NewProviderCounter(&bagProvider{dims: 16}, 1000, 16)
	RunRetriever(context.Background(), application.NewEmbeddingConceptRetriever(pB), inB)
	submitted := ""
	for _, batch := range pA.inputs {
		submitted += strings.Join(batch, "\n")
	}
	if encodeStr(pA.inputs) != encodeStr(pB.inputs) {
		t.Fatal("provider inputs changed with evaluator data")
	}
	for _, forbidden := range []string{"RATIONALE", "C001", "C002", "C003", "J001", "Q001", "development", "held_out",
		"single_target", "ambiguous", "no_match", "proposed", "awaiting", "FREE-TEXT", "possible_concept", "rank"} {
		if strings.Contains(rendered, forbidden) || strings.Contains(submitted, forbidden) {
			t.Fatalf("%q reached a ranking or provider input", forbidden)
		}
	}
}

func encodeStr(v any) string { b, _ := json.Marshal(v); return string(b) }

func TestInputs_RejectsInconsistentFixtures(t *testing.T) {
	cases := map[string]func(f fx){
		"two targets":       func(f fx) { f["judgments"].([]fx)[0]["proposed_relevant_concept_ids"] = []string{"C001", "C002"} },
		"unknown concept":   func(f fx) { f["judgments"].([]fx)[0]["proposed_relevant_concept_ids"] = []string{"C999"} },
		"ambiguous target":  func(f fx) { f["judgments"].([]fx)[2]["proposed_relevant_concept_ids"] = []string{"C001"} },
		"no-match names":    func(f fx) { f["judgments"].([]fx)[3]["possible_concept_ids"] = []string{"C001"} },
		"unknown bucket":    func(f fx) { f["queries"].([]fx)[0]["bucket"] = "maybe" },
		"unknown kind":      func(f fx) { f["queries"].([]fx)[0]["unit_evidence"].(fx)["kind"] = "poetry" },
		"split mismatch":    func(f fx) { f["queries"].([]fx)[0]["split"] = "held_out" },
		"duplicate concept": func(f fx) { f["concepts"].([]fx)[1]["id"] = "C001" },
		"bad query id":      func(f fx) { f["queries"].([]fx)[0]["id"] = "query-1" },
		"same identity": func(f fx) {
			f["concepts"].([]fx)[2]["identity"] = f["concepts"].([]fx)[0]["identity"]
		},
		"missing judgment": func(f fx) { f["judgments"] = f["judgments"].([]fx)[:3] },
		"schema":           func(f fx) { f["schema_version"] = "other" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			f := smallFixture()
			mutate(f)
			raw := encode(t, f)
			in, err := LoadRankingInputs(raw)
			if err == nil {
				_, err = LoadEvaluation(raw, in)
			}
			if err == nil {
				t.Fatal("inconsistent fixture accepted")
			}
		})
	}
}

func TestInputs_FrozenFixture(t *testing.T) {
	raw := frozenFixture(t)
	in, ev := load(t, raw)
	d, err := Digests(raw, in)
	if err != nil || !d.FixtureMatchesFrozen {
		t.Fatalf("frozen fixture hash: %+v %v", d, err)
	}
	// FLH-045's documented canonical judgments hash happens to equal the Go
	// re-encoding of the same section.
	if d.JudgmentsSHA256 != "91b5ac3a61a9a0dbe53690ac178402ee0e1a26a66f05e32e85488d9d717389cf" {
		t.Fatalf("judgments hash %s", d.JudgmentsSHA256)
	}
	dn := CountDenominators(ev, len(in.Documents))
	if len(in.Documents) != 24 || len(in.Queries) != 56 || dn.SingleTarget != 48 || dn.Ambiguous != 4 || dn.NoMatch != 4 ||
		dn.SingleTargetBySplit[splitDevelopment] != 32 || dn.SingleTargetBySplit[splitHeldOut] != 16 ||
		dn.SingleTargetByLanguage["fr"] != 24 || dn.SingleTargetByLanguage["en"] != 24 {
		t.Fatalf("inventory %+v", dn)
	}
	if in.ConceptFixtureIDs[0] != "C001" || in.Documents[0].ConceptID != 1 || in.QueryFixtureIDs[55] != "Q056" {
		t.Fatal("mapping")
	}
}

func TestRunRetriever_RejectsInvalidCandidatesAndStops(t *testing.T) {
	in, _ := load(t, encode(t, smallFixture()))
	run := RunRetriever(context.Background(), badRetriever{}, in)
	if run.State != stateFailed || run.Queries[0].Status != "error" || run.Queries[1].Status != "not_run_after_error" {
		t.Fatalf("run %+v", run)
	}
}

type badRetriever struct{}

func (badRetriever) Name() string { return "bad" }
func (badRetriever) Retrieve(context.Context, application.ConceptRetrievalQuery, []application.ConceptRetrievalDocument, int) ([]application.ConceptRetrievalCandidate, error) {
	return []application.ConceptRetrievalCandidate{{ConceptID: 99, Rank: 1, Score: 1}}, nil
}

// bagProvider is a deterministic in-process fake: hashed bag of words.
type bagProvider struct {
	dims  int
	calls int
}

func (p *bagProvider) Name() string { return "fake:bag" }
func (p *bagProvider) Embed(_ context.Context, texts []string) ([][]float64, error) {
	p.calls++
	out := make([][]float64, len(texts))
	for i, t := range texts {
		v := make([]float64, p.dims)
		for _, w := range strings.Fields(strings.ToLower(t)) {
			h := 0
			for _, r := range w {
				h = (h*31 + int(r)) % p.dims
			}
			v[h]++
		}
		v[0] += 0.01
		out[i] = v
	}
	return out, nil
}

func TestProviderCounter_CapAndDimensionsWithoutRetry(t *testing.T) {
	inner := &bagProvider{dims: 16}
	p := NewProviderCounter(inner, 30, 16)
	if _, err := p.Embed(context.Background(), make([]string, 25)); err != nil {
		t.Fatal(err)
	}
	if _, err := p.Embed(context.Background(), make([]string, 25)); err == nil {
		t.Fatal("call over the cap must be refused")
	}
	if inner.calls != 1 || p.Requests != 1 || p.InputPositions != 25 || p.RefusedOverCap != 1 {
		t.Fatalf("refused call reached the provider: inner %d, counters %+v", inner.calls, p)
	}
	q := NewProviderCounter(&bagProvider{dims: 8}, 100, 16)
	if _, err := q.Embed(context.Background(), []string{"a"}); err == nil || q.Failures != 1 {
		t.Fatalf("dimension mismatch must fail: %v %+v", err, q)
	}
}

func TestOutput_EmptyDirectoryRuleAndExclusiveWrites(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "notes.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := PrepareOutputDir(dir, t.TempDir()); err == nil {
		t.Fatal("a non-empty directory must be refused even without a name clash")
	}
	empty := t.TempDir()
	got, err := PrepareOutputDir(empty, t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := writeNew(filepath.Join(got, "report.json"), []byte("1")); err != nil {
		t.Fatal(err)
	}
	if err := writeNew(filepath.Join(got, "report.json"), []byte("2")); err == nil {
		t.Fatal("an existing file must never be overwritten")
	}
}
