"""
Streamlit Web UI — Autonomous GitHub Platform Intelligence Agent
Run with: streamlit run app.py
"""
import os
import sys
import time
import json
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GitHub Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-title { font-size: 2rem; font-weight: 700; margin-bottom: 0; }
    .sub-title  { color: #666; margin-top: 0; margin-bottom: 2rem; }
    .step-success { background: #d4edda; border-left: 4px solid #28a745; padding: 10px 14px; border-radius: 4px; margin: 6px 0; }
    .step-failed  { background: #f8d7da; border-left: 4px solid #dc3545; padding: 10px 14px; border-radius: 4px; margin: 6px 0; }
    .step-skipped { background: #fff3cd; border-left: 4px solid #ffc107; padding: 10px 14px; border-radius: 4px; margin: 6px 0; }
    .step-running { background: #d1ecf1; border-left: 4px solid #17a2b8; padding: 10px 14px; border-radius: 4px; margin: 6px 0; }
    .metric-box   { background: #f8f9fa; border-radius: 8px; padding: 16px; text-align: center; }
    .metric-num   { font-size: 2rem; font-weight: 700; color: #0366d6; }
    .metric-label { font-size: 0.85rem; color: #666; }
    .synth-badge  { background: #fff3cd; border: 1px solid #ffc107; border-radius: 12px; padding: 2px 10px; font-size: 0.8rem; color: #856404; }
    .memory-note  { font-size: 0.8rem; color: #6c757d; font-style: italic; }
    .learning-box { background: linear-gradient(135deg, #d4edda, #c3e6cb); border-radius: 8px; padding: 16px; border: 1px solid #28a745; }
</style>
""", unsafe_allow_html=True)


# ── Initialise agent (cached) ─────────────────────────────────────────────────
@st.cache_resource
def get_agent():
    from memory.db import init_db
    from tools.registry import initialize_registry
    init_db()
    initialize_registry()
    from agent.core import Agent
    return Agent(
        github_token=os.environ.get("GITHUB_TOKEN", ""),
        default_repo=os.environ.get("DEFAULT_REPO", ""),
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    github_token = st.text_input("GitHub Token", value=os.environ.get("GITHUB_TOKEN", ""), type="password")
    default_repo = st.text_input("Default Repo (owner/repo)", value=os.environ.get("DEFAULT_REPO", ""))

    if github_token:
        os.environ["GITHUB_TOKEN"] = github_token
    if default_repo:
        os.environ["DEFAULT_REPO"] = default_repo

    st.divider()

    st.markdown("## 📋 Quick Demo Instructions")
    demo_instructions = {
        "🐛 Simple: Create bug report": "create a bug report for the login timeout issue",
        "🏷️ Compound: Label all open issues": "find all open issues and add the bug label to each one",
        "📊 Compound: Repo summary + milestone": "get info about the repo and create a milestone called Sprint 1 due next month",
        "⚡ Synthesis: Issue age report": "show me all open issues sorted by age, oldest first with how many days old each is",
        "🔍 Search: Find unassigned issues": "find all open issues that have no assignee and list them",
    }

    selected_demo = st.selectbox("Pick a demo instruction", ["— custom —"] + list(demo_instructions.keys()))

    st.divider()
    st.markdown("## 🧠 Memory Status")

    try:
        from memory.capability_memory import get_capability_stats
        from memory.execution_memory import get_learning_metrics
        from memory.db import init_db
        init_db()
        stats = get_capability_stats()
        col1, col2 = st.columns(2)
        col1.metric("Base Tools", stats["base_capabilities"])
        col2.metric("Synthesized", stats["synthesized_capabilities"])
        st.metric("Known Constraints", stats["known_constraints"])
    except Exception:
        st.info("Memory will load after first run.")


# ── Main area ─────────────────────────────────────────────────────────────────
st.markdown('<p class="main-title">🤖 Autonomous GitHub Agent</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-title">Type a plain English instruction — the agent plans, executes, learns.</p>', unsafe_allow_html=True)

tab_run, tab_memory, tab_metrics = st.tabs(["▶️  Run Agent", "🧠  Memory State", "📈  Learning Metrics"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — RUN
# ══════════════════════════════════════════════════════════════════════════════
with tab_run:
    # Pre-fill from sidebar demo selection
    default_instruction = ""
    if selected_demo and selected_demo != "— custom —":
        default_instruction = demo_instructions[selected_demo]

    col_input, col_repo = st.columns([3, 1])
    with col_input:
        instruction = st.text_input(
            "Instruction",
            value=default_instruction,
            placeholder='e.g. "find all open bugs assigned to nobody and label them triage"',
            label_visibility="collapsed",
        )
    with col_repo:
        repo_override = st.text_input("Repo override", placeholder=default_repo or "owner/repo", label_visibility="collapsed")

    run_btn = st.button("▶️  Run Agent", type="primary", use_container_width=True)

    if run_btn and instruction:
        if not os.environ.get("GITHUB_TOKEN"):
            st.error("❌ Set your GitHub Token in the sidebar first.")
        else:
            agent = get_agent()
            repo = repo_override or default_repo or None

            # Live progress placeholder
            progress_area = st.empty()
            status_area = st.empty()

            with status_area:
                with st.spinner("🤔 Planning steps..."):
                    # Show planning phase
                    progress_area.info("**Step 1/3:** Querying memory for similar past executions...")
                    time.sleep(0.3)
                    progress_area.info("**Step 2/3:** LLM decomposing instruction into executable steps...")
                    time.sleep(0.3)
                    progress_area.info("**Step 3/3:** Executing steps on GitHub...")

            start = time.time()
            try:
                report = agent.run(instruction, repo=repo)
                elapsed = time.time() - start
                progress_area.empty()
                status_area.empty()
            except Exception as e:
                progress_area.empty()
                status_area.empty()
                st.error(f"❌ Agent error: {e}")
                st.stop()

            # ── Overall result banner ──────────────────────────────────────
            if report["overall_success"]:
                st.success(f"✅ **Success** — {report['plan_summary']}")
            else:
                st.warning(f"⚠️ **Partial** — {report['plan_summary']}")

            # ── Stats row ─────────────────────────────────────────────────
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("API Calls", report["total_api_calls"])
            c2.metric("Duration", f"{report['total_duration_ms']}ms")
            c3.metric("Steps OK", f"{report['steps_succeeded']}/{len(report['steps'])}")
            c4.metric("Memory Used", "✅ Yes" if report.get("memory_was_used") else "⬜ No")

            st.divider()

            # ── Steps breakdown ───────────────────────────────────────────
            st.markdown("### 📋 Execution Steps")

            for step in report["steps"]:
                status = step["status"]
                icon = {"success": "✅", "failed": "❌", "skipped": "⏭️"}.get(status, "⚙️")
                css_class = f"step-{status}"

                result_str = ""
                if step.get("result"):
                    r = step["result"]
                    if isinstance(r, dict):
                        # Show key fields nicely
                        key_fields = {k: v for k, v in r.items() if k in ("number", "url", "title", "name", "full_name", "open_issues_count", "id")}
                        result_str = " &nbsp;·&nbsp; ".join(f"<b>{k}</b>: {v}" for k, v in key_fields.items())
                    elif isinstance(r, list):
                        result_str = f"<b>{len(r)} items returned</b>"
                        if r and isinstance(r[0], dict):
                            titles = [f"#{i.get('number','?')} {i.get('title','')}" for i in r[:3]]
                            result_str += ": " + ", ".join(titles)
                            if len(r) > 3:
                                result_str += f" ... +{len(r)-3} more"

                # Strip any HTML tags the LLM may have put in memory_note
                import re as _re
                raw_note = step.get("memory_note", "") or ""
                clean_note = _re.sub(r'<[^>]+>', '', raw_note).strip()

                memory_note_html = ""
                if clean_note:
                    memory_note_html = f'<br><span class="memory-note">🧠 {clean_note}</span>'

                error_html = ""
                if step.get("error"):
                    raw_err = _re.sub(r'<[^>]+>', '', str(step["error"])).strip()
                    error_html = f'<br><span style="color:#dc3545">⚠️ {raw_err[:150]}</span>'
                    if step.get("decision"):
                        clean_dec = _re.sub(r'<[^>]+>', '', str(step.get("decision",""))).strip()
                        error_html += f'<br><span style="color:#856404">Agent decided: {clean_dec}</span>'

                st.markdown(f"""
                <div class="{css_class}">
                    <b>{icon} Step {step['id']} — <code>{step['tool']}</code></b>
                    &nbsp; <span style="color:#666">{step['description']}</span>
                    &nbsp; <span style="color:#999; font-size:0.8rem">({step.get('api_calls',0)} API call{'s' if step.get('api_calls',0)!=1 else ''}, {step.get('duration_ms',0)}ms)</span>
                    {"<br>" + result_str if result_str else ""}
                    {memory_note_html}
                    {error_html}
                </div>
                """, unsafe_allow_html=True)

            # ── Capability synthesis ───────────────────────────────────────
            if report.get("capability_gaps_resolved"):
                st.divider()
                st.markdown("### ⚡ Capability Synthesis")
                for gap in report["capability_gaps_resolved"]:
                    st.success(f"🔧 New tool synthesized at runtime: **`{gap['tool']}`**  \n"
                               f"{gap['description']}  \n"
                               f"✅ Registered in capability memory — will reuse on all future runs")

            # ── Memory delta ──────────────────────────────────────────────
            delta = report.get("memory_delta", {})
            if delta.get("summary"):
                st.divider()
                st.markdown("### 🧠 Memory Updated")
                st.info(delta["summary"])

            # ── Learning signal ───────────────────────────────────────────
            signal = report.get("improvement_signal", {})
            if signal.get("run_count", 1) > 1 and signal.get("message"):
                st.divider()
                st.markdown("### 📈 Learning Signal")
                st.markdown(f"""
                <div class="learning-box">
                    📊 {signal["message"]}
                </div>
                """, unsafe_allow_html=True)
                if signal.get("api_calls_saved", 0) > 0:
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Run 1 API calls", signal["first_run_api_calls"])
                    col2.metric("Latest API calls", signal["latest_run_api_calls"],
                                delta=f"-{signal['api_calls_saved']}", delta_color="inverse")
                    col3.metric("Improvement", f"{signal.get('api_calls_improvement_pct',0)}%")

            # ── Raw JSON toggle ───────────────────────────────────────────
            with st.expander("🔍 View raw execution report (JSON)"):
                st.json({k: v for k, v in report.items() if not k.startswith("_")})


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MEMORY STATE
# ══════════════════════════════════════════════════════════════════════════════
with tab_memory:
    if st.button("🔄 Refresh Memory State"):
        st.rerun()

    try:
        from memory.capability_memory import get_all_capabilities, get_all_constraints
        from memory.db import init_db
        init_db()

        caps = get_all_capabilities()
        constraints = get_all_constraints()

        # Stats
        base = [c for c in caps if not c["is_synthesized"]]
        synth = [c for c in caps if c["is_synthesized"]]

        c1, c2, c3 = st.columns(3)
        c1.metric("Base Tools", len(base))
        c2.metric("Synthesized Tools", len(synth))
        c3.metric("Runtime Constraints", len(constraints))

        st.divider()

        # Capabilities table
        st.markdown("### 🛠️ All Capabilities")
        for cap in caps:
            total_uses = cap["success_count"] + cap["failure_count"]
            success_rate = f"{cap['success_count']/total_uses:.0%}" if total_uses > 0 else "unused"
            badge = '<span class="synth-badge">⚡ SYNTHESIZED</span>' if cap["is_synthesized"] else ""

            with st.expander(f"{'⚡ ' if cap['is_synthesized'] else '🔧 '}`{cap['name']}` — {cap['description'][:60]}"):
                col1, col2, col3 = st.columns(3)
                col1.metric("Success rate", success_rate)
                col2.metric("Total uses", total_uses)
                col3.metric("Avg time", f"{cap['avg_time_ms']:.0f}ms" if total_uses > 0 else "—")

                if cap["constraints"]:
                    st.markdown("**Known constraints:**")
                    for c in cap["constraints"]:
                        st.warning(f"⚠️ [{c['type']}] {c['description']}")

                if cap["is_synthesized"]:
                    st.markdown("**Generated code:**")
                    st.code(cap["implementation"], language="python")

        # Runtime constraints
        if constraints:
            st.divider()
            st.markdown("### ⚠️ Runtime Constraints Discovered")
            for c in constraints:
                st.warning(f"**[{c['tool_name']}]** {c['constraint_type']}: {c['description']}" +
                           (f" *(limit: {c['value']})*" if c["value"] else ""))

    except Exception as e:
        st.info(f"Run an instruction first to populate memory. ({e})")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — LEARNING METRICS
# ══════════════════════════════════════════════════════════════════════════════
with tab_metrics:
    if st.button("🔄 Refresh Metrics"):
        st.rerun()

    try:
        from memory.execution_memory import get_learning_metrics, get_all_learnings
        from memory.db import init_db
        init_db()

        metrics = get_learning_metrics()
        learnings = get_all_learnings()

        if not metrics:
            st.info("📊 Run the same type of instruction at least twice to see improvement metrics.")
        else:
            st.markdown("### 📊 API Call Improvement Over Time")
            st.caption("Shows how the agent learns to use fewer API calls on repeated similar tasks")

            for task_key, m in metrics.items():
                saved = m["api_calls_saved"]
                color = "green" if saved > 0 else "orange" if saved == 0 else "red"
                trend = f"↓ {saved} fewer" if saved > 0 else ("→ same" if saved == 0 else f"↑ {abs(saved)} more")

                with st.expander(f"**{task_key}** — {m['runs']} runs | {trend} API calls"):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Runs", m["runs"])
                    c2.metric("Run 1 API calls", m["first_run_api_calls"])
                    c3.metric("Latest API calls", m["latest_run_api_calls"],
                              delta=f"{-saved}" if saved != 0 else None,
                              delta_color="inverse" if saved > 0 else "normal")
                    c4.metric("Success rate", f"{m['success_rate']:.0%}")

                    if saved > 0:
                        st.success(f"✅ Agent learned to save {saved} API call(s) — "
                                   f"{m['first_run_api_calls']/m['latest_run_api_calls']:.1f}x more efficient")

        st.divider()
        st.markdown("### 🧠 Structured Learnings Extracted")
        if learnings:
            for item in learnings[:10]:
                with st.expander(f"From: *{item['instruction'][:80]}*"):
                    st.json(item["learnings"])
        else:
            st.info("Learnings will appear here after executions complete.")

    except Exception as e:
        st.info(f"Run some instructions first. ({e})")
