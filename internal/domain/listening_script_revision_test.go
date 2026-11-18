package domain

import (
	"encoding/json"
	"slices"
	"strings"
	"testing"
)

func validFixture(t *testing.T) ListeningScript {
	t.Helper()
	s := scriptFixture()
	if err := ValidateListeningScript(&s); err != nil {
		t.Fatal(err)
	}
	return s
}

// The fingerprint of a script equals the fingerprint of its stored JSON read
// back (object key order and a JSON round trip do not matter), and any change
// to a line or a question changes it.
func TestListeningScriptFingerprint_StoredRoundTripAndChanges(t *testing.T) {
	s := validFixture(t)
	fp, err := s.Fingerprint()
	if err != nil || !ValidListeningScriptFingerprint(fp) {
		t.Fatalf("fingerprint %q %v", fp, err)
	}
	segments, _ := json.Marshal(s.Segments())
	content, _ := json.Marshal(s.Content())
	var decoded ListeningExerciseContent
	if err := json.Unmarshal(content, &decoded); err != nil {
		t.Fatal(err)
	}
	reencoded, _ := json.Marshal(decoded)
	var generic any
	_ = json.Unmarshal(reencoded, &generic)
	shuffled, _ := json.MarshalIndent(generic, "", "  ")
	if got, _ := ListeningScriptFingerprint(segments, shuffled); got != fp {
		t.Fatalf("round trip changed the fingerprint: %s != %s", got, fp)
	}
	line := validFixture(t)
	line.Lines[2].Text += " Merci."
	question := validFixture(t)
	question.Questions[0].RationaleZH += "。"
	for name, other := range map[string]ListeningScript{"line": line, "question": question} {
		if got, _ := other.Fingerprint(); got == fp {
			t.Fatalf("a changed %s kept the fingerprint", name)
		}
	}
	if _, err := ListeningScriptFingerprint([]byte("{"), content); err == nil {
		t.Fatal("invalid JSON was fingerprinted")
	}
	for _, bad := range []string{"", "sha256:", "sha256:ABC", "md5:" + fp[7:], fp + "0"} {
		if ValidListeningScriptFingerprint(bad) {
			t.Fatalf("%q accepted as a fingerprint", bad)
		}
	}
}

// The diff lists only what differs: lines by position, questions by item ID
// with the fields that changed, a move as "position", additions and removals.
func TestDiffListeningScript_ListsOnlyWhatDiffers(t *testing.T) {
	a := validFixture(t)
	if c := DiffListeningScript(a.Segments(), a.Content(), a.Segments(), a.Content()); !c.Empty() || c.Lines == nil || c.Questions == nil {
		t.Fatalf("identical content: %+v", c)
	}
	b := validFixture(t)
	b.Lines[1].Speaker = "Mei Lin"
	b.Lines = append(b.Lines, ListeningScriptLine{ID: "s4", Speaker: "Mei", Text: "Merci beaucoup."})
	b.Questions[0].Question = "Où se trouve Mei ?"
	b.Questions[1].AcceptedAlternatives = append(b.Questions[1].AcceptedAlternatives, "11:30")
	b.Questions[2], b.Questions[3] = b.Questions[3], b.Questions[2] // a move
	removed := b.Questions[3]
	b.Questions = b.Questions[:3]
	b.Questions = append(b.Questions, ListeningItem{ID: "u01-l05", Kind: ListeningDetail, Question: "Quel étage ?", ExpectedAnswer: "Le premier.",
		RationaleEN: "s3.", RationaleZH: "s3。", Segments: []int{3}, Evidence: []ListeningEvidence{{Segment: 3, Excerpt: "premier étage"}}})
	b.Annotations = []ListeningAnnotation{{Kind: "vocabulary", Segment: 3, Excerpt: "salle d'attente", NoteEN: "waiting room", NoteZH: "候诊室"}}
	if err := ValidateListeningScript(&b); err != nil {
		t.Fatal(err)
	}
	c := DiffListeningScript(a.Segments(), a.Content(), b.Segments(), b.Content())
	if len(c.Lines) != 2 || c.Lines[0].Line != "s2" || c.Lines[0].Change != "changed" || c.Lines[0].Before.Speaker != "Mei" ||
		c.Lines[1].Line != "s4" || c.Lines[1].Change != "added" || c.Lines[1].Before != nil || c.Lines[1].After.Text != "Merci beaucoup." {
		t.Fatalf("lines: %+v", c.Lines)
	}
	got := map[string][]string{}
	changes := map[string]string{}
	for _, q := range c.Questions {
		got[q.ItemID], changes[q.ItemID] = q.Fields, q.Change
	}
	want := map[string][]string{"u01-l01": {"question"}, "u01-l02": {"accepted_alternatives"}, "u01-l04": {"position"}, "u01-l05": {}, removed.ID: {}}
	if len(got) != len(want) || changes["u01-l05"] != "added" || changes[removed.ID] != "removed" {
		t.Fatalf("questions: %v %v", got, changes)
	}
	for id, fields := range want {
		if !slices.Equal(got[id], fields) {
			t.Fatalf("%s fields %v, want %v", id, got[id], fields)
		}
	}
	if !c.AnnotationsChanged {
		t.Fatal("annotations change not reported")
	}
	// The reverse removes the added line.
	if r := DiffListeningScript(b.Segments(), b.Content(), a.Segments(), a.Content()); r.Lines[1].Change != "removed" || r.Lines[1].After != nil {
		t.Fatalf("reverse lines: %+v", r.Lines)
	}
}

// Lines are aligned by content: a removed or added line is reported once, the
// unchanged lines after it only get new numbers (lines_renumbered), and a line
// that changed and moved names both numbers. Reordered lines stay visible.
func TestDiffListeningScript_AlignsLinesByContent(t *testing.T) {
	seg := func(texts ...string) []TranscriptSegment {
		out := make([]TranscriptSegment, len(texts))
		for i, x := range texts {
			out[i] = TranscriptSegment{Index: i + 1, Speaker: "Mei", Text: x}
		}
		return out
	}
	var content ListeningExerciseContent
	moves := func(c ListeningScriptChanges) string {
		var parts []string
		for _, m := range c.LinesRenumbered {
			parts = append(parts, m.Before+">"+m.After)
		}
		return strings.Join(parts, " ")
	}
	lines := func(c ListeningScriptChanges) string {
		var parts []string
		for _, l := range c.Lines {
			b, a := "-", "-"
			if l.BeforeLine != nil {
				b = *l.BeforeLine
			}
			if l.AfterLine != nil {
				a = *l.AfterLine
			}
			parts = append(parts, l.Change+":"+l.Line+"("+b+","+a+")")
		}
		return strings.Join(parts, " ")
	}
	ten := seg("a", "b", "c", "d", "e", "f", "g", "h", "i", "j")
	// A deletion: one removed line, seven renumbered, nothing reported as changed.
	c := DiffListeningScript(ten, content, seg("a", "b", "d", "e", "f", "g", "h", "i", "j"), content)
	if lines(c) != "removed:s3(s3,-)" || moves(c) != "s4>s3 s5>s4 s6>s5 s7>s6 s8>s7 s9>s8 s10>s9" {
		t.Fatalf("deletion: %s | %s", lines(c), moves(c))
	}
	// A deletion and an edit further down: the edit names both numbers.
	c = DiffListeningScript(ten, content, seg("a", "b", "d", "e", "f", "g", "H!", "i", "j"), content)
	if lines(c) != "removed:s3(s3,-) changed:s7(s8,s7)" || c.Lines[1].Before.Text != "h" || c.Lines[1].After.Text != "H!" ||
		moves(c) != "s4>s3 s5>s4 s6>s5 s7>s6 s9>s8 s10>s9" {
		t.Fatalf("deletion and edit: %s | %s", lines(c), moves(c))
	}
	// An insertion.
	c = DiffListeningScript(seg("a", "b", "c"), content, seg("a", "new", "b", "c"), content)
	if lines(c) != "added:s2(-,s2)" || moves(c) != "s2>s3 s3>s4" {
		t.Fatalf("insertion: %s | %s", lines(c), moves(c))
	}
	// Edits in place in an equal-length script pair by position, as before.
	c = DiffListeningScript(seg("a", "b", "c"), content, seg("a", "B", "C"), content)
	if lines(c) != "changed:s2(s2,s2) changed:s3(s3,s3)" || moves(c) != "" {
		t.Fatalf("edits in place: %s | %s", lines(c), moves(c))
	}
	// Two lines swapped: the move stays visible as a removal and an addition.
	c = DiffListeningScript(seg("a", "b", "c", "d"), content, seg("a", "c", "b", "d"), content)
	if lines(c) != "removed:s2(s2,-) added:s3(-,s3)" || moves(c) != "s3>s2" {
		t.Fatalf("swap: %s | %s", lines(c), moves(c))
	}
	// A speaker change alone is a change.
	b := seg("a", "b")
	b[1].Speaker = "Léa"
	if c = DiffListeningScript(seg("a", "b"), content, b, content); lines(c) != "changed:s2(s2,s2)" {
		t.Fatalf("speaker: %s", lines(c))
	}
}
