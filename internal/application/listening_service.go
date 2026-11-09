package application

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"french-learning-app/internal/domain"
)

// ListeningService implements Exam Listening Lesson v1: saving YouTube material
// with an optional learner-supplied transcript, and one explicit, opt-in
// exercise generation per request. Reads never call the generator. A provider
// failure or unusable output is stored as a failed exercise next to the
// untouched material and transcript; there is no retry and no background work.
type ListeningService struct {
	repo      domain.ListeningRepository
	generator domain.ListeningExerciseGenerator // nil when LISTENING_PROVIDER=disabled
}

// NewListeningService builds the service. generator may be nil (disabled).
func NewListeningService(repo domain.ListeningRepository, generator domain.ListeningExerciseGenerator) *ListeningService {
	return &ListeningService{repo: repo, generator: generator}
}

// ListeningLesson is one material with its latest transcript and every stored
// exercise attempt (newest first).
type ListeningLesson struct {
	Material   domain.ListeningMaterial
	Transcript *domain.ListeningTranscript
	Exercises  []domain.ListeningExercise
}

// ListeningMaterialSummary is a list row.
type ListeningMaterialSummary struct {
	Material          domain.ListeningMaterial
	TranscriptVersion int // 0 when no transcript
	SegmentCount      int
	LatestExercise    *domain.ListeningExercise
}

// ListeningGenerationError carries the stored failed exercise for a provider failure or
// invalid output, so the caller can show it.
type ListeningGenerationError struct {
	Exercise domain.ListeningExercise
	Err      error
}

func (e *ListeningGenerationError) Error() string { return e.Err.Error() }
func (e *ListeningGenerationError) Unwrap() error { return e.Err }

// GeneratorEnabled reports whether preparation can call a provider, and the
// provenance it would record.
func (s *ListeningService) GeneratorEnabled() (bool, string) {
	if s.generator == nil {
		return false, ""
	}
	return true, s.generator.Name()
}

// CreateMaterial validates and stores a link, a title and an optional
// transcript (blank means "no transcript yet").
func (s *ListeningService) CreateMaterial(ctx context.Context, sourceURL, title, transcript string) (*ListeningLesson, error) {
	videoID, canonical, err := domain.ParseYouTubeURL(sourceURL)
	if err != nil {
		return nil, err
	}
	t, err := domain.NormalizeListeningTitle(title)
	if err != nil {
		return nil, err
	}
	var segments []domain.TranscriptSegment
	var timed bool
	if strings.TrimSpace(transcript) != "" {
		if segments, timed, err = domain.ParseTranscript(transcript); err != nil {
			return nil, err
		}
	}
	m, tr, err := s.repo.CreateMaterial(ctx, domain.ListeningMaterial{VideoID: videoID, SourceURL: canonical, Title: t}, segments, timed)
	if err != nil {
		return nil, err
	}
	return &ListeningLesson{Material: m, Transcript: tr, Exercises: []domain.ListeningExercise{}}, nil
}

// AddTranscript stores a new transcript version for existing material.
func (s *ListeningService) AddTranscript(ctx context.Context, materialID int64, transcript string) (*ListeningLesson, error) {
	segments, timed, err := domain.ParseTranscript(transcript)
	if err != nil {
		return nil, err
	}
	if _, err := s.repo.AddTranscript(ctx, materialID, segments, timed); err != nil {
		return nil, err
	}
	return s.GetLesson(ctx, materialID)
}

// GetLesson reads one lesson. It never calls the generator.
func (s *ListeningService) GetLesson(ctx context.Context, materialID int64) (*ListeningLesson, error) {
	m, err := s.repo.GetMaterial(ctx, materialID)
	if err != nil {
		return nil, err
	}
	tr, err := s.repo.LatestTranscript(ctx, materialID)
	if err != nil {
		return nil, err
	}
	ex, err := s.repo.ListExercises(ctx, materialID)
	if err != nil {
		return nil, err
	}
	return &ListeningLesson{Material: m, Transcript: tr, Exercises: ex}, nil
}

// ListMaterials lists every material, newest first. It never calls the generator.
func (s *ListeningService) ListMaterials(ctx context.Context) ([]ListeningMaterialSummary, error) {
	ms, err := s.repo.ListMaterials(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]ListeningMaterialSummary, 0, len(ms))
	for _, m := range ms {
		row := ListeningMaterialSummary{Material: m}
		tr, err := s.repo.LatestTranscript(ctx, m.ID)
		if err != nil {
			return nil, err
		}
		if tr != nil {
			row.TranscriptVersion, row.SegmentCount = tr.Version, len(tr.Segments)
		}
		ex, err := s.repo.ListExercises(ctx, m.ID)
		if err != nil {
			return nil, err
		}
		if len(ex) > 0 {
			row.LatestExercise = &ex[0]
		}
		out = append(out, row)
	}
	return out, nil
}

// GenerateExercise makes one explicit provider call over the latest transcript.
//   - disabled generator: domain.ErrListeningDisabled, nothing stored;
//   - unknown material: domain.ErrNotFound;
//   - no transcript: domain.ErrListeningNoTranscript, no call, nothing stored;
//   - provider failure or invalid output: the failed exercise is stored and
//     returned inside a *ListeningGenerationError;
//   - success: the validated, completed exercise.
//
// The output is validated here against the exact transcript, whatever the
// generator already checked.
func (s *ListeningService) GenerateExercise(ctx context.Context, materialID int64) (*domain.ListeningExercise, error) {
	if s.generator == nil {
		return nil, domain.ErrListeningDisabled
	}
	m, err := s.repo.GetMaterial(ctx, materialID)
	if err != nil {
		return nil, err
	}
	tr, err := s.repo.LatestTranscript(ctx, materialID)
	if err != nil {
		return nil, err
	}
	if tr == nil {
		return nil, domain.ErrListeningNoTranscript
	}
	content, genErr := s.generator.Generate(ctx, domain.ListeningGenerationRequest{Title: m.Title, Segments: tr.Segments})
	if genErr == nil {
		genErr = domain.ValidateListeningExercise(tr.Segments, &content)
	}
	row := domain.ListeningExercise{MaterialID: m.ID, TranscriptID: tr.ID, Generator: s.generator.Name()}
	if genErr != nil {
		if !errors.Is(genErr, domain.ErrProviderTimeout) && !errors.Is(genErr, domain.ErrProviderUnavailable) && !errors.Is(genErr, domain.ErrValidation) {
			genErr = fmt.Errorf("%w: %v", domain.ErrProviderUnavailable, genErr)
		}
		row.Status, row.FailureCode = domain.ListeningExerciseFailed, domain.ListeningFailureCode(genErr)
		// The request context may have expired with the provider; the failure is
		// still recorded so the learner sees an honest status.
		stored, err := s.repo.CreateExercise(context.WithoutCancel(ctx), row)
		if err != nil {
			return nil, err
		}
		return nil, &ListeningGenerationError{Exercise: stored, Err: genErr}
	}
	row.Status, row.Content = domain.ListeningExerciseCompleted, &content
	stored, err := s.repo.CreateExercise(ctx, row)
	if err != nil {
		return nil, err
	}
	return &stored, nil
}
