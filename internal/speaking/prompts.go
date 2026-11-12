package speaking

import _ "embed"

// examplePrompts is the authored speaking prompt set (flh_speaking_prompts_v1):
// three original practical prompts (respond to an invitation, ask for
// information, explain a change of plan), each with content points, a
// duration range and an example transcript with deliberate mistakes. They are
// practice prompts, not official exam items. The file lives inside the image's
// build context and the server validates it at startup.
//
//go:embed prompts/speaking_prompts_v1.json
var examplePrompts []byte

// ExamplePrompts returns the embedded prompt set JSON.
func ExamplePrompts() []byte { return examplePrompts }
