#!/usr/bin/env python3
"""
Run multiple game iterations and generate summary statistics.

Usage:
    python run_games.py --config configs/baseline.json
    python run_games.py --config configs/experimental_v1.json

The config file specifies contestants, number of games, and other parameters.
"""

from dotenv import load_dotenv
load_dotenv()  # Load .env file before other imports

import argparse
import html
import json
import os
import random
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic

from traitors import TraitorsGame, OllamaAgent, GeminiAgent, TestAgent, Agent
from traitors.types import PlayerStatus
from generate_html import generate_game_html
from data_store import save_game_json, save_run_json, update_runs_index
from generate_players_json import main as generate_players_json


def generate_run_analysis(stats: dict, contestant_stats: dict) -> dict:
    """Generate LLM analysis of run results using Claude Opus with extended thinking."""

    # Sort by wins then survival
    sorted_stats = sorted(
        contestant_stats.items(),
        key=lambda x: (x[1]['wins'], x[1]['survived']),
        reverse=True
    )

    def format_player(key, s):
        win_rate = round(s['wins'] / s['games_played'] * 100) if s['games_played'] > 0 else 0
        surv_rate = round(s['survived'] / s['games_played'] * 100) if s['games_played'] > 0 else 0
        murder_rate = round(s['murdered'] / s['games_played'] * 100) if s['games_played'] > 0 else 0
        return f"- {s['name']}: {s['wins']} wins ({win_rate}%), {surv_rate}% survival, {murder_rate}% murdered"

    top_5 = "\n".join(format_player(k, s) for k, s in sorted_stats[:5])
    bottom_5 = "\n".join(format_player(k, s) for k, s in sorted_stats[-5:])

    traitor_rate = round(stats['traitor_wins'] / stats['total_games'] * 100)

    prompt = f"""Analyze this Traitors game simulation run:

**Summary:** {stats['total_games']} games, Traitors won {stats['traitor_wins']} ({traitor_rate}%), Faithful won {stats['faithful_wins']}, avg {stats['avg_rounds']:.1f} rounds

**Top 5 Performers:**
{top_5}

**Bottom 5 Performers:**
{bottom_5}

Write 3-4 paragraphs analyzing:
1. Game balance (is {traitor_rate}% traitor win rate high/low/balanced?)
2. Who dominated and potential reasons (survival patterns, murder avoidance)
3. Who struggled and why (high murder/banishment rates)
4. Notable patterns or insights

Be specific with numbers. Keep it engaging but concise."""

    # Always use Opus with extended thinking for high-quality analysis
    # Use streaming since extended thinking can take >10 minutes
    client = anthropic.Anthropic()
    content = ""
    with client.messages.stream(
        model="claude-opus-4-20250514",
        max_tokens=16000,
        temperature=1,  # Required for extended thinking
        thinking={
            "type": "enabled",
            "budget_tokens": 10000  # Allow deep analysis
        },
        messages=[{"role": "user", "content": prompt}]
    ) as stream:
        for event in stream:
            # Collect text content (skip thinking blocks)
            if hasattr(event, 'type') and event.type == 'content_block_delta':
                if hasattr(event.delta, 'text'):
                    content += event.delta.text

    return {
        "generated_at": datetime.now().isoformat(),
        "model": "claude-opus-4-20250514",
        "content": content
    }


# Map provider names to agent classes
PROVIDER_MAP = {
    "anthropic": Agent,
    "ollama": OllamaAgent,
    "gemini": GeminiAgent,
    "test": TestAgent,
}

# Default models per provider
DEFAULT_MODELS = {
    "anthropic": "claude-3-5-haiku-20241022",
    "ollama": "llama3.2",
    "gemini": "gemini-2.0-flash-lite",
    "test": None,
}

# UK Traitors format: always 19 players per game
PLAYERS_PER_GAME = 19


def select_contestants_for_game(pool: list[dict]) -> list[dict]:
    """Randomly select 19 players from pool for a single game."""
    if len(pool) < PLAYERS_PER_GAME:
        raise ValueError(f"Pool has {len(pool)} players but need at least {PLAYERS_PER_GAME}")
    if len(pool) == PLAYERS_PER_GAME:
        return pool.copy()
    return random.sample(pool, PLAYERS_PER_GAME)


def load_config(config_path: str) -> dict:
    """Load a game configuration file."""
    with open(config_path) as f:
        return json.load(f)


def load_contestants_from_config(config: dict) -> list[dict]:
    """
    Load contestants based on config specification.

    Each contestant entry should have: {"file": "player.json"}
    Optionally with a per-contestant model: {"file": "player.json", "model": "llama3.2"}

    The default_model from config is used if no per-contestant model is specified.
    """
    prompts_dir = Path(__file__).parent / "prompts"
    contestants = []
    default_model = config.get("default_model")

    for entry in config.get("contestants", []):
        prompt_file = entry["file"]
        path = prompts_dir / prompt_file
        if not path.exists():
            raise ValueError(f"Prompt file not found: {prompt_file}")

        with open(path) as f:
            data = json.load(f)

        # Per-contestant model takes precedence, then default_model from config
        contestant_model = entry.get("model", default_model)

        contestant = {
            "name": data["name"],
            "personality_prompt": data["personality_prompt"],
            "_prompt_file": prompt_file,
            "_version": data.get("version", "1.0"),
        }
        if contestant_model:
            contestant["model"] = contestant_model
        contestants.append(contestant)

    return contestants


def load_all_contestants(default_model: str = None) -> list[dict]:
    """Load all contestants from the prompts directory."""
    prompts_dir = Path(__file__).parent / "prompts"
    contestants = []

    for path in sorted(prompts_dir.glob("*.json")):
        with open(path) as f:
            data = json.load(f)

        contestant = {
            "name": data["name"],
            "personality_prompt": data["personality_prompt"],
            "_prompt_file": path.name,
            "_version": data.get("version", "1.0"),
        }
        if default_model:
            contestant["model"] = default_model
        contestants.append(contestant)

    return contestants


def run_single_game(client, contestants, num_traitors, game_log, finale_round=8, verbose=True,
                    agent_class=None, model=None, enable_caching=True):
    """Run a single game and return (results, duration_sec)."""
    import time
    start_time = time.time()

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
        agent_class=agent_class,
        model=model,
        enable_caching=enable_caching,
    )
    results = game.run()

    duration_sec = time.time() - start_time

    # Add additional data for HTML generation
    results["players"] = game.state.players
    results["messages"] = game.state.messages
    results["private_thoughts"] = getattr(game.state, 'private_thoughts', [])
    results["votes"] = game.state.votes
    results["llm_interactions"] = getattr(game.state, 'llm_interactions', [])
    results["finale_round"] = finale_round

    return results, duration_sec


def run_game_worker(args):
    """Worker function for parallel game execution."""
    game_num, contestants, num_traitors, finale_round, api_key, agent_class, model, enable_caching = args

    # Create client only for Anthropic provider
    if agent_class == Agent:
        client = anthropic.Anthropic(api_key=api_key)
    else:
        client = None

    game_log = []

    # Run game silently (verbose=False) when in parallel mode
    results, duration_sec = run_single_game(client, contestants, num_traitors, game_log, finale_round,
                              verbose=False, agent_class=agent_class, model=model,
                              enable_caching=enable_caching)

    return {
        "game_num": game_num,
        "results": results,
        "game_log": game_log,
        "duration_sec": duration_sec,
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


def git_push_progress(run_dir: str, run_id: str, game_num: int, total_games: int, final: bool = False):
    """Commit and push current progress to GitHub."""
    try:
        # Add the run directory and data index
        subprocess.run(["git", "add", run_dir, "data/runs.json"], check=True, capture_output=True)

        # Commit with progress message
        if final:
            msg = f"Run complete with analysis - {run_id} ({total_games} games)"
        else:
            msg = f"Game {game_num}/{total_games} - {run_id}"
        subprocess.run(["git", "commit", "-m", msg], check=True, capture_output=True)

        # Push
        subprocess.run(["git", "push"], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Warning: Git push failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Run multiple Traitors games")
    parser.add_argument("--config", "-c", type=str, required=True,
                        help="Path to game configuration file (e.g., configs/baseline.json)")
    parser.add_argument("--num-games", "-n", type=int,
                        help="Override number of games from config")
    parser.add_argument("--parallel", "-p", type=int, default=1, metavar="N",
                        help="Run N games in parallel (default: 1, sequential)")
    parser.add_argument("--provider", type=str,
                        choices=["anthropic", "ollama", "gemini", "test"],
                        help="LLM provider to use (default: from config or anthropic)")
    parser.add_argument("--model", "-m", type=str,
                        help="Model name (default depends on provider: claude-3-5-haiku for anthropic, llama3.2 for ollama)")
    parser.add_argument("--auto-push", action="store_true",
                        help="Git commit and push after each game (for GitHub Pages progress)")
    args = parser.parse_args()

    # Load configuration first (needed for provider detection)
    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}")
        return 1

    config = load_config(args.config)

    # Determine provider: CLI > config > default
    provider = args.provider or config.get("provider", "anthropic")

    # Get agent class and model based on provider
    agent_class = PROVIDER_MAP[provider]
    model = args.model or config.get("default_model") or DEFAULT_MODELS[provider]

    # Check for API keys based on provider
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if provider == "anthropic" and not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required for Anthropic provider.")
        print("Use --provider ollama for free local inference, --provider gemini for Gemini, or --provider test for testing.")
        return 1

    if provider == "gemini" and not gemini_key:
        print("Error: GEMINI_API_KEY environment variable is required for Gemini provider.")
        print("Get your API key from https://aistudio.google.com/")
        return 1

    # Create client only for Anthropic provider
    if provider == "anthropic":
        client = anthropic.Anthropic(api_key=api_key)
    else:
        client = None
    config_name = config.get("name", os.path.basename(args.config))

    # Load contestants from config
    # Support both fixed roster (contestants) and random pool (player_pool)
    use_pool = "player_pool" in config
    try:
        if use_pool:
            # Load all pool members
            if config["player_pool"] == "all":
                # Load all players from prompts directory
                player_pool = load_all_contestants(config.get("default_model"))
            else:
                pool_config = {**config, "contestants": config["player_pool"]}
                player_pool = load_contestants_from_config(pool_config)
            if len(player_pool) < PLAYERS_PER_GAME:
                print(f"Error: Pool has {len(player_pool)} players but need at least {PLAYERS_PER_GAME}")
                return 1
            # For display, use full pool but games will select from it
            contestants = player_pool
        else:
            contestants = load_contestants_from_config(config)
            player_pool = None
    except ValueError as e:
        print(f"Error loading contestants: {e}")
        return 1

    # Get run parameters (command line overrides config)
    num_games = args.num_games if args.num_games else config.get("num_games", 3)
    num_traitors = config.get("num_traitors", 3)
    finale_round = config.get("finale_round", 8)  # UK Celebrity format default
    enable_caching = config.get("enable_caching", True)  # Only affects Gemini provider

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
    print(f"Provider: {provider} (model: {model or 'default'})")
    if provider == "gemini":
        print(f"Caching: {'enabled' if enable_caching else 'DISABLED'}")
    print(f"Running {num_games} game(s) with {num_traitors} traitors (finale after round {finale_round})...")
    if args.parallel > 1:
        print(f"Parallel execution: {args.parallel} games at a time")
    if args.auto_push:
        print(f"Auto-push enabled: pushing to GitHub after each game")
    if use_pool:
        print(f"Pool mode: {len(player_pool)} players, {PLAYERS_PER_GAME} selected per game")
    else:
        print(f"Contestants ({len(contestants)}): {', '.join(c['name'] for c in contestants)}")
    print("=" * 60)

    games_data = []
    games_durations = []  # Track durations for all games
    game_logs = {}

    # For pool mode, track full pool for stats (games_played will vary per player)
    all_contestants = player_pool if use_pool else contestants
    pool_size = len(player_pool) if use_pool else None

    if args.parallel > 1:
        # Parallel execution
        print(f"\nRunning {num_games} games in parallel (max {args.parallel} concurrent)...")

        # Prepare work items (select per-game contestants if using pool)
        work_items = []
        for i in range(1, num_games + 1):
            if use_pool:
                game_contestants = select_contestants_for_game(player_pool)
            else:
                game_contestants = contestants
            work_items.append(
                (i, game_contestants, num_traitors, finale_round, api_key, agent_class, model, enable_caching)
            )

        completed = 0
        games_data_tuples = []  # Store as tuples for sorting
        games_durations_dict = {}  # Track durations by game number
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {executor.submit(run_game_worker, item): item[0] for item in work_items}

            for future in as_completed(futures):
                game_num = futures[future]
                try:
                    result = future.result()
                    games_data_tuples.append((result["game_num"], result["results"]))
                    game_logs[result["game_num"]] = result["game_log"]
                    games_durations_dict[result["game_num"]] = result["duration_sec"]
                    completed += 1
                    winner = result["results"]["winner"].upper()
                    duration_min = result["duration_sec"] / 60
                    print(f"  Game {result['game_num']} complete: {winner} win ({completed}/{num_games}) [{duration_min:.1f} min]")

                    # Save individual game files immediately
                    gn = result["game_num"]
                    save_game_json(run_dir, gn, result["results"], result["game_log"],
                                   duration_sec=result["duration_sec"])
                    game_html = generate_game_html(result["results"], result["game_log"], contestants,
                                                   back_link=f"index.html", title=f"Game {gn}")
                    with open(os.path.join(run_dir, f"game_{gn}.html"), "w") as f:
                        f.write(game_html)

                    # Update run progress (sort games_data for consistent stats)
                    games_data_tuples.sort(key=lambda x: x[0])
                    games_data = [g[1] for g in games_data_tuples]
                    # Build sorted durations list
                    sorted_durations = [games_durations_dict[i] for i in sorted(games_durations_dict.keys())]
                    save_run_json(run_dir, run_id, config, games_data, all_contestants, pool_size,
                                  games_durations=sorted_durations)
                    update_runs_index("runs", "data")

                    # Git push if enabled
                    if args.auto_push:
                        if git_push_progress(run_dir, run_id, completed, num_games):
                            print(f"    Pushed to GitHub ({completed}/{num_games})")

                except Exception as e:
                    print(f"  Game {game_num} failed: {e}")

        # Final sort after all games
        games_data_tuples.sort(key=lambda x: x[0])
        games_data = [g[1] for g in games_data_tuples]
        # Convert durations dict to sorted list
        games_durations = [games_durations_dict[i] for i in sorted(games_durations_dict.keys())]

    else:
        # Sequential execution (original behavior)
        for i in range(1, num_games + 1):
            print(f"\n{'='*60}")
            print(f"GAME {i} of {num_games}")
            print(f"{'='*60}\n")

            # Select contestants for this game (random if using pool)
            if use_pool:
                game_contestants = select_contestants_for_game(player_pool)
                print(f"Selected: {', '.join(c['name'] for c in game_contestants)}\n")
            else:
                game_contestants = contestants

            game_log = []
            results, duration_sec = run_single_game(client, game_contestants, num_traitors, game_log, finale_round,
                                     agent_class=agent_class, model=model, enable_caching=enable_caching)
            games_data.append(results)
            games_durations.append(duration_sec)

            # Save JSON
            json_path = save_game_json(run_dir, i, results, game_log, duration_sec=duration_sec)

            # Generate individual game HTML (for backwards compatibility)
            game_html = generate_game_html(results, game_log, game_contestants,
                                           back_link=f"index.html",
                                           title=f"Game {i}")

            game_path = os.path.join(run_dir, f"game_{i}.html")
            with open(game_path, "w") as f:
                f.write(game_html)

            duration_min = duration_sec / 60
            print(f"\nGame {i} complete: {results['winner'].upper()} win [{duration_min:.1f} min]")
            print(f"Saved to: {json_path}")

            # Update run progress after each game
            save_run_json(run_dir, run_id, config, games_data, all_contestants, pool_size,
                          games_durations=games_durations)
            update_runs_index("runs", "data")

            # Git push if enabled
            if args.auto_push:
                if git_push_progress(run_dir, run_id, i, num_games):
                    print(f"  Pushed to GitHub ({i}/{num_games})")

    # Generate final run summary
    print(f"\n{'='*60}")
    print("Generating final run summary...")

    # Save run JSON (will be updated again after analysis)
    run_json_path = save_run_json(run_dir, run_id, config, games_data, all_contestants, pool_size,
                                   games_durations=games_durations)
    print(f"Saved: {run_json_path}")

    # Generate analysis (always uses Opus with extended thinking)
    print("Generating run analysis with Claude Opus...")
    with open(run_json_path) as f:
        run_data = json.load(f)
    analysis = generate_run_analysis(run_data["stats"], run_data["contestant_stats"])
    run_data["analysis"] = analysis
    with open(run_json_path, "w") as f:
        json.dump(run_data, f, indent=2)
    print("Analysis complete.")

    # Generate run summary HTML (for backwards compatibility)
    summary_html = generate_run_summary_html(run_id, games_data, all_contestants)
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
        "num_contestants": len(all_contestants),
        "num_traitors": num_traitors,
        "traitor_wins": sum(1 for g in games_data if g["winner"] == "traitors"),
        "faithful_wins": sum(1 for g in games_data if g["winner"] == "faithful"),
        "contestants": [c["name"] for c in all_contestants],
        "prompt_versions": {
            c["name"]: c.get("_version", "original")
            for c in all_contestants
        },
        "avg_rounds": sum(g["rounds_played"] for g in games_data) / len(games_data) if games_data else 0,
    }
    if use_pool:
        metadata["pool_size"] = len(player_pool)
    with open(os.path.join(run_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    # Update prompt stats for contestants with prompt files
    has_custom_prompts = any(c.get("_prompt_file") for c in all_contestants)
    if has_custom_prompts:
        print("Updating prompt stats...")
        update_prompt_stats(all_contestants, games_data)

    # Update global runs index (new JSON format)
    update_runs_index("runs", "data")

    # Regenerate players.json with updated stats
    print("Regenerating players.json...")
    generate_players_json()

    # Final git push with analysis
    if args.auto_push:
        if git_push_progress(run_dir, run_id, num_games, num_games, final=True):
            print("Final push to GitHub complete (with analysis)")

    print(f"\nRun complete!")
    print(f"Run summary: {summary_path}")
    print(f"Global index updated: data/runs.json")
    print(f"Player stats updated: data/players.json")
    print(f"View results at: index.html")

    return 0


if __name__ == "__main__":
    exit(main())
