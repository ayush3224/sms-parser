#!/usr/bin/env python3
"""
main.py — production entry point.
Railway detects this file and runs it. It unconditionally starts the webhook server.

For local interactive CLI, run:  python cli.py
"""
from server import main

# ---------------------------------------------------------------------------
# Bulk import helper
# ---------------------------------------------------------------------------

def _bulk_import(path: str, store) -> None:
    """Import all SMS from a file into Supabase (skips duplicates)."""
    parser = SMSParser()
    console.print(f"[dim]Importing from {path} …[/dim]")
    try:
        sms_list = SMSReader().load(path)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    saved = 0
    for sms in sms_list:
        txn = parser.parse(sms)
        try:
            store.save(sms, txn)
            saved += 1
        except Exception as exc:
            console.print(f"[yellow]Skip {sms.id}:[/yellow] {exc}")

    console.print(f"[green]✓ Imported {saved}/{len(sms_list)} SMS into Supabase[/green]")


if __name__ == "__main__":
    main()
