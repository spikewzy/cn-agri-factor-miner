# Supervision, checkpoints, and reproducibility

The CLI records an explicit structured human decision. It does not authenticate a person or supply approval itself: `origin: human` is an attestation supplied by the actual user/operator. Agents must never fabricate it. Local tests use unmistakable `simulated_test` decisions and unit-test human-record fixtures only in temporary synthetic workspaces; these are not real approvals.

## State flow

`PROPOSED → AWAITING_SPEC_REVIEW → SPEC_APPROVED → NOT_EVALUATED → EVALUATED → ACCEPTED_RESEARCH`.

- Shortlisting creates a logic-only Markdown packet. Human specification approval is mandatory before computation.
- REVISE clears approval, requiring an incremented spec with rationale, a new hash, and another explicit approval. Material changes include formula, input source/sample, unit conversion, vintage policy, horizon, normalization, targets and performance-driven parameter changes. Batch-wide horizon/model/data/code changes require a new **linked** batch; preserve previous attempts when assessing the budget and selection uncertainty.
- REQUEST_EVIDENCE pauses work. Append the evidence by a reviewed version revision; v1 conservatively counts that as a specification revision too.
- REJECT preserves all prior records. MERGE records a distinct active shortlisted destination (never a rejected, merged or accepted candidate), preserves the source history and invalidates the surviving candidate's approval pending a merged-spec revision. Neither action frees the shortlist budget.
- Successful export gives NOT_EVALUATED until external results are imported. The acceptance packet can display evaluation after economic review. Acceptance needs another explicit human decision for the current hash/version, observed PIT lineage, non-synthetic data and all required completed/passing development diagnostics. It means further research/shadow testing, never trading authorization.
- Missing fields yield BLOCKED_DATA. Fix data in a new linked input snapshot; never modify frozen snapshots in place. Leakage or data-integrity failures remain non-overridable in that run. Repair the cause in a linked, newly reviewed run and retain failed trials; do not hide failures by resetting a directory.

Use all six required correction fields: **scope, rationale, evidence, reviewer, timestamp and version**. Scope is the exact commodity/group; do not generalize a soybean-specific correction to every agricultural family. An observed failure is evidence; an explanation for it is a conjecture until separately supported. `templates/correction.json` provides an importable correction record. Each decision in the ledger also has those fields.

## Durable local memory and audit

Each run directory holds immutable input snapshots, data/code/spec hashes, full source lineage, LLM/extraction model/prompt provenance, versioned exports/review packets, and `experiments.jsonl`. The JSONL ledger uses OS file locks and a hash chain; writes append and fsync. Every proposed candidate, revision, review, compute attempt, imported evaluation and integrity failure is retained. Rejected/merged versions are never deleted by an API. Hash checks detect ordinary accidental edits; a writer with filesystem access can rewrite files, so this is not cryptographic identity or an adversarial security system.

Future runs **must** inspect relevant run ledgers and use `init --history prior/run ...` to import their complete candidate/version/decision summaries and source hashes, plus actual existing-factor and human-correction files. The helpers do not scan the user's entire computer or automatically import unrelated commodity corrections. Preserve failed runs in backups/version control; don't delete a run because performance was poor.

The six/three/three budget is hard-capped in each run. Cross-batch continuity and explicit human budget expansion are supervisory duties: include predecessor ledger hashes via `--history` and count linked attempts in research review. v1 has no automatic global search-budget database, budget escalation button or autonomous retry service. A fresh directory is not permission for more mining. Stop and request explicit expansion once the authorized total is used.

Input/code changes require a new reviewed linked run. Spec changes require a new version. Run files must remain outside the skill directory. Code hashes cover all helper `.py` files; input hashes cover the frozen snapshots. Request hashes bind the exported panel/spec and all prior experiment records. When a write is interrupted, inspect the intact ledger and immutable files; do not truncate history to recover. This is a local single-researcher workflow, not an adversarial multiwriter service.
