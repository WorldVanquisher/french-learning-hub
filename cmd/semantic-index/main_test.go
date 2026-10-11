package main

import (
	"bytes"
	"context"
	"strings"
	"testing"
	"time"

	"french-learning-app/internal/application"
	"french-learning-app/internal/storage/sqlite"
)

func TestRun_UsageAndConfigurationRefusals(t *testing.T) {
	for _, k := range []string{"SEMANTIC_SEARCH", "EMBEDDING_PROVIDER", "QDRANT_URL", "EMBEDDING_MODEL_ID", "EMBEDDING_DIMENSIONS"} {
		t.Setenv(k, "")
	}
	cases := []struct {
		args []string
		code int
		want string
	}{
		{nil, 2, "usage: semantic-index"},
		{[]string{"reindex"}, 2, `unknown operation "reindex"`},
		{[]string{"sync"}, 1, "semantic search is not configured"},
	}
	for _, c := range cases {
		var out, errOut bytes.Buffer
		if code := run(c.args, &out, &errOut); code != c.code || !strings.Contains(errOut.String(), c.want) {
			t.Fatalf("%v: code %d stderr %q", c.args, code, errOut.String())
		}
	}

	t.Setenv("SEMANTIC_SEARCH", "qdrant")
	t.Setenv("EMBEDDING_PROVIDER", "http")
	t.Setenv("EMBEDDING_MODEL", "m")
	t.Setenv("EMBEDDING_BASE_URL", "http://127.0.0.1:9/v1")
	t.Setenv("QDRANT_URL", "http://127.0.0.1:9")
	t.Setenv("EMBEDDING_MODEL_ID", "m@1")
	t.Setenv("EMBEDDING_DIMENSIONS", "8")
	t.Setenv("DB_PATH", t.TempDir()+"/cli.db")
	var out, errOut bytes.Buffer
	if code := run([]string{"-batch", "999", "sync"}, &out, &errOut); code != 2 || !strings.Contains(errOut.String(), "-batch must be between 1 and 256") {
		t.Fatalf("batch bound: code %d stderr %q", code, errOut.String())
	}
}

func TestRun_BusyLeaseExitsFour(t *testing.T) {
	dbPath := t.TempDir() + "/busy.db"
	for k, v := range map[string]string{
		"SEMANTIC_SEARCH": "qdrant", "EMBEDDING_PROVIDER": "http", "EMBEDDING_MODEL": "m",
		"EMBEDDING_BASE_URL": "http://127.0.0.1:9/v1", "QDRANT_URL": "http://127.0.0.1:9",
		"EMBEDDING_MODEL_ID": "m@1", "EMBEDDING_DIMENSIONS": "8", "DB_PATH": dbPath,
	} {
		t.Setenv(k, v)
	}
	db, err := sqlite.Open(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	space, _ := application.NewSemanticIndexSpace("flh_concepts", "m@1", 8)
	now := time.Now().UTC()
	if err := sqlite.NewSemanticIndexRepository(db).AcquireLease(context.Background(), space, "other-run-000000", "rebuild", now, now.Add(time.Hour), false); err != nil {
		t.Fatal(err)
	}
	db.Close()
	var out, errOut bytes.Buffer
	if code := run([]string{"sync"}, &out, &errOut); code != 4 || !strings.Contains(errOut.String(), "busy:") || !strings.Contains(errOut.String(), "other-run-000000") {
		t.Fatalf("code %d stderr %q", code, errOut.String())
	}
}
