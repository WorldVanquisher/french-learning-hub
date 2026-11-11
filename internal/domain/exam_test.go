package domain_test

import (
	"errors"
	"strings"
	"testing"

	"french-learning-app/internal/domain"
	"french-learning-app/internal/exam"
	"french-learning-app/internal/reading"
)

func examPack(t *testing.T) domain.ReadingPack {
	t.Helper()
	p, err := domain.ParseReadingPack(reading.ExamplePack())
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func TestMockExamForms_EmbeddedFormsAreValidAgainstThePack(t *testing.T) {
	f, err := domain.ParseMockExamForms(exam.Forms(), examPack(t))
	if err != nil {
		t.Fatal(err)
	}
	if len(f.Forms) != 2 || f.RetrySeconds != 120 {
		t.Fatalf("forms = %+v", f)
	}
}

func TestMockExamForms_RefuseUnusableForms(t *testing.T) {
	pack := examPack(t)
	good := string(exam.Forms())
	for name, broken := range map[string]string{
		"unknown question": strings.Replace(good, `"rd-notice-piscine:q1"`, `"rd-notice-piscine:q9"`, 1),
		"unknown passage":  strings.Replace(good, `"passage": "rd-notice-piscine", "question": "rd-notice-piscine:q1"`, `"passage": "rd-nope", "question": "rd-notice-piscine:q1"`, 1),
		"repeated":         strings.Replace(good, `"rd-notice-piscine:q2"`, `"rd-notice-piscine:q1"`, 1),
		"duration":         strings.Replace(good, `"duration_seconds": 90`, `"duration_seconds": 5`, 1),
		"duplicate id":     strings.Replace(good, `"ce-entrainement-express"`, `"ce-examen-blanc-1"`, 1),
		"unknown field":    strings.Replace(good, `"retry_seconds": 120`, `"retry_seconds": 120, "score_scale": 25`, 1),
		"schema":           strings.Replace(good, MockExamVersion(), "flh_mock_exam_forms_v0", 1),
	} {
		if _, err := domain.ParseMockExamForms([]byte(broken), pack); !errors.Is(err, domain.ErrValidation) {
			t.Errorf("%s: got %v", name, err)
		}
	}
}

func MockExamVersion() string { return domain.MockExamFormsVersion }

func TestFreezeExamItem_ChoicesComeOnlyFromAuthoredAnswers(t *testing.T) {
	pack := examPack(t)
	positions := map[int]bool{}
	for _, p := range pack.Passages {
		for i, q := range p.Questions {
			it, err := domain.FreezeExamItem(pack, domain.MockExamFormRef{Passage: p.ID, Question: q.ID})
			if err != nil {
				t.Fatal(err)
			}
			again, _ := domain.FreezeExamItem(pack, domain.MockExamFormRef{Passage: p.ID, Question: q.ID})
			if strings.Join(again.Choices, "|") != strings.Join(it.Choices, "|") {
				t.Fatalf("%s: choice order is not stable", q.ID)
			}
			if it.Choices[it.Key] != q.ReferenceAnswer || it.WhyWrong[it.Key] != nil || len(it.Choices) != 1+len(q.WrongAnswers) || it.PackItem != i+1 {
				t.Fatalf("%s: %+v", q.ID, it)
			}
			for j, c := range it.Choices {
				if j != it.Key && (it.WhyWrong[j] == nil || it.WhyWrong[j].EN == "" || it.WhyWrong[j].ZH == "" || c == q.ReferenceAnswer) {
					t.Fatalf("%s: choice %d has no authored reason", q.ID, j)
				}
			}
			positions[it.Key] = true
		}
	}
	if len(positions) < 2 {
		t.Errorf("the reference answer is always at position %v", positions)
	}
}

func TestRelatedExamRef_PrefersTheSameKindElsewhereAndNeverRepeats(t *testing.T) {
	pack := examPack(t)
	it, _ := domain.FreezeExamItem(pack, domain.MockExamFormRef{Passage: "rd-annonce-ligne-b", Question: "rd-annonce-ligne-b:q2"})
	exclude := map[string]bool{"rd-annonce-ligne-b:q1": true, "rd-annonce-ligne-b:q2": true, "rd-annonce-ligne-b:q3": true}
	seen := map[string]bool{}
	for {
		ref, err := domain.RelatedExamRef(pack, it, exclude)
		if errors.Is(err, domain.ErrExamNoRelated) {
			break
		}
		if err != nil || seen[ref.Question] || exclude[ref.Question] {
			t.Fatalf("related = %+v %v", ref, err)
		}
		related, _ := domain.FreezeExamItem(pack, ref)
		if related.Kind != "detail" || related.PassageID == "rd-annonce-ligne-b" {
			t.Fatalf("related %s is %s from %s", ref.Question, related.Kind, related.PassageID)
		}
		seen[ref.Question], exclude[ref.Question] = true, true
	}
	if len(seen) == 0 {
		t.Fatal("no related question")
	}
}

func TestExamAnswersAndScore(t *testing.T) {
	one, two := 1, 2
	a := domain.ExamAnswersSHA256(3, map[int]*int{1: &one, 3: &two})
	if a != domain.ExamAnswersSHA256(3, map[int]*int{3: &two, 1: &one, 2: nil}) || a == domain.ExamAnswersSHA256(3, map[int]*int{1: &one}) {
		t.Fatal("answer fingerprints must depend on the answers only")
	}
	items := []domain.ExamItem{{Key: 1}, {Key: 0}, {Key: 2}}
	if c, n := domain.ScoreExam(items, map[int]*int{1: &one, 3: &one}); c != 1 || n != 3 {
		t.Fatalf("score = %d/%d", c, n)
	}
}
