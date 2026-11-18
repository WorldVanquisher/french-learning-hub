package http

import (
	"bytes"
	"compress/gzip"
	"errors"
	"fmt"
	"io/fs"
	"mime"
	"net/http"
	"os"
	"path"
	"regexp"
	"strings"
	"sync"
	"time"
)

// WorkbenchAPIPrefix is the path prefix the built workbench uses for every API
// call (see web/src/api/client.ts). In development Vite proxies it; in a release
// the server strips it itself, so the API routes stay exactly as they are.
const WorkbenchAPIPrefix = "/api"

// NewWorkbenchHandler serves the production workbench build from webDir in front
// of the existing API handler, without changing any API route:
//
//   - GET / serves webDir/index.html.
//   - GET /assets/... serves the built files (no directory listings). A file
//     whose name carries Vite's content hash (name-XXXXXXXX.ext) is cacheable
//     for a year and immutable: a rebuild changes the name, and index.html
//     (no-cache) names the new files. Anything else revalidates (no-cache).
//     Hashed text assets (.js, .css, .svg, .json) are sent gzip-compressed to a
//     client that accepts it (compressed once, in memory; the bundle is about a
//     quarter of its size), with Vary: Accept-Encoding.
//   - /api/... strips the prefix and dispatches to api, matching the Vite proxy.
//   - every other request goes to api unchanged, so root API paths (used by the
//     capture CLI and curl) and their 404s behave as before.
//
// The workbench changes no URL path, so there is deliberately no SPA fallback.
// index.html is read once at startup; an unusable webDir is a startup error.
//
// Symlink policy (FLH-075): every read goes through an os.Root opened on
// webDir, which confines each open to that directory tree, including against
// a link swapped in after startup. A symbolic link (file or directory, at any
// depth) is followed only if it is relative and resolves inside webDir; an
// absolute link, or one whose target is outside webDir, is refused as not
// found. webDir itself may be a link: it is resolved once, when the root opens.
func NewWorkbenchHandler(api http.Handler, webDir string) (http.Handler, error) {
	if webDir == "" {
		return nil, errors.New("workbench directory is empty")
	}
	// The root stays open for the handler's lifetime (one descriptor).
	confined, err := os.OpenRoot(webDir)
	if err != nil {
		return nil, fmt.Errorf("workbench directory: %w", err)
	}
	root := confined.FS()
	info, err := fs.Stat(root, "index.html")
	if err != nil {
		return nil, closeRoot(confined, fmt.Errorf("workbench index.html: %w", err))
	}
	if !info.Mode().IsRegular() {
		return nil, closeRoot(confined, errors.New("workbench index.html is not a regular file"))
	}
	index, err := fs.ReadFile(root, "index.html")
	if err != nil {
		return nil, closeRoot(confined, fmt.Errorf("read workbench index.html: %w", err))
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
	mux.Handle("GET /assets/", cachedAssets(root, compressedAssets(root, assets)))
	mux.Handle(WorkbenchAPIPrefix+"/", http.StripPrefix(WorkbenchAPIPrefix, api))
	// Without this exact pattern ServeMux would redirect /api to /api/; keep it
	// an ordinary unknown API path instead.
	mux.Handle(WorkbenchAPIPrefix, api)
	mux.Handle("/", api)
	return mux, nil
}

// hashedAssetName matches the file names Vite gives built assets: a name, a
// dash, eight content-hash characters and an extension.
var hashedAssetName = regexp.MustCompile(`^[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8}\.[a-z0-9]{1,8}$`)

// cachedAssets sets the caching policy before the file server answers. Only
// an existing regular file with a content-hashed name is long-lived; a missing
// one is never marked cacheable (the file server's error drops the header).
func cachedAssets(root fs.FS, files http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		name := strings.TrimPrefix(r.URL.Path, "/")
		policy := "no-cache"
		if hashedAssetName.MatchString(path.Base(name)) && fs.ValidPath(name) {
			if info, err := fs.Stat(root, name); err == nil && info.Mode().IsRegular() {
				policy = "public, max-age=31536000, immutable"
			}
		}
		w.Header().Set("Cache-Control", policy)
		files.ServeHTTP(w, r)
	})
}

// compressible lists the hashed asset types worth compressing; images and fonts
// are already compressed.
var compressible = map[string]bool{".js": true, ".css": true, ".svg": true, ".json": true}

// gzAsset is one compressed asset, keyed by its name, size and modification
// time, so a file replaced under the same name is compressed again.
type gzAsset struct {
	size    int64
	modTime time.Time
	data    []byte
}

// compressedAssets serves a content-hashed text asset gzip-compressed when the
// request accepts gzip. Everything else (other files, no gzip, a missing file,
// a read error) goes to files unchanged, so confinement, 404s and listings
// stay the file server's.
func compressedAssets(root fs.FS, files http.Handler) http.Handler {
	var cache sync.Map // name -> *gzAsset
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		name := strings.TrimPrefix(r.URL.Path, "/")
		base := path.Base(name)
		ext := path.Ext(base)
		if !compressible[ext] || !hashedAssetName.MatchString(base) || !fs.ValidPath(name) {
			files.ServeHTTP(w, r)
			return
		}
		w.Header().Add("Vary", "Accept-Encoding")
		if !acceptsGzip(r.Header.Get("Accept-Encoding")) {
			files.ServeHTTP(w, r)
			return
		}
		info, err := fs.Stat(root, name)
		if err != nil || !info.Mode().IsRegular() {
			files.ServeHTTP(w, r)
			return
		}
		var asset *gzAsset
		if v, ok := cache.Load(name); ok {
			if a := v.(*gzAsset); a.size == info.Size() && a.modTime.Equal(info.ModTime()) {
				asset = a
			}
		}
		if asset == nil {
			raw, err := fs.ReadFile(root, name)
			if err != nil {
				files.ServeHTTP(w, r)
				return
			}
			var buf bytes.Buffer
			zw, _ := gzip.NewWriterLevel(&buf, gzip.BestCompression)
			if _, err := zw.Write(raw); err != nil || zw.Close() != nil {
				files.ServeHTTP(w, r)
				return
			}
			asset = &gzAsset{size: info.Size(), modTime: info.ModTime(), data: buf.Bytes()}
			cache.Store(name, asset)
		}
		if ct := mime.TypeByExtension(ext); ct != "" {
			w.Header().Set("Content-Type", ct)
		}
		w.Header().Set("Content-Encoding", "gzip")
		http.ServeContent(w, r, base, asset.modTime, bytes.NewReader(asset.data))
	})
}

// acceptsGzip reports whether an Accept-Encoding header allows gzip (a
// "gzip" or "*" coding whose q value is not 0).
func acceptsGzip(header string) bool {
	for _, part := range strings.Split(header, ",") {
		coding, params, _ := strings.Cut(strings.TrimSpace(part), ";")
		coding = strings.ToLower(strings.TrimSpace(coding))
		if coding != "gzip" && coding != "*" {
			continue
		}
		q := strings.ReplaceAll(strings.ToLower(params), " ", "")
		if q == "q=0" || q == "q=0.0" || q == "q=0.00" || q == "q=0.000" {
			return false
		}
		return true
	}
	return false
}

// closeRoot releases the root after a startup failure and returns err.
func closeRoot(root *os.Root, err error) error {
	root.Close()
	return err
}

// fileOnlyFS hides directories so the file server never renders a listing,
// and reports every open failure as not found.
type fileOnlyFS struct{ fsys fs.FS }

func (f fileOnlyFS) Open(name string) (fs.File, error) {
	file, err := f.fsys.Open(name)
	if err != nil {
		// A confinement refusal (a link escaping the root), a missing file and
		// an unreadable one all answer 404, without saying which.
		return nil, &fs.PathError{Op: "open", Path: name, Err: fs.ErrNotExist}
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
