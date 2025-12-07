#!/usr/bin/env python3
"""
Migrate existing runs to the new JSON format.

This script:
1. Creates run.json files from existing metadata.json files
2. Updates the global data/runs.json index
3. Marks runs without JSON game data as "legacy" (has_json=False)

Usage:
    python migrate_to_json.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

from data_store import update_runs_index


def migrate_run(run_dir: str) -> bool:
    """
    Migrate a single run to the new format.

    Args:
        run_dir: Path to the run directory

    Returns:
        True if migration successful, False otherwise
    """
    metadata_path = os.path.join(run_dir, "metadata.json")
    run_json_path = os.path.join(run_dir, "run.json")

    # Skip if already migrated
    if os.path.exists(run_json_path):
        print(f"  Already has run.json, skipping")
        return True

    # Load metadata
    if not os.path.exists(metadata_path):
        print(f"  No metadata.json found, skipping")
        return False

    with open(metadata_path) as f:
        metadata = json.load(f)

    # Skip empty runs
    if metadata.get("traitor_wins", 0) == 0 and metadata.get("faithful_wins", 0) == 0:
        print(f"  Empty run (no wins), skipping")
        return False

    # Count actual game files
    game_count = 0
    for f in os.listdir(run_dir):
        if f.startswith("game_") and f.endswith(".html"):
            game_count += 1

    # Build run.json from metadata
    # Note: We don't have per-game data, so contestant_stats will be empty
    run_data = {
        "run_id": metadata.get("run_id"),
        "timestamp": metadata.get("timestamp"),
        "config_name": metadata.get("config_name"),
        "config_description": metadata.get("config_description", ""),
        "num_traitors": metadata.get("num_traitors", 3),
        "finale_round": 8,  # Default, may not be in old metadata
        "contestants": metadata.get("contestants", []),
        "games": list(range(1, game_count + 1)),
        "stats": {
            "total_games": metadata.get("num_games", game_count),
            "traitor_wins": metadata.get("traitor_wins", 0),
            "faithful_wins": metadata.get("faithful_wins", 0),
            "avg_rounds": metadata.get("avg_rounds", 0),
        },
        "contestant_stats": {},  # Not available from metadata alone
        "legacy": True,  # Mark as legacy (HTML games only)
    }

    # Save run.json
    with open(run_json_path, "w") as f:
        json.dump(run_data, f, indent=2)

    print(f"  Created run.json ({game_count} games)")
    return True


def main():
    """Run the migration."""
    runs_dir = "runs"
    data_dir = "data"

    print("=" * 60)
    print("MIGRATING EXISTING RUNS TO JSON FORMAT")
    print("=" * 60)

    if not os.path.exists(runs_dir):
        print(f"No runs directory found at {runs_dir}")
        return 1

    # Ensure data directory exists
    os.makedirs(data_dir, exist_ok=True)

    # Process each run
    migrated = 0
    skipped = 0

    for run_id in sorted(os.listdir(runs_dir)):
        run_path = os.path.join(runs_dir, run_id)
        if not os.path.isdir(run_path):
            continue

        print(f"\nProcessing: {run_id}")
        if migrate_run(run_path):
            migrated += 1
        else:
            skipped += 1

    # Update global index
    print(f"\n{'=' * 60}")
    print("Updating global runs index...")
    index_path = update_runs_index(runs_dir, data_dir)
    print(f"Saved: {index_path}")

    # Load and display summary
    with open(index_path) as f:
        index_data = json.load(f)

    print(f"\n{'=' * 60}")
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"Runs migrated: {migrated}")
    print(f"Runs skipped:  {skipped}")
    print(f"Total in index: {len(index_data['runs'])}")

    # Show runs in index
    print(f"\nRuns in index:")
    for run in index_data['runs'][:10]:  # Show first 10
        has_json = run.get('has_json', False)
        status = "JSON" if has_json else "HTML (legacy)"
        print(f"  {run['id']}: {run['total_games']} games, {run['traitor_wins']}T/{run['faithful_wins']}F [{status}]")

    return 0


if __name__ == "__main__":
    exit(main())
