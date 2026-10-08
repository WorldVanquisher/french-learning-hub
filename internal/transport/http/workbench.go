package http

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"net/http"
	"os"
)

// WorkbenchAPIPrefix is the path prefix the built workbench uses for every API
// call (see web/src/api/client.ts). In development Vite proxies it; in a release
// the server strips it itself, so the API routes stay exactly as they are.
const WorkbenchAPIPrefix = "/api"

// NewWorkbenchHandler serves the production workbench build from webDir in front
// of the existing API handler, without changing any API route:
//
//   - GET / serves webDir/index.html.
//   - GET /assets/... serves the built files (no directory listings).
//   - /api/... strips the prefix and dispatches to api, matching the Vite proxy.
//   - every other request goes to api unchanged, so root API paths (used by the
//     capture CLI and curl) and their 404s behave as before.
//
// The workbench changes no URL path, so there is deliberately no SPA fallback.
// index.html is read once at startup; an unusable webDir is a startup error.
func NewWorkbenchHandler(api http.Handler, webDir string) (http.Handler, error) {
	if webDir == "" {
		return nil, errors.New("workbench directory is empty")
	}
	root := os.DirFS(webDir)
	info, err := fs.Stat(root, "index.html")
	if err != nil {
		return nil, fmt.Errorf("workbench index.html: %w", err)
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("workbench index.html is not a regular file")
	}
	index, err := fs.ReadFile(root, "index.html")
	if err != nil {
		return nil, fmt.Errorf("read workbench index.html: %w", err)
	}
	modTime := info.ModTime()

	assets := http.FileServerFS(fileOnlyFS{root})

	mux := http.NewServeMux()
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		// Revalidate the entry document so a rebuilt image's new asset names load.
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		http.ServeContent(w, r, "index.html", modTime, bytes.NewReader(index))
	})
	mux.Handle("GET /assets/", assets)
	mux.Handle(WorkbenchAPIPrefix+"/", http.StripPrefix(WorkbenchAPIPrefix, api))
	// Without this exact pattern ServeMux would redirect /api to /api/; keep it
	// an ordinary unknown API path instead.
	mux.Handle(WorkbenchAPIPrefix, api)
	mux.Handle("/", api)
	return mux, nil
}

// fileOnlyFS hides directories so the file server never renders a listing.
type fileOnlyFS struct{ fsys fs.FS }

func (f fileOnlyFS) Open(name string) (fs.File, error) {
	file, err := f.fsys.Open(name)
	if err != nil {
		return nil, err
	}
	info, err := file.Stat()
	if err != nil {
		file.Close()
		return nil, err
	}
	if info.IsDir() {
		file.Close()
		return nil, fs.ErrNotExist
	}
	return file, nil
}
