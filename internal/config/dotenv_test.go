package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// configKeys are every variable Load reads. Tests unset all of them so the
// developer's own environment cannot influence a result.
var configKeys = []string{
	"PORT", "DB_PATH", "HTTP_READ_TIMEOUT", "HTTP_WRITE_TIMEOUT",
	"AI_PROVIDER", "EXTRACTOR_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL",
	"OPENAI_BASE_URL", "OPENAI_TIMEOUT", "EMBEDDING_PROVIDER", "EMBEDDING_API_KEY",
	"EMBEDDING_MODEL", "EMBEDDING_BASE_URL", "EMBEDDING_TIMEOUT",
}

// fakeSecret is a sentinel, not a credential. Tests assert it never appears in an
// error message.
const fakeSecret = "fake-sentinel-value-0000"

// isolate moves the test into an empty temporary working directory and unsets
// every configuration key for the duration of the test.
func isolate(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Chdir(dir)
	for _, key := range configKeys {
		t.Setenv(key, "") // registers restoration of the original value
		if err := os.Unsetenv(key); err != nil {
			t.Fatalf("unset %s: %v", key, err)
		}
	}
	return dir
}

func writeDotEnv(t *testing.T, dir, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, DotEnvFile), []byte(content), 0o600); err != nil {
		t.Fatalf("write .env: %v", err)
	}
}

func TestLoadWithoutDotEnvUsesDefaults(t *testing.T) {
	isolate(t)

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load without .env: %v", err)
	}
	if cfg.Addr != ":8080" || cfg.DBPath != "data/app.db" {
		t.Fatalf("defaults changed: addr=%q db=%q", cfg.Addr, cfg.DBPath)
	}
	if cfg.AI.Provider != ProviderRuleBased || cfg.Extractor.Provider != ExtractorDisabled || cfg.Embedding.Provider != EmbeddingDisabled {
		t.Fatalf("provider defaults changed: %q %q %q", cfg.AI.Provider, cfg.Extractor.Provider, cfg.Embedding.Provider)
	}
	if cfg.AI.OpenAITimeout != 8*time.Second || cfg.WriteTimeout != 10*time.Second {
		t.Fatalf("timeout defaults changed: openai=%v write=%v", cfg.AI.OpenAITimeout, cfg.WriteTimeout)
	}
}

func TestLoadReadsDotEnvFromWorkingDirectory(t *testing.T) {
	dir := isolate(t)
	writeDotEnv(t, dir, strings.Join([]string{
		"# comments and blank lines are allowed",
		"",
		"PORT=9100",
		"DB_PATH=data/local-trial/app.db",
		"EXTRACTOR_PROVIDER=openai",
		"OPENAI_API_KEY=" + fakeSecret,
		"OPENAI_MODEL=example-model",
		"OPENAI_TIMEOUT=5",
		`EMBEDDING_PROVIDER="http"`,
		"EMBEDDING_MODEL=example-embedding",
		"EMBEDDING_BASE_URL=http://127.0.0.1:9999/v1",
	}, "\n"))

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Addr != ":9100" || cfg.DBPath != "data/local-trial/app.db" {
		t.Fatalf("addr=%q db=%q", cfg.Addr, cfg.DBPath)
	}
	if cfg.Extractor.Provider != ExtractorOpenAI || cfg.Extractor.OpenAIAPIKey != fakeSecret || cfg.Extractor.OpenAITimeout != 5*time.Second {
		t.Fatalf("extractor config not read from .env: provider=%q timeout=%v", cfg.Extractor.Provider, cfg.Extractor.OpenAITimeout)
	}
	if cfg.Embedding.Provider != EmbeddingHTTP || cfg.Embedding.BaseURL != "http://127.0.0.1:9999/v1" {
		t.Fatalf("embedding config not read from .env: %q %q", cfg.Embedding.Provider, cfg.Embedding.BaseURL)
	}
	// The analyzer default is untouched by unrelated .env keys.
	if cfg.AI.Provider != ProviderRuleBased {
		t.Fatalf("AI provider = %q, want rule-based", cfg.AI.Provider)
	}
	// Reading .env never modifies the process environment.
	if _, ok := os.LookupEnv("PORT"); ok {
		t.Fatal("Load exported a .env value into the process environment")
	}
}

func TestProcessEnvironmentTakesPrecedenceOverDotEnv(t *testing.T) {
	dir := isolate(t)
	writeDotEnv(t, dir, "PORT=7000\nOPENAI_MODEL=from-dotenv\nAI_PROVIDER=not-a-provider\nDB_PATH=from-dotenv.db\n")
	t.Setenv("PORT", "9000")
	t.Setenv("OPENAI_MODEL", "from-process")
	// A variable present in the process, even as an empty string, still wins: the
	// invalid .env AI_PROVIDER is never consulted and the default applies.
	t.Setenv("AI_PROVIDER", "")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Addr != ":9000" {
		t.Fatalf("Addr = %q, want process value :9000", cfg.Addr)
	}
	if cfg.AI.OpenAIModel != "from-process" {
		t.Fatalf("OpenAIModel = %q, want process value", cfg.AI.OpenAIModel)
	}
	if cfg.AI.Provider != ProviderRuleBased {
		t.Fatalf("AI provider = %q, want default from empty process value", cfg.AI.Provider)
	}
	// Keys absent from the process still come from .env.
	if cfg.DBPath != "from-dotenv.db" {
		t.Fatalf("DBPath = %q, want .env value", cfg.DBPath)
	}
}

func TestEmptyPlaceholderDotEnvKeepsDefaultsValid(t *testing.T) {
	dir := isolate(t)
	writeDotEnv(t, dir, "OPENAI_API_KEY=\nOPENAI_MODEL=\nEMBEDDING_API_KEY=\n")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load with empty placeholders: %v", err)
	}
	if cfg.AI.Provider != ProviderRuleBased || cfg.AI.OpenAIAPIKey != "" || cfg.Extractor.Provider != ExtractorDisabled {
		t.Fatalf("empty placeholders changed behavior: %q %q", cfg.AI.Provider, cfg.Extractor.Provider)
	}
}

func TestDotEnvValuesStillPassProviderValidation(t *testing.T) {
	cases := []struct {
		name    string
		content string
		wantErr string
	}{
		{"unknown provider", "AI_PROVIDER=bogus\n", `unknown AI_PROVIDER "bogus"`},
		{"missing key", "EXTRACTOR_PROVIDER=openai\nOPENAI_MODEL=m\n", "EXTRACTOR_PROVIDER=openai requires OPENAI_API_KEY"},
		{"missing model", "AI_PROVIDER=openai\nOPENAI_API_KEY=" + fakeSecret + "\n", "AI_PROVIDER=openai requires OPENAI_MODEL"},
		{"missing embedding url", "EMBEDDING_PROVIDER=http\nEMBEDDING_MODEL=m\nEMBEDDING_API_KEY=" + fakeSecret + "\n", "requires EMBEDDING_BASE_URL"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dir := isolate(t)
			writeDotEnv(t, dir, tc.content)
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), tc.wantErr) {
				t.Fatalf("err = %v, want containing %q", err, tc.wantErr)
			}
			if strings.Contains(err.Error(), fakeSecret) {
				t.Fatalf("validation error exposed a secret value: %v", err)
			}
		})
	}
}

func TestMalformedDotEnvErrorIsClearAndSecretSafe(t *testing.T) {
	cases := []struct {
		name     string
		content  string
		wantKind string
	}{
		{
			name:     "unterminated quote",
			content:  "PORT=8080\nOPENAI_API_KEY=\"" + fakeSecret + "\nOPENAI_MODEL=m\n",
			wantKind: "unterminated quoted value",
		},
		{
			name:     "invalid variable name",
			content:  "BAD-NAME=1\nOPENAI_API_KEY=" + fakeSecret + "\n",
			wantKind: "invalid character in a variable name",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dir := isolate(t)
			writeDotEnv(t, dir, tc.content)

			_, err := Load()
			if err == nil {
				t.Fatal("expected an error for a malformed .env")
			}
			msg := err.Error()
			for _, want := range []string{".env", "malformed", tc.wantKind, "values are not shown"} {
				if !strings.Contains(msg, want) {
					t.Fatalf("error %q does not contain %q", msg, want)
				}
			}
			for _, leaked := range []string{fakeSecret, "OPENAI_API_KEY", "BAD-NAME"} {
				if strings.Contains(msg, leaked) {
					t.Fatalf("error exposes .env content %q: %q", leaked, msg)
				}
			}
		})
	}
}

func TestUnreadableDotEnvIsAnError(t *testing.T) {
	dir := isolate(t)
	if err := os.Mkdir(filepath.Join(dir, DotEnvFile), 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	_, err := Load()
	if err == nil || !strings.Contains(err.Error(), "cannot read .env") {
		t.Fatalf("err = %v, want a cannot-read error", err)
	}
}

func TestSingleQuotedDotEnvValuesAreLiteral(t *testing.T) {
	dir := isolate(t)
	// godotenv expands $NAME in unquoted and double-quoted values; single quotes
	// keep a value such as a key containing "$" exactly as written.
	writeDotEnv(t, dir, "EXTRACTOR_PROVIDER=openai\nOPENAI_MODEL=m\nOPENAI_API_KEY='abc$DEF'\n")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Extractor.OpenAIAPIKey != "abc$DEF" {
		t.Fatalf("single-quoted value was altered: got length %d", len(cfg.Extractor.OpenAIAPIKey))
	}
}
