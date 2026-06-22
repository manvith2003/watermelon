# Demo

Three instructions of increasing complexity, run live on the walkthrough call.

---

## Instruction 1 — Simple

```
python main.py run "create a bug report for the login timeout issue" --repo owner/repo
```

**What the agent does:**
1. Checks memory for any prior similar executions → none on first run
2. Plans 2 steps: `create_issue` with title, body, and labels=["bug"]
3. Creates the issue via GitHub API
4. Returns execution report: issue URL, API calls used (1), duration

**What to show on the call:**
- The created issue appearing in the GitHub UI
- The structured execution report output
- Run it a second time with a slightly different phrasing ("log a bug for the login session timeout") → show the memory context influencing the plan: planner says "reusing known-good approach from prior execution" in the memory_note column

---

## Instruction 2 — Compound

```
python main.py run "find all open issues assigned to nobody, label them as needs-triage, and post a comment on each asking the team to pick it up" --repo owner/repo
```

**What the agent does:**
1. Checks memory for similar executions → may find related patterns from Demo 1
2. Plans 4 steps:
   - `list_labels` — check if needs-triage label exists
   - `create_label` — create it if missing (or skip if found)
   - `list_issues` — fetch open, unassigned issues (assignee=none)
   - Loop: `update_issue` (add label) + `add_issue_comment` on each
3. Handles partial failure: if one comment fails (e.g., issue was locked), it logs the failure and continues — no silent half-completion
4. Returns full report: N issues updated, M comments posted, failures listed

**What to show on the call:**
- The before/after state in GitHub (issues now have the label + comments)
- If step 2 fails (label already exists), show the agent's failure decision: "skip — label already present, continue"
- Run `python main.py memory` to show memory state has grown: new execution stored, step pattern updated

---

## Instruction 3 — Novel (triggers capability synthesis)

```
python main.py run "generate a weekly issue velocity report: show me how many issues were opened vs closed in the last 7 days, grouped by label" --repo owner/repo
```

**What the agent does:**
1. Decomposes: needs `search_issues` for opened/closed in date range, grouped by label
2. Identifies capability gap: no `get_issue_velocity` tool exists in registry
3. **Synthesizes** at runtime:
   - LLM generates a Python function that calls `/search/issues` with `created:>DATE` and `closed:>DATE` queries, then aggregates by label
   - Compiles, tests against the repo
   - Registers as `get_issue_velocity` in capability memory
4. Executes the synthesized tool
5. Returns a formatted velocity report

**What to show on the call:**
- The synthesis happening live: "⚡ Capability Synthesis — synthesized new tool: get_issue_velocity"
- Run `python main.py memory` → synthesized_capabilities count increases from 0 to 1
- Run the same instruction again → synthesis does NOT happen again (tool reused from memory)
- Run `python main.py metrics` → show the learning signal table with real API call numbers

---

## Before/After Numbers (for the learning signal demonstration)

Run Instruction 1 five times with slight rephrasing variations, then show:

```
python main.py metrics
```

Expected output:
```
Task type               | Run 1 API calls | Latest API calls | Saved
create bug report issue |       3         |       1          |  -2
```

The improvement: on run 1 the planner also called `get_repo_info` to verify the repo exists (defensive planning). By run 3, memory shows that step always succeeds and is unnecessary for simple issue creation — the planner drops it, saving 2 API calls per similar run.
