package sqlite

import (
	sqldriver "database/sql/driver"
	"strings"

	driver "modernc.org/sqlite"
)

// searchFoldFunction is the deterministic SQL function used by the learning-record
// text filter (FLH-090). It lower-cases text with Go's Unicode mapping, so the
// filter is case-insensitive for every script, not only ASCII as SQLite's LIKE
// is. It performs no accent folding and no Unicode normalization: "é" and "e"
// differ, and a decomposed "é" does not match a composed one. NULL stays NULL.
// It is a read-time helper only; nothing stores folded text.
const searchFoldFunction = "flh_search_fold_v1"

func init() {
	driver.MustRegisterDeterministicScalarFunction(searchFoldFunction, 1,
		func(_ *driver.FunctionContext, args []sqldriver.Value) (sqldriver.Value, error) {
			switch v := args[0].(type) {
			case nil:
				return nil, nil
			case string:
				return foldSearchText(v), nil
			case []byte:
				return foldSearchText(string(v)), nil
			default:
				return nil, nil
			}
		})
}

// foldSearchText is applied to both the query and the stored text, so they are
// always compared under the same mapping.
func foldSearchText(s string) string { return strings.ToLower(s) }
