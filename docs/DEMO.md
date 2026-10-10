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

There are four synthetic learning records:

1. « il faut que je fasse »
2. « bien que »
3. « je suis allé »
4. « I miss you »

And seven Concepts, which together cover every case:

| Concept | What it demonstrates |
| --- | --- |
| subjonctif après « il faut que » | Supported; preferred unit from the current extraction; a member from historical extraction v1; a RELATED relation |
| subjonctif de faire | **Orphaned**: its only member is from a historical extraction |
| subjonctif après « bien que » | Supported; a member suppressed by the learner (admission); record analysis corrected before extraction |
| mode subjonctif | Orphaned, never supported; relation only (NARROWER) |
| passé composé avec être | Supported; history: a unit that was reassigned to another Concept |
| accord du participe passé avec être | Supported by that reassigned unit |
| tu me manques | Supported; history: a unit later marked INVALID |

## Walkthrough

1. **Open the library.** Click **Knowledge Library** to browse all seven
   Concepts. Active ones come first, and every result shows its status.
2. **Search.** Type `subjonctif` and press **Search**.
   - Four Concepts match.
   - Each result says where it matched (target, identity features), and how
     many CURRENT SAME members and supporting units it has.
   - The two orphaned Concepts are listed last, honestly labelled.
3. **Open « il faut que ».**
   - *Status:* active, with the support rule explained.
   - *Preferred representation:* the reworded unit from the current extraction.
   - *Current support:* 1 unit.
   - *Current members that do not provide support:* the v1 unit. Its record was
     re-extracted, so it is shown as historical extraction v1 and not counted as
     support.
   - *Current relations:* RELATED, which is explicitly not membership or support.
4. **Follow the evidence.** On the v1 member, click **View source record #1**.
   - The original learner question and its context are shown.
   - The extraction is marked *Historical*, naming the current one.
   - The interpretation this extraction used is analysis v1, with a note that a
     newer analysis (v2) exists.
5. **Return.** Click **← Back to concept #1**, then **← Back to results for
   “subjonctif”**. The query and results are unchanged, and focus is back on the
   Concept you opened.
6. **Search the wording.** Search `fasse`.
   - Two Concepts match only through **member unit wording**: "not in the
     concept identity. A CURRENT SAME member matched; membership is not
     support."
   - Search follows CURRENT SAME membership, not support. Here both matching
     members come from record #1's historical extraction v1.
   - Open **subjonctif de faire**: it is *Orphaned*, has no current support, and
     its member is shown with the reason. It stays inspectable.
   - A unit that was reassigned away no longer matches under its former
     Concept (step 7's reassigned unit matches only concept #6).
7. **History is never current.**
   - Search `être` and open **passé composé avec être**. *Historical evidence*
     shows a unit that "now belongs to concept #6". Click the link to open it.
   - Search `manques` and open **tu me manques**. The history shows a unit that
     is "now marked INVALID".
8. **Corrected interpretation.** Search `bien que` and open the Concept.
   - One member is listed as not providing support because its admission is
     suppressed.
   - View the source of record #2: the interpretation is **corrected** by
     feedback, showing the corrected and original explanation.

Nothing in this walkthrough writes data or calls a provider. Open the browser's
network panel to confirm that only GET requests are sent.

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
