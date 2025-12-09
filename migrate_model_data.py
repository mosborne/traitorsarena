#!/usr/bin/env python3
"""Migrate existing run data to include model information.

This script updates all existing run data to include model information:
- Updates run.json: Changes contestant_stats keys from "Name" to "Name|model"
  and adds model field to each entry
- Updates game_*.json: Adds model field to each player

All existing runs used claude-3-5-haiku-20241022 as the default model.
"""

import json
from pathlib import Path

DEFAULT_MODEL = "claude-3-5-haiku-20241022"
RUNS_DIR = Path("runs")


def migrate_run(run_dir: Path) -> bool:
    """Migrate a single run directory.

    Returns True if migration was performed, False if skipped.
    """
    run_json = run_dir / "run.json"
    if not run_json.exists():
        return False

    with open(run_json) as f:
        data = json.load(f)

    # Check if already migrated (look for pipe in keys or model field in stats)
    contestant_stats = data.get("contestant_stats", {})
    if any("|" in key for key in contestant_stats.keys()):
        print(f"  Skipping {run_dir.name} - already migrated (composite keys)")
        return False

    # Also check if any entry has a model field already
    if any(stats.get("model") for stats in contestant_stats.values()):
        print(f"  Skipping {run_dir.name} - already has model data")
        return False

    # Migrate contestant_stats keys
    old_stats = data.get("contestant_stats", {})
    new_stats = {}
    for name, stats in old_stats.items():
        new_key = f"{name}|{DEFAULT_MODEL}"
        stats["name"] = name
        stats["model"] = DEFAULT_MODEL
        new_stats[new_key] = stats
    data["contestant_stats"] = new_stats

    with open(run_json, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Migrated {run_json.name}")

    # Migrate game files
    game_count = 0
    for game_json in sorted(run_dir.glob("game_*.json")):
        with open(game_json) as f:
            game_data = json.load(f)

        modified = False
        # Add model to each player
        for player_data in game_data.get("players", {}).values():
            if "model" not in player_data or player_data["model"] is None:
                player_data["model"] = DEFAULT_MODEL
                modified = True

        if modified:
            with open(game_json, "w") as f:
                json.dump(game_data, f, indent=2)
            game_count += 1

    if game_count > 0:
        print(f"  Migrated {game_count} game files")

    return True


def main():
    print(f"Migrating runs to include model: {DEFAULT_MODEL}")
    print(f"Scanning {RUNS_DIR}...")
    print()

    if not RUNS_DIR.exists():
        print(f"Runs directory not found: {RUNS_DIR}")
        return

    migrated_count = 0
    skipped_count = 0

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue

        print(f"Processing {run_dir.name}...")
        if migrate_run(run_dir):
            migrated_count += 1
        else:
            skipped_count += 1

    print()
    print(f"Done! Migrated {migrated_count} runs, skipped {skipped_count}")


if __name__ == "__main__":
    main()
