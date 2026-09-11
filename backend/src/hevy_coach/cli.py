"""Command line interface: import, inspect, benchmark, and talk to the coach."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from hevy_coach import csv_import
from hevy_coach.analytics import metrics, progression
from hevy_coach.analytics.benchmark import benchmark
from hevy_coach.analytics.standards import LEVELS
from hevy_coach.config import get_settings
from hevy_coach.db import Database

app = typer.Typer(
    add_completion=False,
    help="Hevy training analytics, strength benchmarking, and an AI coach.",
    no_args_is_help=True,
)
console = Console()


def _db() -> Database:
    return Database(get_settings().database_path)


@app.command("import")
def import_csv(
    file: Annotated[
        Path | None,
        typer.Option(help="Import this export instead of the newest one in the folder"),
    ] = None,
    prune: Annotated[
        bool, typer.Option(help="Drop workouts the export no longer contains")
    ] = True,
) -> None:
    """Import a Hevy CSV export (the newest one in the workouts folder)."""
    settings = get_settings()
    db = _db()

    try:
        with console.status("Importing export..."):
            result = csv_import.import_export(settings, db, path=file, prune=prune)
    except csv_import.ExportError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[green]{result.summary()}[/green]")
    for error in result.errors[:10]:
        console.print(f"[yellow]warning:[/yellow] {error}")
    if len(result.errors) > 10:
        console.print(f"[yellow]...and {len(result.errors) - 10} more skipped rows.[/yellow]")
    if result.unmapped:
        names = ", ".join(result.unmapped[:6])
        console.print(
            f"[dim]{len(result.unmapped)} exercises have no muscle mapping ({names}"
            f"{'...' if len(result.unmapped) > 6 else ''}) and count as \"other\" in the "
            "volume breakdown. Add them to data/muscle_map.json.[/dim]"
        )
    console.print(f"Local database now holds {db.workout_count()} workouts.")


@app.command()
def demo(
    weeks: Annotated[int, typer.Option(help="Weeks of history to generate")] = 20,
) -> None:
    """Seed the database with synthetic history (no Hevy account needed)."""
    from hevy_coach.demo import seed

    db = _db()
    if db.workout_count() > 0:
        console.print(
            f"[yellow]Database already holds {db.workout_count()} workouts.[/yellow] "
            "Demo data would be mixed in with them. Point DATABASE_PATH at a "
            "scratch file, or delete the existing database first."
        )
        raise typer.Exit(1)

    count = seed(db, weeks=weeks)
    console.print(f"[green]Seeded {count} synthetic workouts[/green] over {weeks} weeks.")
    console.print("Try: [bold]hevy-coach benchmark[/bold] or [bold]hevy-coach insights[/bold]")


@app.command()
def status() -> None:
    """Show what is in the local database."""
    db = _db()
    settings = get_settings()
    stats = metrics.overview(db)

    table = Table(show_header=False, box=None)
    table.add_row("Workouts", f"{stats.workouts:,}")
    first, last = (stats.first_workout or "-")[:10], (stats.last_workout or "-")[:10]
    table.add_row("First / last", f"{first} -> {last}")
    table.add_row("Working sets", f"{stats.total_sets:,}")
    table.add_row("Total volume", f"{stats.total_volume_kg:,.0f} kg")
    table.add_row("Sessions/week", f"{stats.avg_workouts_per_week}")
    table.add_row("Avg duration", f"{stats.avg_duration_minutes or '-'} min")
    table.add_row("Bodyweight", f"{stats.bodyweight_kg or settings.bodyweight_kg} kg")
    table.add_row("Last import", db.get_meta(csv_import.LAST_IMPORT_KEY) or "never")
    table.add_row("Export file", db.get_meta(csv_import.IMPORTED_FILE_KEY) or "-")
    console.print(Panel(table, title="Training log", expand=False))


@app.command("benchmark")
def benchmark_command(
    days: Annotated[int, typer.Option(help="Window for each lift's best e1RM")] = 365,
    limit: Annotated[int, typer.Option(help="Rows to show")] = 20,
) -> None:
    """Compare your lifts against bodyweight-adjusted strength standards."""
    settings = get_settings()
    report = benchmark(_db(), settings, days=days)

    if not report.entries:
        console.print(
            "[yellow]Nothing to benchmark yet.[/yellow] Run [bold]hevy-coach import[/bold] first."
        )
        raise typer.Exit(0)

    for caveat in report.caveats:
        console.print(f"[yellow]![/yellow] {caveat}\n")

    table = Table(title=f"Strength standards ({report.sex}, {report.bodyweight_kg:g} kg)")
    table.add_column("Exercise")
    table.add_column("e1RM", justify="right")
    table.add_column("Level")
    table.add_column("Score", justify="right")
    table.add_column("To next", justify="right")

    for entry in report.entries[:limit]:
        score = entry.score
        to_next = (
            f"+{score['kg_to_next_level']:g} kg -> {score['next_level']}"
            if score["kg_to_next_level"] is not None
            else "-"
        )
        table.add_row(
            entry.title,
            f"{score['e1rm_kg']:g} kg",
            score["level"],
            f"{score['level_score']:.2f}",
            to_next,
        )

    console.print(table)
    if report.overall_level_score is not None:
        console.print(
            f"Overall: [bold]{report.overall_level}[/bold] "
            f"({report.overall_level_score:.2f} on a 0-4 scale, "
            f"{' < '.join(LEVELS)})"
        )
    if report.unmapped:
        names = ", ".join(item["title"] for item in report.unmapped[:6])
        console.print(
            f"[dim]{len(report.unmapped)} exercises have no load standard ({names}"
            f"{'...' if len(report.unmapped) > 6 else ''}). Bodyweight and timed "
            "movements only have rep standards; anything else can be added to "
            "data/exercise_map.json.[/dim]"
        )


@app.command()
def insights(
    days: Annotated[int, typer.Option(help="Analysis window")] = 180,
) -> None:
    """Show rule-based findings: stalls, regressions, low volume, imbalances."""
    settings = get_settings()
    found = progression.insights(_db(), settings, days=days)
    if not found:
        console.print("[green]No issues found in the current window.[/green]")
        return

    colours = {"warning": "red", "suggestion": "yellow", "info": "cyan"}
    for item in found:
        console.print(
            f"[{colours[item.severity]}]{item.severity.upper():10s}[/] "
            f"[bold]{item.title}[/bold]\n           {item.detail}\n"
        )


@app.command()
def trends(
    days: Annotated[int, typer.Option(help="Analysis window")] = 180,
    limit: Annotated[int, typer.Option(help="Rows to show")] = 20,
) -> None:
    """Per-exercise e1RM trend, newest activity first."""
    settings = get_settings()
    rows = progression.exercise_trends(_db(), settings, days=days)[:limit]
    if not rows:
        console.print("[yellow]Not enough session history to fit trends.[/yellow]")
        return

    marks = {
        "progressing": "[green]^ progressing[/green]",
        "maintaining": "[cyan]= maintaining[/cyan]",
        "stalling": "[yellow]- stalling[/yellow]",
        "regressing": "[red]v regressing[/red]",
    }
    table = Table(title=f"Exercise trends (last {days} days)")
    table.add_column("Exercise")
    table.add_column("Sessions", justify="right")
    table.add_column("e1RM now", justify="right")
    table.add_column("kg/month", justify="right")
    table.add_column("Trend")

    for row in rows:
        table.add_row(
            row.title,
            str(row.sessions),
            f"{row.latest_e1rm_kg:g}",
            f"{row.slope_kg_per_month:+.1f}",
            marks.get(row.trend, row.trend),
        )
    console.print(table)


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="What to ask the coach")],
) -> None:
    """Ask the AI coach a question about your training."""
    from hevy_coach.coach import ask as ask_module
    from hevy_coach.coach import cli_agent

    db = _db()
    if db.workout_count() == 0:
        console.print(
            "[yellow]No workouts imported.[/yellow] Run [bold]hevy-coach import[/bold] first."
        )
        raise typer.Exit(1)

    try:
        with console.status("Thinking..."):
            result = ask_module.answer(db, get_settings(), question)
    except cli_agent.CoachUnavailable as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(Markdown(result["answer"] or "_No answer returned._"))
    if result["tools_used"]:
        console.print(f"\n[dim]tools: {', '.join(dict.fromkeys(result['tools_used']))}[/dim]")
    via = result["backend"] + (" (cached)" if result.get("cached") else "")
    console.print(f"[dim]via: {via}[/dim]")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: Annotated[bool, typer.Option(help="Reload on code changes")] = False,
) -> None:
    """Run the API server for the Nuxt frontend."""
    import uvicorn

    uvicorn.run("hevy_coach.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
