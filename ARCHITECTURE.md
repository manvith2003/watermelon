# Architecture

## 1. What does your memory system store, and why did you structure it that way?

Memory is a SQLite database (`~/.github_agent/memory.db`) with four tables, split into two distinct layers:

**Execution Memory** (`executions` + `step_patterns` tables)

Each completed execution stores: the original instruction, the full step decomposition, per-step results (success/failure + error), total API call count, wall-clock time, and a `learnings` JSON blob — structured observations extracted from the run (e.g., "validation error on `create_issue`: milestone field must be an integer", "successful tool sequence: `get_repo_info → list_issues → add_issue_comment`").

The `step_patterns` table normalises instructions into a signature (8 key words, stop-words removed) and tracks the optimal step sequence for each type: how many API calls the best run used, success/failure counts, and the exact step list. This is what the planner queries before decomposing — if a known-good pattern exists, it reuses it rather than reasoning from scratch.

**Why this structure:** A vector store of past prompts would only let the agent recognise *similar* instructions. The structured schema lets it extract *actionable* knowledge — specific step orderings, discovered constraints, API call counts — and use that to make different, measurably better decisions.

**Capability Memory** (`capabilities` + `runtime_constraints` tables)

Stores every tool (base and synthesized) with: its Python source, success/failure counts, average execution time, last used timestamp, and a JSON array of runtime-discovered constraints. The `runtime_constraints` table separately tracks field validation rules, rate limits, and pagination limits discovered during real API calls.

Both are persistent across sessions. The agent never forgets a synthesized tool or a discovered constraint.

---

## 2. How does capability synthesis work in your implementation?

When the executor encounters a step whose `tool` name doesn't exist in the registry, it calls `synthesizer.synthesize_capability()`. The flow:

1. **Reason** — the LLM is given the tool name, a description of what it needs to do, and all known runtime constraints from memory. It generates a Python function that calls GitHub's REST API using the shared `GitHubClient`.

2. **Compile** — the generated code is `exec()`-ed in a controlled namespace containing only `ToolResult` and `client`. If it fails to compile or if the function isn't defined, this counts as a failed attempt.

3. **Test** — the function is called with inferred minimal parameters (e.g., the authenticated user's own repo). If it raises or returns `success=False`, the LLM is shown the error and traceback and asked to fix it. Up to 3 attempts total.

4. **Register** — on success, the function source is written to `capabilities` (is_synthesized=1) and loaded into the in-memory tool registry. On the next invocation — even in a different session — it loads from the DB without re-synthesizing.

If all attempts fail, the executor records what was tried and why, and the step is marked `failed` with full detail. No silent failures.

Example novel instructions that trigger synthesis (not covered by the 17 base tools):
- `bulk_close_issues` — closes multiple issues in one LLM-generated loop
- `get_issue_velocity` — computes open/closed ratio over a time window
- `find_stale_issues` — finds issues with no activity in N days

---

## 3. What is your learning signal, and what does the agent do differently on run N vs run 1?

**Primary signal: API calls per task type, measured across runs.**

The `step_patterns` table tracks `avg_api_calls` for each normalised instruction type. The `learning/feedback.py` module computes a `improvement_signal` dict after every run showing concrete before/after numbers.

**Mechanism:**

On run 1: the planner has no memory context. It decomposes from scratch. For "find all open unassigned issues and create a triage comment on each", it might call `get_repo_info` first (1 API call), then `list_issues` with state=open (1), then `list_repo_collaborators` to verify "unassigned" (1), then a loop of `add_issue_comment` (N). Total: N+3.

On run 2+: the planner receives the `optimal_step_pattern` in its context — the exact step sequence that worked in the fewest API calls, flagged explicitly: *"Known optimal pattern: skip get_repo_info, skip list_repo_collaborators — list_issues with assignee=none directly."* The planner adopts this, saving 2 API calls regardless of N.

**Secondary signals:**
- **Failure rate** drops as runtime constraints are learned. After the first run discovers "GitHub returns max 100 items per page", every subsequent plan respects that limit rather than failing mid-execution.
- **Synthesis reuse rate**: once a tool is synthesized (e.g., `bulk_close_issues`), it's available immediately on every subsequent run. Re-synthesis never happens for the same tool name.
- **Constraint-aware planning**: the planner receives all known runtime constraints in its system prompt; plans that previously hit validation errors are automatically corrected.

**What the demo shows:**

The `python main.py metrics` command prints a table: task type | run 1 API calls | latest run API calls | saved | success rate. Live numbers, not assertions.
