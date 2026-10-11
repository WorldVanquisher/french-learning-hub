package application

import "time"

// LEGACY (FLH-040) types for the migration-010 bookkeeping tables. Since
// FLH-042 no production code uses them; they remain only for the legacy
// repository methods kept so the FLH-041 diagnostic compiles. See
// internal/storage/sqlite/semantic_index_legacy.go.

const (
	SemanticIndexStateBuilding = "building"
	SemanticIndexStateComplete = "complete"
	SemanticIndexStatePartial  = "partial"
)

// SemanticIndexCollection is the FLH-040 bookkeeping row (legacy).
type SemanticIndexCollection struct {
	Collection     string     `json:"collection"`
	Representation string     `json:"representation"`
	ModelID        string     `json:"model_id"`
	Dimensions     int        `json:"dimensions"`
	State          string     `json:"state"`
	RunID          string     `json:"run_id"`
	RunOperation   string     `json:"run_operation"`
	RunStartedAt   time.Time  `json:"run_started_at"`
	UpdatedAt      time.Time  `json:"updated_at"`
	CompletedAt    *time.Time `json:"completed_at"`
	LastError      string     `json:"last_error"`
}
