// Command history-export writes a portable learning history export
// (learning_history_export_v1) from a running server into a directory you
// choose: NAME.ndjson (for the app's import preview) and NAME.txt (a
// readable copy). Audio and credentials are never exported; transcripts and
// notes only with -transcripts / -notes. It never overwrites a file.
//
//	history-export -dir DIR [-name NAME] [-transcripts] [-notes] [-url URL]
//
// The server URL resolves as -url, then FRENCH_HUB_URL, then
// http://localhost:8080.
package main

import (
	"flag"
	"fmt"
	"net/http"
	"os"
	"time"

	"french-learning-app/internal/historyexport"
)

func main() { os.Exit(run(os.Args[1:])) }

func run(args []string) int {
	fs := flag.NewFlagSet("history-export", flag.ContinueOnError)
	dir := fs.String("dir", "", "existing directory to write into (required)")
	name := fs.String("name", "learning-history-"+time.Now().Format("20060102"), "file name without extension")
	transcripts := fs.Bool("transcripts", false, "include Speaking transcript texts")
	notes := fs.Bool("notes", false, "include Mistake Notebook record texts and Writing draft texts")
	base := fs.String("url", "", "server URL (default FRENCH_HUB_URL, then http://localhost:8080)")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if *base == "" {
		*base = os.Getenv("FRENCH_HUB_URL")
	}
	if *base == "" {
		*base = "http://localhost:8080"
	}
	files, err := historyexport.Run(&http.Client{Timeout: 60 * time.Second}, *base, *dir, *name, historyexport.Options{Transcripts: *transcripts, Notes: *notes})
	if err != nil {
		fmt.Fprintln(os.Stderr, "history-export:", err)
		return 1
	}
	for _, f := range files {
		fmt.Printf("%s\topens as text: %v\tapp import: %s\n", f.Path, f.OpensText, f.AppImport)
	}
	return 0
}
