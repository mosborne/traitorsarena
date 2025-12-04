#!/usr/bin/env python3
"""Generate the HTML index page with game results."""

import html
from traitors import DemoGame
from main import EXAMPLE_CONTESTANTS


def generate_html(results: dict, game_log: list[str]) -> str:
    """Generate the HTML page with game explanation and results."""

    # Build the game log HTML
    game_log_html = "\n".join(f"<div class='log-line'>{html.escape(line)}</div>" for line in game_log)

    # Build contestant cards
    contestant_cards = ""
    for contestant in EXAMPLE_CONTESTANTS:
        role = "traitor" if contestant["name"] in results["traitors"] else "faithful"
        status = "survived" if contestant["name"] in results["survivors"] else "eliminated"

        # Get fate
        player = results["players"].get(contestant["name"])
        if player:
            if player.is_alive:
                fate = "Survived"
                fate_class = "survived"
            elif player.status.value == "banished":
                fate = "Banished"
                fate_class = "banished"
            else:
                fate = "Murdered"
                fate_class = "murdered"
        else:
            fate = "Unknown"
            fate_class = ""

        contestant_cards += f"""
        <div class="contestant-card {role} {fate_class}">
            <div class="contestant-name">{html.escape(contestant["name"])}</div>
            <div class="contestant-role">{role.upper()}</div>
            <div class="contestant-fate">{fate}</div>
            <div class="contestant-personality">{html.escape(contestant["personality_prompt"][:150])}...</div>
        </div>
        """

    # Build round summary
    rounds_html = ""
    current_round = 0
    for msg in results["messages"]:
        if msg.round_num != current_round:
            if current_round > 0:
                rounds_html += "</div>"
            current_round = msg.round_num
            rounds_html += f"<div class='round-section'><h4>Round {current_round}</h4>"

        private_class = "private-msg" if msg.is_private else ""
        private_label = "[TRAITOR SECRET] " if msg.is_private else ""
        rounds_html += f"""
        <div class="message {private_class}">
            <span class="speaker">{html.escape(msg.speaker)}:</span>
            <span class="content">{html.escape(private_label)}{html.escape(msg.content)}</span>
        </div>
        """
    if current_round > 0:
        rounds_html += "</div>"

    # Determine winner styling
    winner_class = "faithful-win" if results["winner"] == "faithful" else "traitor-win"
    winner_text = "THE FAITHFUL" if results["winner"] == "faithful" else "THE TRAITORS"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Traitors - LLM Game Simulator</title>
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

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: var(--bg-dark);
            color: var(--text-light);
            line-height: 1.6;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }}

        header {{
            text-align: center;
            padding: 3rem 0;
            background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%);
            border-bottom: 3px solid var(--accent-red);
        }}

        h1 {{
            font-size: 3rem;
            color: var(--accent-red);
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
            margin-bottom: 0.5rem;
        }}

        .subtitle {{
            color: var(--accent-gold);
            font-size: 1.2rem;
        }}

        section {{
            margin: 2rem 0;
            padding: 2rem;
            background: var(--bg-card);
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }}

        h2 {{
            color: var(--accent-gold);
            border-bottom: 2px solid var(--accent-red);
            padding-bottom: 0.5rem;
            margin-bottom: 1.5rem;
        }}

        h3 {{
            color: var(--accent-green);
            margin: 1.5rem 0 1rem;
        }}

        h4 {{
            color: var(--text-light);
            margin: 1rem 0 0.5rem;
        }}

        .rules-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
        }}

        .rule-card {{
            background: rgba(255,255,255,0.05);
            padding: 1.5rem;
            border-radius: 8px;
            border-left: 4px solid var(--accent-gold);
        }}

        .rule-card h4 {{
            color: var(--accent-gold);
            margin-bottom: 0.5rem;
        }}

        .parameters {{
            background: #0a0a15;
            padding: 1.5rem;
            border-radius: 8px;
            font-family: 'Consolas', monospace;
        }}

        .param {{
            margin: 0.5rem 0;
        }}

        .param-name {{
            color: var(--accent-green);
        }}

        .param-value {{
            color: var(--accent-gold);
        }}

        .contestant-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
        }}

        .contestant-card {{
            background: rgba(255,255,255,0.05);
            padding: 1.5rem;
            border-radius: 8px;
            position: relative;
            overflow: hidden;
        }}

        .contestant-card.traitor {{
            border: 2px solid var(--accent-red);
        }}

        .contestant-card.faithful {{
            border: 2px solid var(--accent-green);
        }}

        .contestant-card.banished::after,
        .contestant-card.murdered::after {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            pointer-events: none;
        }}

        .contestant-name {{
            font-size: 1.5rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }}

        .contestant-role {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: bold;
            margin-bottom: 0.5rem;
        }}

        .traitor .contestant-role {{
            background: var(--accent-red);
        }}

        .faithful .contestant-role {{
            background: var(--accent-green);
        }}

        .contestant-fate {{
            color: var(--text-muted);
            font-style: italic;
            margin-bottom: 0.5rem;
        }}

        .contestant-personality {{
            font-size: 0.9rem;
            color: var(--text-muted);
        }}

        .winner-banner {{
            text-align: center;
            padding: 2rem;
            border-radius: 10px;
            margin: 2rem 0;
        }}

        .faithful-win {{
            background: linear-gradient(135deg, #1a4d4d 0%, #2a9d8f 100%);
            border: 3px solid var(--accent-green);
        }}

        .traitor-win {{
            background: linear-gradient(135deg, #4a1a2e 0%, #e94560 100%);
            border: 3px solid var(--accent-red);
        }}

        .winner-text {{
            font-size: 2.5rem;
            font-weight: bold;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
        }}

        .round-section {{
            margin: 1.5rem 0;
            padding: 1rem;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
        }}

        .message {{
            margin: 0.75rem 0;
            padding: 0.5rem;
            background: rgba(255,255,255,0.03);
            border-radius: 4px;
        }}

        .private-msg {{
            background: rgba(233, 69, 96, 0.15);
            border-left: 3px solid var(--accent-red);
        }}

        .speaker {{
            font-weight: bold;
            color: var(--accent-gold);
        }}

        .content {{
            color: var(--text-light);
        }}

        .game-log {{
            background: #0a0a15;
            padding: 1rem;
            border-radius: 8px;
            max-height: 500px;
            overflow-y: auto;
            font-family: 'Consolas', monospace;
            font-size: 0.85rem;
        }}

        .log-line {{
            padding: 0.1rem 0;
            white-space: pre-wrap;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            text-align: center;
        }}

        .stat-box {{
            background: rgba(255,255,255,0.05);
            padding: 1.5rem;
            border-radius: 8px;
        }}

        .stat-value {{
            font-size: 2rem;
            font-weight: bold;
            color: var(--accent-gold);
        }}

        .stat-label {{
            color: var(--text-muted);
            font-size: 0.9rem;
        }}

        footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-size: 0.9rem;
        }}

        code {{
            background: rgba(0,0,0,0.3);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-family: 'Consolas', monospace;
        }}
    </style>
</head>
<body>
    <header>
        <h1>🗡️ THE TRAITORS 🗡️</h1>
        <p class="subtitle">LLM-Powered Game Simulator</p>
    </header>

    <div class="container">
        <section>
            <h2>About The Game</h2>
            <p>The Traitors is a social deduction game based on the hit TV show. Players are secretly assigned roles as either <strong>Faithful</strong> or <strong>Traitors</strong>. The Faithful must work together to identify and banish the Traitors, while the Traitors must deceive, manipulate, and eliminate the Faithful without being caught.</p>

            <div class="rules-grid" style="margin-top: 1.5rem;">
                <div class="rule-card">
                    <h4>🎭 Role Assignment</h4>
                    <p>At the start, players are randomly assigned as Traitors or Faithful. Only Traitors know who the other Traitors are.</p>
                </div>
                <div class="rule-card">
                    <h4>💬 Discussion Phase</h4>
                    <p>All players discuss, share observations, and voice suspicions. This is where alliances form and accusations fly.</p>
                </div>
                <div class="rule-card">
                    <h4>🗳️ Voting Phase</h4>
                    <p>Players vote to banish someone they suspect is a Traitor. The player with the most votes is eliminated and their role revealed.</p>
                </div>
                <div class="rule-card">
                    <h4>🌙 Night Phase</h4>
                    <p>Traitors meet secretly and choose one Faithful player to "murder". The victim is eliminated from the game.</p>
                </div>
            </div>

            <h3>Win Conditions</h3>
            <ul style="margin-left: 1.5rem;">
                <li><strong style="color: var(--accent-green);">Faithful Win:</strong> All Traitors are banished</li>
                <li><strong style="color: var(--accent-red);">Traitors Win:</strong> They survive to the end OR outnumber the Faithful</li>
            </ul>
        </section>

        <section>
            <h2>Simulation Parameters</h2>
            <div class="parameters">
                <div class="param"><span class="param-name">contestants:</span> <span class="param-value">list[dict]</span> - List of players with name and personality_prompt</div>
                <div class="param"><span class="param-name">num_traitors:</span> <span class="param-value">int = 2</span> - Number of traitors to assign</div>
                <div class="param"><span class="param-name">num_rounds:</span> <span class="param-value">int = 3</span> - Maximum number of game rounds</div>
                <div class="param"><span class="param-name">client:</span> <span class="param-value">Anthropic = None</span> - Optional Anthropic client for LLM calls</div>
                <div class="param"><span class="param-name">log_callback:</span> <span class="param-value">Callable = print</span> - Function to handle game logging</div>
            </div>

            <h3>Example Usage</h3>
            <div class="parameters" style="margin-top: 1rem;">
                <code style="display: block; white-space: pre;">from traitors import TraitorsGame

contestants = [
    {{"name": "Alice", "personality_prompt": "You are analytical and suspicious..."}},
    {{"name": "Bob", "personality_prompt": "You are charismatic and deflective..."}},
    # ... more contestants
]

game = TraitorsGame(contestants=contestants, num_traitors=2, num_rounds=3)
results = game.run()</code>
            </div>
        </section>

        <section>
            <h2>Game Results</h2>

            <div class="winner-banner {winner_class}">
                <div class="winner-text">🏆 {winner_text} WIN! 🏆</div>
            </div>

            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-value">{results['rounds_played']}</div>
                    <div class="stat-label">Rounds Played</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value">{len(results['survivors'])}</div>
                    <div class="stat-label">Survivors</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value">{len(results['traitors'])}</div>
                    <div class="stat-label">Total Traitors</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value">{len(results['faithful'])}</div>
                    <div class="stat-label">Total Faithful</div>
                </div>
            </div>
        </section>

        <section>
            <h2>The Contestants</h2>
            <div class="contestant-grid">
                {contestant_cards}
            </div>
        </section>

        <section>
            <h2>Game Transcript</h2>
            {rounds_html}
        </section>

        <section>
            <h2>Full Game Log</h2>
            <div class="game-log">
                {game_log_html}
            </div>
        </section>
    </div>

    <footer>
        <p>The Traitors LLM Simulator - Powered by Claude AI</p>
        <p>Each contestant is controlled by an AI agent with a unique personality prompt.</p>
    </footer>
</body>
</html>
"""


def main():
    # Capture game log
    game_log = []

    def log_capture(msg: str):
        game_log.append(msg)
        print(msg)

    # Run the game with a fixed seed for reproducibility
    game = DemoGame(
        contestants=EXAMPLE_CONTESTANTS,
        num_traitors=2,
        num_rounds=3,
        log_callback=log_capture,
        seed=42,
    )

    results = game.run()

    # Generate HTML
    html_content = generate_html(results, game_log)

    # Write to file
    with open("index.html", "w") as f:
        f.write(html_content)

    print("\n" + "=" * 60)
    print("HTML report generated: index.html")
    print("=" * 60)


if __name__ == "__main__":
    main()
