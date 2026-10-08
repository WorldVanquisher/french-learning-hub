package domain

import (
	"context"
	"fmt"
	"regexp"
	"strings"
)

var operationUUID = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// NormalizeAnnotationOperationID accepts UUID text in canonical hyphenated form.
func NormalizeAnnotationOperationID(id string) (string, error) {
	if !operationUUID.MatchString(id) {
		return "", fmt.Errorf("%w: invalid annotation operation ID", ErrValidation)
	}
	return strings.ToLower(id), nil
}

// AnnotationOperationInput contains every accepted semantic field. Action is
// distinct or relation; relation is populated only for the latter.
type AnnotationOperationInput struct {
	Action    string          `json:"action"`
	UnitID    int64           `json:"unit_id"`
	ConceptID int64           `json:"concept_id"`
	Relation  ConceptRelation `json:"relation,omitempty"`
}

func (in AnnotationOperationInput) Validate() error {
	if in.UnitID <= 0 || in.ConceptID <= 0 || (in.Action != "distinct" && in.Action != "relation") ||
		(in.Action == "distinct" && in.Relation != "") ||
		(in.Action == "relation" && (!ValidConceptRelation(in.Relation) || in.Relation == RelationSame)) {
		return fmt.Errorf("%w: invalid annotation operation", ErrValidation)
	}
	return nil
}

// AnnotationOperation is a historical committed result, never current authority.
type AnnotationOperation struct {
	ID          string
	Input       AnnotationOperationInput
	Distinction *UnitConceptDistinction
	Link        *UnitConceptLink
}
type AnnotationOperationRepository interface {
	CommitAnnotationOperation(context.Context, string, AnnotationOperationInput, string) (*AnnotationOperation, bool, error)
	GetAnnotationOperation(context.Context, string) (*AnnotationOperation, error)
}
