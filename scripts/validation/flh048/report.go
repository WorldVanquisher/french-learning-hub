package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// v2 (FLH-052): freeze status against the compiled FLH-045 constant, the
// run deadline, and the exact baseline's structural note.
const reportSchema = "flh048_exploratory_retrieval_comparison_v2"

// Labels are written verbatim into every report and summary.
var Labels = []string{
	"EXPLORATORY comparison against author-proposed synthetic judgments (FLH-045, awaiting human review).",
	"NOT the production concept_retrieval_eval_policy_v1 report.",
	"NOT independently collected human ground truth.",
	"No claim of generalization or semantic improvement: 56 small, correlated synthetic queries; the author has seen the held-out split.",
}

// Sources whose bytes define the behaviour measured here.
var sourceFiles = []string{
	"internal/application/concept_retrieval.go",
	"internal/application/concept_weighted_lexical_retrieval.go",
	"internal/application/concept_bm25_retrieval.go",
	"internal/application/concept_embedding_retrieval.go",
	"internal/application/concept_retrieval_evaluation_service.go",
	"internal/domain/concept.go",
	"internal/domain/knowledge.go",
	"internal/embedding/http.go",
	"scripts/validation/flh048/main.go",
	"scripts/validation/flh048/inputs.go",
	"scripts/validation/flh048/rank.go",
	"scripts/validation/flh048/metrics.go",
	"scripts/validation/flh048/report.go",
}

type IDMap struct {
	FixtureID string `json:"fixture_id"`
	RuntimeID int64  `json:"runtime_id"`
}

type QueryReport struct {
	QueryID  string `json:"query_id"`
	UnitID   int64  `json:"unit_id"`
	GroupID  string `json:"group_id"`
	Split    string `json:"split"`
	Language string `json:"language"`
	Bucket   string `json:"bucket"`
	QueryRun
}

type RetrieverReport struct {
	RetrieverRun
	RankingDigest    string        `json:"ranking_digest"`
	DurationTotalNS  int64         `json:"duration_total_ns"`
	DurationMedianNS int64         `json:"duration_median_ns"`
	Errors           int           `json:"errors"`
	Structure        *Structure    `json:"structure,omitempty"` // exact baseline only
	Evaluation       Evaluated     `json:"evaluation"`
	Queries          []QueryReport `json:"queries"`
}

type Report struct {
	Schema        string            `json:"report_schema"`
	Labels        []string          `json:"labels"`
	Run           map[string]any    `json:"run"`
	Inputs        InputDigests      `json:"inputs"`
	FixtureStatus map[string]string `json:"fixture"`
	Sources       map[string]string `json:"source_sha256"`
	Configuration map[string]any    `json:"configuration"`
	Denominators  Denominators      `json:"denominators"`
	ConceptIDs    []IDMap           `json:"concept_id_mapping"`
	QueryIDs      []IDMap           `json:"query_id_mapping"`
	Baselines     []RetrieverReport `json:"offline_baselines"`
	Embedding     RetrieverReport   `json:"embedding"`
}

// Structure explains whether exact signature matching is possible at all on
// these inputs. It is computed from the ranking inputs, never from labels.
type Structure struct {
	Documents                   int    `json:"documents"`
	DocumentsWithScopeOrFeature int    `json:"documents_with_scope_or_features"`
	Queries                     int    `json:"queries"`
	QueriesWithScopeOrFeature   int    `json:"candidate_identities_with_scope_or_features"`
	ExactMatchPossible          bool   `json:"exact_match_possible"`
	Note                        string `json:"note"`
}

// ExactStructure counts scope/identity features on both sides. A signature
// covers target, intent, scope and features, so a document with a scope or
// features can only match a candidate identity that has them too.
func ExactStructure(in *RankingInputs) *Structure {
	st := &Structure{Documents: len(in.Documents), Queries: len(in.Queries)}
	for _, d := range in.Documents {
		if d.Scope != "" || len(d.IdentityFeatures) > 0 {
			st.DocumentsWithScopeOrFeature++
		}
	}
	for _, q := range in.Queries {
		if q.CandidateIdentity.Scope != "" || len(q.CandidateIdentity.IdentityFeatures) > 0 {
			st.QueriesWithScopeOrFeature++
		}
	}
	st.ExactMatchPossible = !(st.DocumentsWithScopeOrFeature == st.Documents && st.QueriesWithScopeOrFeature == 0)
	if st.ExactMatchPossible {
		st.Note = "Some fixture Concepts lack scope/features or some derived candidates have them; exact matches are possible in principle."
	} else {
		st.Note = fmt.Sprintf("Structural: all %d fixture Concepts have a non-empty scope or identity features, while every candidate identity derived by domain.DeriveCandidateIdentity has neither, so no exact signature can match on these inputs. Its zeros are not evidence about semantic quality. Target identities are never copied into query inputs to change this.", st.Documents)
	}
	return st
}

func idMap(ids []string) []IDMap {
	out := make([]IDMap, len(ids))
	for i, id := range ids {
		out[i] = IDMap{FixtureID: id, RuntimeID: int64(i + 1)}
	}
	return out
}

// rankingDigest hashes ordered results without timing, so two runs can be
// compared for identical rankings.
func rankingDigest(run RetrieverRun) string {
	type row struct {
		Status string `json:"status"`
		Hits   []Hit  `json:"hits"`
		Error  string `json:"error"`
	}
	rows := make([][]byte, 0, len(run.Queries))
	for _, q := range run.Queries {
		b, _ := json.Marshal(row{q.Status, q.Hits, q.Error})
		rows = append(rows, b)
	}
	return lengthPrefixedSHA256(rows)
}

func buildRetrieverReport(run RetrieverRun, ev *Evaluation) RetrieverReport {
	rr := RetrieverReport{RetrieverRun: run, Evaluation: Evaluate(run, ev), Queries: make([]QueryReport, 0, len(run.Queries))}
	durations := make([]int64, 0, len(run.Queries))
	for i, q := range run.Queries {
		m := ev.Queries[i]
		rr.Queries = append(rr.Queries, QueryReport{QueryID: m.FixtureID, UnitID: m.UnitID, GroupID: m.GroupID,
			Split: m.Split, Language: m.Language, Bucket: m.Bucket, QueryRun: q})
		if q.Status == "error" {
			rr.Errors++
		}
		if q.Status != "not_run_after_error" {
			rr.DurationTotalNS += q.DurationNS
			durations = append(durations, q.DurationNS)
		}
	}
	if len(durations) > 0 {
		sort.Slice(durations, func(i, j int) bool { return durations[i] < durations[j] })
		rr.DurationMedianNS = durations[len(durations)/2]
	}
	rr.RankingDigest = rankingDigest(run)
	return rr
}

func fmtMetric(v *float64) string {
	if v == nil {
		return "n/a"
	}
	return fmt.Sprintf("%.3f", *v)
}

func metricRow(name string, m *Metrics) string {
	if m == nil {
		return fmt.Sprintf("| %s | n/a | n/a | n/a | n/a | n/a |\n", name)
	}
	return fmt.Sprintf("| %s | %d | %s (%d) | %s (%d) | %s (%d) | %s |\n", name, m.N,
		fmtMetric(m.Recall1), m.Hits1, fmtMetric(m.Recall3), m.Hits3, fmtMetric(m.Recall5), m.Hits5, fmtMetric(m.MRR5))
}

// Summary renders the compact readable summary.
func Summary(r *Report) string {
	var b strings.Builder
	b.WriteString("# FLH-048 exploratory retrieval comparison\n\n")
	for _, l := range r.Labels {
		fmt.Fprintf(&b, "> **%s**\n", l)
	}
	fmt.Fprintf(&b, "\nFixture `%s` sha256 `%s`; frozen reference (%s) `%s`; matches the frozen reference: %v. Ranking inputs sha256 `%s`. Judgments sha256 `%s`.\n",
		r.FixtureStatus["path"], r.Inputs.FixtureSHA256, r.Inputs.FrozenReference, r.Inputs.FrozenReferenceSHA256, r.Inputs.FixtureMatchesFrozen,
		r.Inputs.RankingInputsSHA256, r.Inputs.JudgmentsSHA256)
	if r.Run != nil {
		fmt.Fprintf(&b, "Overall timeout %v: %v.\n", r.Run["timeout"], r.Run["deadline"])
	}
	d := r.Denominators
	fmt.Fprintf(&b, "Catalog %d Concepts; %d queries: %d single-target (development %d, held out %d; fr %d, en %d), %d ambiguous and %d no-match (unscored). K = 5; MRR is truncated at 5.\n\n",
		d.CatalogConcepts, d.TotalQueries, d.SingleTarget, d.SingleTargetBySplit[splitDevelopment], d.SingleTargetBySplit[splitHeldOut],
		d.SingleTargetByLanguage["fr"], d.SingleTargetByLanguage["en"], d.Ambiguous, d.NoMatch)

	b.WriteString("## Offline baselines (existing implementations, untuned)\n\n")
	header := "| Slice | N | Recall@1 (hits) | Recall@3 (hits) | Recall@5 (hits) | MRR@5 |\n| --- | --- | --- | --- | --- | --- |\n"
	for _, rr := range r.Baselines {
		writeRetriever(&b, rr, header)
	}
	b.WriteString("## Embedding (caller-supplied endpoint only)\n\n")
	if r.Embedding.State == stateUnavailable {
		fmt.Fprintf(&b, "`%s`: **unavailable** — %s No metrics.\n\n", r.Embedding.Name, r.Embedding.Note)
	} else {
		b.WriteString("Kept apart from the baselines: its meaning depends entirely on the endpoint supplied. A stub or fake endpoint tests plumbing only.\n\n")
		writeRetriever(&b, r.Embedding, header)
	}
	b.WriteString("Full per-query top-five IDs, ranks, scores, evidence, errors and durations: `report.json`.\n")
	return b.String()
}

func writeRetriever(b *strings.Builder, rr RetrieverReport, header string) {
	fmt.Fprintf(b, "### `%s` — %s\n\n", rr.Name, rr.State)
	if rr.Note != "" {
		fmt.Fprintf(b, "%s\n\n", rr.Note)
	}
	if rr.Structure != nil {
		fmt.Fprintf(b, "%s\n\n", rr.Structure.Note)
	}
	if rr.Evaluation.Overall == nil {
		fmt.Fprintf(b, "No metrics (state %s, %d error(s)); a partial run is never scored.\n\n", rr.State, rr.Errors)
		for _, q := range rr.Queries {
			if q.Status == "error" {
				fmt.Fprintf(b, "First error (%s): %s\n\n", q.QueryID, q.Error)
				break
			}
		}
	} else {
		b.WriteString(header)
		b.WriteString(metricRow("all single-target", rr.Evaluation.Overall))
		for _, k := range sortedKeys(rr.Evaluation.BySplit) {
			b.WriteString(metricRow("split "+k, rr.Evaluation.BySplit[k]))
		}
		for _, k := range sortedKeys(rr.Evaluation.ByLanguage) {
			b.WriteString(metricRow("language "+k, rr.Evaluation.ByLanguage[k]))
		}
		for _, k := range sortedKeys(rr.Evaluation.BySplitLanguage) {
			b.WriteString(metricRow(k, rr.Evaluation.BySplitLanguage[k]))
		}
		b.WriteString("\n")
	}
	alts := []string{}
	for _, a := range rr.Evaluation.Ambiguous {
		parts := []string{}
		for _, k := range sortedKeys(a.AlternativeRanks) {
			r := "-"
			if a.AlternativeRanks[k] != nil {
				r = fmt.Sprint(*a.AlternativeRanks[k])
			}
			parts = append(parts, k+"@"+r)
		}
		alts = append(alts, fmt.Sprintf("%s returned %d [%s]", a.QueryID, a.Returned, strings.Join(parts, " ")))
	}
	nm := []string{}
	for _, n := range rr.Evaluation.NoMatch {
		nm = append(nm, fmt.Sprintf("%s returned %d", n.QueryID, n.Returned))
	}
	fmt.Fprintf(b, "Unscored ambiguous (alternative@rank): %s.  \n", strings.Join(alts, "; "))
	fmt.Fprintf(b, "Unscored no-match (descriptive; no approved false-positive definition): %s; %d of %d returned at least one Concept.  \n",
		strings.Join(nm, "; "), rr.Evaluation.NoMatchWithAnyResult, len(rr.Evaluation.NoMatch))
	fmt.Fprintf(b, "Errors %d; Retrieve time total %.2f ms, median %.3f ms; ranking digest `%s`.\n\n",
		rr.Errors, float64(rr.DurationTotalNS)/1e6, float64(rr.DurationMedianNS)/1e6, rr.RankingDigest)
	if rr.Provider != nil {
		p := rr.Provider
		fmt.Fprintf(b, "Provider counters: %d request(s), %d input positions, %d unique input hashes, %d failure(s), %d refused over cap, observed dimensions %v.\n\n",
			p.Requests, p.InputPositions, p.UniqueInputHashes, p.Failures, p.RefusedOverCap, p.ObservedDims)
	}
}

// ---------------------------------------------------------------- output safety

// resolvePath returns an absolute, symlink-resolved path, also for a path
// whose tail does not exist yet (the nearest existing ancestor is resolved).
func resolvePath(p string) (string, error) {
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", err
	}
	abs = filepath.Clean(abs)
	rest := []string{}
	cur := abs
	for {
		if _, err := os.Lstat(cur); err == nil {
			resolved, err := filepath.EvalSymlinks(cur)
			if err != nil {
				return "", err
			}
			for i := len(rest) - 1; i >= 0; i-- {
				resolved = filepath.Join(resolved, rest[i])
			}
			return resolved, nil
		}
		parent := filepath.Dir(cur)
		if parent == cur {
			return abs, nil
		}
		rest = append(rest, filepath.Base(cur))
		cur = parent
	}
}

func within(path, dir string) bool {
	rel, err := filepath.Rel(dir, path)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel)
}

// PrepareOutputDir refuses an output location inside the repository (which
// contains the source fixtures and this runner), inside the fixture's
// directory, or equal to an input; an existing directory must be empty.
func PrepareOutputDir(out, repoRoot string, inputs ...string) (string, error) {
	if strings.TrimSpace(out) == "" {
		return "", errors.New("-out is required (a new or empty directory outside the repository)")
	}
	dir, err := resolvePath(out)
	if err != nil {
		return "", err
	}
	root, err := resolvePath(repoRoot)
	if err != nil {
		return "", err
	}
	if within(dir, root) {
		return "", fmt.Errorf("output %s is inside the repository %s; write results outside source fixtures", dir, root)
	}
	for _, in := range inputs {
		ip, err := resolvePath(in)
		if err != nil {
			return "", err
		}
		if within(dir, filepath.Dir(ip)) || within(ip, dir) {
			return "", fmt.Errorf("output %s collides with input %s", dir, ip)
		}
	}
	info, err := os.Stat(dir)
	switch {
	case err == nil && !info.IsDir():
		return "", fmt.Errorf("output %s exists and is not a directory", dir)
	case err == nil:
		f, err := os.Open(dir)
		if err != nil {
			return "", err
		}
		defer f.Close()
		if _, err := f.Readdirnames(1); err != io.EOF {
			return "", fmt.Errorf("output %s is not empty; refusing to overwrite", dir)
		}
	case errors.Is(err, os.ErrNotExist):
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return "", err
		}
	default:
		return "", err
	}
	return dir, nil
}

// writeNew creates a file that must not exist yet.
func writeNew(path string, data []byte) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}
