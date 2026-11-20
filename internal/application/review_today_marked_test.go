package application

import (
	"context"
	"reflect"
	"testing"
	"time"

	"french-learning-app/internal/domain"
)

// R3-065: Review Today resolves only the records marked for retry, and the
// queue and history are exactly what resolving every record gave.

type countingNotebookRepo struct {
	srcs  []domain.LearningCaptureSource
	marks map[int64]domain.RetryMark
}

func (r *countingNotebookRepo) ListSources(context.Context) ([]domain.LearningCaptureSource, error) {
	return r.srcs, nil
}
func (r *countingNotebookRepo) GetSourceByEntry(context.Context, int64) (domain.LearningCaptureSource, error) {
	return domain.LearningCaptureSource{}, domain.ErrNotFound
}
func (r *countingNotebookRepo) CurrentMarks(context.Context) (map[int64]domain.RetryMark, error) {
	return r.marks, nil
}
func (r *countingNotebookRepo) SetMark(context.Context, int64, bool, time.Time) (domain.RetryMark, bool, error) {
	return domain.RetryMark{}, false, nil
}

type countingResolver struct{ n int }

func (c *countingResolver) ResolveSource(_ context.Context, ref domain.CaptureSourceRef) (domain.ResolvedSource, error) {
	c.n++
	return domain.ResolvedSource{Skill: domain.SourceSkill(ref.Type)}, nil
}

type countingEntries struct{ n int }

func (c *countingEntries) GetByID(_ context.Context, id int64) (*domain.Entry, error) {
	c.n++
	return &domain.Entry{ID: id, OriginalInput: "x"}, nil
}

func TestReviewItems_ResolvesOnlyMarkedRecordsAndKeepsTheQueue(t *testing.T) {
	now := time.Date(2026, 11, 20, 9, 0, 0, 0, time.UTC)
	repo := &countingNotebookRepo{marks: map[int64]domain.RetryMark{}}
	for i := int64(1); i <= 500; i++ {
		repo.srcs = append(repo.srcs, domain.LearningCaptureSource{EntryID: 501 - i, Ref: domain.CaptureSourceRef{Type: "listening_item", RecordID: 1, Item: int(i)}})
	}
	for _, id := range []int64{7, 120, 333} {
		repo.marks[id] = domain.RetryMark{EntryID: id, Marked: true, At: now.Add(-time.Duration(id) * time.Minute)}
	}
	repo.marks[8] = domain.RetryMark{EntryID: 8, Marked: false, At: now} // unmarked: history only

	res, ent := &countingResolver{}, &countingEntries{}
	svc := NewMistakeNotebookService(repo, res, ent, nil)
	marked, total, err := svc.ReviewItems(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if total != 500 || len(marked) != 3 || res.n != 3 || ent.n != 3 {
		t.Fatalf("total %d marked %d resolved %d entries read %d; want 500, 3, 3, 3", total, len(marked), res.n, ent.n)
	}
	all, err := svc.ListItems(context.Background(), "", false)
	if err != nil {
		t.Fatal(err)
	}
	got := BuildReviewTodayCounted(nil, marked, total, now)
	want := BuildReviewToday(nil, all, now)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("queue differs:\n got %+v\nwant %+v", got, want)
	}
	if got.History.NotebookItems != 500 || len(got.Items) != 3 {
		t.Fatalf("history %+v items %d", got.History, len(got.Items))
	}
}
