.PHONY: help tidy build run test fmt vet clean

BINARY := bin/server

help:
	@echo "Targets:"
	@echo "  tidy   - go mod tidy"
	@echo "  build  - compile the server to $(BINARY)"
	@echo "  run    - run the server"
	@echo "  test   - run all tests"
	@echo "  fmt    - format all Go files"
	@echo "  vet    - run go vet"
	@echo "  clean  - remove build artifacts"

tidy:
	go mod tidy

build:
	go build -o $(BINARY) ./cmd/server

run:
	go run ./cmd/server

test:
	go test ./...

fmt:
	gofmt -w .

vet:
	go vet ./...

clean:
	rm -rf bin
