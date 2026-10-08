package config

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strings"

	"github.com/joho/godotenv"
)

// DotEnvFile is the optional local configuration file that Load reads from the
// process working directory. It is parsed with github.com/joho/godotenv.
const DotEnvFile = ".env"

// source resolves one configuration key. A variable present in the process
// environment always wins, even when it is set to an empty string; otherwise the
// value from the optional .env file is used. The process environment is never
// modified.
type source struct {
	dotenv map[string]string
}

func (s source) get(key string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return s.dotenv[key]
}

// readDotEnv parses path into a map. A missing file is valid and yields an empty
// map. Errors identify the file and the kind of problem but never include file
// contents: the parser's own messages quote raw input, which may contain secrets,
// so they are deliberately not wrapped or echoed.
func readDotEnv(path string) (map[string]string, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return map[string]string{}, nil
	}
	if err != nil {
		var pathErr *fs.PathError
		if errors.As(err, &pathErr) {
			return nil, fmt.Errorf("config: cannot read %s: %v", path, pathErr.Err)
		}
		return nil, fmt.Errorf("config: cannot read %s", path)
	}

	values, err := godotenv.UnmarshalBytes(data)
	if err != nil {
		return nil, fmt.Errorf(
			"config: %s is malformed (%s); values are not shown. Use KEY=value lines and close every quote",
			path, describeParseError(err),
		)
	}
	return values, nil
}

// describeParseError classifies a godotenv parse error without exposing any of
// the input the parser quoted in its message.
func describeParseError(err error) string {
	msg := err.Error()
	switch {
	case strings.HasPrefix(msg, "unexpected character"):
		return "invalid character in a variable name"
	case strings.HasPrefix(msg, "unterminated quoted value"):
		return "unterminated quoted value"
	case strings.HasPrefix(msg, "zero length string"):
		return "missing variable name"
	default:
		return "unparseable content"
	}
}
