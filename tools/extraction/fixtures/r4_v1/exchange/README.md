# Agent exchange round trip (`flh_agent_context_v1` / `flh_agent_corrections_v1`, R4; synthetic)

| File | What it is |
|---|---|
| `context.json` | the packet for one reviewed exercise (no answer; units, evidence verified against the learner's text; last outcome only) |
| `context.claude-code.md`, `context.codex.md` | the same Markdown body; only the first line names the agent |
| `return-*.json` | what the two local stand-ins (scripted, no model) wrote |
| `preview-*.txt` | the read-only classification: nothing applied |
| `accepted-decisions.json` | the learner accepted one candidate from each: ordinary edit decisions with `via` provenance |
| `context-after.json` | re-export after acceptance: both units `corrected` with the accepted texts |
| `preview-*-against-r2.txt` | the same returns against revision 2: the correction on the changed unit is `outdated` |
| `report.json` | the checks, the provenance fields of both agents and the refused documents with their recovery commands |

Contract: `tools/extraction/LOOP.md` §2. Regenerate with `scripts/r4_exchange.py --write`.
