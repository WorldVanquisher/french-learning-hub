package listening

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
)

// The embedded pack is what the private workbench imports. It must pass the
// server's own validation and carry the canonical workbook's 12 listening
// scripts and all 120 questions unchanged: same lines and speakers, same
// options in the same order, same key, same evidence. Nothing may look like a
// link, a video or a timestamp.
func TestEmbeddedScriptPackMatchesTheWorkbook(t *testing.T) {
	pack, err := domain.ParseListeningScriptPack(ScriptPack())
	if err != nil {
		t.Fatalf("ParseListeningScriptPack: %v", err)
	}
	var wb struct {
		SchemaVersion string `json:"schema_version"`
		Units         []struct {
			ID        string `json:"id"`
			Band      string `json:"band"`
			Listening struct {
				Title    string `json:"title"`
				Audio    any    `json:"audio"`
				Speakers []struct {
					ID    string `json:"id"`
					Label string `json:"label"`
				} `json:"speakers"`
				Turns []struct {
					ID      string `json:"id"`
					Speaker string `json:"speaker"`
					Text    string `json:"text"`
				} `json:"turns"`
				Questions []struct {
					ID      string `json:"id"`
					Type    string `json:"type"`
					Kind    string `json:"kind"`
					Stem    string `json:"stem"`
					Options []struct {
						Text    string `json:"text"`
						Correct bool   `json:"correct"`
					} `json:"options"`
					ReferenceAnswer string   `json:"reference_answer"`
					Alternatives    []string `json:"accepted_alternatives"`
					Evidence        []struct {
						Ref     string `json:"ref"`
						Excerpt string `json:"excerpt"`
					} `json:"evidence"`
				} `json:"questions"`
			} `json:"listening"`
		} `json:"units"`
	}
	raw, err := os.ReadFile(filepath.Join("..", "..", "content", "workbooks", "reading_listening_v1.json"))
	if err != nil {
		t.Fatalf("read workbook: %v", err)
	}
	if err := json.Unmarshal(raw, &wb); err != nil {
		t.Fatalf("decode workbook: %v", err)
	}
	if len(pack.Scripts) != 12 || len(wb.Units) != 12 {
		t.Fatalf("scripts = %d, units = %d, want 12 each", len(pack.Scripts), len(wb.Units))
	}
	questions := 0
	for i, u := range wb.Units {
		s := pack.Scripts[i]
		L := u.Listening
		if s.ID != "ls-wb1-"+u.ID || s.Title != L.Title || s.StyleLevel != u.Band || s.Source.Pack != wb.SchemaVersion {
			t.Fatalf("%s: script header %+v does not match the workbook", u.ID, s)
		}
		if L.Audio != nil {
			t.Fatalf("%s: the workbook now has audio; the pack format has none", u.ID)
		}
		labels := map[string]string{}
		for _, sp := range L.Speakers {
			labels[sp.ID] = sp.Label
		}
		if len(s.Lines) != len(L.Turns) {
			t.Fatalf("%s: %d lines, workbook has %d", u.ID, len(s.Lines), len(L.Turns))
		}
		for k, turn := range L.Turns {
			if l := s.Lines[k]; l.ID != turn.ID || l.Text != turn.Text || l.Speaker != labels[turn.Speaker] {
				t.Errorf("%s line %s differs from the workbook", u.ID, turn.ID)
			}
		}
		for k, seg := range s.Segments() {
			if seg.Index != k+1 || seg.StartSeconds != nil {
				t.Errorf("%s segment %d: index %d, start %v", u.ID, k+1, seg.Index, seg.StartSeconds)
			}
		}
		if len(s.Questions) != len(L.Questions) {
			t.Fatalf("%s: %d questions, workbook has %d", u.ID, len(s.Questions), len(L.Questions))
		}
		for k, q := range L.Questions {
			it := s.Questions[k]
			questions++
			if it.ID != q.ID || it.Kind != q.Kind || it.Question != q.Stem {
				t.Errorf("%s: question %s header differs", u.ID, q.ID)
			}
			if q.Type == "single_choice" {
				if len(it.Choices) != len(q.Options) {
					t.Errorf("%s: %d choices, workbook has %d", q.ID, len(it.Choices), len(q.Options))
					continue
				}
				for c, o := range q.Options {
					if it.Choices[c] != o.Text || (o.Correct != (it.ExpectedAnswer == o.Text)) {
						t.Errorf("%s: choice %d or its key differs", q.ID, c+1)
					}
				}
			} else if it.ExpectedAnswer != q.ReferenceAnswer || len(it.Choices) != 0 || strings.Join(it.AcceptedAlternatives, "|") != strings.Join(q.Alternatives, "|") {
				t.Errorf("%s: short answer differs", q.ID)
			}
			if len(it.Evidence) != len(q.Evidence) {
				t.Errorf("%s: evidence count differs", q.ID)
				continue
			}
			for e, ev := range q.Evidence {
				if "s"+itoa(it.Evidence[e].Segment) != ev.Ref || it.Evidence[e].Excerpt != ev.Excerpt {
					t.Errorf("%s: evidence %d differs", q.ID, e+1)
				}
			}
		}
	}
	if questions != 120 {
		t.Fatalf("questions = %d, want 120", questions)
	}
	// Nothing fabricated: no link, no video ID or timestamp field anywhere, and
	// no clock time in a script line (where it would read as a timestamp).
	// Explanations may give a time of day the script says in words.
	for _, banned := range []*regexp.Regexp{regexp.MustCompile(`https?://`), regexp.MustCompile(`youtu`),
		regexp.MustCompile(`"(video_id|source_url|start_seconds|audio)"`)} {
		if loc := banned.FindIndex(ScriptPack()); loc != nil {
			t.Errorf("the pack contains %q", ScriptPack()[loc[0]:loc[1]])
		}
	}
	clock := regexp.MustCompile(`\b\d{1,2}:\d{2}\b`)
	for _, s := range pack.Scripts {
		for _, l := range s.Lines {
			if clock.MatchString(l.Text) {
				t.Errorf("%s %s: a script line contains a clock time", s.ID, l.ID)
			}
		}
	}
}

func itoa(n int) string { b, _ := json.Marshal(n); return string(b) }
