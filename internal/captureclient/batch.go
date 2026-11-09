package captureclient

// Batch import: an explicit, bounded list of learning_capture_v1 files sent one
// at a time, unchanged, through Client.Import (POST /captures).
//
// The batch runner adds orchestration and reporting only. Validation,
// fingerprinting, idempotency and conflict detection stay on the server, so
// every outcome except a local file problem is decided by the server's response:
//
//	201              -> created
//	200              -> replayed  (the server already holds identical content)
//	409              -> conflict  (same capture_id, different content; server unchanged)
//	400 / 422        -> invalid   (checked by the server; nothing stored)
//	anything else    -> unconfirmed (no usable response: the capture may or may
//	                    not have been stored)
//	no connection    -> not_attempted (the server received nothing)
//
// Nothing is retried automatically. Rerunning the same files is the recovery
// path: the server's capture receipt reports a committed capture as replayed and
// an uncommitted one as created, so no duplicate record can result.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"sort"
	"strings"
)

// MaxBatchFiles bounds one batch. Larger sets are split by the caller into
// several explicit runs.
const MaxBatchFiles = 100

// MaxPayloadBytes bounds a single capture file, matching the single-file CLI.
const MaxPayloadBytes = 1 << 20 // 1 MiB

// maxConsecutiveNoResponse stops a batch whose server has stopped answering
// (unconfirmed files or failed connections in a row), so a down backend is not
// contacted once per remaining file.
const maxConsecutiveNoResponse = 3

// maxDetail bounds any diagnostic text taken from an error or a server message.
const maxDetail = 160

// Outcome is the per-file result of a batch run or preview.
type Outcome string

const (
	// OutcomeReady (preview only): local checks passed; the server outcome is unknown.
	OutcomeReady Outcome = "ready"
	// OutcomeCreated: the server stored a new capture (201).
	OutcomeCreated Outcome = "created"
	// OutcomeReplayed: the server already held identical content under this capture_id (200).
	OutcomeReplayed Outcome = "replayed"
	// OutcomeConflict: the server holds different content under this capture_id (409); it kept its copy.
	OutcomeConflict Outcome = "conflict"
	// OutcomeInvalid: rejected by a local file check (never sent) or by server validation (400/422).
	OutcomeInvalid Outcome = "invalid"
	// OutcomeUnconfirmed: sent, but no usable response arrived; it may or may not be stored.
	OutcomeUnconfirmed Outcome = "unconfirmed"
	// OutcomeNotAttempted: never delivered: the batch was interrupted or stopped
	// first, or the connection to the server could not be opened.
	OutcomeNotAttempted Outcome = "not_attempted"
)

// Outcomes lists every outcome in report order.
var Outcomes = []Outcome{OutcomeReady, OutcomeCreated, OutcomeReplayed, OutcomeConflict, OutcomeInvalid, OutcomeUnconfirmed, OutcomeNotAttempted}

// Checked says who decided an outcome.
type Checked string

const (
	CheckedLocal  Checked = "local"  // decided by this client from the file alone
	CheckedServer Checked = "server" // decided by the server's response
	CheckedNone   Checked = "none"   // nobody decided: unconfirmed or not attempted
)

// FileReport is one file's outcome. It carries identifiers and status codes
// only — never learner text or the request body.
type FileReport struct {
	Index      int     // 1-based position in the processing order
	Path       string  // as given by the caller
	CaptureID  string  // display label read from the file; "" if absent or not printable
	Outcome    Outcome // see Outcome
	Checked    Checked // who decided the outcome
	Status     int     // HTTP status, 0 when no response was received
	EntryID    int64   // created / replayed only
	AnalysisID *int64  // created / replayed only; nil = no analysis
	Detail     string  // short, content-free explanation
	Warning    string  // non-fatal note (e.g. a capture_id repeated in the batch)
}

// BatchReport is the aggregate result.
type BatchReport struct {
	Preview     bool
	Interrupted bool   // the context was cancelled before every file was decided
	StoppedWhy  string // non-empty when the batch stopped early for another reason
	Files       []FileReport
}

// Count returns how many files ended with outcome o.
func (r *BatchReport) Count(o Outcome) int {
	n := 0
	for _, f := range r.Files {
		if f.Outcome == o {
			n++
		}
	}
	return n
}

// ErrBatchRefused marks a batch rejected before any file was read or sent.
var ErrBatchRefused = errors.New("batch refused")

// PlanBatch validates the file list and returns it in processing order: sorted
// by byte-wise comparison of the paths as given, so the same set of files is
// always processed in the same order regardless of argument order or locale.
// It refuses an empty list, more than MaxBatchFiles, and the same file listed
// twice (by path or by identity). Nothing is sent.
func PlanBatch(paths []string) ([]string, error) {
	if len(paths) == 0 {
		return nil, fmt.Errorf("%w: no capture files given", ErrBatchRefused)
	}
	if len(paths) > MaxBatchFiles {
		return nil, fmt.Errorf("%w: %d files given, at most %d per batch", ErrBatchRefused, len(paths), MaxBatchFiles)
	}
	ordered := append([]string(nil), paths...)
	sort.Strings(ordered)
	type statted struct {
		path string
		info os.FileInfo
	}
	var seen []statted
	for i, p := range ordered {
		if p == "" {
			return nil, fmt.Errorf("%w: empty file path", ErrBatchRefused)
		}
		if i > 0 && ordered[i-1] == p {
			return nil, fmt.Errorf("%w: %s is listed more than once", ErrBatchRefused, displayPath(p))
		}
		info, err := os.Stat(p)
		if err != nil {
			continue // reported per file as a local invalid outcome
		}
		for _, other := range seen {
			if os.SameFile(other.info, info) {
				return nil, fmt.Errorf("%w: %s and %s are the same file", ErrBatchRefused, displayPath(other.path), displayPath(p))
			}
		}
		seen = append(seen, statted{p, info})
	}
	return ordered, nil
}

// readLocal applies the local checks and returns the payload. These checks are
// about the file only: it exists, is a regular file, is readable, is at most
// MaxPayloadBytes and is not blank. Whether the content is a valid capture is
// for the server to decide.
func readLocal(path string) ([]byte, error) {
	info, err := os.Stat(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, errors.New("file not found")
		}
		return nil, errors.New("file cannot be read")
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("not a regular file")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, errors.New("file cannot be read")
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, MaxPayloadBytes+1))
	if err != nil {
		return nil, errors.New("file cannot be read")
	}
	if len(b) > MaxPayloadBytes {
		return nil, errors.New("file exceeds the 1 MiB limit")
	}
	if len(bytes.TrimSpace(b)) == 0 {
		return nil, errors.New("file is empty")
	}
	return b, nil
}

// captureLabel extracts capture_id for display only. It is not validation: the
// payload is sent unchanged whatever this returns. The label is shown only when
// it is a short identifier in the portable capture-id character set, so a
// malformed file can never make the report print free text.
func captureLabel(payload []byte) string {
	var probe struct {
		CaptureID json.RawMessage `json:"capture_id"`
	}
	if json.Unmarshal(payload, &probe) != nil || len(probe.CaptureID) == 0 {
		return ""
	}
	var id string
	if json.Unmarshal(probe.CaptureID, &id) != nil {
		return ""
	}
	id = strings.TrimSpace(id)
	if id == "" || len(id) > 200 {
		return ""
	}
	for i := 0; i < len(id); i++ {
		c := id[i]
		ok := (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
			(i > 0 && (c == '.' || c == '_' || c == ':' || c == '-'))
		if !ok {
			return ""
		}
	}
	return id
}

// PreviewBatch runs the local checks over every file and makes no HTTP request.
// Files that pass are "ready"; the server may still report them as created,
// replayed, conflict or invalid.
func PreviewBatch(paths []string) (*BatchReport, error) {
	ordered, err := PlanBatch(paths)
	if err != nil {
		return nil, err
	}
	rep := &BatchReport{Preview: true}
	for i, p := range ordered {
		fr := FileReport{Index: i + 1, Path: p, Checked: CheckedLocal}
		payload, err := readLocal(p)
		if err != nil {
			fr.Outcome, fr.Detail = OutcomeInvalid, err.Error()
		} else {
			fr.Outcome, fr.CaptureID = OutcomeReady, captureLabel(payload)
			fr.Detail = "local checks passed; server checks not run"
		}
		rep.Files = append(rep.Files, fr)
	}
	markRepeatedIDs(rep)
	return rep, nil
}

// RunBatch sends each file in order and records the server's verdict. A file
// that fails the local checks is reported invalid and not sent; the other files
// are still processed. When ctx is cancelled, the request in flight (if any) is
// unconfirmed and every later file is not attempted. After
// maxConsecutiveNoResponse files in a row without a server response
// (unconfirmed, or a connection that could not be opened) the batch stops the
// same way. No request is ever retried.
func (c *Client) RunBatch(ctx context.Context, paths []string) (*BatchReport, error) {
	ordered, err := PlanBatch(paths)
	if err != nil {
		return nil, err
	}
	rep := &BatchReport{}
	streak := 0
	stopped := false
	for i, p := range ordered {
		fr := FileReport{Index: i + 1, Path: p}
		if !stopped && ctx.Err() != nil {
			rep.Interrupted = true
			stopped = true
		}
		if stopped {
			fr.Outcome, fr.Checked = OutcomeNotAttempted, CheckedNone
			if rep.Interrupted {
				fr.Detail = "not sent: the batch was interrupted"
			} else {
				fr.Detail = "not sent: " + rep.StoppedWhy
			}
			if payload, err := readLocal(p); err == nil {
				fr.CaptureID = captureLabel(payload)
			}
			rep.Files = append(rep.Files, fr)
			continue
		}

		payload, err := readLocal(p)
		if err != nil {
			fr.Outcome, fr.Checked, fr.Detail = OutcomeInvalid, CheckedLocal, err.Error()+"; not sent"
			rep.Files = append(rep.Files, fr)
			continue // a local problem says nothing about the server: keep the streak
		}
		fr.CaptureID = captureLabel(payload)

		res, err := c.Import(ctx, payload)
		classify(&fr, res, err, payload)
		rep.Files = append(rep.Files, fr)

		if fr.Outcome == OutcomeUnconfirmed || fr.Outcome == OutcomeNotAttempted {
			streak++
			if ctx.Err() != nil {
				rep.Interrupted = true
				stopped = true
			} else if streak >= maxConsecutiveNoResponse {
				rep.StoppedWhy = fmt.Sprintf("the batch stopped after %d files in a row without a server response", streak)
				stopped = true
			}
		} else {
			streak = 0
		}
	}
	markRepeatedIDs(rep)
	return rep, nil
}

// classify maps one Import result to an outcome.
func classify(fr *FileReport, res *Result, err error, payload []byte) {
	if err == nil {
		fr.Checked, fr.EntryID, fr.AnalysisID = CheckedServer, res.EntryID, res.AnalysisID
		if res.Created {
			fr.Outcome, fr.Status, fr.Detail = OutcomeCreated, http.StatusCreated, "stored as a new capture"
		} else {
			fr.Outcome, fr.Status, fr.Detail = OutcomeReplayed, http.StatusOK, "already stored with identical content; nothing new written"
		}
		return
	}
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		fr.Status = apiErr.StatusCode
		msg := safeServerMessage(apiErr.Message, payload)
		switch apiErr.StatusCode {
		case http.StatusConflict:
			fr.Outcome, fr.Checked = OutcomeConflict, CheckedServer
			fr.Detail = "server holds different content for this capture_id and kept it"
		case http.StatusBadRequest, http.StatusUnprocessableEntity:
			fr.Outcome, fr.Checked = OutcomeInvalid, CheckedServer
			fr.Detail = "rejected by server validation"
			if msg != "" {
				fr.Detail += ": " + msg
			}
		default:
			fr.Outcome, fr.Checked = OutcomeUnconfirmed, CheckedNone
			fr.Detail = fmt.Sprintf("unexpected HTTP %d; whether it was stored is unknown", apiErr.StatusCode)
		}
		return
	}
	fr.Outcome, fr.Checked = OutcomeUnconfirmed, CheckedNone
	var opErr *net.OpError
	switch {
	case errors.As(err, &opErr) && opErr.Op == "dial":
		// The connection was never opened, so the server received nothing.
		fr.Outcome = OutcomeNotAttempted
		fr.Detail = "could not connect to the server (" + bound(transportReason(err)) + "); not sent"
	case errors.Is(err, context.Canceled):
		fr.Detail = "interrupted while waiting for the response; it may have been stored"
	case errors.Is(err, context.DeadlineExceeded) || isTimeout(err):
		fr.Detail = "timed out waiting for the response; it may have been stored"
	case strings.HasPrefix(err.Error(), "decode capture response"):
		fr.Detail = "the success response could not be read; it may have been stored"
	default:
		fr.Detail = "no complete response (" + bound(transportReason(err)) + "); it may have been stored"
	}
}

func isTimeout(err error) bool {
	var t interface{ Timeout() bool }
	return errors.As(err, &t) && t.Timeout()
}

// transportReason keeps the innermost error text, which names the network
// failure (e.g. "connection refused", "EOF") without the request body.
func transportReason(err error) string {
	for {
		next := errors.Unwrap(err)
		if next == nil {
			return err.Error()
		}
		err = next
	}
}

// safeServerMessage bounds the server's public message and withholds it if it
// repeats any part of the request content.
func safeServerMessage(msg string, payload []byte) string {
	msg = bound(msg)
	if msg == "" {
		return ""
	}
	if len(msg) >= 8 && bytes.Contains(payload, []byte(msg)) {
		return "(server message withheld: it repeats request content)"
	}
	return msg
}

// bound makes text single-line, printable and at most maxDetail bytes.
func bound(s string) string {
	s = strings.Map(func(r rune) rune {
		if r < 0x20 || r == 0x7f {
			return ' '
		}
		return r
	}, strings.TrimSpace(s))
	if len(s) > maxDetail {
		cut := maxDetail
		for cut > 0 && (s[cut]&0xC0) == 0x80 {
			cut--
		}
		s = s[:cut] + "…"
	}
	return s
}

// markRepeatedIDs warns when two files in one batch carry the same capture_id:
// the server will answer the later one with replayed (identical content) or
// conflict (different content).
func markRepeatedIDs(rep *BatchReport) {
	first := map[string]int{}
	for i := range rep.Files {
		id := rep.Files[i].CaptureID
		if id == "" {
			continue
		}
		if j, ok := first[id]; ok {
			rep.Files[i].Warning = fmt.Sprintf("same capture_id as file #%d", rep.Files[j].Index)
			continue
		}
		first[id] = i
	}
}

// displayPath quotes a path only when it contains characters that would break
// a one-line report.
func displayPath(p string) string {
	for _, r := range p {
		if r < 0x20 || r == 0x7f || r == '\t' {
			return fmt.Sprintf("%q", p)
		}
	}
	return p
}

// DisplayPath is displayPath for callers that render reports.
func DisplayPath(p string) string { return displayPath(p) }
