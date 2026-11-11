// Package exam holds the authored Mock Exam v1 forms. Every form only names
// questions of the embedded reading pack (flh_reading_pack_v1); the server
// validates the forms against that pack at startup.
package exam

import _ "embed"

//go:embed forms/mock_exam_forms_v1.json
var forms []byte

// Forms returns the embedded forms JSON.
func Forms() []byte { return forms }
