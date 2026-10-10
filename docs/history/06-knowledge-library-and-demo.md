# 6. Knowledge Library and its demo

Covers FLH-034 to FLH-039. FLH-035 to FLH-038 are dated 2026-10-09 and
2026-10-10; the FLH-034 plan is undated but precedes FLH-035 Phase B, which
tested it. Current behaviour:
[ARCHITECTURE §9](../ARCHITECTURE.md#9-knowledge-library) and
[DEMO.md](../DEMO.md).

## The problem

After extraction and Concept Review existed, there was still no simple way to
answer "what have I learned about X, and where did that come from?" The
annotation tools were built for reviewers and researchers, not for reading
back curated knowledge, and there was no short, repeatable way to show the
system to someone else.

## Initial implementation

**FLH-034 (Claude Code; undated plan).** A read-only Knowledge Library:

- three GET endpoints, served by a service that holds only read interfaces;
- deterministic keyword prefix search over Concept identity and current-member
  wording, with documented fields, ordering and limits;
- a Concept page that places every unit in exactly one section: supporting,
  member but not supporting, current relation, or history;
- a source page that resolves the exact analysis and feedback an extraction
  used;
- a synthetic demo fixture seeded only through the public API, with a local stub
  extractor and a scripted browser walkthrough.

No migration, router or dependency was added
([plan](../plans/FLH-034-knowledge-library.md)).

## Independent acceptance and corrections

- **FLH-035, 2026-10-09 (Codex).** Phase A prepared expectations from existing
  contracts before the integration. Phase B ran the merged author demo and found
  five P2 defects ([report](../validation/FLH-035-knowledge-library-acceptance.md)):
  - B1: the plan said historical units were not searched, while search actually
    (and correctly) followed current membership, including members from older
    extractions;
  - B2: the demo server listened on all interfaces despite a loopback claim;
  - B3: duplicate React keys when one unit held two relations to a Concept;
  - B4: `demo.sh stop` signalled any PID in its PID file;
  - B5: setup reported success after a port collision and a failed seed,
    because `tee` masked the exit status.
- **FLH-036, 2026-10-09 (Claude Code).** Fixed all five
  ([plan](../plans/FLH-036-knowledge-demo.md),
  [report](../validation/FLH-036-knowledge-demo.md)):
  - B1: corrected the wording instead of changing the search;
  - B2: added an optional `LISTEN_HOST` bind setting, leaving the default
    unchanged, and bound the demo to `127.0.0.1`;
  - B3: keyed relation rows by link ID;
  - B4 and B5: added process ownership by PID, start time and command line,
    port refusal before any launch, and readiness that counts only the started
    child's listener.

  It recorded that the unchanged FLH-035 harness could not run on macOS and
  that some of its probes asserted the defects themselves.
- **FLH-037, 2026-10-10 (Codex).** Updated the acceptance harness to assert
  fixed behaviour and passed 84 probe groups on Linux with no defects, including
  independent `/proc` identity and listener checks. Browser interaction and the
  human presentation were **NOT RUN** there
  ([report](../validation/FLH-037-knowledge-demo-final.md)).
- **FLH-038, 2026-10-10 (Claude Code).** The owner completed all six manual
  demo steps, but found the French grammar titles and explanations hard to
  follow. The fixture and the page copy became English-first. French examples
  and grammar terms were kept, membership versus support was explained as
  "filed" versus "supporting", and no behaviour, API or search rule changed.
  English titles were chosen so that every fixture search expectation in the
  FLH-035 harness still holds (checked by replaying its searches, not by running
  the harness) ([plan](../plans/FLH-038-english-demo-experience.md),
  [report](../validation/FLH-038-english-demo-experience.md)).
- **FLH-039 (this documentation consolidation).** No behaviour change; it moved
  the canonical Library description into ARCHITECTURE §9.

## Evidence summary

| Claim | Evidence | Kind |
| --- | --- | --- |
| Library contract (search, sections, source, read-only) | FLH-035 Phase B, FLH-037 | Independently verified (HTTP, Linux) |
| Demo safety (binding, process ownership, failures) | FLH-036 (macOS), FLH-037 (Linux) | Author-verified and independently verified |
| Browser walkthrough, DEV and production | FLH-036, FLH-038 (headless Chrome, macOS) | Author-verified |
| Human presentation | Owner feedback recorded in FLH-038 | Human acceptance of the steps; timing not measured |

## Remaining limits

Search is prefix keyword matching without an index; there is no URL state;
DISTINCT pairs are not shown; and the FLH-034 plan's label wording predates
FLH-038. See [ARCHITECTURE §9.1](../ARCHITECTURE.md#91-search-contract-and-limitations).
