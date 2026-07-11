#!/usr/bin/env python3.12
"""
LeadFlow — AI-powered business lead finder and outreach tool.
Finds businesses, extracts contacts, writes personalized messages,
and lets you approve before anything sends.
"""
import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box
from database import init_db, get_leads, update_business_status, insert_outreach, mark_sent, get_stats, get_ab_stats
from finder import run_finder
from ai_writer import generate_all
from sender import send_email, parse_subject_body
from analyzer import PITCH_LABELS

console = Console()

BANNER = (
    "[bold cyan]"
    r"  _                    _ _____ _" "\n"
    r" | |    ___  __ _  __| |  ___| | _____      __" "\n"
    r" | |   / _ \/ _` |/ _` | |_  | |/ _ \ \ /\ / /" "\n"
    r" | |__|  __/ (_| | (_| |  _| | | (_) \ V  V /" "\n"
    r" |_____\___|\__,_|\__,_|_|   |_|\___/ \_/\_/" "\n"
    "[/bold cyan]\n"
    "[dim]AI-powered business finder & quality outreach tool[/dim]\n"
)


def show_banner():
    console.print(BANNER)


def show_stats():
    stats = get_stats()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_row("[cyan]New leads[/]", str(stats.get("new", 0)))
    table.add_row("[yellow]Approved[/]", str(stats.get("approved", 0)))
    table.add_row("[green]Sent[/]", str(stats.get("sent", 0)))
    table.add_row("[bold green]Replied[/]", str(stats.get("replied", 0)))
    table.add_row("[dim]Skipped[/]", str(stats.get("skipped", 0)))

    # A/B variant reply rates
    try:
        ab = get_ab_stats()
        if ab:
            table.add_row("", "")
            table.add_row("[dim]IG A/B variants[/]", "")
            for row in ab:
                variant = row["variant"] or "?"
                sent = row["sent"]
                replied = row["replied"]
                rate = f"{int(replied/sent*100)}%" if sent else "—"
                table.add_row(f"  [cyan]Variant {variant}[/]", f"{replied}/{sent} replied ({rate})")
    except Exception:
        pass

    console.print(Panel(table, title="[bold]Pipeline Status[/]", border_style="dim"))


def find_businesses():
    console.print("\n[bold cyan]— Find Businesses —[/]\n")
    niche = Prompt.ask("[cyan]Business niche[/]", default="restaurants")
    location = Prompt.ask("[cyan]Location[/]", default="Austin, Texas, USA")
    max_r = int(Prompt.ask("[cyan]Max results[/]", default="20"))
    console.print()
    run_finder(niche, location, max_r)
    Prompt.ask("\n[dim]Press Enter to return to menu[/]")


def review_lead(lead: dict) -> str:
    """
    Show one lead and let user approve/skip/mark replied.
    Returns: 'approved' | 'skipped' | 'quit'
    """
    console.clear()

    # Header
    score = lead.get("website_score", 0)
    score_color = "green" if score >= 70 else ("yellow" if score >= 40 else "red")

    console.print(Panel(
        f"[bold white]{lead['name']}[/]  [dim]{lead.get('city', '')} · {lead.get('country', '')}[/]",
        border_style="cyan"
    ))

    # Details table
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column(style="dim", width=14)
    table.add_column()

    if lead.get("google_rating"):
        table.add_row("Google", f"{'★' * int(lead['google_rating'])} {lead['google_rating']} ({lead.get('google_reviews', 0)} reviews)")
    table.add_row("Website", lead.get("website") or "[red]None[/]")
    table.add_row("Site Score", f"[{score_color}]{score}/100[/]")
    if lead.get("site_builder"):
        table.add_row("[yellow]Builder[/]", f"[yellow]{lead['site_builder']}[/] ← pitch hook: DIY site, we can replace it")
    table.add_row("Gap", lead.get("gap", "—"))
    table.add_row("Pitch", PITCH_LABELS.get(lead.get("pitch_type", ""), "—"))
    if lead.get("complaint_hook"):
        table.add_row("[magenta]Reviews[/]", f"[magenta]{lead['complaint_hook']}[/]")
    table.add_row("", "")
    table.add_row("Email", lead.get("email") or "[dim]not found[/]")
    table.add_row("Instagram", f"@{lead['instagram']}" if lead.get("instagram") else "[dim]not found[/]")
    table.add_row("LinkedIn", lead.get("linkedin_url") or "[dim]not found[/]")
    table.add_row("WhatsApp", lead.get("whatsapp") or "[dim]not found[/]")
    console.print(table)

    # Check if worth pursuing
    has_contact = any([lead.get("email"), lead.get("instagram"), lead.get("linkedin_url")])
    if not has_contact:
        console.print("[yellow]No contact found — limited outreach options.[/]\n")

    action = Prompt.ask(
        "\n[bold]Action[/]",
        choices=["a", "s", "q", "r"],
        default="s",
        show_choices=False,
        show_default=False,
    )
    # a=approve, s=skip, q=quit review, r=mark replied

    console.print("[dim]  a=approve  s=skip  r=mark replied  q=back to menu[/]", end="")

    if action == "q":
        return "quit"
    if action == "s":
        update_business_status(lead["id"], "skipped")
        return "skipped"
    if action == "r":
        update_business_status(lead["id"], "replied")
        console.print("\n[bold green]Marked as replied![/]")
        return "replied"  # fix #9: was "approved" — wrong return confused review loop

    # Approve — generate messages
    console.print("\n[dim]Generating personalized messages...[/]")
    try:
        drafts = generate_all(lead)
    except Exception as e:
        console.print(f"[red]AI writer error: {e}[/]")
        Prompt.ask("[dim]Press Enter to continue[/]")
        return "skipped"

    # Show and confirm each message
    for channel, draft in drafts.items():
        console.print(f"\n[bold cyan]── {channel.upper()} MESSAGE ──[/]")
        console.print(Panel(draft, border_style="dim"))

        edit = Confirm.ask("Edit this message?", default=False)
        if edit:
            console.print("[dim]Paste your revised message below. Type END on a new line when done.[/]")
            lines = []
            while True:
                line = input()
                if line.strip().upper() == "END":
                    break
                lines.append(line)
            draft = "\n".join(lines)

        insert_outreach(lead["id"], channel, draft)

    # Send emails now, DMs are manual (shown for copying)
    if lead.get("email") and "email" in drafts:
        send_now = Confirm.ask(f"\nSend email to [cyan]{lead['email']}[/] now?", default=True)
        if send_now:
            try:
                subject, body = parse_subject_body(drafts["email"])
                import uuid
                tracking_id = str(uuid.uuid4())
                send_email(lead["email"], subject, body, tracking_id, lead.get("demo_tunnel_url") or "", business_id=lead["id"])
                mark_sent(lead["id"], "email", is_autopilot=False, subject_used=subject, tracking_id=tracking_id)
                console.print("[green]Email sent.[/]")
            except Exception as e:
                console.print(f"[red]Send failed: {e}[/]")

    if "instagram" in drafts:
        console.print(f"\n[cyan]Instagram DM[/] → open @{lead['instagram']} and send this manually:")
        console.print(Panel(drafts["instagram"], border_style="cyan"))

    if "linkedin" in drafts:
        console.print(f"\n[cyan]LinkedIn DM[/] → open {lead.get('linkedin_url')} and send:")
        console.print(Panel(drafts["linkedin"], border_style="cyan"))

    update_business_status(lead["id"], "sent")
    Prompt.ask("\n[dim]Press Enter for next lead[/]")
    return "approved"


def review_leads():
    leads = get_leads(status="new")
    if not leads:
        console.print("\n[yellow]No new leads to review. Run [bold]Find Businesses[/] first.[/]")
        Prompt.ask("[dim]Press Enter to return[/]")
        return

    console.print(f"\n[bold]{len(leads)} new leads to review.[/] (a=approve, s=skip, r=replied, q=back)\n")
    Prompt.ask("[dim]Press Enter to start reviewing[/]")

    for lead in leads:
        result = review_lead(lead)
        if result == "quit":
            break


def view_sent():
    leads = get_leads(status="sent")
    console.print(f"\n[bold cyan]Sent Leads ({len(leads)})[/]\n")
    for lead in leads:
        channels = []
        if lead.get("email"):
            channels.append("email")
        if lead.get("instagram"):
            channels.append("ig")
        if lead.get("linkedin_url"):
            channels.append("li")
        console.print(f"  [white]{lead['name']}[/] [dim]{lead.get('city','')}[/]  → {', '.join(channels)}")
        mark_r = Confirm.ask(f"  Mark as replied?", default=False)
        if mark_r:
            update_business_status(lead["id"], "replied")
    Prompt.ask("\n[dim]Press Enter to return[/]")


def main_menu():
    init_db()
    while True:
        console.clear()
        show_banner()
        show_stats()

        console.print("[bold]What do you want to do?[/]\n")
        console.print("  [cyan][1][/] Find businesses")
        console.print("  [cyan][2][/] Review new leads")
        console.print("  [cyan][3][/] View sent / mark replied")
        console.print("  [cyan][q][/] Quit\n")

        choice = Prompt.ask("Choice", choices=["1", "2", "3", "q"], default="1")

        if choice == "1":
            find_businesses()
        elif choice == "2":
            review_leads()
        elif choice == "3":
            view_sent()
        elif choice == "q":
            console.print("\n[dim]Bye.[/]\n")
            sys.exit(0)


if __name__ == "__main__":
    main_menu()
