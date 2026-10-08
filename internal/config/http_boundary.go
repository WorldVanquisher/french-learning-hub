package config

import (
	"errors"
	"net"
	"net/netip"
	"net/url"
	"strconv"
	"strings"
)

// HTTPBoundaryConfig permits exact destination hosts and trusted browser origins.
// Hosts are independent of ports; trusted origins include scheme and port.
type HTTPBoundaryConfig struct {
	AllowedHosts   []string
	TrustedOrigins []string
}

func loadHTTPBoundary(src source) (HTTPBoundaryConfig, error) {
	cfg := HTTPBoundaryConfig{AllowedHosts: []string{"localhost", "127.0.0.1", "::1"}}
	// Vite rewrites Host but retains Origin. These are explicit development
	// exceptions, not CORS permissions; no response access headers are added.
	origins := src.get("HTTP_TRUSTED_ORIGINS")
	if origins == "" {
		origins = "http://localhost:5173,http://127.0.0.1:5173,http://[::1]:5173"
	}
	if hosts := src.get("HTTP_ALLOWED_HOSTS"); hosts != "" {
		for _, value := range strings.Split(hosts, ",") {
			host, err := NormalizeHTTPHostname(strings.TrimSpace(value))
			if err != nil {
				return HTTPBoundaryConfig{}, errors.New("HTTP_ALLOWED_HOSTS must contain comma-separated exact DNS names or IP addresses, without ports or wildcards")
			}
			cfg.AllowedHosts = append(cfg.AllowedHosts, host)
		}
	}
	for _, value := range strings.Split(origins, ",") {
		origin, err := NormalizeHTTPOrigin(strings.TrimSpace(value))
		if err != nil {
			return HTTPBoundaryConfig{}, errors.New("HTTP_TRUSTED_ORIGINS must contain comma-separated HTTP(S) origins without credentials, paths, queries, fragments or wildcards")
		}
		cfg.TrustedOrigins = append(cfg.TrustedOrigins, origin)
	}
	return cfg, nil
}

// NormalizeHTTPHostname accepts ASCII DNS names or unbracketed IP literals.
// It performs no DNS lookup and accepts no patterns, ports or IPv6 zones.
func NormalizeHTTPHostname(value string) (string, error) {
	if ip, err := netip.ParseAddr(value); err == nil && ip.Zone() == "" {
		return ip.String(), nil
	}
	if value == "" || len(value) > 253 {
		return "", errors.New("invalid hostname")
	}
	for _, label := range strings.Split(value, ".") {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return "", errors.New("invalid hostname")
		}
		for _, c := range label {
			if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-') {
				return "", errors.New("invalid hostname")
			}
		}
	}
	return strings.ToLower(value), nil
}

// NormalizeHTTPAuthority validates a request Host and returns its hostname and
// canonical authority. IPv6 authorities require brackets; ports are 1..65535.
func NormalizeHTTPAuthority(value string) (string, string, error) {
	u, err := url.Parse("//" + value)
	if err != nil || u.Host == "" || u.User != nil || u.Path != "" || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || strings.ContainsAny(value, "?#") {
		return "", "", errors.New("invalid authority")
	}
	host, err := NormalizeHTTPHostname(u.Hostname())
	if err != nil {
		return "", "", err
	}
	if strings.HasPrefix(value, "[") && !strings.Contains(host, ":") {
		return "", "", errors.New("brackets require IPv6")
	}
	port := u.Port()
	authority := host
	if strings.Contains(host, ":") {
		if !strings.HasPrefix(value, "[") {
			return "", "", errors.New("IPv6 authority needs brackets")
		}
		authority = "[" + host + "]"
	}
	if port != "" {
		n, err := strconv.Atoi(port)
		if err != nil || n < 1 || n > 65535 {
			return "", "", errors.New("invalid port")
		}
		authority = net.JoinHostPort(host, strconv.Itoa(n))
	} else if strings.HasSuffix(value, ":") {
		return "", "", errors.New("empty port")
	}
	return host, authority, nil
}

// NormalizeHTTPOrigin requires a serialized HTTP(S) origin, never a URL with
// userinfo or a path. Default ports are omitted for same-origin comparison.
func NormalizeHTTPOrigin(value string) (string, error) {
	u, err := url.Parse(value)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Opaque != "" || u.User != nil || u.Path != "" || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || strings.ContainsAny(value, "?#") {
		return "", errors.New("invalid origin")
	}
	host, authority, err := NormalizeHTTPAuthority(u.Host)
	if err != nil {
		return "", err
	}
	if (u.Scheme == "http" && strings.HasSuffix(authority, ":80")) || (u.Scheme == "https" && strings.HasSuffix(authority, ":443")) {
		authority = host
		if strings.Contains(host, ":") {
			authority = "[" + host + "]"
		}
	}
	return u.Scheme + "://" + authority, nil
}
