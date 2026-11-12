package domain

import (
	"encoding/json"
	"slices"
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
