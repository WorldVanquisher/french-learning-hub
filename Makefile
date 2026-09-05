.PHONY: help tidy build build-capture run capture test fmt vet verify clean

BINARY := bin/server
CAPTURE_BINARY := bin/capture

help:
	@echo "Targets:"
	@echo "  tidy          - go mod tidy"
	@echo "  build         - compile the server to $(BINARY)"
	@echo "  build-capture - compile the capture CLI to $(CAPTURE_BINARY)"
	@echo "  run           - run the server"
	@echo "  capture       - run the capture CLI (pass args via ARGS=...)"
	@echo "  test          - run all tests"
	@echo "  fmt           - format all Go files"
	@echo "  vet           - run go vet"
	@echo "  verify        - run non-mutating release verification"
	@echo "  clean         - remove build artifacts"

tidy:
	go mod tidy

build:
	go build -o $(BINARY) ./cmd/server

build-capture:
	go build -o $(CAPTURE_BINARY) ./cmd/capture

run:
	go run ./cmd/server

# Example: make capture ARGS="-file examples/captures/manual-example.json"
capture:
	go run ./cmd/capture $(ARGS)

test:
	go test ./...

fmt:
	gofmt -w .

vet:
	go vet ./...

verify:
	@files="$$(gofmt -l .)"; \
	if [ -n "$$files" ]; then \
		echo "Go files need formatting:"; \
		echo "$$files"; \
		exit 1; \
	fi
	go test ./...
	go vet ./...
	@verify_dir="$$(mktemp -d)"; \
	trap 'rm -rf "$$verify_dir"' EXIT; \
	go build -o "$$verify_dir/server" ./cmd/server; \
	go build -o "$$verify_dir/capture" ./cmd/capture
	@test -d web/node_modules || { \
		echo "web/node_modules is missing; run 'cd web && npm ci' first"; \
		exit 1; \
	}
	cd web && npm run typecheck
	cd web && npm test
	cd web && npm run build

clean:
	rm -rf bin
