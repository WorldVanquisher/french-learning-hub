package http

import (
	"errors"
	"mime"
	"net/http"
	"strings"

	"french-learning-app/internal/config"
)

// NewBrowserBoundary wraps the complete server handler before routing/static
// serving. Host checks protect reads as well as writes from unapproved DNS names.
// This is browser-request protection, not authentication: non-browser clients
// can supply headers themselves. Forwarded headers never grant trust.
func NewBrowserBoundary(next http.Handler, policy config.HTTPBoundaryConfig) (http.Handler, error) {
	hosts := make(map[string]bool)
	for _, value := range policy.AllowedHosts {
		host, err := config.NormalizeHTTPHostname(value)
		if err != nil {
			return nil, errors.New("invalid HTTP boundary host configuration")
		}
		hosts[host] = true
	}
	if len(hosts) == 0 {
		return nil, errors.New("HTTP boundary requires allowed hosts")
	}
	trusted := make(map[string]bool)
	protection := http.NewCrossOriginProtection()
	for _, value := range policy.TrustedOrigins {
		origin, err := config.NormalizeHTTPOrigin(value)
		if err != nil {
			return nil, errors.New("invalid HTTP boundary origin configuration")
		}
		if err := protection.AddTrustedOrigin(origin); err != nil {
			return nil, errors.New("invalid HTTP boundary origin configuration")
		}
		trusted[origin] = true
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, err := config.NormalizeHTTPAuthority(r.Host)
		if err != nil || !hosts[host] {
			writeError(w, http.StatusForbidden, "request host is not allowed")
			return
		}
		switch r.Method {
		case http.MethodGet, http.MethodHead, http.MethodOptions:
			next.ServeHTTP(w, r)
			return
		}

		// Reject malformed/multiple origins even if Fetch Metadata says same-origin.
		checked := *r
		checked.Header = r.Header.Clone()
		origins := r.Header.Values("Origin")
		if len(origins) > 0 {
			origin, err := config.NormalizeHTTPOrigin(origins[0])
			scheme := "http"
			if r.TLS != nil {
				scheme = "https"
			}
			sameOrigin, _ := config.NormalizeHTTPOrigin(scheme + "://" + r.Host)
			if len(origins) != 1 || err != nil || (origin != sameOrigin && !trusted[origin]) {
				writeError(w, http.StatusForbidden, "cross-origin browser request is not allowed")
				return
			}
			checked.Header.Set("Origin", origin)
			checked.Host = strings.TrimPrefix(sameOrigin, scheme+"://")
		}
		if len(r.Header.Values("Sec-Fetch-Site")) > 1 || protection.Check(&checked) != nil {
			writeError(w, http.StatusForbidden, "cross-origin browser request is not allowed")
			return
		}

		// Preserve bodyless workbench POSTs and existing no-Origin CLI clients.
		// A browser mutation with a body must use JSON, never form/simple types.
		if len(origins) > 0 || len(r.Header.Values("Sec-Fetch-Site")) > 0 {
			contentTypes := r.Header.Values("Content-Type")
			bodyPresent := r.Body != nil && r.Body != http.NoBody && r.ContentLength != 0
			if bodyPresent || len(contentTypes) > 0 {
				mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
				if len(contentTypes) != 1 || err != nil || mediaType != "application/json" {
					writeError(w, http.StatusUnsupportedMediaType, "browser request body must use application/json")
					return
				}
			}
		}
		next.ServeHTTP(w, r)
	}), nil
}
