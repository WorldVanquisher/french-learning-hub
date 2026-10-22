package domain

import (
	"errors"
	"strings"
	"testing"
)

func suggestionRequest() SuggestionRequest {
	return SuggestionRequest{Units: []SuggestionUnitInput{
		{UnitID: 1, Candidates: []SuggestionConceptInput{{ConceptID: 10}, {ConceptID: 11}}},
		{UnitID: 2, Candidates: []SuggestionConceptInput{{ConceptID: 12}}},
	}}
}

func id(n int64) *int64 { return &n }

func TestValidateSuggestionProposals(t *testing.T) {
	ok := []SuggestionProposal{
		{UnitID: 2, Outcome: SuggestionUncertain, Reason: "Not enough evidence."},
		{UnitID: 1, Outcome: SuggestionSuggested, ConceptID: id(11), Reason: " same "},
	}
	got, err := ValidateSuggestionProposals(suggestionRequest(), ok)
	if err != nil || got[0].UnitID != 1 || got[0].Reason != "same" || got[1].UnitID != 2 {
		t.Fatalf("got %+v, %v (want request order, trimmed reasons)", got, err)
	}
	bad := map[string][]SuggestionProposal{
		"missing":         {ok[1]},
		"foreign unit":    append(append([]SuggestionProposal{}, ok...), SuggestionProposal{UnitID: 3, Outcome: SuggestionUncertain, Reason: "x"}),
		"duplicate":       {ok[0], ok[0], ok[1]},
		"foreign concept": {ok[0], {UnitID: 1, Outcome: SuggestionSuggested, ConceptID: id(12), Reason: "x"}},
		"no concept":      {ok[0], {UnitID: 1, Outcome: SuggestionSuggested, Reason: "x"}},
		"concept on none": {ok[0], {UnitID: 1, Outcome: SuggestionNoSuitableCandidate, ConceptID: id(10), Reason: "x"}},
		"local outcome":   {ok[0], {UnitID: 1, Outcome: SuggestionNoCandidates, Reason: "x"}},
		"empty reason":    {ok[0], {UnitID: 1, Outcome: SuggestionUncertain, Reason: "   "}},
		"long reason":     {ok[0], {UnitID: 1, Outcome: SuggestionUncertain, Reason: strings.Repeat("é", MaxSuggestionReasonChars+1)}},
	}
	for name, proposals := range bad {
		if _, err := ValidateSuggestionProposals(suggestionRequest(), proposals); !errors.Is(err, ErrValidation) {
			t.Errorf("%s: err = %v", name, err)
		}
	}
}

func TestValidateSuggestionUnitIDs(t *testing.T) {
	if err := ValidateSuggestionUnitIDs([]int64{3, 1, 2}); err != nil {
		t.Fatal(err)
	}
	tooMany := make([]int64, MaxSuggestionUnits+1)
	for i := range tooMany {
		tooMany[i] = int64(i + 1)
	}
	for name, ids := range map[string][]int64{"empty": nil, "too many": tooMany, "dup": {1, 1}, "zero": {0}} {
		if err := ValidateSuggestionUnitIDs(ids); !errors.Is(err, ErrValidation) {
			t.Errorf("%s: err = %v", name, err)
		}
	}
}

func TestSuggestionStaleErrorIsConflict(t *testing.T) {
	err := error(&SuggestionStaleError{Reasons: []SuggestionStaleReason{StaleUnitHasCurrentSame}})
	if !errors.Is(err, ErrConceptConflict) || !strings.Contains(err.Error(), "unit_has_current_same") {
		t.Fatal(err)
	}
}

func TestSuggestionTextChars(t *testing.T) {
	ex := "é"
	u := SuggestionUnitInput{Canonical: "ab", Statement: "çé", Example: &ex}
	c := SuggestionConceptInput{Target: "a", IdentityFeatures: map[string]string{"k": "vv"}, MemberExamples: []SuggestionMemberExample{{Canonical: "x", Statement: "yz"}}}
	if u.TextChars() != 5 || c.TextChars() != 7 {
		t.Fatalf("chars %d %d", u.TextChars(), c.TextChars())
	}
}
