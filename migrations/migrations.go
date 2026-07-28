// Package migrations embeds the SQL migration files so they ship inside the
// binary and can be applied at startup without external file dependencies.
package migrations

import "embed"

// Files holds every .sql migration, applied in lexical filename order.
//
//go:embed *.sql
var Files embed.FS
