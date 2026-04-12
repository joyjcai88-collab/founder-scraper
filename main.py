#!/usr/bin/env python3
"""Founder Scraper — AI-powered founder enrichment and scoring for VC deal flow."""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from analyzer.enricher import enrich_founder
from analyzer.scorer import score_founder
from models.founder import FounderCard

console = Console()


def _score_color(score: float) -> str:
    if score >= 70:
        return "green"
    elif score >= 45:
        return "yellow"
    return "red"


def _score_bar(score: int, width: int = 20) -> str:
    filled = int(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def display_card(card: FounderCard) -> None:
    """Render a FounderCard as a rich terminal panel."""
    color = _score_color(card.overall_score)

    # Header
    header = Text()
    header.append(f"{card.name}", style="bold white")
    if card.company:
        header.append(f"  •  {card.company}", style="dim")

    # Overall score
    score_text = Text()
    score_text.append(f"\n  Overall Score: ", style="bold")
    score_text.append(f"{card.overall_score:.0f}/100", style=f"bold {color}")
    score_text.append(f"  {_score_bar(int(card.overall_score))}\n")

    # Breakdown table
    breakdown_table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    breakdown_table.add_column("Category", width=18)
    breakdown_table.add_column("Score", width=8, justify="right")
    breakdown_table.add_column("Bar", width=22)
    breakdown_table.add_column("Rationale", ratio=1)

    if card.breakdown:
        categories = [
            ("Founder Quality", card.breakdown.founder_quality, card.breakdown.founder_quality_rationale, "30%"),
            ("Market", card.breakdown.market, card.breakdown.market_rationale, "25%"),
            ("Traction", card.breakdown.traction, card.breakdown.traction_rationale, "25%"),
            ("Network", card.breakdown.network, card.breakdown.network_rationale, "10%"),
            ("Intangibles", card.breakdown.intangibles, card.breakdown.intangibles_rationale, "10%"),
        ]

        for name, score, rationale, weight in categories:
            c = _score_color(score)
            breakdown_table.add_row(
                f"{name} ({weight})",
                f"[{c}]{score}[/{c}]",
                f"[{c}]{_score_bar(score, 15)}[/{c}]",
                rationale[:120],
            )

    # Thesis fit
    thesis_text = ""
    if card.thesis_fit_summary:
        thesis_text = f"\n[bold]Thesis Fit:[/bold] {card.thesis_fit_summary}"

    # Risks
    risks_text = ""
    if card.key_risks:
        risks_text = "\n[bold]Key Risks:[/bold]"
        for risk in card.key_risks:
            risks_text += f"\n  • {risk}"

    # Sources
    sources_text = ""
    if card.source_links:
        sources_text = "\n[bold]Sources:[/bold]"
        for link in card.source_links[:5]:
            sources_text += f"\n  {link}"

    # Assemble the panel
    content = Text.from_markup(f"{score_text}")
    console.print(Panel(header, style=f"bold {color}", expand=True))
    console.print(score_text)
    console.print(breakdown_table)
    if thesis_text:
        console.print(thesis_text)
    if risks_text:
        console.print(risks_text)
    if sources_text:
        console.print(sources_text)
    console.print()


async def run(name: str, company: str | None = None) -> None:
    """Run the full enrichment and scoring pipeline."""
    console.print(f"\n[bold]Enriching founder:[/bold] {name}", end="")
    if company:
        console.print(f" @ {company}", end="")
    console.print("\n")

    with console.status("[bold cyan]Scraping public data..."):
        profile = await enrich_founder(name, company)

    # Show what data was found
    sources_found = []
    if profile.github:
        sources_found.append("GitHub")
    if profile.crunchbase:
        sources_found.append("Crunchbase")
    if profile.twitter:
        sources_found.append("Twitter/X")
    if profile.web_search:
        sources_found.append("Web Search")

    if sources_found:
        console.print(f"[green]Data found from:[/green] {', '.join(sources_found)}")
    else:
        console.print("[yellow]Warning: No data found from any source. Scores will be conservative.[/yellow]")

    with console.status("[bold cyan]Analyzing with Claude..."):
        card = await score_founder(profile)

    console.print()
    display_card(card)


def main() -> None:
    load_dotenv(override=True)

    parser = argparse.ArgumentParser(
        description="AI-powered founder enrichment and scoring for VC deal flow.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "Tobi Lutke"
  python main.py "Tobi Lutke" --company "Shopify"
  python main.py "Patrick Collison" --company "Stripe"
        """,
    )
    parser.add_argument("name", help="Founder's full name")
    parser.add_argument("--company", "-c", help="Company name (optional, improves accuracy)")
    args = parser.parse_args()

    try:
        asyncio.run(run(args.name, args.company))
    except KeyboardInterrupt:
        console.print("\n[dim]Cancelled.[/dim]")
        sys.exit(1)
    except RuntimeError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
