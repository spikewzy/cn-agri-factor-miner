# Inputs, availability, and expression contract

## Discover and snapshot before proposing

Input directory contains `manifest.json`, `predictors.json`, `data_dictionary.json`, `existing_factors.json`, and `human_corrections.json`. `cli init --history ...` also snapshots prior hash-validated experiment/review histories into `research_memory.json`. Empty catalogs/corrections are allowed only when discovery actually found none. Inspect human corrections before drafting new ideas. No mandatory data provider, API, database or subscription is assumed.

The manifest freezes the commodity group and configurable registry, weekly decision/execution timestamps, fit cutoffs, evaluator split/model/horizon policy, discovery audit and model/prompt provenance. Each decision's fitting cutoff must equal its chronological split's training end; execution must be later than decision time. The real registry must carry symbol, exchange, multiplier, tick size, delivery quality/location, effective interval, verification time, primary source, source snapshot hash and calendar source. These fields are human/source-verified attestations, not an online verifier. Verify that every execution falls in an actual tradable session and its correct Chinese trading date before submission; v1 validates chronology/intervals, not exchange calendars themselves.

Store predictor and label data separately. Do not copy any final holdout into the exploratory workspace or a tools-accessible location; the path convention and `input_scope` check do not create an OS sandbox. An independent custodian controls final assessment. No file reader in this skill searches for holdout data.

## Predictor records

| Field | Meaning |
|---|---|
| `field`, `source` | Dictionary key and a specific provider/sample; the input rule selects one source explicitly. |
| `period_start`, `period_end` | ISO dates for observation or forecast target, not publication dates. |
| `published_at`, `available_at` | Timezone-aware ISO timestamps; available >= published. Use `America/New_York` release calendars upstream for DST, retain offset in the exported timestamp, and map to the Chinese session calendar explicitly. |
| `revision` | Nonnegative, source-ordered revision integer within field/source/period/kind; retain every vintage. |
| `kind` | `forecast` or `realization`; future-target forecasts can be issued now. A realization cannot precede the outcome period end. |
| `unit`, `value` | Explicit unit and finite number; no coercion of strings, booleans or NaN into observations. |
| `availability_basis` | `observed`, `reconstructed`, `unknown`, or `synthetic`. Only fully observed lineage is eligible for verified-PIT status. An assumed lag is reconstructed, never observed. |
| `event_id` | Canonical source event identifier. Upstream reviewed canonicalization must identify reposts. |

For `text_derived: true`, additionally retain `source_excerpt`, `source_url`, `extraction_version`, `model_version`, `prompt_hash`, `archived_input_hash`, and `retrospective_llm` (boolean). Preserve the referenced source text in input artifacts. Evidence records classify observation/forecast/opinion/rumor; extracting a number from a rumor does not make it a physical observation. Archive the conversion from an event to physical units, its assumptions and source lineage; otherwise keep it qualitative and block the numeric factor. `deduplicate_events` removes canonical reposts but retains revisions and rejects conflicting extractions. It does not discover that two differently named events are the same event.

Unknown actual publication time must not be filled with an invented timestamp. If a justified lag model is available, document and label reconstructed availability; without one, ingestion returns `BLOCKED_DATA` for missing timestamps. No verified historical-performance claim is possible with unknown/reconstructed timestamps. Retrospective LLM judgments remain separately marked even if source timestamps are genuine; real prospective shadow evidence is required for an uncontaminated information-edge claim.

Each declared input rule provides `source`, `unit`, `kind`, `max_release_age_days`, `max_observation_age_days` and, for forecasts, `target_days`. v1 forecast access requires an exact interval [decision date + 1, decision date + target_days]. Different forecast alignment (monthly marketing-year targets, partially overlapping windows) needs a reviewed extension; do not silently resample or prorate forecasts.

`AsOf.history` selects the highest available revision for each observation/source. `latest` selects the latest eligible observation, then bounds both release age and observation age. Holding a monthly value weekly does not create new releases. Forward use ends at the declared limit. No backfill, centered windows, future fitting, implicit source averaging or unrestricted predictor frame is provided. All computation accesses data through `AsOf` even for lagged and seasonal inputs.

## Expression language

Finite JSON trees only. No `eval`, generated code, arbitrary imports, code strings, operator plugins or unrestricted formula search.

- Leaves: `{"field":"meal_stock"}` (must be declared); `{"const":4}` (finite number).
- Binary: `add`, `sub`, `mul`, `div`, `min`, `max`, each with `args: [left,right]`.
- Unary: `neg`, with one arg.
- `change`: one arg and positive integer `days`; computes current value minus the as-of value at the past date. This is a change, not a forecast surprise.
- `seasonal_anomaly`: one arg plus `anchor`, `min_years >= 2`, `calendar: "calendar_month"`. Subtract the equal-year-weighted mean of eligible same-month values in earlier years. One value per observation period; only vintages available by the supplied fit cutoff can enter. The child expression is evaluated at each historical anchor's availability time. It implements a deterministic training-only seasonal baseline, not future/full-sample z-scoring.

Division by (near) zero yields `BLOCKED_DATA`. Tree depth is capped. Validate each input's unit and **review dimensional consistency of the full expression**, including units represented by constants (for example coverage scales in weeks). v1 does not implement symbolic unit algebra. Check sample/location compatibility separately. New operators, calendar mappings, fitted transformations and unit conversions require review and tests. Freeze units/parameters in the spec.

A surprise would require a forecast and realization for the same variable, target period and units, with correct issue and outcome availability. There is deliberately no generic `surprise` operator that could accidentally treat a forecast revision as one.

## Checked source access, 2026-09-21

These are discovery entry points, not connected data feeds. No real observations were downloaded into the sample.

| Source category | Checked entry point | Actual result / unresolved coverage |
|---|---|---|
| Chinese exchanges | [DCE](https://www.dce.com.cn/dceg/) and [DCE announcement URL](https://www.dce.com.cn/dce/content/2026/ywggytz/18628268.html) | Direct web read returned an internal retrieval error. Official live symbols/contract metadata remain unverified. Sample M/Y are explicitly unverified hints and never used for real execution. Other exchanges require their own verification. |
| MARA / CASDE | [MARA](https://www.moa.gov.cn/) | Homepage accessible; no CASDE series, report vintage archive or publication timestamps ingested/verified. |
| Customs | [China Customs](https://www.customs.gov.cn/) | Direct web read failed; no import series or API access verified. |
| NBS | [National Bureau of Statistics](https://www.stats.gov.cn/) | Homepage accessible; no livestock/crop history or vintage coverage verified. |
| USDA reports | [WASDE official page](https://www.usda.gov/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report) | Official landing page accessible after redirect; no historical records, structured API, forecast-vintage completeness or download pipeline verified. |
| Company disclosures / licensed surveys | Supplied source-specific files, issuer/exchange primary disclosures when relevant | None supplied in this workspace. Weekly same-sample stocks, disappearance, arrival forecast vintages and crush plans remain missing. No subscription presumed. |

Use supplied/licensed data when available and record actual permissions/coverage. Recheck access on each real research run; do not turn this dated access log into a claim that data are currently connected.
