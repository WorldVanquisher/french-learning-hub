package config

import (
	"reflect"
	"strings"
	"testing"
)

func TestHTTPBoundaryConfiguration(t *testing.T) {
	t.Setenv("HTTP_ALLOWED_HOSTS", "")
	t.Setenv("HTTP_TRUSTED_ORIGINS", "")
	cfg, err := loadHTTPBoundary(source{})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(cfg.AllowedHosts, []string{"localhost", "127.0.0.1", "::1"}) || !reflect.DeepEqual(cfg.TrustedOrigins, []string{"http://localhost:5173", "http://127.0.0.1:5173", "http://[::1]:5173"}) {
		t.Fatalf("unexpected defaults: %+v", cfg)
	}
	t.Setenv("HTTP_ALLOWED_HOSTS", " NAS.home ,192.168.1.20,fd00::20")
	t.Setenv("HTTP_TRUSTED_ORIGINS", "https://NAS.home:443,http://localhost:5174")
	cfg, err = loadHTTPBoundary(source{})
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(cfg.AllowedHosts, []string{"localhost", "127.0.0.1", "::1", "nas.home", "192.168.1.20", "fd00::20"}) || !reflect.DeepEqual(cfg.TrustedOrigins, []string{"https://nas.home", "http://localhost:5174"}) {
		t.Fatalf("unexpected explicit configuration: %+v", cfg)
	}
}

func TestHTTPBoundaryInvalidConfigurationIsSafe(t *testing.T) {
	for _, key := range []string{"HTTP_ALLOWED_HOSTS", "HTTP_TRUSTED_ORIGINS"} {
		values := []string{"*", "a,,b", "  ", "SECRET_VALUE/path", "http://user:SECRET_VALUE@localhost", "null", "https://localhost?", "https://localhost#", "localhost:8080", "[::1]", "localhost.", "a_b", "fe80::1%eth0"}
		if key == "HTTP_ALLOWED_HOSTS" {
			// null is a valid literal DNS name, not a wildcard.
			values = append(values[:5], values[6:]...)
		}
		for _, value := range values {
			t.Run(key+"/"+value, func(t *testing.T) {
				t.Setenv("HTTP_ALLOWED_HOSTS", "")
				t.Setenv("HTTP_TRUSTED_ORIGINS", "")
				t.Setenv(key, value)
				_, err := loadHTTPBoundary(source{})
				if err == nil || !strings.Contains(err.Error(), key) || strings.Contains(err.Error(), "SECRET_VALUE") {
					t.Fatalf("expected secret-safe configuration error, got %v", err)
				}
			})
		}
	}
}

func TestNormalizeHTTPAuthority(t *testing.T) {
	for _, tc := range []struct{ input, host, authority string }{
		{"LOCALHOST:8080", "localhost", "localhost:8080"},
		{"127.0.0.1", "127.0.0.1", "127.0.0.1"},
		{"[0:0:0:0:0:0:0:1]:8080", "::1", "[::1]:8080"},
		{"[fd00::20]", "fd00::20", "[fd00::20]"},
		{"nas.home:18080", "nas.home", "nas.home:18080"},
	} {
		host, authority, err := NormalizeHTTPAuthority(tc.input)
		if err != nil || host != tc.host || authority != tc.authority {
			t.Errorf("%q => %q, %q, %v", tc.input, host, authority, err)
		}
	}
	for _, input := range []string{"", "localhost:", "localhost:0", "localhost:65536", "localhost:-1", "localhost:secret", "localhost/path", "localhost?", "localhost#", "user:secret@localhost", "::1", "[localhost]", "[127.0.0.1]", "fe80::1%eth0", "localhost.", "a_b", "localhost,attacker.example"} {
		if _, _, err := NormalizeHTTPAuthority(input); err == nil {
			t.Errorf("accepted invalid authority %q", input)
		}
	}
}

func TestLoadHTTPBoundaryUsesResolvedSource(t *testing.T) {
	clearAIEnv(t)
	t.Setenv("EXTRACTOR_PROVIDER", "disabled")
	t.Setenv("HTTP_ALLOWED_HOSTS", "")
	t.Setenv("HTTP_TRUSTED_ORIGINS", "")
	cfg, err := load(source{dotenv: map[string]string{"HTTP_ALLOWED_HOSTS": "ignored.example"}})
	if err != nil || len(cfg.HTTPBoundary.AllowedHosts) != 3 {
		t.Fatalf("empty process value must override file: %+v, %v", cfg.HTTPBoundary, err)
	}
	t.Setenv("HTTP_ALLOWED_HOSTS", "*")
	if _, err := load(source{}); err == nil {
		t.Fatal("Load must reject invalid boundary before server startup")
	}
}
