package reading

import _ "embed"

// examplePack is the authored reading pack (flh_reading_pack_v1): original
// French practice passages with reviewed questions, offered as ready examples
// in the private Reading view. It is authored practice material, not an
// official exam item and no certified CEFR level. It lives here, inside the
// image's build context, and the server validates it at startup.
//
//go:embed pack/reading_pack_v1.json
var examplePack []byte

// ExamplePack returns the embedded pack JSON.
func ExamplePack() []byte { return examplePack }
