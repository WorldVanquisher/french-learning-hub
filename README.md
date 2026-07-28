# French Learning App

A small Go HTTP service that persistently stores French-learning questions and
their original context. The original user input is treated as the source of
truth; AI-generated metadata (category, explanation, confidence) is stored in
separate, editable fields and never overwrites the original record.

This is the first milestone: a single backend, SQLite persistence, and one
workflow from question input to persistent storage. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design principles.

## Requirements

- Go 1.26+ (uses `net/http` method-based routing)
- No CGO required — SQLite is provided by the pure-Go `modernc.org/sqlite` driver.

## Layout

```
cmd/server            program entry point + graceful shutdown
internal/domain       Entry entity, Repository interface, validation
internal/application  use cases (create/get/list entry)
internal/storage/sqlite  SQLite repository + migration runner
internal/transport/http  HTTP handlers and routing
internal/config       environment-based configuration
migrations            embedded .sql migrations
```

Layers are kept separate: HTTP handlers hold no database logic, and the
application layer depends only on the domain `Repository` interface.

## Configuration

Configuration comes from the environment (see [.env.example](.env.example)).
Defaults work out of the box:

| Variable             | Default        | Description                     |
| -------------------- | -------------- | ------------------------------- |
| `PORT`               | `8080`         | HTTP listen port                |
| `DB_PATH`            | `data/app.db`  | SQLite database file path       |
| `HTTP_READ_TIMEOUT`  | `10`           | Read timeout (seconds)          |
| `HTTP_WRITE_TIMEOUT` | `10`           | Write timeout (seconds)         |

## Running

```bash
make run          # or: go run ./cmd/server
```

The database file and its directory are created automatically on first run,
and migrations are applied at startup.

## API

### Health

```bash
curl localhost:8080/healthz
# {"status":"ok"}
```

### Create an entry

```bash
curl -X POST localhost:8080/entries \
  -H 'Content-Type: application/json' \
  -d '{"original_input":"Je suis fatigué","original_context":"texting a friend"}'
```

Response `201 Created`:

```json
{
  "id": 1,
  "original_input": "Je suis fatigué",
  "original_context": "texting a friend",
  "created_at": "2026-07-27T12:00:00Z",
  "updated_at": "2026-07-27T12:00:00Z"
}
```

`original_input` is required. Requests with an empty input or unknown JSON
fields are rejected with `400`.

### Get an entry

```bash
curl localhost:8080/entries/1
```

### List entries (newest first)

```bash
curl 'localhost:8080/entries?limit=20'
# {"entries":[ ... ]}
```

## Development

```bash
make test    # run all tests
make vet     # go vet
make fmt     # gofmt -w .
make build   # compile to bin/server
```
