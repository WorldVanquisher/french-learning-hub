package writing

import _ "embed"

// examplePrompts is the authored writing prompt set (flh_writing_prompts_v1):
// three original practical tasks, each with content points, a word range and
// an example first draft with deliberate mistakes. They are practice tasks,
// not official exam items. The file lives inside the image's build context and
// the server validates it at startup.
//
//go:embed prompts/writing_prompts_v1.json
var examplePrompts []byte

// ExamplePrompts returns the embedded prompt set JSON.
func ExamplePrompts() []byte { return examplePrompts }
