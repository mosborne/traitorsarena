#!/usr/bin/env python3
"""
Run multiple game iterations and generate summary statistics.

Usage:
    python run_games.py [num_iterations]

Example:
    python run_games.py 5   # Run 5 game iterations
"""

import argparse
import html
import json
import os
import re
from datetime import datetime

import anthropic

from main import EXAMPLE_CONTESTANTS
from traitors import TraitorsGame
from traitors.types import PlayerStatus
from generate_html import generate_game_html


def run_single_game(client, contestants, num_traitors, game_log):
    """Run a single game and return results."""
    game = TraitorsGame(
        contestants=contestants,
        num_traitors=num_traitors,
        client=client,
        log_callback=lambda msg: game_log.append(msg) or print(msg),
    )
    results = game.run()

    # Add additional data for HTML generation
    results["players"] = game.state.players
    results["messages"] = game.state.messages
    results["private_thoughts"] = getattr(game.state, 'private_thoughts', [])
    results["votes"] = game.state.votes

    return results


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
                    metadata = {"traitor_wins": 0, "faithful_wins": 0}

                runs.append({
                    "id": run_id,
                    "games": game_count,
                    "traitor_wins": metadata.get("traitor_wins", 0),
                    "faithful_wins": metadata.get("faithful_wins", 0),
                })

    # Sort by date descending
    runs.sort(key=lambda x: x["id"], reverse=True)

    # Build runs HTML
    if runs:
        runs_html = ""
        for run in runs:
            runs_html += f"""
            <li class="run-item">
                <a href="runs/{run['id']}/index.html">{run['id']}</a>
                <div class="run-stats">
                    <div class="run-stat">
                        <div class="run-stat-value">{run['games']}</div>
                        <div class="run-stat-label">Games</div>
                    </div>
                    <div class="run-stat">
                        <div class="run-stat-value traitor-text">{run['traitor_wins']}</div>
                        <div class="run-stat-label">Traitor Wins</div>
                    </div>
                    <div class="run-stat">
                        <div class="run-stat-value faithful-text">{run['faithful_wins']}</div>
                        <div class="run-stat-label">Faithful Wins</div>
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


def main():
    parser = argparse.ArgumentParser(description="Run multiple Traitors games")
    parser.add_argument("num_games", type=int, nargs="?", default=3,
                        help="Number of games to run (default: 3)")
    args = parser.parse_args()

    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required.")
        return 1

    client = anthropic.Anthropic(api_key=api_key)

    # Create run directory
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join("runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    print(f"Starting run: {run_id}")
    print(f"Running {args.num_games} game(s)...")
    print("=" * 60)

    games_data = []

    for i in range(1, args.num_games + 1):
        print(f"\n{'='*60}")
        print(f"GAME {i} of {args.num_games}")
        print(f"{'='*60}\n")

        game_log = []
        results = run_single_game(client, EXAMPLE_CONTESTANTS, 3, game_log)
        games_data.append(results)

        # Generate individual game HTML
        game_html = generate_game_html(results, game_log, EXAMPLE_CONTESTANTS,
                                       back_link=f"index.html",
                                       title=f"Game {i}")

        game_path = os.path.join(run_dir, f"game_{i}.html")
        with open(game_path, "w") as f:
            f.write(game_html)

        print(f"\nGame {i} complete: {results['winner'].upper()} win")
        print(f"Saved to: {game_path}")

    # Generate run summary
    print(f"\n{'='*60}")
    print("Generating run summary...")

    summary_html = generate_run_summary_html(run_id, games_data, EXAMPLE_CONTESTANTS)
    summary_path = os.path.join(run_dir, "index.html")
    with open(summary_path, "w") as f:
        f.write(summary_html)

    # Save metadata for index updates
    metadata = {
        "traitor_wins": sum(1 for g in games_data if g["winner"] == "traitors"),
        "faithful_wins": sum(1 for g in games_data if g["winner"] == "faithful"),
    }
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f)

    # Update main index
    update_main_index("runs")

    print(f"\nRun complete!")
    print(f"Summary: {summary_path}")
    print(f"Main index updated: index.html")

    return 0


if __name__ == "__main__":
    exit(main())
