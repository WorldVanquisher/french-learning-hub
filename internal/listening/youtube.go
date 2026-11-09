package listening

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"french-learning-app/internal/domain"
)

// maxPlaylistPageBytes bounds one playlistItems response. A larger response is
// invalid, never truncated and parsed.
const maxPlaylistPageBytes = 1 << 20

// pageToken bounds a continuation token before it is sent back.
var pageToken = regexp.MustCompile(`^[A-Za-z0-9_-]{1,256}$`)

// YouTubePlaylist reads one playlist's official metadata with the YouTube Data
// API v3 playlistItems.list: video ID, title, publication time and privacy
// status only. It never requests media, captions or web pages. Requests are
// bounded: at most ceil(maxItems/50) pages, one timeout per request, 1 MiB per
// response, no redirects. The API key travels in a header, never in the URL.
type YouTubePlaylist struct {
	apiKey     string
	playlistID string
	baseURL    string
	maxItems   int
	client     *http.Client
}

var _ domain.ListeningPlaylistSource = (*YouTubePlaylist)(nil)

// NewYouTubePlaylist builds the source. maxItems is clamped to 1..200.
func NewYouTubePlaylist(apiKey, playlistID, baseURL string, maxItems int, timeout time.Duration) *YouTubePlaylist {
	if maxItems < 1 {
		maxItems = domain.DefaultPlaylistItems
	}
	if maxItems > domain.MaxPlaylistItems {
		maxItems = domain.MaxPlaylistItems
	}
	return &YouTubePlaylist{
		apiKey: apiKey, playlistID: playlistID, baseURL: strings.TrimRight(baseURL, "/"), maxItems: maxItems,
		client: &http.Client{
			Timeout:       timeout,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
	}
}

// Name is the source provenance shown in status.
func (y *YouTubePlaylist) Name() string { return "youtube-data-api-v3:playlistItems" }

type playlistPage struct {
	NextPageToken string `json:"nextPageToken"`
	Items         []struct {
		Snippet struct {
			Title    string `json:"title"`
			Position *int   `json:"position"`
		} `json:"snippet"`
		ContentDetails struct {
			VideoID          string `json:"videoId"`
			VideoPublishedAt string `json:"videoPublishedAt"`
		} `json:"contentDetails"`
		Status struct {
			PrivacyStatus string `json:"privacyStatus"`
		} `json:"status"`
	} `json:"items"`
}

// List reads up to maxItems playlist entries in playlist order. Private,
// deleted and malformed entries are counted as skipped, never stored. Errors
// wrap domain.ErrPlaylist* and never carry the key, the URL or a body.
func (y *YouTubePlaylist) List(ctx context.Context) (domain.PlaylistListing, error) {
	out := domain.PlaylistListing{PlaylistID: y.playlistID}
	token := ""
	pages := (y.maxItems + domain.PlaylistPageSize - 1) / domain.PlaylistPageSize
	for page := 0; page < pages; page++ {
		p, err := y.page(ctx, token, min(domain.PlaylistPageSize, y.maxItems-page*domain.PlaylistPageSize))
		if err != nil {
			return domain.PlaylistListing{}, err
		}
		for _, it := range p.Items {
			if len(out.Items)+out.Skipped >= y.maxItems {
				break
			}
			id := it.ContentDetails.VideoID
			title := domain.NormalizePlaylistTitle(it.Snippet.Title)
			privacy := it.Status.PrivacyStatus
			if !domain.ValidYouTubeVideoID(id) || title == "" || (privacy != "public" && privacy != "unlisted") {
				out.Skipped++
				continue
			}
			item := domain.PlaylistItem{VideoID: id, Title: title, Position: len(out.Items) + out.Skipped}
			if it.Snippet.Position != nil {
				item.Position = *it.Snippet.Position
			}
			if at, err := time.Parse(time.RFC3339, it.ContentDetails.VideoPublishedAt); err == nil {
				at = at.UTC()
				item.PublishedAt = &at
			}
			out.Items = append(out.Items, item)
		}
		if p.NextPageToken == "" || len(out.Items)+out.Skipped >= y.maxItems {
			break
		}
		if !pageToken.MatchString(p.NextPageToken) {
			return domain.PlaylistListing{}, fmt.Errorf("%w: malformed page token", domain.ErrPlaylistInvalid)
		}
		token = p.NextPageToken
	}
	return out, nil
}

func (y *YouTubePlaylist) page(ctx context.Context, token string, size int) (playlistPage, error) {
	var none playlistPage
	q := url.Values{}
	q.Set("part", "snippet,contentDetails,status")
	q.Set("playlistId", y.playlistID)
	q.Set("maxResults", strconv.Itoa(size))
	q.Set("fields", "nextPageToken,items(snippet(title,position),contentDetails(videoId,videoPublishedAt),status(privacyStatus))")
	if token != "" {
		q.Set("pageToken", token)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, y.baseURL+"/playlistItems?"+q.Encode(), nil)
	if err != nil {
		return none, fmt.Errorf("%w: build request", domain.ErrPlaylistUnavailable)
	}
	req.Header.Set("X-Goog-Api-Key", y.apiKey)
	req.Header.Set("Accept", "application/json")
	resp, err := y.client.Do(req)
	if err != nil {
		if isTimeout(ctx, err) {
			return none, fmt.Errorf("%w: request timed out", domain.ErrPlaylistTimeout)
		}
		return none, fmt.Errorf("%w: request failed", domain.ErrPlaylistUnavailable)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxPlaylistPageBytes+1))
	if err != nil {
		if isTimeout(ctx, err) {
			return none, fmt.Errorf("%w: reading the response timed out", domain.ErrPlaylistTimeout)
		}
		return none, fmt.Errorf("%w: reading the response failed", domain.ErrPlaylistUnavailable)
	}
	switch {
	case resp.StatusCode == http.StatusOK:
	case resp.StatusCode == http.StatusBadRequest, resp.StatusCode == http.StatusUnauthorized,
		resp.StatusCode == http.StatusForbidden, resp.StatusCode == http.StatusNotFound:
		// A bad or restricted key, an exhausted quota, or an unknown/private playlist.
		return none, fmt.Errorf("%w: HTTP %d", domain.ErrPlaylistRefused, resp.StatusCode)
	default:
		return none, fmt.Errorf("%w: HTTP %d", domain.ErrPlaylistUnavailable, resp.StatusCode)
	}
	if len(body) > maxPlaylistPageBytes {
		return none, fmt.Errorf("%w: response exceeds %d bytes", domain.ErrPlaylistInvalid, maxPlaylistPageBytes)
	}
	var p playlistPage
	if err := json.Unmarshal(body, &p); err != nil {
		return none, fmt.Errorf("%w: malformed JSON", domain.ErrPlaylistInvalid)
	}
	if len(p.Items) > size {
		return none, fmt.Errorf("%w: more items than requested", domain.ErrPlaylistInvalid)
	}
	return p, nil
}

// isTimeout reports a client or context deadline.
func isTimeout(ctx context.Context, err error) bool {
	if errors.Is(ctx.Err(), context.DeadlineExceeded) || errors.Is(err, context.DeadlineExceeded) {
		return true
	}
	var ne interface{ Timeout() bool }
	return errors.As(err, &ne) && ne.Timeout()
}
