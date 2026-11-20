// Package historyexport writes a learning history export into a directory the
// learner selected, and never anywhere else: a file name is a single plain
// name (no separator, no "..", no leading dot), the file must not exist yet
// (no overwrite, no following a planted link), and the resolved path must sit
// directly in the selected directory.
package historyexport

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var plainName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`)

// ErrUnsafePath is returned for any directory or name that could write
// outside the selected directory.
var ErrUnsafePath = errors.New("unsafe export path")

// SafeFile returns dir/name+ext after checking that it cannot escape dir.
func SafeFile(dir, name, ext string) (string, error) {
	if dir == "" {
		return "", fmt.Errorf("%w: choose an export directory", ErrUnsafePath)
	}
	if !plainName.MatchString(name) || strings.Contains(name, "..") || strings.HasSuffix(name, ".") {
		return "", fmt.Errorf("%w: %q is not a plain file name (letters, digits, '.', '_' and '-'; no path, no '..')", ErrUnsafePath, name)
	}
	info, err := os.Stat(dir)
	if err != nil || !info.IsDir() {
		return "", fmt.Errorf("%w: %q is not an existing directory", ErrUnsafePath, dir)
	}
	clean := filepath.Clean(dir)
	full := filepath.Join(clean, name+ext)
	if filepath.Dir(full) != clean || filepath.Base(full) != name+ext {
		return "", fmt.Errorf("%w: %q would leave %q", ErrUnsafePath, name+ext, dir)
	}
	return full, nil
}

// WriteNew writes data to path, refusing an existing file or link.
func WriteNew(path string, data []byte) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		if errors.Is(err, os.ErrExist) {
			return fmt.Errorf("%s already exists; nothing was overwritten", filepath.Base(path))
		}
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

// File is one written export file and how it opens.
type File struct {
	Path      string
	OpensText bool
	AppImport string // "preview only" or "none"
}

// Options are the export's optional texts.
type Options struct{ Transcripts, Notes bool }

func query(opts Options, format string) string {
	q := url.Values{}
	if opts.Transcripts {
		q.Set("transcripts", "true")
	}
	if opts.Notes {
		q.Set("notes", "true")
	}
	if format != "" {
		q.Set("format", format)
	}
	return q.Encode()
}

// Run fetches the export (NDJSON and its readable text copy) from base and
// writes both into dir under name. Paths are checked before any request.
func Run(client *http.Client, base, dir, name string, opts Options) ([]File, error) {
	nd, err := SafeFile(dir, name, ".ndjson")
	if err != nil {
		return nil, err
	}
	txt, err := SafeFile(dir, name, ".txt")
	if err != nil {
		return nil, err
	}
	for _, p := range []string{nd, txt} {
		if _, err := os.Lstat(p); err == nil {
			return nil, fmt.Errorf("%s already exists; nothing was written", filepath.Base(p))
		}
	}
	get := func(format string) ([]byte, error) {
		resp, err := client.Get(strings.TrimRight(base, "/") + "/learning-history/export?" + query(opts, format))
		if err != nil {
			return nil, fmt.Errorf("the server did not answer: %w", err)
		}
		defer resp.Body.Close()
		body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
		if err != nil {
			return nil, err
		}
		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("the server answered %d", resp.StatusCode)
		}
		return body, nil
	}
	ndjson, err := get("")
	if err != nil {
		return nil, err
	}
	text, err := get("text")
	if err != nil {
		return nil, err
	}
	if err := WriteNew(nd, ndjson); err != nil {
		return nil, err
	}
	if err := WriteNew(txt, text); err != nil {
		return nil, err
	}
	return []File{{Path: nd, OpensText: true, AppImport: "preview only"}, {Path: txt, OpensText: true, AppImport: "none"}}, nil
}
