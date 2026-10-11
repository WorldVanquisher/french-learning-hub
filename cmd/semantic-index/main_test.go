package main

import (
	"bytes"
	"strings"
	"testing"
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
