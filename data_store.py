"""
JSON data storage for game results.

This module handles serializing game results to JSON and updating the global runs index.
"""

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def serialize_value(obj: Any) -> Any:
    """Convert objects to JSON-serializable format."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: serialize_value(v) for k, v in asdict(obj).items()}
    elif hasattr(obj, 'value'):  # Enum
        return obj.value
    elif isinstance(obj, dict):
        return {k: serialize_value(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [serialize_value(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj


def save_game_json(run_dir: str, game_num: int, results: dict, game_log: list[str]) -> str:
    """
    Save a single game's results to JSON.

    Args:
        run_dir: Directory for this run (e.g., runs/2025-12-07_18-13-46)
        game_num: Game number (1-indexed)
        results: Game results from TraitorsGame.run()
        game_log: List of log messages from the game

    Returns:
        Path to the saved JSON file
    """
    # Organize data by round
    rounds_data = []
    current_round = None

    # Get messages, votes, thoughts organized by round
    messages = results.get("messages", [])
    votes = results.get("votes", [])
    private_thoughts = results.get("private_thoughts", [])
    players = results.get("players", {})

    # Group by round number
    max_round = results.get("rounds_played", 1)
    for round_num in range(1, max_round + 1):
        round_messages = [serialize_value(m) for m in messages if getattr(m, 'round_num', 0) == round_num]
        round_votes = [serialize_value(v) for v in votes if getattr(v, 'round_num', 0) == round_num]
        round_thoughts = [serialize_value(t) for t in private_thoughts if getattr(t, 'round_num', 0) == round_num]

        # Find who was banished/murdered this round
        banished = None
        murdered = None
        for name, player in players.items():
            if hasattr(player, 'eliminated_round') and player.eliminated_round == round_num:
                if hasattr(player, 'status'):
                    status = player.status.value if hasattr(player.status, 'value') else str(player.status)
                    if status == "banished":
                        role = player.role.value if hasattr(player.role, 'value') else str(player.role)
                        banished = {"name": name, "role": role}
                    elif status == "murdered":
                        murdered = {"name": name}

        rounds_data.append({
            "round_num": round_num,
            "messages": round_messages,
            "votes": round_votes,
            "private_thoughts": round_thoughts,
            "banished": banished,
            "murdered": murdered,
        })

    # Build player data
    players_data = {}
    for name, player in players.items():
        players_data[name] = {
            "role": player.role.value if hasattr(player.role, 'value') else str(player.role),
            "status": player.status.value if hasattr(player.status, 'value') else str(player.status),
            "eliminated_round": getattr(player, 'eliminated_round', None),
        }

    game_data = {
        "game_id": game_num,
        "winner": results.get("winner"),
        "rounds_played": results.get("rounds_played"),
        "traitors": results.get("traitors", []),
        "faithful": results.get("faithful", []),
        "survivors": results.get("survivors", []),
        "prize_pool": results.get("prize_pool", 100000),
        "prize_distribution": results.get("prize_distribution", {}),
        "finale_round": results.get("finale_round", 8),
        "players": players_data,
        "rounds": rounds_data,
        "game_log": game_log,
    }

    # Save to file
    json_path = os.path.join(run_dir, f"game_{game_num}.json")
    with open(json_path, "w") as f:
        json.dump(game_data, f, indent=2, default=str)

    return json_path


def save_run_json(run_dir: str, run_id: str, config: dict, games_data: list, contestants: list) -> str:
    """
    Save run summary to JSON.

    Args:
        run_dir: Directory for this run
        run_id: Run identifier (timestamp)
        config: Config dict used for this run
        games_data: List of game results
        contestants: List of contestant dicts

    Returns:
        Path to the saved JSON file
    """
    # Calculate contestant stats
    contestant_stats = {}
    for c in contestants:
        name = c["name"]
        contestant_stats[name] = {
            "games_played": 0,
            "times_traitor": 0,
            "times_faithful": 0,
            "wins": 0,
            "survived": 0,
            "banished": 0,
            "murdered": 0,
            "total_prize": 0,
        }

    traitor_wins = 0
    faithful_wins = 0
    total_rounds = 0

    for game in games_data:
        winner = game.get("winner")
        if winner == "traitors":
            traitor_wins += 1
        else:
            faithful_wins += 1

        total_rounds += game.get("rounds_played", 0)

        # Process each contestant
        traitors = game.get("traitors", [])
        survivors = game.get("survivors", [])
        players = game.get("players", {})
        prize_dist = game.get("prize_distribution", {})

        for name in contestant_stats:
            stats = contestant_stats[name]
            stats["games_played"] += 1

            is_traitor = name in traitors
            if is_traitor:
                stats["times_traitor"] += 1
            else:
                stats["times_faithful"] += 1

            # Check if won
            if name in survivors:
                if (winner == "traitors" and is_traitor) or (winner == "faithful" and not is_traitor):
                    stats["wins"] += 1

            # Check status
            if name in survivors:
                stats["survived"] += 1
            elif name in players:
                player = players[name]
                status = player.get("status") if isinstance(player, dict) else getattr(player, 'status', None)
                if status:
                    status_val = status.value if hasattr(status, 'value') else str(status)
                    if status_val == "banished":
                        stats["banished"] += 1
                    elif status_val == "murdered":
                        stats["murdered"] += 1

            # Prize
            stats["total_prize"] += prize_dist.get(name, 0)

    run_data = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "config_name": config.get("name", "unknown"),
        "config_description": config.get("description", ""),
        "num_traitors": config.get("num_traitors", 3),
        "finale_round": config.get("finale_round", 8),
        "contestants": [c["name"] for c in contestants],
        "games": list(range(1, len(games_data) + 1)),
        "stats": {
            "total_games": len(games_data),
            "traitor_wins": traitor_wins,
            "faithful_wins": faithful_wins,
            "avg_rounds": total_rounds / len(games_data) if games_data else 0,
        },
        "contestant_stats": contestant_stats,
    }

    json_path = os.path.join(run_dir, "run.json")
    with open(json_path, "w") as f:
        json.dump(run_data, f, indent=2)

    return json_path


def update_runs_index(runs_dir: str = "runs", data_dir: str = "data") -> str:
    """
    Update the global runs index from all run directories.

    Args:
        runs_dir: Directory containing all runs
        data_dir: Directory to save the index

    Returns:
        Path to the saved index file
    """
    runs = []

    if os.path.exists(runs_dir):
        for run_id in sorted(os.listdir(runs_dir), reverse=True):
            run_path = os.path.join(runs_dir, run_id)
            if not os.path.isdir(run_path):
                continue

            # Try to load run.json first, fall back to metadata.json
            run_json = os.path.join(run_path, "run.json")
            metadata_json = os.path.join(run_path, "metadata.json")

            if os.path.exists(run_json):
                with open(run_json) as f:
                    data = json.load(f)
                runs.append({
                    "id": run_id,
                    "timestamp": data.get("timestamp"),
                    "config_name": data.get("config_name"),
                    "config_description": data.get("config_description", ""),
                    "total_games": data.get("stats", {}).get("total_games", 0),
                    "traitor_wins": data.get("stats", {}).get("traitor_wins", 0),
                    "faithful_wins": data.get("stats", {}).get("faithful_wins", 0),
                    "avg_rounds": data.get("stats", {}).get("avg_rounds", 0),
                    "contestants": data.get("contestants", []),
                    "num_traitors": data.get("num_traitors", 3),
                    "has_json": True,
                })
            elif os.path.exists(metadata_json):
                with open(metadata_json) as f:
                    data = json.load(f)
                # Skip empty runs
                if data.get("traitor_wins", 0) == 0 and data.get("faithful_wins", 0) == 0:
                    continue
                runs.append({
                    "id": run_id,
                    "timestamp": data.get("timestamp"),
                    "config_name": data.get("config_name"),
                    "config_description": data.get("config_description", ""),
                    "total_games": data.get("num_games", 0),
                    "traitor_wins": data.get("traitor_wins", 0),
                    "faithful_wins": data.get("faithful_wins", 0),
                    "avg_rounds": data.get("avg_rounds", 0),
                    "contestants": data.get("contestants", []),
                    "num_traitors": data.get("num_traitors", 3),
                    "has_json": False,  # Legacy HTML only
                })

    # Ensure data directory exists
    os.makedirs(data_dir, exist_ok=True)

    index_data = {
        "updated": datetime.now().isoformat(),
        "runs": runs,
    }

    index_path = os.path.join(data_dir, "runs.json")
    with open(index_path, "w") as f:
        json.dump(index_data, f, indent=2)

    return index_path
