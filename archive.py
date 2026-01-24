#!/usr/bin/env python3
"""
Archive management CLI for The Traitors game simulator.

Commands:
    create <id> --name "..." [--description "..."] [--keep-players "A,B,C"]
    list
    show <id>
"""

import argparse
import sys
from datetime import datetime

from data_store import (
    create_archive,
    get_archive,
    get_archive_players,
    list_archives,
)


def cmd_create(args):
    """Create a new archive from current runs."""
    keep_players = []
    if args.keep_players:
        keep_players = [p.strip() for p in args.keep_players.split(",")]

    print(f"Creating archive '{args.id}'...")
    print(f"  Name: {args.name}")
    if args.description:
        print(f"  Description: {args.description}")
    if keep_players:
        print(f"  Keeping stats for: {', '.join(keep_players)}")

    try:
        result = create_archive(
            archive_id=args.id,
            name=args.name,
            description=args.description or "",
            keep_players=keep_players,
        )
        print()
        print("Archive created successfully!")
        print(f"  Runs archived: {result['run_count']}")
        print(f"  Total games: {result['total_games']}")
        print(f"  Location: data/archives/{args.id}/")
        print()
        print("Current season has been reset:")
        print("  - runs.json is now empty")
        if keep_players:
            print(f"  - Player stats kept for: {', '.join(keep_players)}")
            print("  - All other player stats have been reset to zero")
        else:
            print("  - All player stats have been reset to zero")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args):
    """List all archives."""
    archives = list_archives()

    if not archives:
        print("No archives found.")
        return

    print(f"{'ID':<20} {'Name':<30} {'Runs':<6} {'Games':<8} {'Created':<20}")
    print("-" * 90)

    for archive in archives:
        created = archive.get("created", "")[:10]  # Just date
        print(
            f"{archive['id']:<20} "
            f"{archive['name'][:28]:<30} "
            f"{archive['run_count']:<6} "
            f"{archive['total_games']:<8} "
            f"{created:<20}"
        )


def cmd_show(args):
    """Show details of a specific archive."""
    archive = get_archive(args.id)

    if not archive:
        print(f"Error: Archive '{args.id}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Archive: {archive['id']}")
    print(f"Name: {archive['name']}")
    if archive.get("description"):
        print(f"Description: {archive['description']}")
    print(f"Created: {archive['created']}")
    print()

    runs = archive.get("runs", [])
    print(f"Runs ({len(runs)}):")
    print(f"  {'ID':<25} {'Config':<20} {'Games':<8} {'T Wins':<8} {'F Wins':<8}")
    print("  " + "-" * 75)

    for run in runs:
        print(
            f"  {run['id']:<25} "
            f"{run.get('config_name', 'unknown')[:18]:<20} "
            f"{run.get('total_games', 0):<8} "
            f"{run.get('traitor_wins', 0):<8} "
            f"{run.get('faithful_wins', 0):<8}"
        )

    # Player stats summary
    players_data = get_archive_players(args.id)
    if players_data:
        players = players_data.get("players", [])
        print()
        print(f"Players ({len(players)} with stats):")

        # Sort by total prize descending
        players_sorted = sorted(
            players,
            key=lambda p: p.get("stats", {}).get("totalPrize", 0),
            reverse=True,
        )

        print(f"  {'Name':<15} {'Games':<8} {'Wins':<8} {'Prize':<12}")
        print("  " + "-" * 45)

        for player in players_sorted[:10]:  # Top 10
            stats = player.get("stats", {})
            games = stats.get("games", 0)
            if games == 0:
                continue
            wins = stats.get("traitorWin", 0) + stats.get("faithfulWin", 0)
            prize = stats.get("totalPrize", 0)
            print(
                f"  {player['name']:<15} "
                f"{games:<8} "
                f"{wins:<8} "
                f"${prize:,}"
            )

        if len(players_sorted) > 10:
            print(f"  ... and {len(players_sorted) - 10} more players")


def main():
    parser = argparse.ArgumentParser(
        description="Archive management for The Traitors game simulator"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # create command
    create_parser = subparsers.add_parser("create", help="Create a new archive")
    create_parser.add_argument("id", help="Archive ID (e.g., 'season-1')")
    create_parser.add_argument(
        "--name", "-n", required=True, help="Human-readable name for the archive"
    )
    create_parser.add_argument(
        "--description", "-d", help="Optional description"
    )
    create_parser.add_argument(
        "--keep-players",
        "-k",
        help="Comma-separated list of player names to keep stats for",
    )

    # list command
    subparsers.add_parser("list", help="List all archives")

    # show command
    show_parser = subparsers.add_parser("show", help="Show archive details")
    show_parser.add_argument("id", help="Archive ID to show")

    args = parser.parse_args()

    if args.command == "create":
        cmd_create(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "show":
        cmd_show(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
