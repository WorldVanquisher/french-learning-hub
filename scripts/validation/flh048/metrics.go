package main

import "sort"

// Metrics are exploratory Recall@1/3/5 and MRR@5 over single-target cases.
// MRR@5 averages 1/rank when the target is in the returned top five and 0
// otherwise (truncated at five, not full-catalog MRR). With N = 0 every value
// is null, never zero.
type Metrics struct {
	N        int      `json:"n"`
	Hits1    int      `json:"hits_at_1"`
	Hits3    int      `json:"hits_at_3"`
	Hits5    int      `json:"hits_at_5"`
	Recall1  *float64 `json:"recall_at_1"`
	Recall3  *float64 `json:"recall_at_3"`
	Recall5  *float64 `json:"recall_at_5"`
	MRR5     *float64 `json:"mrr_at_5"`
	rrSum    float64
	finished bool
}

func (m *Metrics) add(rank int) {
	m.N++
	if rank == 1 {
		m.Hits1++
	}
	if rank >= 1 && rank <= 3 {
		m.Hits3++
	}
	if rank >= 1 && rank <= 5 {
		m.Hits5++
		m.rrSum += 1 / float64(rank)
	}
}

func (m *Metrics) finish() {
	if m.finished {
		return
	}
	m.finished = true
	if m.N == 0 {
		return
	}
	n := float64(m.N)
	r1, r3, r5, mrr := float64(m.Hits1)/n, float64(m.Hits3)/n, float64(m.Hits5)/n, m.rrSum/n
	m.Recall1, m.Recall3, m.Recall5, m.MRR5 = &r1, &r3, &r5, &mrr
}

// CaseResult is the evaluator's view of one single-target query.
type CaseResult struct {
	QueryID         string `json:"query_id"`
	Split           string `json:"split"`
	Language        string `json:"language"`
	GroupID         string `json:"group_id"`
	TargetFixtureID string `json:"proposed_target"`
	TargetRank      *int   `json:"target_rank"` // null = not in returned top five
}

// UnscoredResult describes an ambiguous or no-match query without a metric:
// these have no asserted relevant target.
type UnscoredResult struct {
	QueryID  string `json:"query_id"`
	Split    string `json:"split"`
	Language string `json:"language"`
	Returned int    `json:"returned"`
	// Ambiguous only: rank of each proposed alternative within the returned
	// list (null if absent). Observation, not a relevance score.
	AlternativeRanks map[string]*int `json:"alternative_ranks,omitempty"`
}

// Evaluated is the exploratory evaluation of one retriever's run.
type Evaluated struct {
	// Metrics are null for a retriever that failed or was unavailable: a
	// partial run never produces a metric.
	Overall         *Metrics            `json:"overall"`
	BySplit         map[string]*Metrics `json:"by_split"`
	ByLanguage      map[string]*Metrics `json:"by_language"`
	BySplitLanguage map[string]*Metrics `json:"by_split_language"`
	ByGroup         map[string]*Metrics `json:"by_group"`
	Cases           []CaseResult        `json:"single_target_cases"`
	Ambiguous       []UnscoredResult    `json:"ambiguous_cases"`
	NoMatch         []UnscoredResult    `json:"no_match_cases"`
	// Descriptive count only: no approved false-positive definition exists.
	NoMatchWithAnyResult int `json:"no_match_queries_with_any_result"`
}

// Denominators are fixed by the fixture, independent of any retriever.
type Denominators struct {
	SingleTarget           int            `json:"single_target"`
	SingleTargetBySplit    map[string]int `json:"single_target_by_split"`
	SingleTargetByLanguage map[string]int `json:"single_target_by_language"`
	Ambiguous              int            `json:"ambiguous_unscored"`
	NoMatch                int            `json:"no_match_unscored"`
	TotalQueries           int            `json:"total_queries"`
	CatalogConcepts        int            `json:"catalog_concepts"`
}

func CountDenominators(ev *Evaluation, catalog int) Denominators {
	d := Denominators{SingleTargetBySplit: map[string]int{}, SingleTargetByLanguage: map[string]int{}, TotalQueries: len(ev.Queries), CatalogConcepts: catalog}
	for _, q := range ev.Queries {
		switch q.Bucket {
		case bucketSingleTarget:
			d.SingleTarget++
			d.SingleTargetBySplit[q.Split]++
			d.SingleTargetByLanguage[q.Language]++
		case bucketAmbiguous:
			d.Ambiguous++
		case bucketNoMatch:
			d.NoMatch++
		}
	}
	return d
}

// Evaluate joins a retriever's ranking output with evaluator judgments. It is
// the only place where proposed targets meet results.
func Evaluate(run RetrieverRun, ev *Evaluation) Evaluated {
	out := Evaluated{Cases: []CaseResult{}, Ambiguous: []UnscoredResult{}, NoMatch: []UnscoredResult{}}
	scored := run.State == stateCompleted
	if scored {
		out.Overall = &Metrics{}
		out.BySplit, out.ByLanguage, out.BySplitLanguage, out.ByGroup = map[string]*Metrics{}, map[string]*Metrics{}, map[string]*Metrics{}, map[string]*Metrics{}
	}
	bucket := func(m map[string]*Metrics, k string) *Metrics {
		if m[k] == nil {
			m[k] = &Metrics{}
		}
		return m[k]
	}
	for i, q := range ev.Queries {
		var hits []Hit
		if i < len(run.Queries) {
			hits = run.Queries[i].Hits
		}
		switch q.Bucket {
		case bucketSingleTarget:
			c := CaseResult{QueryID: q.FixtureID, Split: q.Split, Language: q.Language, GroupID: q.GroupID, TargetFixtureID: q.TargetFixtureID}
			rank := 0
			for _, h := range hits {
				if h.ConceptID == q.TargetID {
					rank = h.Rank
					r := h.Rank
					c.TargetRank = &r
					break
				}
			}
			out.Cases = append(out.Cases, c)
			if scored {
				out.Overall.add(rank)
				bucket(out.BySplit, q.Split).add(rank)
				bucket(out.ByLanguage, q.Language).add(rank)
				bucket(out.BySplitLanguage, q.Split+"/"+q.Language).add(rank)
				bucket(out.ByGroup, q.GroupID).add(rank)
			}
		case bucketAmbiguous:
			u := UnscoredResult{QueryID: q.FixtureID, Split: q.Split, Language: q.Language, Returned: len(hits), AlternativeRanks: map[string]*int{}}
			for _, alt := range q.PossibleFixtureIDs {
				u.AlternativeRanks[alt] = nil
				for _, h := range hits {
					if h.ConceptFixtureID == alt {
						r := h.Rank
						u.AlternativeRanks[alt] = &r
					}
				}
			}
			out.Ambiguous = append(out.Ambiguous, u)
		case bucketNoMatch:
			out.NoMatch = append(out.NoMatch, UnscoredResult{QueryID: q.FixtureID, Split: q.Split, Language: q.Language, Returned: len(hits)})
			if len(hits) > 0 {
				out.NoMatchWithAnyResult++
			}
		}
	}
	if scored {
		out.Overall.finish()
		for _, m := range []map[string]*Metrics{out.BySplit, out.ByLanguage, out.BySplitLanguage, out.ByGroup} {
			for _, v := range m {
				v.finish()
			}
		}
	}
	return out
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
