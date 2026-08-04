package domain

import (
	"crypto/sha256"
	"encoding/hex"
	"strconv"
	"strings"
)

// CaptureFingerprint computes a deterministic SHA-256 fingerprint over the
// meaningful content of a capture. It is used to detect whether a repeated
// capture_id submission carries the same content (idempotent replay) or
// different content (conflict).
//
// Canonicalization (documented precisely):
//
//   - The fingerprint is computed over a canonical field encoding, NOT over raw
//     JSON bytes, so JSON key ordering and insignificant whitespace never affect
//     it.
//   - The caller passes already-normalized values (the same normalization
//     NewLearningCaptureInput.Validate applies: surrounding whitespace trimmed on
//     original input, context, discussion summary, analysis explanation, and
//     analysis uncertainty; category lowercased+trimmed; source and schema
//     version validated). No further trimming happens here, so the fingerprint
//     reflects exactly what is stored.
//   - Each field is encoded as its byte length in decimal, a colon, the raw
//     bytes, and a trailing newline. Length-prefixing makes the boundaries
//     unambiguous, so no reshuffling of content across adjacent fields can yield
//     the same stream (e.g. input "ab"+context "c" differs from input "a"+context
//     "bc").
//   - Analysis presence is encoded explicitly ("1" present / "0" absent) before
//     the analysis fields, so adding or removing an analysis always changes the
//     fingerprint even if the analysis fields would otherwise be empty.
//   - Confidence is formatted with strconv.FormatFloat(f, 'f', -1, 64), the
//     shortest decimal that round-trips, so equal float64 values always encode
//     identically.
//   - Timestamps and database IDs are deliberately excluded.
//
// Only standard-library cryptography is used. The canonical content and this
// input are never logged.
func CaptureFingerprint(in PreparedLearningCapture) string {
	var b strings.Builder

	writeField := func(label, value string) {
		// label guards against any theoretical cross-field ambiguity and makes the
		// stream self-describing; it is a fixed constant per field.
		b.WriteString(label)
		b.WriteByte('=')
		b.WriteString(strconv.Itoa(len(value)))
		b.WriteByte(':')
		b.WriteString(value)
		b.WriteByte('\n')
	}

	writeField("schema_version", in.SchemaVersion)
	writeField("capture_id", in.CaptureID)
	writeField("source", string(in.Source))
	writeField("original_input", in.OriginalInput)
	writeField("original_context", in.OriginalContext)
	writeField("discussion_summary", in.DiscussionSummary)

	if in.Analysis != nil {
		writeField("has_analysis", "1")
		writeField("analysis_category", in.Analysis.Category)
		writeField("analysis_explanation", in.Analysis.Explanation)
		writeField("analysis_confidence", strconv.FormatFloat(in.Analysis.Confidence, 'f', -1, 64))
		writeField("analysis_uncertainty", in.Analysis.Uncertainty)
	} else {
		writeField("has_analysis", "0")
	}

	sum := sha256.Sum256([]byte(b.String()))
	return hex.EncodeToString(sum[:])
}
