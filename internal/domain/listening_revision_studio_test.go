package domain

import (
	"strings"
	"testing"
)

func sides(ws []WordEdit) (before, after string) {
	var b, a strings.Builder
	for _, w := range ws {
		if w.Op != WordInserted {
			b.WriteString(w.Text)
		}
		if w.Op != WordRemoved {
			a.WriteString(w.Text)
		}
	}
	return b.String(), a.String()
}

// Word edits rebuild both lines exactly: French punctuation, narrow and
// ordinary non-breaking spaces, curly apostrophes, guillemets, ellipses and
// line breaks are never normalized.
func TestDiffWords_RebuildsBothSidesExactly(t *testing.T) {
	cases := [][2]string{
		{"Bonjour ! Ça va ?", "Bonjour ! Comment ça va ?"},
		{"« Je finis le travail à 17 h 30… »", "« Je finis le travail à 18 h… » Voilà."},
		{"Aujourd’hui, c’est peut-être fermé.\nRevenez demain.", "Aujourd’hui, c’est fermé.\n\nRevenez lundi."},
		{"", "Une ligne ajoutée."},
		{"Une ligne retirée.", ""},
		{"Identique : rien ne change !", "Identique : rien ne change !"},
		{strings.Repeat("Il était une fois, dans une ville très lointaine, une étudiante qui s’appelait Hélène. ", 40),
			strings.Repeat("Il était une fois, dans une ville très lointaine, une étudiante qui s’appelait Hélène. ", 39) + "Fin."},
	}
	for _, c := range cases {
		ws := DiffWords(c[0], c[1])
		if b, a := sides(ws); b != c[0] || a != c[1] {
			t.Errorf("DiffWords(%q, %q) rebuilds %q / %q", c[0], c[1], b, a)
		}
		for i := 1; i < len(ws); i++ {
			if ws[i].Op == ws[i-1].Op {
				t.Errorf("adjacent %s runs not merged: %v", ws[i].Op, ws)
			}
		}
	}
}

func TestDiffWords_LabelsInsertedAndRemovedWords(t *testing.T) {
	got := DiffWords("Je finis le travail à 17 h 30.", "Je finis le travail à 18 h.")
	want := []WordEdit{{WordSame, "Je finis le travail à "}, {WordRemoved, "17"}, {WordInserted, "18"}, {WordSame, " h"}, {WordRemoved, " 30"}, {WordSame, "."}}
	if len(got) != len(want) {
		t.Fatalf("got %v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
	// A word with an apostrophe or hyphen is one token: changing it is one edit.
	if got := DiffWords("C'est peut-être là.", "C'est sûrement là."); len(got) != 4 || got[1] != (WordEdit{WordRemoved, "peut-être"}) || got[2] != (WordEdit{WordInserted, "sûrement"}) {
		t.Fatalf("joined words: %v", got)
	}
}

func TestAlignListeningBlocks_EveryLineInOrderWithKinds(t *testing.T) {
	seg := func(i int, sp, text string) TranscriptSegment {
		return TranscriptSegment{Index: i, Speaker: sp, Text: text}
	}
	before := []TranscriptSegment{seg(1, "A", "Bonjour."), seg(2, "B", "Ligne retirée."), seg(3, "A", "Je finis à 17 h 30."), seg(4, "B", "Au revoir.")}
	after := []TranscriptSegment{seg(1, "A", "Bonjour."), seg(2, "A", "Je finis à 18 h."), seg(3, "B", "Au revoir."), seg(4, "C", "Ligne ajoutée.")}
	blocks := AlignListeningBlocks(before, after)
	var kinds []string
	for _, b := range blocks {
		kinds = append(kinds, b.Kind)
	}
	// Between the matched lines (Bonjour, Au revoir) the gap pairs by
	// position, as in DiffListeningScript: before s2 pairs with after s2
	// (changed) and before s3 is left over (removed).
	if strings.Join(kinds, ",") != "same,changed,removed,renumbered,added" {
		t.Fatalf("kinds: %v", kinds)
	}
	ch := blocks[1]
	if *ch.BeforeLine != "s2" || *ch.AfterLine != "s2" || !ch.SpeakerChange || len(ch.Words) == 0 {
		t.Fatalf("changed block: %+v", ch)
	}
	if b, a := sides(ch.Words); b != "Ligne retirée." || a != "Je finis à 18 h." {
		t.Fatalf("changed words rebuild %q %q", b, a)
	}
	if r := blocks[2]; *r.BeforeLine != "s3" || r.AfterLine != nil || r.Before.Text != "Je finis à 17 h 30." {
		t.Fatalf("removed: %+v", r)
	}
	if r := blocks[3]; *r.BeforeLine != "s4" || *r.AfterLine != "s3" || len(r.Words) != 0 {
		t.Fatalf("renumbered: %+v", r)
	}
	// Equal scripts: every block is "same".
	for _, b := range AlignListeningBlocks(before, before) {
		if b.Kind != BlockSame {
			t.Fatalf("same scripts: %+v", b)
		}
	}
}
