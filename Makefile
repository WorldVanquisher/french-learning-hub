.PHONY: help tidy build build-capture run capture test fmt vet clean

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

clean:
	rm -rf bin
