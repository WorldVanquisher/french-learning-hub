package sqlite

import (
	"strings"
	"time"

	driver "modernc.org/sqlite"
)

// Timestamp text must be compared as instants: RFC3339Nano trims fractional
// zeros, and equivalent instants can have different offsets. A read-time
// collation preserves existing rows and Go's nanosecond comparison semantics.
// Registration applies to every subsequently opened driver connection.
func init() {
	driver.MustRegisterCollationUtf8("flh_timestamp_v1", compareTimestampText)
}

func compareTimestampText(left, right string) int {
	l, le := time.Parse(time.RFC3339Nano, left)
	r, re := time.Parse(time.RFC3339Nano, right)
	if le == nil && re == nil {
		return l.Compare(r)
	}
	// Collations cannot return errors. Keep invalid values in a separate, greater
	// class so latest-record reads select them and their scanners reject them,
	// rather than silently treating corrupted timestamps as older valid records.
	if le != nil && re == nil {
		return 1
	}
	if le == nil && re != nil {
		return -1
	}
	return strings.Compare(left, right)
}
