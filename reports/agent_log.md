# AI Agent Decision Log

Khong can copy full conversation. Ghi cac decision quan trong.

## Decision 1
- Hypothesis:
- Prompt / request to agent:
- Agent proposal:
- Evidence/test:
- Accept / reject / revise:
- Why:

## Decision 2
- Hypothesis:
- Prompt / request to agent:
- Agent proposal:
- Evidence/test:
- Accept / reject / revise:
- Why:

## Decision 3
- Hypothesis: Type drift must be detected explicitly; numeric coercion alone can hide invalid values.
- Prompt / request to agent: Preserve `student_api.validate_orders` and add contract type checks plus severity-aware actions.
- Agent proposal: Add independent type issues for string/integer/number/datetime and map critical/warning/info to block/warn/log.
- Evidence/test: Reviewed `orders_contract.yaml`, `STUDENT_API.md`, and public contract cases. Runtime pytest is unavailable because the environment has no pytest executable.
- Accept / reject / revise: Accept
- Why: Keeps the stable return shape, preserves existing checks, and prevents range validation from masking type errors.

## Decision 4
- Hypothesis: Freshness must be deterministic in tests; using wall-clock time directly would mark the fixed public healthy fixture stale.
- Prompt / request to agent: Implement reliability behavior without causing time-dependent false failures.
- Agent proposal: Defer freshness implementation until an explicit/testable reference-time policy is chosen; do not add a broad `.gitignore` rule that could hide submission reports.
- Evidence/test: Public fixture timestamps are fixed at 2026-08-28 while the lab environment date is 2026-08-29; the contract threshold is 30 minutes.
- Accept / reject / revise: Revise next step
- Why: Freshness remains required, but needs a controlled `as_of` strategy compatible with both public and hidden evaluation.

## Decision 5
- Hypothesis: Revenue can inflate when multiple active customer dimension rows match one order.
- Prompt / request to agent: Write the smallest dbt unit test exposing the duplicate-active-version case, then make the model deterministic.
- Agent proposal: Add a unit test with two active C0001 versions and deduplicate by latest `valid_from` before joining.
- Evidence/test: `fct_daily_revenue.sql` joins all active rows; the expected two orders totaling 170.0 would otherwise become four rows totaling 340.0.
- Accept / reject / revise: Accept
- Why: The test captures transformation correctness, not only schema validity.

## Decision 6
- Hypothesis: Reliability checks should be packaged into repeatable validation flows.
- Prompt / request to agent: Convert the GX one-expectation-at-a-time example into Suite, ValidationDefinition, and Checkpoint.
- Agent proposal: Build one reusable suite and run it through a Checkpoint with summary results.
- Evidence/test: Great Expectations documentation defines Checkpoint as the production validation abstraction and supports actions based on validation results.
- Accept / reject / revise: Accept
- Why: This gives a stable place to add severity-based actions without changing the student API.

## Decision 7
- Hypothesis: The baseline runner should not page on the healthy generated batch solely because the static history has a different weekday volume pattern.
- Prompt / request to agent: Keep weekday context available while avoiding a false alert in the supplied healthy fixture.
- Agent proposal: Use a broad robust trailing history in `run_baseline.py`; let the stable API support same-segment history when a caller has a trustworthy segment.
- Evidence/test: The generated healthy batch has about 600 rows while historical Saturday values are about 235–268; direct same-weekday comparison produced a false anomaly.
- Accept / reject / revise: Accept
- Why: Separates caller data selection from detector capability and preserves seasonality support for valid contexts.

## Decision 8
- Hypothesis: KB freshness and minimum content length belong in the same contract validation layer as orders.
- Prompt / request to agent: Reuse the validator for `kb_contract.yaml` and expose stale KB evidence in the baseline report.
- Agent proposal: Support both `columns` and `fields`, add `min_length`, and pass an explicit UTC reference time from the baseline runner.
- Evidence/test: `stale_kb` changed publish timestamps by three hours; baseline then reported one KB contract failure while healthy reset reported zero.
- Accept / reject / revise: Accept
- Why: It detects the public stale-KB fault without changing the stable orders API.
