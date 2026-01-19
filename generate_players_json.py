#!/usr/bin/env python3
"""
Generate data/players.json by aggregating player stats from all game runs.

This script:
1. Reads all prompts/*.json files for player definitions
2. Aggregates contestant_stats from all runs/*/run.json files
3. Computes derived stats (survival%, win rates)
4. Outputs data/players.json for the players.html page

Usage:
    python generate_players_json.py
"""

import json
import os
from datetime import datetime
from pathlib import Path


def load_prompt_files(prompts_dir: Path) -> dict:
    """Load all prompt files and return a dict keyed by player name."""
    players = {}

    for prompt_file in prompts_dir.glob("*.json"):
        try:
            with open(prompt_file) as f:
                data = json.load(f)

            name = data.get("name")
            if not name:
                continue

            # Handle duplicate names (different versions) by using name|version as key
            version = data.get("version", "1.0")
            key = f"{name}|{version}"

            players[key] = {
                "name": name,
                "version": f"v{version}",
                "file": prompt_file.name,
                "created": data.get("created", ""),
                "designNotes": data.get("design_notes", ""),
                "hypothesis": data.get("hypothesis", ""),
                "prompt": data.get("personality_prompt", ""),
            }
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not load {prompt_file}: {e}")

    return players


def aggregate_role_prizes_from_games(runs_dir: Path) -> dict:
    """Read game_*.json files to get role-specific prize data."""
    role_prizes = {}  # name -> {"traitor": 0, "faithful": 0}

    for game_json in runs_dir.glob("*/game_*.json"):
        try:
            with open(game_json) as f:
                game = json.load(f)

            prize_dist = game.get("prize_distribution", {})
            players = game.get("players", {})

            for name, prize in prize_dist.items():
                if name not in role_prizes:
                    role_prizes[name] = {"traitor": 0, "faithful": 0}

                role = players.get(name, {}).get("role", "faithful")
                role_prizes[name][role] += prize
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not load {game_json}: {e}")

    return role_prizes


def aggregate_stats_from_runs(runs_dir: Path) -> dict:
    """Aggregate contestant stats from all run.json files.

    Returns a dict keyed by player name with aggregated stats.
    """
    aggregated = {}

    for run_json in runs_dir.glob("*/run.json"):
        try:
            with open(run_json) as f:
                run_data = json.load(f)

            contestant_stats = run_data.get("contestant_stats", {})

            for key, stats in contestant_stats.items():
                # Key format is "Name|model", extract just the name
                name = stats.get("name", key.split("|")[0])

                if name not in aggregated:
                    aggregated[name] = {
                        "games": 0,
                        "traitor": 0,
                        "faithful": 0,
                        "traitorWins": 0,
                        "faithfulWins": 0,
                        "survived": 0,
                        "banished": 0,
                        "murdered": 0,
                        "totalPrize": 0,
                        "prizeWhenTraitor": 0,
                        "prizeWhenFaithful": 0,
                    }

                agg = aggregated[name]
                agg["games"] += stats.get("games_played", 0)
                agg["traitor"] += stats.get("times_traitor", 0)
                agg["faithful"] += stats.get("times_faithful", 0)
                agg["survived"] += stats.get("survived", 0)
                agg["banished"] += stats.get("banished", 0)
                agg["murdered"] += stats.get("murdered", 0)
                agg["totalPrize"] += stats.get("total_prize", 0)

                # Handle wins - run.json has "wins" which is total wins
                # We need to split by role. Approximation: if they won and survived,
                # credit to the role they played
                wins = stats.get("wins", 0)
                times_traitor = stats.get("times_traitor", 0)
                times_faithful = stats.get("times_faithful", 0)
                survived = stats.get("survived", 0)

                # For per-role wins, we need to estimate. The run.json doesn't track
                # wins_as_traitor/wins_as_faithful directly.
                # We can approximate by checking if wins > 0 and role counts.
                # A more accurate approach would track this at game level, but for now
                # we'll use a simple heuristic.
                if wins > 0:
                    # Distribute wins proportionally to games played as each role
                    # This is an approximation - actual wins are game-specific
                    total_games = times_traitor + times_faithful
                    if total_games > 0:
                        traitor_ratio = times_traitor / total_games
                        agg["traitorWins"] += round(wins * traitor_ratio)
                        agg["faithfulWins"] += wins - round(wins * traitor_ratio)

        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not load {run_json}: {e}")

    return aggregated


def compute_derived_stats(stats: dict) -> dict:
    """Compute derived statistics like survival% and win rates."""
    games = stats.get("games", 0)

    if games == 0:
        return {
            **stats,
            "survival": 0,
            "traitorWin": 0,
            "faithfulWin": 0,
        }

    survival = round(stats["survived"] / games * 100)

    traitor_games = stats.get("traitor", 0)
    faithful_games = stats.get("faithful", 0)

    traitor_win = round(stats["traitorWins"] / traitor_games * 100) if traitor_games > 0 else 0
    faithful_win = round(stats["faithfulWins"] / faithful_games * 100) if faithful_games > 0 else 0

    return {
        **stats,
        "survival": survival,
        "traitorWin": traitor_win,
        "faithfulWin": faithful_win,
    }


def main():
    base_dir = Path(__file__).parent
    prompts_dir = base_dir / "prompts"
    runs_dir = base_dir / "runs"
    data_dir = base_dir / "data"

    # Ensure data directory exists
    data_dir.mkdir(exist_ok=True)

    print("Loading prompt files...")
    players = load_prompt_files(prompts_dir)
    print(f"  Found {len(players)} player definitions")

    print("Aggregating stats from runs...")
    run_stats = aggregate_stats_from_runs(runs_dir)
    print(f"  Found stats for {len(run_stats)} players across runs")

    print("Aggregating role-specific prizes from games...")
    role_prizes = aggregate_role_prizes_from_games(runs_dir)
    print(f"  Found role-specific prizes for {len(role_prizes)} players")

    # Merge stats into player definitions
    # For players with multiple versions, merge stats by name
    final_players = []

    for key, player in players.items():
        name = player["name"]

        # Get aggregated stats for this player name
        if name in run_stats:
            stats = compute_derived_stats(run_stats[name])
        else:
            stats = {
                "games": 0,
                "traitor": 0,
                "faithful": 0,
                "traitorWins": 0,
                "faithfulWins": 0,
                "survived": 0,
                "banished": 0,
                "murdered": 0,
                "totalPrize": 0,
                "prizeWhenTraitor": 0,
                "prizeWhenFaithful": 0,
                "survival": 0,
                "traitorWin": 0,
                "faithfulWin": 0,
            }

        # Merge role-specific prizes
        if name in role_prizes:
            rp = role_prizes[name]
            stats["prizeWhenTraitor"] = rp.get("traitor", 0)
            stats["prizeWhenFaithful"] = rp.get("faithful", 0)

        final_players.append({
            "name": player["name"],
            "version": player["version"],
            "file": player["file"],
            "created": player["created"],
            "designNotes": player["designNotes"],
            "hypothesis": player["hypothesis"],
            "prompt": player["prompt"],
            "stats": {
                "games": stats["games"],
                "traitor": stats["traitor"],
                "faithful": stats["faithful"],
                "survival": stats["survival"],
                "traitorWin": stats["traitorWin"],
                "faithfulWin": stats["faithfulWin"],
                "banished": stats["banished"],
                "murdered": stats["murdered"],
                "totalPrize": stats["totalPrize"],
                "prizeWhenTraitor": stats["prizeWhenTraitor"],
                "prizeWhenFaithful": stats["prizeWhenFaithful"],
            }
        })

    # Sort by name, then version
    final_players.sort(key=lambda p: (p["name"], p["version"]))

    output = {
        "updated": datetime.now().isoformat(),
        "players": final_players,
    }

    output_path = data_dir / "players.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Generated {output_path}")
    print(f"  {len(final_players)} players with stats")

    # Show some example stats
    players_with_games = [p for p in final_players if p["stats"]["games"] > 0]
    print(f"  {len(players_with_games)} players with game data")
    if players_with_games:
        top = max(players_with_games, key=lambda p: p["stats"]["games"])
        print(f"  Most games: {top['name']} ({top['stats']['games']} games)")


if __name__ == "__main__":
    main()
