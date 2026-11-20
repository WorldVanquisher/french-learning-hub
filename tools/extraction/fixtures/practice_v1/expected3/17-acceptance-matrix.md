| From | Event | Expected | Observed | OK | Rule |
|---|---|---|---|---|---|
| pending | approve | approved | approved | yes | a learner decision |
| pending | reject | rejected | rejected | yes | a learner decision |
| pending | edit | corrected | corrected | yes | the learner's wording replaces the proposal; the proposal is kept |
| pending (supported) | batch approve | approved | approved | yes | only supported items without cue, conflict or paraphrase |
| pending (unsupported) | batch approve | pending | pending | yes | never batched |
| batch applied | the same batch command again | nothing written | nothing written | yes | a repeated batch is a no-op |
| batch shown, then a decision on a non-member | batch approve with the shown ID | accepted | accepted | yes | the members and their hashes are unchanged |
| batch shown, then a decision on a member | batch approve with the shown ID | refused | refused | yes | a batch ID binds exactly the members shown |
| pending (paraphrase) | approve without attestation | refused | refused | yes | a paraphrase is never evidence |
| pending (paraphrase) | approve with --attest-paraphrase | approved | approved | yes | the attestation is recorded as the learner's |
| approved | revision, item unchanged | approved | approved | yes | carried while unchanged |
| rejected | revision, item unchanged | rejected | rejected | yes | the reason stays with revision 1 |
| approved | revision, spacing only | approved | approved | yes | not material: Unicode spaces, apostrophes, NFC |
| approved | revision, material change (same item ID) | needs_review (changed) | needs_review (changed) | yes | a material change is never covered by the old approval |
| approved | revision rewrites the claim statement | pending (new item ID) | pending (new item ID) | yes | a claim's ID hashes its statement: a rewritten claim is a new item, and no approval transfers to it |
| approved | revision removes the quote | needs_review (changed) | needs_review (changed) | yes | practice is withdrawn |
| needs_review (quote removed) | revision restores the quote | needs_review (restored) | needs_review (restored) | yes | no silent reactivation |
| needs_review (restored) | approve | approved | approved | yes | a new learner decision |
| approved | absent from one revision, back unchanged | approved | approved | yes | a decision on an unchanged item is kept |
| approved | revision moves the quote | approved (moved shown) | approved (moved shown) | yes | a moved quote is still located |
| pending conflict pair | batch | both left to the learner | both left to the learner | yes | a conflict is decided one by one |
| conflict, one side rejected | batch | other side batchable | other side batchable | yes | a resolved conflict blocks nothing |
| batch interrupted | retry without repair | refused | refused | yes | a torn write is never read as data |
| batch interrupted, repaired | retry the same batch | each member approved once | each member approved once | yes | the retry writes only what is missing |

24 of 24 transitions as expected.
