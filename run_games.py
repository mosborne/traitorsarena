#!/usr/bin/env python3
"""
Run multiple game iterations and generate summary statistics.

Usage:
    python run_games.py --config configs/baseline.json
    python run_games.py --config configs/experimental_v1.json

The config file specifies contestants, number of games, and other parameters.
"""

import argparse
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic

from main import EXAMPLE_CONTESTANTS
from traitors import TraitorsGame
from traitors.types import PlayerStatus
from generate_html import generate_game_html
from data_store import save_game_json, save_run_json, update_runs_index


# Build lookup for original contestants
ORIGINAL_CONTESTANTS = {c["name"]: c for c in EXAMPLE_CONTESTANTS}


def load_config(config_path: str) -> dict:
    """Load a game configuration file."""
    with open(config_path) as f:
        return json.load(f)


def load_contestants_from_config(config: dict) -> list[dict]:
    """
    Load contestants based on config specification.

    Each contestant entry can be:
    - {"source": "original", "name": "Marcus"} - use original contestant
    - {"source": "prompt", "file": "improved_v1.json"} - use prompt file
    """
    prompts_dir = Path(__file__).parent / "prompts"
    contestants = []

    for entry in config.get("contestants", []):
        source = entry.get("source", "original")

        if source == "original":
            name = entry["name"]
            if name not in ORIGINAL_CONTESTANTS:
                raise ValueError(f"Unknown original contestant: {name}")
            contestants.append(ORIGINAL_CONTESTANTS[name].copy())

        elif source == "prompt":
            prompt_file = entry["file"]
            path = prompts_dir / prompt_file
            if not path.exists():
                raise ValueError(f"Prompt file not found: {prompt_file}")

            with open(path) as f:
                data = json.load(f)

            contestants.append({
                "name": data["name"],
                "personality_prompt": data["personality_prompt"],
                "_prompt_file": prompt_file,
                "_version": data.get("version", "1.0"),
            })
        else:
            raise ValueError(f"Unknown source type: {source}")

    return contestants


def run_single_game(client, contestants, num_traitors, game_log, finale_round=8, verbose=True):
    """Run a single game and return results."""
    def log_handler(msg):
        game_log.append(msg)
        if verbose:
            print(msg)

    game = TraitorsGame(
        contestants=contestants,
        num_traitors=num_traitors,
        finale_round=finale_round,
        client=client,
        log_callback=log_handler,
    )
    results = game.run()

    # Add additional data for HTML generation
    results["players"] = game.state.players
    results["messages"] = game.state.messages
    results["private_thoughts"] = getattr(game.state, 'private_thoughts', [])
    results["votes"] = game.state.votes
    results["llm_interactions"] = getattr(game.state, 'llm_interactions', [])
    results["finale_round"] = finale_round

    return results


def run_game_worker(args):
    """Worker function for parallel game execution."""
    game_num, contestants, num_traitors, finale_round, api_key = args

    # Each worker creates its own client for thread safety
    client = anthropic.Anthropic(api_key=api_key)
    game_log = []

    # Run game silently (verbose=False) when in parallel mode
    results = run_single_game(client, contestants, num_traitors, game_log, finale_round, verbose=False)

    return {
        "game_num": game_num,
        "results": results,
        "game_log": game_log,
    }


def generate_run_summary_html(run_id: str, games_data: list, contestants: list) -> str:
    """Generate HTML summary page for a run with competitor stats."""

    # Calculate per-contestant statistics
    contestant_stats = {}
    for c in contestants:
        contestant_stats[c["name"]] = {
            "games_played": 0,
            "times_traitor": 0,
            "times_faithful": 0,
            "wins_as_traitor": 0,
            "wins_as_faithful": 0,
            "survived": 0,
            "banished": 0,
            "murdered": 0,
            "total_prize": 0,
        }

    total_traitor_wins = 0
    total_faithful_wins = 0

    for game in games_data:
        winner = game["winner"]
        if winner == "traitors":
            total_traitor_wins += 1
        else:
            total_faithful_wins += 1

        for name, player in game["players"].items():
            if name not in contestant_stats:
                continue

            stats = contestant_stats[name]
            stats["games_played"] += 1

            if player.is_traitor:
                stats["times_traitor"] += 1
                if winner == "traitors" and player.is_alive:
                    stats["wins_as_traitor"] += 1
            else:
                stats["times_faithful"] += 1
                if winner == "faithful":
                    stats["wins_as_faithful"] += 1

            if player.is_alive:
                stats["survived"] += 1
            elif player.status == PlayerStatus.BANISHED:
                stats["banished"] += 1
            else:
                stats["murdered"] += 1

            # Add prize money from this game
            prize = game.get("prize_distribution", {}).get(name, 0)
            stats["total_prize"] += prize

    # Build games list HTML
    games_list = ""
    for i, game in enumerate(games_data, 1):
        winner_class = "traitor-win" if game["winner"] == "traitors" else "faithful-win"
        winner_text = "Traitors" if game["winner"] == "traitors" else "Faithful"
        traitors = ", ".join(game["traitors"])
        games_list += f"""
        <tr class="{winner_class}-row">
            <td><a href="game_{i}.html">Game {i}</a></td>
            <td class="{winner_class}">{winner_text}</td>
            <td>{game["rounds_played"]}</td>
            <td class="traitor-text">{traitors}</td>
            <td>{len(game["survivors"])}</td>
        </tr>
        """

    # Build contestant stats table
    stats_rows = ""
    for name, stats in sorted(contestant_stats.items(),
                              key=lambda x: (x[1]["wins_as_traitor"] + x[1]["wins_as_faithful"]) / max(x[1]["games_played"], 1),
                              reverse=True):
        if stats["games_played"] == 0:
            continue
        win_rate = ((stats["wins_as_traitor"] + stats["wins_as_faithful"]) / stats["games_played"]) * 100
        survival_rate = (stats["survived"] / stats["games_played"]) * 100
        stats_rows += f"""
        <tr>
            <td class="contestant-name">{html.escape(name)}</td>
            <td>{stats["games_played"]}</td>
            <td><span class="traitor-text">{stats["times_traitor"]}</span> / <span class="faithful-text">{stats["times_faithful"]}</span></td>
            <td>{stats["wins_as_traitor"] + stats["wins_as_faithful"]}</td>
            <td>{win_rate:.0f}%</td>
            <td>${stats["total_prize"]:,}</td>
            <td>{stats["survived"]}</td>
            <td>{survival_rate:.0f}%</td>
            <td>{stats["banished"]}</td>
            <td>{stats["murdered"]}</td>
        </tr>
        """

    # Build contestants cards
    contestants_html = ""
    for c in contestants:
        # Get a short description from the personality prompt
        desc = c.get("personality_prompt", "")
        # Extract first sentence or first 150 chars
        if ". " in desc:
            short_desc = desc.split(". ")[0] + "."
        else:
            short_desc = desc[:150] + "..." if len(desc) > 150 else desc
        # Clean up the "You are X" prefix
        short_desc = short_desc.replace("You are ", "").strip()
        if short_desc and short_desc[0].islower():
            short_desc = short_desc[0].upper() + short_desc[1:]

        contestants_html += f"""
            <div class="contestant-card">
                <div class="contestant-card-name">{html.escape(c["name"])}</div>
                <div class="contestant-card-desc">{html.escape(short_desc)}</div>
            </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Run {run_id} - The Traitors</title>
    <style>
        :root {{
            --bg-dark: #1a1a2e;
            --bg-card: #16213e;
            --accent-red: #e94560;
            --accent-gold: #f4a261;
            --accent-green: #2a9d8f;
            --text-light: #eee;
            --text-muted: #888;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: var(--bg-dark);
            color: var(--text-light);
            line-height: 1.6;
        }}

        .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}

        header {{
            text-align: center;
            padding: 2rem 0;
            background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%);
            border-bottom: 3px solid var(--accent-red);
        }}

        h1 {{ font-size: 2.5rem; color: var(--accent-red); margin-bottom: 0.5rem; }}
        .subtitle {{ color: var(--accent-gold); font-size: 1rem; }}
        .back-link {{ margin-top: 1rem; }}
        .back-link a {{ color: var(--accent-gold); text-decoration: none; }}
        .back-link a:hover {{ text-decoration: underline; }}

        section {{
            margin: 2rem 0;
            padding: 2rem;
            background: var(--bg-card);
            border-radius: 10px;
        }}

        h2 {{
            color: var(--accent-gold);
            border-bottom: 2px solid var(--accent-red);
            padding-bottom: 0.5rem;
            margin-bottom: 1.5rem;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            text-align: center;
            margin-bottom: 2rem;
        }}

        .stat-box {{
            background: rgba(255,255,255,0.05);
            padding: 1.5rem;
            border-radius: 8px;
        }}

        .stat-value {{ font-size: 2rem; font-weight: bold; color: var(--accent-gold); }}
        .stat-label {{ color: var(--text-muted); font-size: 0.9rem; }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            overflow: hidden;
        }}

        th {{
            background: rgba(233, 69, 96, 0.3);
            color: var(--accent-gold);
            padding: 1rem;
            text-align: left;
            font-weight: bold;
        }}

        td {{
            padding: 0.75rem 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}

        tr:hover {{ background: rgba(255,255,255,0.05); }}

        .traitor-win {{ color: var(--accent-red); font-weight: bold; }}
        .faithful-win {{ color: var(--accent-green); font-weight: bold; }}
        .traitor-win-row {{ background: rgba(233, 69, 96, 0.1); }}
        .faithful-win-row {{ background: rgba(42, 157, 143, 0.1); }}
        .traitor-text {{ color: var(--accent-red); }}
        .faithful-text {{ color: var(--accent-green); }}
        .contestant-name {{ font-weight: bold; color: var(--accent-gold); }}

        .contestant-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
        }}

        .contestant-card {{
            background: rgba(255,255,255,0.05);
            padding: 1rem;
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.1);
        }}

        .contestant-card-name {{
            font-size: 1.1rem;
            font-weight: bold;
            color: var(--accent-gold);
            margin-bottom: 0.5rem;
        }}

        .contestant-card-desc {{
            font-size: 0.85rem;
            color: var(--text-muted);
        }}

        a {{ color: var(--accent-gold); }}

        footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
        }}
    </style>
</head>
<body>
    <header>
        <h1>Run: {run_id}</h1>
        <p class="subtitle">{len(games_data)} Games Simulated</p>
        <p class="back-link"><a href="../../index.html">&larr; Back to Home</a></p>
    </header>

    <div class="container">
        <section>
            <h2>Contestants</h2>
            <p style="margin-bottom: 1rem;">This run features {len(contestants)} AI-powered contestants:</p>
            <div class="contestant-grid">
                {contestants_html}
            </div>
        </section>

        <section>
            <h2>Summary Statistics</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-value">{len(games_data)}</div>
                    <div class="stat-label">Games Played</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value traitor-win">{total_traitor_wins}</div>
                    <div class="stat-label">Traitor Wins</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value faithful-win">{total_faithful_wins}</div>
                    <div class="stat-label">Faithful Wins</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value">{total_traitor_wins / len(games_data) * 100:.0f}%</div>
                    <div class="stat-label">Traitor Win Rate</div>
                </div>
            </div>
        </section>

        <section>
            <h2>Games</h2>
            <table>
                <thead>
                    <tr>
                        <th>Game</th>
                        <th>Winner</th>
                        <th>Rounds</th>
                        <th>Traitors</th>
                        <th>Survivors</th>
                    </tr>
                </thead>
                <tbody>
                    {games_list}
                </tbody>
            </table>
        </section>

        <section>
            <h2>Contestant Performance</h2>
            <table>
                <thead>
                    <tr>
                        <th>Contestant</th>
                        <th>Games</th>
                        <th>Role (T/F)</th>
                        <th>Wins</th>
                        <th>Win Rate</th>
                        <th>Prize Won</th>
                        <th>Survived</th>
                        <th>Survival Rate</th>
                        <th>Banished</th>
                        <th>Murdered</th>
                    </tr>
                </thead>
                <tbody>
                    {stats_rows}
                </tbody>
            </table>
        </section>
    </div>

    <footer>
        <p>The Traitors LLM Simulator - Powered by Claude AI</p>
    </footer>
</body>
</html>
"""


def update_main_index(runs_dir: str):
    """Update the main index.html with links to all runs."""
    # Find all run directories
    runs = []
    if os.path.exists(runs_dir):
        for run_id in os.listdir(runs_dir):
            run_path = os.path.join(runs_dir, run_id)
            if os.path.isdir(run_path):
                # Count games in run
                game_count = len([f for f in os.listdir(run_path) if f.startswith("game_") and f.endswith(".html")])

                # Parse run metadata if available
                metadata_path = os.path.join(run_path, "metadata.json")
                if os.path.exists(metadata_path):
                    with open(metadata_path) as f:
                        metadata = json.load(f)
                else:
                    metadata = {}

                runs.append({
                    "id": run_id,
                    "games": game_count,
                    "traitor_wins": metadata.get("traitor_wins", 0),
                    "faithful_wins": metadata.get("faithful_wins", 0),
                    "num_contestants": metadata.get("num_contestants", 12),
                    "num_traitors": metadata.get("num_traitors", 3),
                    "config_name": metadata.get("config_name", ""),
                    "config_description": metadata.get("config_description", ""),
                    "prompt_versions": metadata.get("prompt_versions", {}),
                    "contestants": metadata.get("contestants", []),
                    "avg_rounds": metadata.get("avg_rounds", 0),
                    "timestamp": metadata.get("timestamp", ""),
                })

    # Sort by date descending
    runs.sort(key=lambda x: x["id"], reverse=True)

    # Build runs HTML
    if runs:
        runs_html = ""
        for run in runs:
            # Format timestamp nicely
            if run["timestamp"]:
                try:
                    dt = datetime.fromisoformat(run["timestamp"])
                    time_str = dt.strftime("%b %d, %Y at %H:%M")
                except (ValueError, TypeError):
                    time_str = run["id"]
            else:
                time_str = run["id"]

            # Calculate win rate
            total_games = run["traitor_wins"] + run["faithful_wins"]
            if total_games > 0:
                traitor_rate = (run["traitor_wins"] / total_games) * 100
            else:
                traitor_rate = 0

            # Build badges
            badges = []
            if run["config_name"]:
                badges.append(f'<span class="badge config">{html.escape(run["config_name"])}</span>')

            # Count custom prompts
            custom_prompts = sum(1 for v in run["prompt_versions"].values() if v != "original")
            if custom_prompts > 0:
                badges.append(f'<span class="badge custom">{custom_prompts} custom</span>')

            # Contestant list with version info
            contestants_display = []
            for name in run["contestants"][:6]:
                version = run["prompt_versions"].get(name, "original")
                if version != "original":
                    contestants_display.append(f"{name} (v{version})")
                else:
                    contestants_display.append(name)
            contestants_str = ", ".join(contestants_display)
            if len(run["contestants"]) > 6:
                contestants_str += f" +{len(run['contestants']) - 6} more"

            runs_html += f"""
            <li class="run-item">
                <div class="run-header">
                    <a href="runs/{run['id']}/index.html" class="run-title">{time_str}</a>
                    <div class="run-badges">{''.join(badges)}</div>
                </div>
                <div class="run-meta">
                    <span class="meta-item">
                        <span class="meta-icon">*</span>
                        {run['num_contestants']} contestants ({run['num_traitors']} traitors)
                    </span>
                    <span class="meta-item">
                        <span class="meta-icon">#</span>
                        {run['games']} games, ~{run['avg_rounds']:.1f} rounds avg
                    </span>
                </div>
                <div class="run-description">{html.escape(run['config_description']) if run['config_description'] else ''}</div>
                <div class="run-contestants">{html.escape(contestants_str) if contestants_str else 'Original contestants'}</div>
                <div class="run-stats">
                    <div class="run-stat">
                        <div class="run-stat-value traitor-text">{run['traitor_wins']}</div>
                        <div class="run-stat-label">Traitor Wins</div>
                    </div>
                    <div class="run-stat">
                        <div class="run-stat-value faithful-text">{run['faithful_wins']}</div>
                        <div class="run-stat-label">Faithful Wins</div>
                    </div>
                    <div class="run-stat">
                        <div class="run-stat-value" style="color: {'var(--accent-red)' if traitor_rate > 50 else 'var(--accent-green)' if traitor_rate < 50 else 'var(--text-light)'};">{traitor_rate:.0f}%</div>
                        <div class="run-stat-label">Traitor Rate</div>
                    </div>
                </div>
            </li>
            """
    else:
        runs_html = '<li class="no-runs">No game runs yet. Run <code>python run_games.py</code> to simulate games.</li>'

    # Read and update index.html
    with open("index.html", "r") as f:
        content = f.read()

    # Replace the runs placeholder
    content = re.sub(
        r'(<ul class="runs-list" id="runs-list">).*?(</ul>)',
        f'\\1\n                {runs_html}\n            \\2',
        content,
        flags=re.DOTALL
    )

    with open("index.html", "w") as f:
        f.write(content)


def update_prompt_stats(contestants: list, games_data: list):
    """Update stats in prompt files based on game results."""
    prompts_dir = Path(__file__).parent / "prompts"

    for game in games_data:
        for name, player in game["players"].items():
            # Find contestant with prompt file
            contestant = next((c for c in contestants if c["name"] == name), None)
            if not contestant or "_prompt_file" not in contestant:
                continue

            prompt_file = prompts_dir / contestant["_prompt_file"]
            if not prompt_file.exists():
                continue

            try:
                with open(prompt_file) as f:
                    data = json.load(f)

                stats = data.get("stats", {
                    "games_played": 0,
                    "times_traitor": 0,
                    "times_faithful": 0,
                    "wins_as_traitor": 0,
                    "wins_as_faithful": 0,
                    "survived": 0,
                    "banished": 0,
                    "murdered": 0
                })

                stats["games_played"] += 1

                if player.is_traitor:
                    stats["times_traitor"] += 1
                    if game["winner"] == "traitors" and player.is_alive:
                        stats["wins_as_traitor"] += 1
                else:
                    stats["times_faithful"] += 1
                    if game["winner"] == "faithful":
                        stats["wins_as_faithful"] += 1

                if player.is_alive:
                    stats["survived"] += 1
                elif player.status == PlayerStatus.BANISHED:
                    stats["banished"] += 1
                else:
                    stats["murdered"] += 1

                data["stats"] = stats

                with open(prompt_file, "w") as f:
                    json.dump(data, f, indent=2)

            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Could not update stats for {prompt_file}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Run multiple Traitors games")
    parser.add_argument("--config", "-c", type=str, required=True,
                        help="Path to game configuration file (e.g., configs/baseline.json)")
    parser.add_argument("--num-games", "-n", type=int,
                        help="Override number of games from config")
    parser.add_argument("--parallel", "-p", type=int, default=1, metavar="N",
                        help="Run N games in parallel (default: 1, sequential)")
    args = parser.parse_args()

    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required.")
        return 1

    client = anthropic.Anthropic(api_key=api_key)

    # Load configuration
    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}")
        return 1

    config = load_config(args.config)
    config_name = config.get("name", os.path.basename(args.config))

    # Load contestants from config
    try:
        contestants = load_contestants_from_config(config)
    except ValueError as e:
        print(f"Error loading contestants: {e}")
        return 1

    # Get run parameters (command line overrides config)
    num_games = args.num_games if args.num_games else config.get("num_games", 3)
    num_traitors = config.get("num_traitors", 3)
    finale_round = config.get("finale_round", 8)  # UK Celebrity format default

    # Create run directory
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join("runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    # Save a copy of the config used
    with open(os.path.join(run_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    print(f"Starting run: {run_id}")
    print(f"Config: {config_name}")
    if config.get("description"):
        print(f"Description: {config['description']}")
    print(f"Running {num_games} game(s) with {num_traitors} traitors (finale after round {finale_round})...")
    if args.parallel > 1:
        print(f"Parallel execution: {args.parallel} games at a time")
    print(f"Contestants ({len(contestants)}): {', '.join(c['name'] for c in contestants)}")
    print("=" * 60)

    games_data = []
    game_logs = {}

    if args.parallel > 1:
        # Parallel execution
        print(f"\nRunning {num_games} games in parallel (max {args.parallel} concurrent)...")

        # Prepare work items
        work_items = [
            (i, contestants, num_traitors, finale_round, api_key)
            for i in range(1, num_games + 1)
        ]

        completed = 0
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {executor.submit(run_game_worker, item): item[0] for item in work_items}

            for future in as_completed(futures):
                game_num = futures[future]
                try:
                    result = future.result()
                    games_data.append((result["game_num"], result["results"]))
                    game_logs[result["game_num"]] = result["game_log"]
                    completed += 1
                    winner = result["results"]["winner"].upper()
                    print(f"  Game {result['game_num']} complete: {winner} win ({completed}/{num_games})")
                except Exception as e:
                    print(f"  Game {game_num} failed: {e}")

        # Sort by game number
        games_data.sort(key=lambda x: x[0])
        games_data = [g[1] for g in games_data]

        # Generate JSON and HTML files for each game
        print("\nGenerating game files...")
        for i, results in enumerate(games_data, 1):
            game_log = game_logs.get(i, [])
            # Save JSON
            save_game_json(run_dir, i, results, game_log)
            # Save HTML (for backwards compatibility)
            game_html = generate_game_html(results, game_log, contestants,
                                           back_link=f"index.html",
                                           title=f"Game {i}")
            game_path = os.path.join(run_dir, f"game_{i}.html")
            with open(game_path, "w") as f:
                f.write(game_html)

    else:
        # Sequential execution (original behavior)
        for i in range(1, num_games + 1):
            print(f"\n{'='*60}")
            print(f"GAME {i} of {num_games}")
            print(f"{'='*60}\n")

            game_log = []
            results = run_single_game(client, contestants, num_traitors, game_log, finale_round)
            games_data.append(results)

            # Save JSON
            json_path = save_game_json(run_dir, i, results, game_log)

            # Generate individual game HTML (for backwards compatibility)
            game_html = generate_game_html(results, game_log, contestants,
                                           back_link=f"index.html",
                                           title=f"Game {i}")

            game_path = os.path.join(run_dir, f"game_{i}.html")
            with open(game_path, "w") as f:
                f.write(game_html)

            print(f"\nGame {i} complete: {results['winner'].upper()} win")
            print(f"Saved to: {json_path}")

    # Generate run summary
    print(f"\n{'='*60}")
    print("Generating run summary...")

    # Save run JSON (new format)
    run_json_path = save_run_json(run_dir, run_id, config, games_data, contestants)
    print(f"Saved: {run_json_path}")

    # Generate run summary HTML (for backwards compatibility)
    summary_html = generate_run_summary_html(run_id, games_data, contestants)
    summary_path = os.path.join(run_dir, "index.html")
    with open(summary_path, "w") as f:
        f.write(summary_html)

    # Save comprehensive metadata for legacy index updates
    metadata = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "config_name": config_name,
        "config_description": config.get("description", ""),
        "num_games": num_games,
        "num_contestants": len(contestants),
        "num_traitors": num_traitors,
        "traitor_wins": sum(1 for g in games_data if g["winner"] == "traitors"),
        "faithful_wins": sum(1 for g in games_data if g["winner"] == "faithful"),
        "contestants": [c["name"] for c in contestants],
        "prompt_versions": {
            c["name"]: c.get("_version", "original")
            for c in contestants
        },
        "avg_rounds": sum(g["rounds_played"] for g in games_data) / len(games_data) if games_data else 0,
    }
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    # Update prompt stats for contestants with prompt files
    has_custom_prompts = any(c.get("_prompt_file") for c in contestants)
    if has_custom_prompts:
        print("Updating prompt stats...")
        update_prompt_stats(contestants, games_data)

    # Update global runs index (new JSON format)
    update_runs_index("runs", "data")

    print(f"\nRun complete!")
    print(f"Run summary: {summary_path}")
    print(f"Global index updated: data/runs.json")
    print(f"View results at: index.html")

    return 0


if __name__ == "__main__":
    exit(main())
