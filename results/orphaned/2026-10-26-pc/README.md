# Orphaned time series (desktop PC, 2026-10-26)

These three files reached the repository in commit `5d38c91` ("Add raw research data"). The runs that wrote them were recorded in the desktop PC's local `results/ueic.sqlite`. When that database met the repository's copy in a `git stash pop` conflict, the repository's copy was kept, so **no database record points to these files**. They are kept here rather than deleted.

Forensic comparison against every stored time series (run on 2026-10-26):

| File | Matches | Max relative difference in grid power |
|---|---|---|
| `26efa04e…` | E001, S1_moderate, compute_only, seed 0 | 0 (identical) |
| `d6f64f14…` | E001, S1_moderate, fixed, seed 0 | 0 (identical) |
| `9802c8eb…` | closest: E001, S1_moderate, cooling_only, seed 0 | 1.8% (not identical) |

Two are exact copies of stored runs. The third is unexplained. It was not reproduced by re-running E001 seed-0 cells with default parameters or with the first (rejected) calibration values. All three are 4-hour runs with default-looking supply temperature and flow traces. They add no information to the store, and nothing in `docs/` or `results/` uses them.
