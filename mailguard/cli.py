"""mailguard command-line interface.

Examples:
    mailguard check foo@bar.com
    mailguard bulk leads.csv -o out.csv --smtp --catchall -c 100
    mailguard bulk leads.csv --column Email -o out.csv
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from mailguard import __version__
from mailguard.core import validate_bulk_sync, validate_sync

app = typer.Typer(
    name="mailguard",
    help="Async bulk email validator with layered deliverability scoring.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"mailguard {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-v", callback=_version_callback, is_eager=True
    ),
) -> None:
    """mailguard — layered email validation for GTM marketers."""


@app.command()
def check(
    email: str = typer.Argument(..., help="Email to validate"),
    smtp: bool = typer.Option(False, "--smtp", help="Run SMTP RCPT probe (may be blocked)"),
    catchall: bool = typer.Option(False, "--catchall", help="Detect catch-all domains"),
    json_out: bool = typer.Option(False, "--json", help="Output JSON"),
    timeout: float = typer.Option(10.0, "--timeout", help="Per-call timeout"),
) -> None:
    """Validate a single email address."""
    result = validate_sync(email, check_smtp=smtp, check_catchall=catchall, timeout=timeout)
    if json_out:
        console.print_json(json.dumps(result.to_dict()))
        raise typer.Exit(0 if result.is_valid else 1)

    table = Table(show_header=False, box=None)
    table.add_row("Email", result.email)
    verdict_color = {
        "deliverable": "green",
        "risky": "yellow",
        "undeliverable": "red",
        "unknown": "dim",
    }.get(result.verdict, "white")
    table.add_row("Verdict", f"[{verdict_color}]{result.verdict}[/{verdict_color}]")
    table.add_row("Score", f"{result.score}/100")
    table.add_row("Reason", result.reason)
    table.add_row("Type", result.email_type)
    table.add_row("Syntax", "✓" if result.syntax_ok else "✗")
    table.add_row("MX", f"{'✓' if result.mx_ok else '✗'} {result.mx_host}".strip())
    table.add_row("Disposable", "yes" if result.disposable else "no")
    table.add_row("Role-based", "yes" if result.role_based else "no")
    table.add_row("Free provider", "yes" if result.free_provider else "no")
    if result.catch_all is not None:
        table.add_row("Catch-all", "yes" if result.catch_all else "no")
    if result.smtp_ok is not None:
        table.add_row("SMTP", "accepted" if result.smtp_ok else "rejected")
    if result.typo_suggestion:
        table.add_row("Suggestion", f"[yellow]{result.typo_suggestion}[/yellow]")
    console.print(table)
    raise typer.Exit(0 if result.is_valid else 1)


def _detect_email_column(header: list[str]) -> int:
    """Find the most likely email column by name."""
    candidates = ("email", "e-mail", "mail", "address", "email_address", "emailaddress")
    for i, col in enumerate(header):
        if col.strip().lower() in candidates:
            return i
    return 0


@app.command()
def bulk(
    input_file: Path = typer.Argument(..., exists=True, readable=True, help="Input CSV"),
    output: Path = typer.Option("validation_results.csv", "-o", "--output", help="Output CSV"),
    column: str | None = typer.Option(None, "--column", help="Name of email column"),
    concurrency: int = typer.Option(50, "-c", "--concurrency", help="Concurrent validations"),
    smtp: bool = typer.Option(False, "--smtp", help="Run SMTP probe (slow, may be blocked)"),
    catchall: bool = typer.Option(False, "--catchall", help="Detect catch-all domains"),
    timeout: float = typer.Option(10.0, "--timeout", help="Per-call timeout"),
    no_header: bool = typer.Option(False, "--no-header", help="Input CSV has no header row"),
) -> None:
    """Validate a CSV of email addresses in bulk."""
    with input_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        console.print("[red]Input file is empty.[/red]")
        raise typer.Exit(1)

    if no_header:
        header: list[str] = [f"col_{i}" for i in range(len(rows[0]))]
        data_rows = rows
    else:
        header = rows[0]
        data_rows = rows[1:]

    # Detect email column
    if column is not None:
        try:
            email_idx = header.index(column)
        except ValueError:
            console.print(f"[red]Column '{column}' not found. Available: {header}[/red]")
            raise typer.Exit(1) from None
    else:
        email_idx = _detect_email_column(header)
        console.print(f"[dim]Using email column: {header[email_idx]!r}[/dim]")

    emails = [row[email_idx] for row in data_rows if len(row) > email_idx and row[email_idx].strip()]
    console.print(f"[bold]Validating {len(emails)} emails...[/bold]")

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Validating", total=len(emails))

        def cb(done: int, total: int) -> None:
            progress.update(task, completed=done)

        results = validate_bulk_sync(
            emails,
            concurrency=concurrency,
            check_smtp=smtp,
            check_catchall=catchall,
            timeout=timeout,
            progress_cb=cb,
        )

    # Build result map for alignment
    result_map = {r.email: r for r in results}

    out_header = header + [
        "mg_verdict", "mg_score", "mg_reason", "mg_type",
        "mg_mx_host", "mg_disposable", "mg_role", "mg_free_provider",
        "mg_catch_all", "mg_smtp", "mg_typo_suggestion",
    ]
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not no_header:
            writer.writerow(out_header)
        for row in data_rows:
            if len(row) <= email_idx:
                writer.writerow(row + [""] * 11)
                continue
            email = row[email_idx].strip()
            r = result_map.get(email)
            if r is None:
                writer.writerow(row + [""] * 11)
                continue
            writer.writerow(
                row
                + [
                    r.verdict,
                    r.score,
                    r.reason,
                    r.email_type,
                    r.mx_host,
                    "yes" if r.disposable else "no",
                    "yes" if r.role_based else "no",
                    "yes" if r.free_provider else "no",
                    "" if r.catch_all is None else ("yes" if r.catch_all else "no"),
                    "" if r.smtp_ok is None else ("ok" if r.smtp_ok else "rejected"),
                    r.typo_suggestion or "",
                ]
            )

    # Summary
    deliverable = sum(1 for r in results if r.verdict == "deliverable")
    risky = sum(1 for r in results if r.verdict == "risky")
    undeliverable = sum(1 for r in results if r.verdict == "undeliverable")

    summary = Table(title="Summary", show_header=True)
    summary.add_column("Bucket")
    summary.add_column("Count", justify="right")
    summary.add_column("%", justify="right")
    total = max(len(results), 1)
    summary.add_row("[green]Deliverable[/green]", str(deliverable), f"{deliverable/total:.0%}")
    summary.add_row("[yellow]Risky[/yellow]", str(risky), f"{risky/total:.0%}")
    summary.add_row("[red]Undeliverable[/red]", str(undeliverable), f"{undeliverable/total:.0%}")
    console.print(summary)
    console.print(f"[bold green]→ Saved to {output}[/bold green]")


@app.command(name="update-lists")
def update_lists() -> None:
    """Refresh disposable / free-provider lists from upstream sources."""
    import httpx

    sources = {
        "disposable_domains.txt": (
            "https://raw.githubusercontent.com/disposable-email-domains/"
            "disposable-email-domains/main/disposable_email_blocklist.conf"
        ),
    }
    data_dir = Path(__file__).parent / "data"
    for filename, url in sources.items():
        console.print(f"Fetching {url}...")
        try:
            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            (data_dir / filename).write_text(resp.text, encoding="utf-8")
            console.print(f"[green]✓[/green] {filename} updated ({len(resp.text.splitlines())} entries)")
        except Exception as e:
            console.print(f"[red]✗[/red] {filename}: {e}")


if __name__ == "__main__":
    app()
