# Roster-continuity Phase-1 ablation

Generated 2026-08-09T23:20 UTC by `scripts/ablate_roster.py` (protocol and decision rule pre-registered in ASSUMPTIONS §66 before the run).

- Matches: 6796; standard rows 13337, low-history rows 2789
- Arm OFF: selected lightgbm(best_iter=106) + isotonic (candidates {'logistic_regression(C=0.03)': 0.65981, 'lightgbm(best_iter=106)': 0.6592})
- Arm ON:  selected lightgbm(best_iter=103) + isotonic (candidates {'logistic_regression(C=0.03)': 0.65621, 'lightgbm(best_iter=103)': 0.65488}); roster col nonzero {'roster_ext_maps_diff': 0.871, 'roster_coplay_diff': 0.936}

## Validation (selection window)

| slice | arm | n | log loss | brier | acc |
|---|---|---|---|---|---|
| val | off | 2078 | 0.6504 | 0.2297 | 0.6155 |
| val | on | 2078 | 0.6447 | 0.2272 | 0.6213 |
| val_lowh | off | 288 | 0.6658 | 0.2362 | 0.6285 |
| val_lowh | on | 288 | 0.6413 | 0.224 | 0.6701 |
| test | off | 2118 | 0.6716 | 0.2379 | 0.5996 |
| test | on | 2118 | 0.6619 | 0.2334 | 0.6029 |
| test_lowh | off | 145 | 0.6901 | 0.2485 | 0.5724 |
| test_lowh | on | 145 | 0.6283 | 0.2194 | 0.6828 |

## Validation by tier (map grain)

| tier | off LL (n) | on LL (n) |
|---|---|---|
| game_changers | 0.602 (237) | 0.6005 (237) |
| other | 0.6838 (48) | 0.6919 (48) |
| tier1 | 0.6648 (438) | 0.6685 (438) |
| tier2 | 0.6531 (1355) | 0.6431 (1355) |

## Decision (rule fixed in §66 before the run)

- Primary (low-history val LL improves): MET (off 0.6658 vs on 0.6413)
- Guard (overall val LL not worse by >0.001): MET (off 0.6504 vs on 0.6447)
- Verdict: **SHIP default ON**

Test rows above are a disclosed second read of the same window results-2yr used; validation decided, test is the record. Runtime 182s.