#!/usr/bin/env python3
"""Monitor script for tracking Traitors game run progress."""

import os
import sys
import time
import glob
import subprocess
from datetime import datetime


def get_latest_run_dir():
    """Get the most recent run directory."""
    runs = sorted(glob.glob("runs/2025-*"))
    return runs[-1] if runs else None


def count_games(run_dir):
    """Count completed games in a run directory."""
    games = glob.glob(f"{run_dir}/game_*.html")
    return len(games)


def get_game_result(game_file):
    """Extract winner from a game file."""
    try:
        with open(game_file, 'r') as f:
            content = f.read()
            if "WINNER: THE TRAITORS" in content:
                return "TRAITORS"
            elif "WINNER: THE FAITHFUL" in content:
                return "FAITHFUL"
            elif "GAME OVER" in content:
                return "COMPLETED"
    except:
        pass
    return "IN_PROGRESS"


def get_process_status():
    """Check if a game process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "run_games.py"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            return pids
    except:
        pass
    return []


def get_config_info(run_dir):
    """Get config info from run directory."""
    config_file = f"{run_dir}/config.json"
    if os.path.exists(config_file):
        import json
        with open(config_file) as f:
            config = json.load(f)
            return {
                "name": config.get("config_name", "unknown"),
                "num_games": config.get("num_games", 10),
                "description": config.get("description", "")[:60]
            }
    return {"name": "unknown", "num_games": 10, "description": ""}


def monitor_once():
    """Run monitoring check once."""
    print(f"\n{'='*60}")
    print(f"TRAITORS GAME MONITOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Check process status
    pids = get_process_status()
    if pids:
        print(f"\nProcess Status: RUNNING (PID: {', '.join(pids)})")
    else:
        print(f"\nProcess Status: NOT RUNNING")

    # Get latest run
    run_dir = get_latest_run_dir()
    if not run_dir:
        print("\nNo runs found.")
        return

    print(f"\nLatest Run: {run_dir}")

    # Get config info
    config = get_config_info(run_dir)
    print(f"Config: {config['name']}")
    print(f"Target: {config['num_games']} games")

    # Count completed games
    completed = count_games(run_dir)
    print(f"\nProgress: {completed}/{config['num_games']} games completed")

    # Show results for each game
    if completed > 0:
        print(f"\nResults:")
        traitor_wins = 0
        faithful_wins = 0

        for i in range(1, completed + 1):
            game_file = f"{run_dir}/game_{i}.html"
            if os.path.exists(game_file):
                result = get_game_result(game_file)
                size_kb = os.path.getsize(game_file) // 1024
                mtime = datetime.fromtimestamp(os.path.getmtime(game_file))

                if result == "TRAITORS":
                    traitor_wins += 1
                    icon = "X"
                elif result == "FAITHFUL":
                    faithful_wins += 1
                    icon = "O"
                else:
                    icon = "?"

                print(f"  Game {i}: {result:10} [{icon}] ({size_kb}KB, {mtime.strftime('%H:%M:%S')})")

        print(f"\nSummary: Traitors {traitor_wins} - {faithful_wins} Faithful")
        if completed > 0:
            print(f"Traitor win rate: {traitor_wins/completed*100:.1f}%")

    # Estimate time remaining
    if completed > 0 and completed < config['num_games'] and pids:
        games = sorted(glob.glob(f"{run_dir}/game_*.html"))
        if len(games) >= 2:
            first_time = os.path.getmtime(games[0])
            last_time = os.path.getmtime(games[-1])
            avg_time = (last_time - first_time) / (len(games) - 1)
            remaining = config['num_games'] - completed
            eta_seconds = remaining * avg_time
            eta_minutes = eta_seconds / 60
            print(f"\nETA: ~{eta_minutes:.0f} minutes ({remaining} games remaining, ~{avg_time/60:.1f} min/game)")


def monitor_loop(interval=30):
    """Continuously monitor with given interval."""
    print(f"Starting continuous monitoring (Ctrl+C to stop)...")
    print(f"Checking every {interval} seconds")

    try:
        while True:
            os.system('clear' if os.name != 'nt' else 'cls')
            monitor_once()

            # Check if process is still running
            if not get_process_status():
                print("\n[Process completed or stopped]")
                break

            print(f"\n[Next update in {interval}s - Ctrl+C to stop]")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        monitor_loop(interval)
    else:
        monitor_once()
        print("\nTip: Run with --loop [seconds] for continuous monitoring")
