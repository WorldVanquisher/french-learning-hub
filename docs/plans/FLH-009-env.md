# FLH-009 — Local `.env` configuration support

Owner: Claude Code (implementation). Status: implemented, awaiting human review.

## Scope

Owned: `internal/config/`, `.env.example`, `.gitignore`, `go.mod`/`go.sum`
(one dependency), and this note. Not touched: server wiring (`cmd/server`),
Docker files, frontend, shared READMEs and guides.

## Configuration contract

- `config.Load()` reads an optional file named `.env` (`config.DotEnvFile`) from
  the **process working directory**. `make run` and `go run ./cmd/server` from the
  repository root therefore read `<repo>/.env`.
- Parsing uses `github.com/joho/godotenv` v1.5.1 (`UnmarshalBytes`). The file is
  read into a map; the process environment is never modified.
- Resolution per key: a variable **present** in the process environment wins,
  even when its value is empty; otherwise the `.env` value is used; otherwise the
  existing default applies. Empty values continue to behave as unset.
- A missing `.env` is valid and changes nothing.
- An unreadable `.env` (e.g. a directory, or no permission) fails startup with
  `config: cannot read .env: <OS reason>`.
- A malformed `.env` fails startup with
  `config: .env is malformed (<kind>); values are not shown. ...` where `<kind>` is
  one of: invalid character in a variable name, unterminated quoted value, missing
  variable name, unparseable content. The parser's own message is never wrapped or
  echoed, because it quotes raw file content.
- All existing defaults and provider validation are unchanged and apply equally
  to values that come from `.env`. Validation messages never include key values.
- Syntax notes (godotenv): `KEY=value` per line, `#` comments, optional `export`.
  Unquoted and double-quoted values expand `$NAME` / `${NAME}` from earlier lines
  of the same file; single-quoted values are literal. Secrets containing `$` or
  `#` should be single-quoted.

## Local file

A repository-root `.env` did not exist and was created (mode 600) with comments
and two empty placeholders, `OPENAI_API_KEY=` and `EMBEDDING_API_KEY=`. Empty
placeholders keep every default valid. `.gitignore` already ignored `.env` at any
depth, so it was not changed.

## Verification

- `go test ./internal/config/ -count=1` and `go test ./... -count=1`: pass.
- `gofmt -l .`: no output. `go vet ./...`: pass.
- Mutation checks in a scratch copy: echoing the parser error fails the
  secret-safety test; letting `.env` win fails the precedence test.
- Server smoke test from temporary working directories: `.env` port and
  database were used; a process `PORT` overrode `.env`; a malformed `.env`
  exited with status 1 and the sentinel value did not appear in the output.

## Follow-up for the documentation owner

These shared documents still state that `.env` is not loaded automatically and
need a separate, bilingual update:

- `README.md` (section on enabling OpenAI, "The service does not load `.env`
  automatically")
- `docs/QUICKSTART.md` ("Optional providers": "it does not automatically load a
  `.env` file")
- `docs/LOCAL_LEARNING_WORKFLOW.zh-CN.md` (section 6: "不自动加载 `.env`")

`README.zh-CN.md` has no equivalent statement. The local-learning workflow's
`DB_PATH`/`PORT` exports still win over `.env` because process variables take
precedence.
