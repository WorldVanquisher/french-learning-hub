// Command capture is a thin CLI for the French Learning Hub POST /captures
// endpoint. It reads a prepared learning_capture_v1 JSON document from a file or
// stdin and posts it, unchanged, to the backend.
//
// It is NOT a chatbot, NOT an analyzer, and NOT an importer that rewrites data:
// it neither contacts any model nor modifies the payload. The server owns every
// capture rule (schema, source, entry, taxonomy, and analysis validation,
// fingerprinting, idempotency, and conflict detection); this command only
// transports the JSON over HTTP.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"

	"french-learning-app/internal/captureclient"
)

const defaultURL = "http://localhost:8080"

// maxPayload bounds how much input the CLI reads, so a runaway file or stream
// cannot exhaust memory. Captures are small structured documents.
const maxPayload = 1 << 20 // 1 MiB

func main() {
	if err := run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr); err != nil {
		fmt.Fprintf(os.Stderr, "capture: %v\n", err)
		os.Exit(1)
	}
}

// run parses flags, reads the payload from -file or stdin, posts it, and reports
// the result. It returns an error (causing a non-zero exit) for any failure,
// including server conflicts and validation errors; an idempotent replay is a
// success.
func run(args []string, stdin io.Reader, stdout, stderr io.Writer) error {
	fs := flag.NewFlagSet("capture", flag.ContinueOnError)
	fs.SetOutput(stderr)
	fs.Usage = func() {
		fmt.Fprintf(stderr, "Usage: capture [-url URL] [-file capture.json]\n\n")
		fmt.Fprintf(stderr, "Posts a learning_capture_v1 JSON document to the French Learning Hub.\n")
		fmt.Fprintf(stderr, "Reads from -file, or from stdin when -file is omitted.\n\n")
		fmt.Fprintf(stderr, "Backend URL precedence: -url flag, then FRENCH_HUB_URL, then %s\n\n", defaultURL)
		fmt.Fprintf(stderr, "Flags:\n")
		fs.PrintDefaults()
	}

	var (
		urlFlag  = fs.String("url", "", "backend base URL (overrides FRENCH_HUB_URL; default "+defaultURL+")")
		fileFlag = fs.String("file", "", "path to a learning_capture_v1 JSON file (default: read stdin)")
	)
	if err := fs.Parse(args); err != nil {
		return err
	}

	baseURL := resolveURL(*urlFlag, os.Getenv("FRENCH_HUB_URL"))

	payload, err := readPayload(*fileFlag, stdin)
	if err != nil {
		return err
	}

	client, err := captureclient.New(baseURL)
	if err != nil {
		return err
	}

	// Cancel the request on Ctrl-C / SIGTERM so a hung backend does not block.
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	result, err := client.Import(ctx, payload)
	if err != nil {
		return err
	}

	printResult(stdout, result)
	return nil
}

// resolveURL applies the documented precedence: -url flag, then FRENCH_HUB_URL,
// then the built-in default.
func resolveURL(flagVal, envVal string) string {
	if flagVal != "" {
		return flagVal
	}
	if envVal != "" {
		return envVal
	}
	return defaultURL
}

// readPayload reads the capture JSON from path, or from stdin when path is
// empty, bounded to maxPayload bytes.
func readPayload(path string, stdin io.Reader) ([]byte, error) {
	var r io.Reader
	if path != "" {
		f, err := os.Open(path)
		if err != nil {
			return nil, fmt.Errorf("open capture file: %w", err)
		}
		defer f.Close()
		r = f
	} else {
		r = stdin
	}

	// Read one extra byte to detect payloads that exceed the cap.
	b, err := io.ReadAll(io.LimitReader(r, maxPayload+1))
	if err != nil {
		return nil, fmt.Errorf("read capture payload: %w", err)
	}
	if len(b) > maxPayload {
		return nil, errors.New("capture payload exceeds 1 MiB limit")
	}
	return b, nil
}

// printResult writes a stable, human-readable summary of the import result.
func printResult(w io.Writer, r *captureclient.Result) {
	analysis := "null"
	if r.AnalysisID != nil {
		analysis = fmt.Sprintf("%d", *r.AnalysisID)
	}
	if r.Created {
		fmt.Fprintln(w, "capture stored (new)")
	} else {
		fmt.Fprintln(w, "capture already existed (idempotent replay)")
	}
	fmt.Fprintf(w, "capture_id:  %s\n", r.CaptureID)
	fmt.Fprintf(w, "entry_id:    %d\n", r.EntryID)
	fmt.Fprintf(w, "analysis_id: %s\n", analysis)
	fmt.Fprintf(w, "created:     %t\n", r.Created)
}
