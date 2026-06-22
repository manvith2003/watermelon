#!/usr/bin/env python3
"""
Autonomous Platform Intelligence Agent — GitHub Edition
Watermelon Software Recruitment Assignment

Usage:
  python main.py run "create a bug report for the login timeout issue" --repo owner/repo
  python main.py run "find all open unassigned issues and label them as triage"
  python main.py memory
  python main.py metrics
"""
import json
import os
import sys
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.syntax import Syntax
from rich.tree import Tree

console = Console()


def run_instruction(instruction: str, repo: str | None, verbose: bool):
    from agent.core import Agent

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        console.print("[red]Error: GITHUB_TOKEN not set in .env[/red]")
        sys.exit(1)

    default_repo = repo or os.environ.get("DEFAULT_REPO")
    agent = Agent(github_token=token, default_repo=default_repo)

    console.print()
    console.print(Panel(
        f"[bold cyan]Instruction:[/bold cyan] {instruction}" +
        (f"\n[dim]Repo: {default_repo}[/dim]" if default_repo else ""),
        title="[bold]Autonomous GitHub Agent[/bold]",
        border_style="cyan",
    ))

    with console.status("[bold yellow]Planning...[/bold yellow]"):
        start = time.time()
        report = agent.run(instruction, repo=repo)
        elapsed = time.time() - start

    _render_report(report, verbose)


def _render_report(report: dict, verbose: bool):
    overall = report["overall_success"]
    status_color = "green" if overall else "red"
    status_icon = "✓" if overall else "✗"

    console.print()
    console.print(Panel(
        f"[{status_color}]{status_icon} {report['plan_summary']}[/{status_color}]\n"
        f"[dim]Steps: {report['steps_succeeded']} succeeded, {report['steps_failed']} failed | "
        f"API calls: {report['total_api_calls']} | "
        f"Time: {report['total_duration_ms']}ms | "
        f"Memory used: {'yes' if report.get('memory_was_used') else 'no'}[/dim]",
        title="[bold]Execution Report[/bold]",
        border_style=status_color,
    ))

    # Steps table
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold dim")
    table.add_column("#", width=3)
    table.add_column("Tool", style="cyan")
    table.add_column("Description")
    table.add_column("Status", width=8)
    table.add_column("API calls", width=9, justify="right")
    table.add_column("ms", width=6, justify="right")
    if verbose:
        table.add_column("Memory note", style="dim")

    for step in report["steps"]:
        status = step["status"]
        status_color = {"success": "green", "failed": "red", "skipped": "yellow"}.get(status, "white")
        row = [
            str(step["id"]),
            step["tool"],
            step["description"][:60],
            f"[{status_color}]{status}[/{status_color}]",
            str(step.get("api_calls", 0)),
            str(step.get("duration_ms", 0)),
        ]
        if verbose:
            row.append(step.get("memory_note") or "")
        table.add_row(*row)

    console.print(table)

    # Failed step details
    failed = [s for s in report["steps"] if s["status"] == "failed"]
    if failed:
        console.print()
        console.print("[bold red]Failed Steps:[/bold red]")
        for s in failed:
            console.print(f"  [red]• {s['tool']}:[/red] {s.get('error', 'unknown error')}")
            if s.get("decision"):
                console.print(f"    [dim]Agent decided: {s['decision']}[/dim]")

    # Capability synthesis
    if report.get("capability_gaps_resolved"):
        console.print()
        console.print("[bold yellow]⚡ Capability Synthesis[/bold yellow]")
        for gap in report["capability_gaps_resolved"]:
            console.print(f"  [yellow]• Synthesized new tool: [bold]{gap['tool']}[/bold][/yellow]")
            console.print(f"    [dim]{gap['description']}[/dim]")
            console.print(f"    [green]→ Registered in capability memory for future reuse[/green]")

    # Memory delta
    delta = report.get("memory_delta", {})
    if delta:
        console.print()
        console.print("[bold blue]Memory Delta[/bold blue]")
        console.print(f"  [dim]{delta.get('summary', '')}[/dim]")

    # Self-learning signal
    signal = report.get("improvement_signal", {})
    if signal and signal.get("improvement") is not None or signal.get("run_count", 1) > 1:
        console.print()
        console.print(Panel(
            f"[bold green]{signal.get('message', '')}[/bold green]",
            title="[bold]📈 Learning Signal[/bold]",
            border_style="green",
        ))

    # Verbose: show full results
    if verbose:
        console.print()
        console.print("[dim]Full step results:[/dim]")
        for step in report["steps"]:
            if step.get("result"):
                console.print(Syntax(
                    json.dumps(step["result"], indent=2, default=str)[:500],
                    "json", theme="monokai", line_numbers=False
                ))


def show_memory(verbose: bool):
    from agent.core import Agent
    from memory.db import init_db
    from tools.registry import initialize_registry
    init_db()
    initialize_registry()

    agent = Agent(github_token=os.environ.get("GITHUB_TOKEN", ""))
    state = agent.show_memory_state()

    console.print()
    console.print(Panel("[bold]Memory State[/bold]", border_style="blue"))

    # Capabilities
    cap_stats = state["capabilities"]
    console.print(f"\n[bold cyan]Capabilities[/bold cyan]")
    console.print(f"  Base tools:         {cap_stats['base_capabilities']}")
    console.print(f"  Synthesized tools:  [yellow]{cap_stats['synthesized_capabilities']}[/yellow]")
    console.print(f"  Known constraints:  {cap_stats['known_constraints']}")

    if cap_stats["most_used"]:
        console.print(f"\n  Most used:")
        for cap in cap_stats["most_used"]:
            console.print(f"    • {cap['name']}: {cap['success_count']} calls, avg {cap['avg_time_ms']:.0f}ms")

    # Learning metrics
    metrics = state["learning_metrics"]
    if metrics:
        console.print(f"\n[bold cyan]Learning Metrics (by task type)[/bold cyan]")
        table = Table(box=box.SIMPLE, header_style="bold dim")
        table.add_column("Task type")
        table.add_column("Runs", justify="right")
        table.add_column("Run 1 API calls", justify="right")
        table.add_column("Latest API calls", justify="right")
        table.add_column("Saved", justify="right")
        table.add_column("Success rate", justify="right")

        for key, m in metrics.items():
            saved = m["api_calls_saved"]
            saved_str = f"[green]-{saved}[/green]" if saved > 0 else f"[red]+{abs(saved)}[/red]" if saved < 0 else "0"
            table.add_row(
                key[:40],
                str(m["runs"]),
                str(m["first_run_api_calls"]),
                str(m["latest_run_api_calls"]),
                saved_str,
                f"{m['success_rate']:.0%}",
            )
        console.print(table)
    else:
        console.print("\n  [dim]No learning data yet — run some instructions first.[/dim]")


def show_metrics():
    from memory.db import init_db
    from memory.execution_memory import get_learning_metrics
    init_db()
    metrics = get_learning_metrics()
    if metrics:
        console.print_json(json.dumps(metrics, indent=2))
    else:
        console.print("[dim]No metrics yet.[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous GitHub Platform Intelligence Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py run "create a bug report for login timeout" --repo owner/repo
  python main.py run "find all open unassigned issues, label them triage, and post a summary comment on each"
  python main.py run "bulk close all issues labeled 'wontfix' with a closing comment"
  python main.py memory
  python main.py metrics
        """,
    )

    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run a natural language instruction")
    run_p.add_argument("instruction", help="What to do on GitHub")
    run_p.add_argument("--repo", "-r", help="Target repo (owner/repo). Overrides DEFAULT_REPO in .env")
    run_p.add_argument("--verbose", "-v", action="store_true", help="Show full step results and memory notes")

    mem_p = sub.add_parser("memory", help="Show current memory state")
    mem_p.add_argument("--verbose", "-v", action="store_true")

    sub.add_parser("metrics", help="Show learning metrics as JSON")

    args = parser.parse_args()

    if args.command == "run":
        run_instruction(args.instruction, args.repo, args.verbose)
    elif args.command == "memory":
        show_memory(getattr(args, "verbose", False))
    elif args.command == "metrics":
        show_metrics()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
