# Speaking Lab 2: offline candidate review (items 101–110, 2026-11-19)

The review helps the owner decide whether to promote a transcription model. It
never promotes one, and the serving default is unchanged. Usage:
`tools/speaking/README.md` § Candidate review, and § Reproduce with packaged code.
Every number below comes from a command run in this batch. The raw outputs are in
the owner's sealed handoffs `lab-107` and `lab-110`, outside Git.

## Status

| Items | State | Where |
|---|---|---|
| 101 baseline check | done: the worktree matched the lab-100 snapshot before editing | `lab-107` |
| 102–107 candidate review, standing, counts, measures, outcomes, thresholds | implemented and tested | `flh_speaking/candidate_review.py`, `lab.py` |
| 108 packaged-code reproduction | run | `scripts/lab_experiment.py reproduce` |
| 109 review of the base-vs-small experiment and its walkthrough | run | `lab candidate-review`, `lab candidate-review-walkthrough` |
| 110 strict suite, clean demo, handoff | run | below |

## 108: the smallest comparison with packaged code

1. **Rebuild.** `docker build --build-arg TORCH_INDEX=cpu -t flh-speaking:cpu-lab2-20261119 .` took 15 s.
   - The dependency layer came from cache: the lock bytes are unchanged, and the run checks that the image's lock hash equals the tree's.
   - The code layer was rebuilt.
2. **Code check.** `reproduce` compared the 23 files of the image's `/opt/program/flh_speaking` with this tree's.
   - No differences, and nothing was mounted from the tree.
   - Against the older image `cpu-lab20261119`, the same step refused with exit 1 and named the 5 files that differ.
3. **Smallest slice.** Speaker 2085, 5 clean clips: the speaker with the least audio.
   - whisper-base (19.4 s) and whisper-small (41.3 s) both ran with no network, 2 CPUs and 2 GB.
   - Every text and status equals the first run: 5/5 for each model.
4. **Comparison.** The paired comparison equals the one built from the first run's outputs for the same IDs, with measured resources excluded.
   - WER: base 0.2177, small 0.0996.
   - One speaker gives no interval.
5. **Review inside the image.** `insufficient_support`, exit 4 (5 clips < 30, 1 speaker < 30).
   - It is byte-identical to the rendering by this tree's code.

## 109: review of the base-vs-small experiment and why 8 speakers are not enough

**Review.** It was rendered inside the rebuilt image from the stored outputs of
`lab-exp-3e998448c4e6ea64`, with the experiment result and data manifest bound.
- Outcome: `insufficient_support`, exit 4.
- The JSON and text are byte-identical to the lab-107 rendering.

**Walkthrough.** `lab candidate-review-walkthrough --review REVIEW.json --data-manifest DATA_V1/manifest.jsonl`.
1. **Clips vs speakers.** 40 paired clips (pass, ≥ 30) come from 8 speakers (fail, < 30). Clips of one speaker are not independent, so 22 more distinct speakers are needed.
2. **Every speaker.** whisper-small makes fewer errors for 8 of 8 speakers. The per-speaker difference runs from −0.0610 (speaker 296) to −0.1719 (speaker 4482).
   - All 8 pointing one way has probability 0.0078 under no difference (two-sided sign test).
   - So the direction for these speakers is unlikely to be chance. That says nothing yet about other speakers.
3. **Stability.**
   - The speaker-bootstrap interval is [−0.1338, −0.0952]. Five consecutive seeds move an end by at most 0.0014, so the random draw is not the weakness.
   - 8 speakers allow 6,435 distinct resamples, against 5.9e16 for 30.
   - Leaving one speaker out moves the difference between −0.1196 and −0.1055.
   - Treating the 40 clips as independent gives [−0.1369, −0.0897]. That is wider here, but it answers the wrong question.
4. **Supply.** The frozen data offers dev 4, ood 1, test 8 and train 24 speakers (37 overall), and every split is below 30.
   - More speakers must come from new data. They must not come from splitting one speaker's clips.
   - Thirty readers of audiobooks would still say little about learners.
5. **Other checks.** All 6 quality and resource checks pass.
   - If the same values came with enough support, the outcome would be `ready_for_owner_review`. That is not a forecast, and the limit is not lowered to fit the data.
6. **Decision.** The comparison stays an observation. Promotion is not performed, and the serving default is unchanged.

The synthetic `insufficient` scenario has its own walkthrough, checked byte for
byte by `candidate-review-demo --check`.

## 110: validation (this run)

| Command | Outcome |
|---|---|
| In `flh-speaking:cpu-lab2-20261119`, with `--network none --cpus 2 --memory 1g` and the tokenizer fixture: `run_tests.py --require-deps --expect-offline` | 118 run, 0 skipped, 0 failures, network reachable [], 19.4 s, peak 537 MiB, exit 0 |
| The same with `-X dev` | 118 run, 0 skipped, exit 0; 2 ResourceWarnings in unchanged baseline files (finding below) |
| Host: `python3 -B -X dev scripts/run_tests.py` | 118 run, 28 skipped (numpy, av, torch not on the host), exit 0, 0 ResourceWarnings |
| `lab candidate-review-demo --out NEW --check`, in a new directory | exit 0, 7 files |
| `lab demo --check` | exit 0 |
| `lab privacy-check` over the evidence and handoff | 0 findings |

**Finding (not fixed: outside this slice's files).** The unclosed files are at
`flh_speaking/prepare.py:380`, where the hash of the base manifest is read without
`with`, and `tests/test_robustness.py:111`, where the output manifest is read
without `with`. Both run only where numpy and av are installed. Proposed fix:
read each with a `with open(...)` block. Test outcomes are unaffected.

## Owner decisions

- **Default limits.** `max_interval_upper` 0.0 is inclusive, while A1 of `flh_speaking_acceptance_v1` is strict. `min_paired_samples` 30 and `max_peak_rss_mb` 2048 are proposals.
- **Where 22 more speakers come from.** The frozen test split has 8, so new public data is needed: a speaker-labelled French read-speech set, or learner recordings collected with consent.
- **Image tag.** Image `flh-speaking:cpu-lab2-20261119` is local only. Whether to keep it or rebuild from the committed tree is the owner's choice.
