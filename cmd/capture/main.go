// Command capture is a thin CLI for the French Learning Hub POST /captures
// endpoint. It reads a prepared learning_capture_v1 JSON document from a file or
// stdin and posts it, unchanged, to the backend. With -batch it sends an
// explicit, bounded list of such files one at a time (see batchUsage), and with
// -batch -preview it checks those files locally without any HTTP request.
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
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"french-learning-app/internal/captureclient"
)

const defaultURL = "http://localhost:8080"

// maxPayload bounds how much input the CLI reads, so a runaway file or stream
// cannot exhaust memory. Captures are small structured documents.
const maxPayload = 1 << 20 // 1 MiB

// Batch exit statuses. The single-file mode keeps its original 0/1 contract.
const (
	exitOK          = 0 // batch: every file created or replayed; preview: every file ready
	exitRejected    = 1 // batch: some file conflict or invalid, none unconfirmed; preview: some file invalid
	exitUsage       = 2 // refused before any file was read or sent
	exitUnconfirmed = 3 // batch: some file unconfirmed or not attempted; rerun the same files
)

// exitError carries a specific exit status. An empty message prints nothing
// (the report already explains the outcome).
type exitError struct {
	code int
	msg  string
}

func (e *exitError) Error() string { return e.msg }

func main() {
	if err := run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr); err != nil {
		var ee *exitError
		if errors.As(err, &ee) {
			if ee.msg != "" {
				fmt.Fprintf(os.Stderr, "capture: %s\n", ee.msg)
			}
			os.Exit(ee.code)
		}
		fmt.Fprintf(os.Stderr, "capture: %v\n", err)
		os.Exit(1)
	}
}

// run parses flags, reads the payload from -file or stdin, posts it, and reports
// the result. It returns an error (causing a non-zero exit) for any failure,
// including server conflicts and validation errors; an idempotent replay is a
// success. With -batch it delegates to runBatch, whose *exitError carries the
// batch exit status; the single-file contract (0 success, 1 any failure) is
// unchanged.
func run(args []string, stdin io.Reader, stdout, stderr io.Writer) error {
	fs := flag.NewFlagSet("capture", flag.ContinueOnError)
	fs.SetOutput(stderr)
	fs.Usage = func() {
		fmt.Fprintf(stderr, "Usage: capture [-url URL] [-file capture.json]\n")
		fmt.Fprintf(stderr, "       capture -batch [-preview] [-url URL] FILE...\n\n")
		fmt.Fprintf(stderr, "Posts a learning_capture_v1 JSON document to the French Learning Hub.\n")
		fmt.Fprintf(stderr, "Reads from -file, or from stdin when -file is omitted.\n\n")
		fmt.Fprint(stderr, batchUsage)
		fmt.Fprintf(stderr, "Backend URL precedence: -url flag, then FRENCH_HUB_URL, then %s\n\n", defaultURL)
		fmt.Fprintf(stderr, "Flags:\n")
		fs.PrintDefaults()
	}

	var (
		urlFlag  = fs.String("url", "", "backend base URL (overrides FRENCH_HUB_URL; default "+defaultURL+")")
		fileFlag = fs.String("file", "", "path to a learning_capture_v1 JSON file (default: read stdin)")
		batch    = fs.Bool("batch", false, fmt.Sprintf("send the FILE arguments one at a time, in path order (at most %d)", captureclient.MaxBatchFiles))
		preview  = fs.Bool("preview", false, "with -batch: check the files locally and send nothing (no HTTP request)")
	)
	if err := fs.Parse(args); err != nil {
		return err
	}

	baseURL := resolveURL(*urlFlag, os.Getenv("FRENCH_HUB_URL"))

	switch {
	case *batch && *fileFlag != "":
		return usageError(stderr, "-file cannot be combined with -batch; list the files as arguments")
	case *preview && !*batch:
		return usageError(stderr, "-preview requires -batch")
	case !*batch && fs.NArg() > 0:
		return usageError(stderr, "unexpected arguments; use -file for one file or -batch FILE... for several")
	case *batch:
		return runBatch(baseURL, *preview, fs.Args(), stdout, stderr)
	}

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

const batchUsage = `Batch mode (-batch FILE...):
  Sends each file, unchanged, as its own POST /captures request, one at a time,
  in byte-wise path order. The server decides every outcome except local file
  problems. Nothing is retried automatically.

  Local checks (this program): the list has 1 to 100 files and no file twice;
  each file exists, is a regular readable file, is at most 1 MiB and not blank.
  Server-only checks: JSON shape and fields, schema_version, capture_id format,
  source, entry and analysis validation, taxonomy, and whether the capture_id is
  new (created), already stored identically (replayed) or stored with different
  content (conflict).

  Outcomes: created, replayed, conflict, invalid, unconfirmed (sent, but no
  usable response: it may or may not be stored), not_attempted (never
  delivered: the connection failed, or the batch was interrupted or stopped
  after 3 files in a row without a server response). Rerun the same files to
  settle unconfirmed and not_attempted files: a stored capture comes back as
  replayed, never as a duplicate.

  -preview checks the files locally and makes no HTTP request.

  Exit status: 0 all created/replayed (preview: all ready); 1 some conflict or
  invalid; 3 some unconfirmed or not_attempted (rerun); 2 refused before any
  file was read or sent. Reports show capture_ids, paths and status codes only,
  never learner text or request bodies.

`

// usageError prints the usage and returns exit status 2.
func usageError(stderr io.Writer, msg string) error {
	fmt.Fprintf(stderr, "capture: %s\n\n", msg)
	fmt.Fprintf(stderr, "Usage: capture [-url URL] [-file capture.json]\n")
	fmt.Fprintf(stderr, "       capture -batch [-preview] [-url URL] FILE...\n")
	return &exitError{code: exitUsage}
}

// runBatch executes -batch (or -batch -preview) and maps the report to an exit
// status.
func runBatch(baseURL string, preview bool, files []string, stdout, stderr io.Writer) error {
	for _, f := range files {
		if strings.HasPrefix(f, "-") {
			return usageError(stderr, "flags must come before the files, and stdin (-) is not a batch input")
		}
	}
	if preview {
		rep, err := captureclient.PreviewBatch(files)
		if err != nil {
			return &exitError{code: exitUsage, msg: err.Error()}
		}
		printBatch(stdout, rep, "")
		if rep.Count(captureclient.OutcomeInvalid) > 0 {
			return &exitError{code: exitRejected}
		}
		return nil
	}

	client, err := captureclient.New(baseURL)
	if err != nil {
		return &exitError{code: exitUsage, msg: err.Error()}
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	rep, err := client.RunBatch(ctx, files)
	if err != nil {
		return &exitError{code: exitUsage, msg: err.Error()}
	}
	printBatch(stdout, rep, redactURL(baseURL))
	return batchExit(rep)
}

// batchExit maps a submitted batch to its exit status.
func batchExit(rep *captureclient.BatchReport) error {
	switch {
	case rep.Count(captureclient.OutcomeUnconfirmed)+rep.Count(captureclient.OutcomeNotAttempted) > 0:
		return &exitError{code: exitUnconfirmed}
	case rep.Count(captureclient.OutcomeConflict)+rep.Count(captureclient.OutcomeInvalid) > 0:
		return &exitError{code: exitRejected}
	}
	return nil
}

// redactURL removes any user:password from the URL before it is printed.
func redactURL(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return "(backend URL)"
	}
	return u.Redacted()
}

// printBatch writes the per-file lines, the summary and next steps. Each file
// line carries the outcome, path, capture_id label, who decided and the HTTP
// status: identifiers only, never learner text or request bodies.
func printBatch(w io.Writer, rep *captureclient.BatchReport, target string) {
	n := len(rep.Files)
	if rep.Preview {
		fmt.Fprintf(w, "capture batch PREVIEW: %d file(s) in path order; no HTTP request is made\n", n)
		fmt.Fprintln(w, "local checks run: file exists, regular and readable, at most 1 MiB, not blank; no file listed twice")
		fmt.Fprintln(w, "server-only checks NOT run: JSON fields, schema_version, capture_id format, source, entry/analysis validation, taxonomy, created vs replayed vs conflict")
	} else {
		fmt.Fprintf(w, "capture batch: %d file(s) in path order, one request each to %s/captures, no automatic retry\n", n, target)
	}
	for _, f := range rep.Files {
		id := f.CaptureID
		if id == "" {
			id = "-"
		}
		fmt.Fprintf(w, "[%d/%d] %-13s %s  capture_id=%s  checked=%s", f.Index, n, f.Outcome, captureclient.DisplayPath(f.Path), id, f.Checked)
		if f.Status != 0 {
			fmt.Fprintf(w, "  status=%d", f.Status)
		}
		if f.Outcome == captureclient.OutcomeCreated || f.Outcome == captureclient.OutcomeReplayed {
			analysis := "null"
			if f.AnalysisID != nil {
				analysis = fmt.Sprintf("%d", *f.AnalysisID)
			}
			fmt.Fprintf(w, "  entry_id=%d  analysis_id=%s", f.EntryID, analysis)
		}
		fmt.Fprintf(w, "  # %s\n", f.Detail)
		if f.Warning != "" {
			if rep.Preview {
				fmt.Fprintf(w, "      warning: %s; the server will report the later one as replayed (identical) or conflict (different)\n", f.Warning)
			} else {
				fmt.Fprintf(w, "      note: %s\n", f.Warning)
			}
		}
	}
	fmt.Fprintf(w, "summary: total=%d", n)
	shown := []captureclient.Outcome{captureclient.OutcomeReady, captureclient.OutcomeInvalid}
	if !rep.Preview {
		shown = captureclient.Outcomes[1:] // every outcome except ready
	}
	for _, o := range shown {
		fmt.Fprintf(w, " %s=%d", o, rep.Count(o))
	}
	fmt.Fprintln(w)
	if rep.Interrupted {
		fmt.Fprintln(w, "interrupted: files after the last decided one were not sent")
	} else if rep.StoppedWhy != "" {
		fmt.Fprintf(w, "stopped: %s\n", rep.StoppedWhy)
	}
	if !rep.Preview {
		if rep.Count(captureclient.OutcomeUnconfirmed)+rep.Count(captureclient.OutcomeNotAttempted) > 0 {
			fmt.Fprintln(w, "next: rerun the same command with the same, unchanged files; stored captures report replayed, the rest are sent once")
		}
		if rep.Count(captureclient.OutcomeConflict) > 0 {
			fmt.Fprintln(w, "next: a conflict left the stored capture unchanged; give new content a new capture_id (GET /captures/{capture_id} shows the stored receipt)")
		}
	}
}
