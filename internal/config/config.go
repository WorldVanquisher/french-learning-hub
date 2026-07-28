// Package config loads runtime configuration from the environment, applying
// safe defaults for local development.
package config

import (
	"os"
	"strconv"
	"time"
)

// Config holds the server's runtime settings.
type Config struct {
	// Addr is the TCP address the HTTP server listens on (e.g. ":8080").
	Addr string
	// DBPath is the filesystem path to the SQLite database file.
	DBPath string
	// ReadTimeout and WriteTimeout bound HTTP request handling.
	ReadTimeout  time.Duration
	WriteTimeout time.Duration
}

// Load builds a Config from environment variables, falling back to defaults
// suitable for local development.
//
//	PORT        -> Addr (":" + PORT), default ":8080"
//	DB_PATH     -> DBPath, default "data/app.db"
func Load() Config {
	return Config{
		Addr:         ":" + getenv("PORT", "8080"),
		DBPath:       getenv("DB_PATH", "data/app.db"),
		ReadTimeout:  getdur("HTTP_READ_TIMEOUT", 10*time.Second),
		WriteTimeout: getdur("HTTP_WRITE_TIMEOUT", 10*time.Second),
	}
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getdur(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if secs, err := strconv.Atoi(v); err == nil && secs > 0 {
			return time.Duration(secs) * time.Second
		}
	}
	return def
}
