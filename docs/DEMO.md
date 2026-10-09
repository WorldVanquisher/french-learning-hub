# Knowledge Library demo (two minutes)

This demo shows the Knowledge Library (FLH-034) on a synthetic, isolated
database. It needs no paid provider, secret, personal database or external
service:

- analysis uses the local rule-based analyzer;
- extraction goes to a local stub (`scripts/demo/flh034/stub_extractor.py`);
- all data is written through the normal HTTP API by
  `scripts/demo/flh034/seed.py`.

## Setup

Requirements: Go, Python 3, Node.js/npm and `curl`. Commands run from the
repository root.

```sh
npm --prefix web ci && npm --prefix web run build     # production workbench build
WORK=$(mktemp -d)/flh034-demo                         # new, isolated directory
sh scripts/demo/flh034/demo.sh setup "$WORK" "$PWD/web/dist"
```

Open <http://127.0.0.1:18934/>. The ports are `DEMO_PORT` (18934) and
`STUB_PORT` (18933).

`setup` refuses to run unless `WORK` is a **new or empty absolute directory
outside the repository**:

- it never reuses or resets a database;
- it cannot touch `data/`;
- `seed.py` also refuses a non-loopback backend, or one that already holds
  entries or Concepts.

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
   - Each result says where it matched (target, identity features).
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
   - Two Concepts match only through current unit wording ("not in the concept
     identity").
   - Open **subjonctif de faire**: it is *Orphaned*, has no current support, and
     its member is shown with the reason. It stays inspectable.
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
contains a `.flh034-demo` marker).

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
