# Thin external evaluator protocol

This skill implements deterministic predictor computation and local diagnostics. It does not contain an evaluator/backtester or compute IC, returns, Sharpe ratios, portfolios or trades.

`compute` writes an immutable version directory with:

- `specification.json`: approved current specification.
- `factor-panel.json`: decision/execution timestamps, explicit trading-date mapping, fitting cutoff, factor version/hash, value and source/vintage lineage.
- `diagnostics.json`: coverage, sign counts, range, freshness checks, input units, unique observation periods, available calendar years and PIT eligibility. Crop-year mapping and data-fitted outlier assessment remain explicit external/manual requirements.
- `evaluation-request.json`: full panel/specification, hashed data/code/model/prompt provenance, frozen model/splits/horizon/overlap/execution policies, existing-factor catalog and all prior attempt events. `request_hash` binds the complete request.

Until a separately produced matching response is imported, the result is **NOT_EVALUATED**. Never fill unavailable diagnostics with guessed performance. A small sample may stay `INSUFFICIENT_DATA` indefinitely.

## Fixed batch contract

Chronological training/development/walk-forward test windows must be predeclared, with nonoverlapping test segments and training earlier than each test. Each decision explicitly names its split's training cutoff. The sample has one development split to keep it small; real work can configure multiple walk-forward windows. Freeze the baseline model, regularization, commodity group, primary two-week horizon and execution rules before testing. Don't jointly tune factor/model/horizon/fill rules for Sharpe.

All fitting, seasonal normalization, imputation if a future reviewed method permits it, winsorization, standardization and learned parameters occur **inside each training split**. Recompute panels for the corresponding training cutoff. Admit a training label only if both `outcome_end` and `observable_at` are <= the training cutoff; use `pit.observable_labels` only in evaluator-side code. Purge split-crossing labels and account for overlapping weekly 14-day horizons using a declared embargo/block bootstrap or appropriate HAC procedure; disclose block/lag choices and sensitivity.

Use externally controlled **real-contract-aware** return labels. The evaluator verifies expiry/delivery exclusions, roll selection, roll timing, actual tradability, holidays and night-session trading dates. Fill strictly after signal availability; no same-bar closing fills. Do not construct returns from spliced continuous prices or count contracts of one commodity as independent economic observations. Any performance claim requires documented rolls, costs and execution assumptions.

## Requested diagnostics

Every diagnostic has `status: PASS | FAIL | INSUFFICIENT_DATA` and source-backed `evidence`. A status is an evaluator attestation, not proof independently verified by this adapter.

1. Coverage, missing/stale rates, units, outliers, sign behavior and available **crop** years.
2. Per-commodity time-series IC and Rank IC with uncertainty and effective sample size. v1 disables cross-sectional IC. A future expansion must explicitly justify comparable sufficiently numerous commodities.
3. Crop-year/regime stability and small predeclared substantive parameter perturbations. Count tested variants in the three-specification budget. Address serial dependence and short samples.
4. Incremental OOS contribution versus the fixed baseline and existing factors, with factor-family ablation using the same model and splits.
5. Redundancy in formula structure, economic mechanism and observed exposures. Low pairwise correlation alone does not establish independence; family overlap alone does not prove uselessness.
6. Selection uncertainty incorporating **all** attempted/rejected/revised candidates. An ordinary p-value after repeated search is insufficient. Report attempted count and the uncertainty of the selection process; do not cherry-pick trials.
7. Where measurable, intermediate physical prediction (for example subsequent feasible/actual crushing) alongside the eventual return association. Distinguish mechanism failure from a noisy return test.

## Response and final holdout

Use `templates/evaluator-response.json`; the template deliberately has no fake results. Required checks are `point_in_time`, `observable_labels`, `training_only_fits`, `real_contract_labels` and `overlap_handled`. Missing/false checks or a changed request/spec/panel produce an integrity failure, not approval. Invalid external attestations cannot be rescued by a human override. Insufficient diagnostics prevent acceptance but preserve the response for research.

Only `assessment_scope: development_only` is importable. Final holdout data/results stay with an independent custodian; frozen candidate specifications/requests can be exported for that custodian's final assessment without exposing the final holdout to the exploratory agent. Restrict actual filesystem/tool access externally; JSON scope labels are not access control. Pre-register finalists, record selection uncertainty, and refrain from iterative redesign using final results.

Timestamp-correct historical documents do not erase modern LLM outcome knowledge. Separate retrospective extraction/reasoning from live availability, archive input/model/prompt hashes and require prospective shadow validation before claiming an uncontaminated live-information edge.
