# Knowledge Library demo (two minutes)

This demo shows the Knowledge Library (FLH-034) on a synthetic, isolated
database. It needs no paid provider, secret, personal database or external
service:

- analysis uses the local rule-based analyzer;
- extraction goes to a local stub (`scripts/demo/flh034/stub_extractor.py`);
- all data is written through the normal HTTP API by
  `scripts/demo/flh034/seed.py`.

## Setup

Requirements: Go, Python 3, Node.js/npm and `curl`, on **Linux or macOS**
(process ownership uses Linux `/proc`, or macOS `ps` and `lsof`; other
platforms are refused). Commands run from the repository root.

Setup is preparation, not part of the two-minute presentation. Measured on
macOS (FLH-036): the frontend build took about 2 s after `npm ci`, a cold
server build took about 7 s, and setup with a warm Go cache took 1–2 s. Do it
before the audience arrives.

```sh
npm --prefix web ci && npm --prefix web run build     # production workbench build
WORK=$(mktemp -d)/flh034-demo                         # new, isolated directory
sh scripts/demo/flh034/demo.sh setup "$WORK" "$PWD/web/dist"
```

Open <http://127.0.0.1:18934/>. The ports are `DEMO_PORT` (18934) and
`STUB_PORT` (18933); override them with those variables. Both must be free:
setup refuses an occupied port before it builds, launches or seeds anything,
so no fixture request can reach another program.

The demo server is started with `LISTEN_HOST=127.0.0.1` and listens only on
IPv4 loopback; the stub also binds `127.0.0.1`. Setup accepts readiness only
once the process it started itself holds that loopback listener, and prints
it, for example `server pid 26205 listens on 127.0.0.1 port 18934 (loopback
only)`. A plain server run without `LISTEN_HOST` still listens on all
interfaces, as before.

`setup` refuses to run unless `WORK` is a **new or empty absolute directory
outside the repository**:

- it never reuses or resets a database;
- it cannot touch `data/`;
- `seed.py` also refuses a non-loopback backend, or one that already holds
  entries or Concepts.

If any step fails (build, port, start, readiness or seed), setup prints
`setup FAILED`, stops the processes it started, and exits non-zero. It writes
`seed.json` only after a successful seed; a failed seed leaves
`seed.partial.json`. The failed directory is kept for its logs; remove it with
`demo.sh cleanup "$WORK"` before trying again.

To use the Vite development server instead, run setup without the second
argument. Then run:

```sh
FRENCH_HUB_URL=http://127.0.0.1:18934 npm --prefix web run dev
```

## What the fixture contains

The demo is English-first (FLH-038): concept titles, rule explanations and the
learner's questions are in English. Every example sentence stays French, and so
do the grammar terms a learner meets in class (subjonctif, passé composé,
« bien que », malgré), usually with an English gloss.

There are four synthetic learning records, each an English question about French:

1. Why do we say « il faut que je fasse » and not « il faut que je fais »?
2. Bien que + subjunctive or indicative? I wrote « bien qu'il pleut ».
3. I wrote « je suis allé au cinéma hier ». Is that correct?
4. How do I say « I miss you » in French?

And seven Concepts, which together cover every case:

| Concept | What it demonstrates |
| --- | --- |
| subjunctive after « il faut que » | Supported; best explanation from the current extraction; a unit from an older extraction is still filed here but no longer supports it; a RELATED link |
| subjunctive forms of faire | **Orphaned**: its only filed unit comes from an older extraction |
| subjunctive after « bien que » | Supported; a filed unit the learner hid (admission suppressed); the record's interpretation was corrected before extraction |
| overview of the subjunctive mood | Orphaned, never supported; linked only (NARROWER) |
| passé composé with être | Supported; history: a unit that was moved to another Concept |
| agreement of the past participle with être | Supported by that moved unit |
| tu me manques: saying you miss someone | Supported; history: a unit later marked INVALID |

Titles are stored in lower case because Concept identity is normalized. The
fixture changes only freshly seeded demo databases: no existing record, Concept
or translation is created, rewritten or migrated.

## Walkthrough (about two minutes)

Two ideas carry the demo:

- A **unit is filed under a Concept** when it was judged to be the same idea
  (technically, its CURRENT SAME membership).
- A unit **supports** the Concept only while it also comes from its record's
  current extraction and the learner has not hidden it.

1. **Open the library.** Click **Knowledge Library**. All seven Concepts are
   listed, active ones first, each with how many units are filed there and how
   many currently support it.
2. **Search.** Type `subjunctive` and press **Search**. Four Concepts match by
   title, and the two orphaned ones are listed last. (`subjonctif` finds the
   same four.)
3. **Open “subjunctive after « il faut que »”.**
   - *Status* says in plain English why it is active.
   - *Best explanation* is the reworded unit from the current extraction, with
     its French example « Il faut que tu viennes demain. »
   - *Filed here but not supporting* shows the older v1 unit and why it no
     longer counts.
   - *Linked units* shows a RELATED link, which gives no support.
4. **Follow the evidence.** On the v1 unit, click **View source record #1**.
   The page shows what the learner wrote, marks extraction v1 as *Historical*,
   and shows the interpretation it used (analysis v1, with a newer v2 noted).
5. **Return.** Click **← Back to concept #1**, then **← Back to results for
   “subjunctive”**. The query and results are unchanged, and focus is back on
   the Concept you opened.
6. **Search a French word.** Search `fasse`. Two Concepts match only through
   the French examples of units filed under them, and each result says that
   being filed is not support. Open **subjunctive forms of faire**: it is
   *Orphaned*, with its filed unit and the reason shown.
7. **History is never current.**
   - Search `être` and open **passé composé with être**. *History* says the
     unit "was moved: it is now filed under concept #6"; click the link.
   - Search `manques` and open **tu me manques: saying you miss someone**. Its
     history shows a unit "later marked INVALID".
8. **Corrected interpretation.** Search `bien que` and open the Concept. One
   unit is filed but not supporting because "the learner hid it". View the
   source of record #2: the interpretation was **corrected by a person**, and
   both the explanation used and the one before correction are shown.

Concept, unit, record and extraction numbers stay visible in small print for
tracing, but the main text reads without them. Nothing in this walkthrough
writes data or calls a provider. Open the browser's network panel to confirm
that only GET requests are sent.

## Restart and cleanup

```sh
sh scripts/demo/flh034/demo.sh stop    "$WORK"
sh scripts/demo/flh034/demo.sh start   "$WORK" "$PWD/web/dist"   # same database; results persist
sh scripts/demo/flh034/demo.sh cleanup "$WORK"                   # stops and deletes only this demo directory
```

`start`, `stop` and `cleanup` act only on a directory created by `setup` (it
contains a `.flh034-demo` marker). The marker and a PID are not enough to send
a signal:

- At launch, `proc_guard.py` records each process's PID, kernel start time and
  command line in `server.id` and `stub.id`. `server.pid` and `stub.pid` still
  hold just the PID.
- `stop` signals a process only if all three still match, and the command names
  this directory (`WORK/server`, or the stub started with `WORK` as its
  argument). It then waits for the process to exit.
- A dead PID is reported as a stale record and removed.
- A live PID whose start time or command differs (reused or misattributed) is
  **never signalled**; its record is removed and the mismatch is reported.
- `stop` and `cleanup` then look for any process still carrying this
  directory's identity. If one is found, `stop` exits non-zero and `cleanup`
  refuses to delete the directory, naming the PID for you to inspect.

Interrupting setup with Ctrl-C runs the same cleanup. A `kill -9` of the script
itself or a power loss cannot; run `cleanup` afterwards.

## Automated walkthrough (optional)

`scripts/demo/flh034/walkthrough.mjs` performs the steps above in headless
Chrome and asserts what each one shows. It also checks that no non-GET request
is sent. It needs `playwright-core` in a temporary directory, which is not a
project dependency:

```sh
PW=$(mktemp -d); npm install --prefix "$PW" playwright-core
cp scripts/demo/flh034/walkthrough.mjs "$PW/" && mkdir -p "$WORK/shots"
node "$PW/walkthrough.mjs" http://127.0.0.1:18934 "$WORK/shots" prod
```

It expects a freshly seeded demo, because it refers to records #1 and #2 and
concept #6.

Add `--multi-relation` as a fourth argument to run W11 after the read-only
steps. W11 records RELATED and BROADER from unit #9 to concept #3 through the
API, outside the browser, so it writes to the demo database. It then checks
that both relations are shown and that the browser logged no React
duplicate-key warning. React prints that warning only in development builds, so
the check is meaningful against Vite. Run the read-only walkthrough first if
you need its database snapshot.
