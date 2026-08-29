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
