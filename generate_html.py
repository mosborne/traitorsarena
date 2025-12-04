#!/usr/bin/env python3
"""Generate the HTML index page with game results."""

import html
import os
from traitors import TraitorsGame, DemoGame
from traitors.types import PlayerStatus
from main import EXAMPLE_CONTESTANTS


def build_game_summary(results: dict) -> str:
    """Build a narrative summary of the game."""
    players = results["players"]
    votes = results.get("votes", [])
    messages = results.get("messages", [])

    # Group events by round
    round_summaries = []

    # Track eliminations per round
    banished_by_round = {}
    murdered_by_round = {}

    for player in players.values():
        if not player.is_alive:
            if player.status == PlayerStatus.BANISHED:
                # Find which round they were banished
                for vote in votes:
                    if vote.target == player.name:
                        round_num = vote.round_num
                        banished_by_round[round_num] = player
                        break
            else:  # MURDERED
                # Find the round from private messages
                for msg in reversed(messages):
                    if msg.is_private and msg.round_num > 0:
                        murdered_by_round[msg.round_num] = player
                        break

    # Build round-by-round summary
    for round_num in range(1, results["rounds_played"] + 1):
        round_events = []

        banished = banished_by_round.get(round_num)
        if banished:
            if banished.is_traitor:
                round_events.append(f"<strong>{banished.name}</strong> was banished and revealed to be a <span class='traitor-text'>TRAITOR</span> - a win for the faithful!")
            else:
                round_events.append(f"<strong>{banished.name}</strong> was banished but was actually <span class='faithful-text'>FAITHFUL</span> - the traitors celebrate as an innocent falls.")

        murdered = murdered_by_round.get(round_num)
        if murdered:
            round_events.append(f"That night, the traitors murdered <strong>{murdered.name}</strong> ({murdered.role.value}).")

        if round_events:
            round_summaries.append(f"<p><strong>Round {round_num}:</strong> " + " ".join(round_events) + "</p>")

    # Build the outcome narrative
    if results["winner"] == "traitors":
        surviving_traitors = [p.name for p in players.values() if p.is_alive and p.is_traitor]
        outcome = f"<p class='outcome traitor-outcome'>The traitors achieved victory! <strong>{', '.join(surviving_traitors)}</strong> successfully deceived the group and survived to the end.</p>"
    else:
        outcome = "<p class='outcome faithful-outcome'>The faithful prevailed! They successfully identified and banished all the traitors.</p>"

    # Initial setup
    traitor_names = ", ".join(results["traitors"])
    faithful_names = ", ".join(results["faithful"])
    setup = f"<p><strong>The Setup:</strong> {len(results['traitors'])} traitors (<span class='traitor-text'>{traitor_names}</span>) infiltrated a group of {len(results['faithful'])} faithful players (<span class='faithful-text'>{faithful_names}</span>).</p>"

    return f"""
    <div class="game-summary">
        {setup}
        {"".join(round_summaries)}
        {outcome}
    </div>
    """


def generate_html(results: dict, game_log: list[str], used_real_llm: bool = False) -> str:
    """Generate the HTML page with game explanation and results."""

    # Build the game log HTML
    game_log_html = "\n".join(f"<div class='log-line'>{html.escape(line)}</div>" for line in game_log)

    # Build the game summary
    game_summary = build_game_summary(results)

    # Build contestant cards
    contestant_cards = ""
    for contestant in EXAMPLE_CONTESTANTS:
        role = "traitor" if contestant["name"] in results["traitors"] else "faithful"

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

    # Build round summary with messages and private thoughts
    rounds_html = ""
    current_round = 0
    in_night_phase = False  # Track if we've entered night phase for this round

    # Get private thoughts indexed by round
    thoughts_by_round = {}
    for thought in results.get("private_thoughts", []):
        if thought.round_num not in thoughts_by_round:
            thoughts_by_round[thought.round_num] = []
        thoughts_by_round[thought.round_num].append(thought)

    # Track which messages are discussion vs traitor night chat
    for msg in results["messages"]:
        if msg.round_num != current_round:
            # Close night phase section if we were in one
            if in_night_phase:
                rounds_html += "</div>"  # Close night-phase-section
                in_night_phase = False

            # Add private thoughts from previous round before closing it
            if current_round > 0 and current_round in thoughts_by_round:
                rounds_html += "<div class='phase-header'>Private Thoughts Before Voting</div>"
                for thought in thoughts_by_round[current_round]:
                    player = results["players"].get(thought.player)
                    is_traitor = player and player.is_traitor
                    thought_class = "traitor-thought" if is_traitor else "faithful-thought"
                    role_label = "TRAITOR" if is_traitor else "FAITHFUL"
                    rounds_html += f"""
                    <div class="thought {thought_class}">
                        <div class="thought-label">{role_label} - {html.escape(thought.player)}'s thoughts</div>
                        <div>{html.escape(thought.content)}</div>
                    </div>
                    """
                rounds_html += "</div>"
            elif current_round > 0:
                rounds_html += "</div>"

            current_round = msg.round_num
            rounds_html += f"<div class='round-section'><h4>Round {current_round}</h4>"
            rounds_html += "<div class='phase-header'>☀️ Discussion Phase</div>"

        # Check if we're transitioning to night phase (private traitor messages)
        if msg.is_private and not in_night_phase:
            rounds_html += """
            <div class='night-phase-section'>
                <div class='phase-header night-header'>🌙 Night Phase - Traitor Meeting</div>
                <div class='night-subtext'>The traitors meet in secret while the faithful sleep...</div>
            """
            in_night_phase = True

        private_class = "private-msg" if msg.is_private else ""
        rounds_html += f"""
        <div class="message {private_class}">
            <span class="speaker">{html.escape(msg.speaker)}:</span>
            <span class="content">{html.escape(msg.content)}</span>
        </div>
        """

    # Handle final round - close any open sections
    if current_round > 0:
        # Close night phase section if still open
        if in_night_phase:
            rounds_html += "</div>"  # Close night-phase-section

        if current_round in thoughts_by_round:
            rounds_html += "<div class='phase-header'>Private Thoughts Before Voting</div>"
            for thought in thoughts_by_round[current_round]:
                player = results["players"].get(thought.player)
                is_traitor = player and player.is_traitor
                thought_class = "traitor-thought" if is_traitor else "faithful-thought"
                role_label = "TRAITOR" if is_traitor else "FAITHFUL"
                rounds_html += f"""
                <div class="thought {thought_class}">
                    <div class="thought-label">{role_label} - {html.escape(thought.player)}'s thoughts</div>
                    <div>{html.escape(thought.content)}</div>
                </div>
                """
        rounds_html += "</div>"

    # Determine winner styling
    winner_class = "faithful-win" if results["winner"] == "faithful" else "traitor-win"
    winner_text = "THE FAITHFUL" if results["winner"] == "faithful" else "THE TRAITORS"

    # Mode indicator
    mode_badge = '<span class="mode-badge llm">LLM-Powered (Claude Haiku)</span>' if used_real_llm else '<span class="mode-badge demo">Demo Mode</span>'

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

        .mode-badge {{
            display: inline-block;
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-size: 0.9rem;
            font-weight: bold;
            margin-top: 1rem;
        }}

        .mode-badge.llm {{
            background: var(--accent-green);
            color: white;
        }}

        .mode-badge.demo {{
            background: var(--accent-gold);
            color: #1a1a2e;
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

        .night-phase-section {{
            background: rgba(20, 10, 30, 0.6);
            border: 2px solid rgba(233, 69, 96, 0.4);
            border-radius: 8px;
            padding: 1rem;
            margin: 1.5rem 0;
        }}

        .night-header {{
            color: var(--accent-red) !important;
            font-size: 1.1rem;
        }}

        .night-subtext {{
            color: var(--text-muted);
            font-style: italic;
            font-size: 0.9rem;
            margin-bottom: 1rem;
        }}

        .thought {{
            margin: 0.75rem 0;
            padding: 0.75rem;
            background: rgba(100, 100, 150, 0.15);
            border-left: 3px solid #8888cc;
            border-radius: 4px;
            font-style: italic;
        }}

        .thought.traitor-thought {{
            background: rgba(233, 69, 96, 0.1);
            border-left-color: var(--accent-red);
        }}

        .thought.faithful-thought {{
            background: rgba(42, 157, 143, 0.1);
            border-left-color: var(--accent-green);
        }}

        .thought-label {{
            font-size: 0.75rem;
            font-weight: bold;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }}

        .traitor-thought .thought-label {{
            color: var(--accent-red);
        }}

        .faithful-thought .thought-label {{
            color: var(--accent-green);
        }}

        .speaker {{
            font-weight: bold;
            color: var(--accent-gold);
        }}

        .content {{
            color: var(--text-light);
        }}

        .phase-header {{
            color: var(--accent-gold);
            font-weight: bold;
            margin: 1rem 0 0.5rem;
            padding-bottom: 0.25rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}

        .game-summary {{
            background: rgba(0,0,0,0.2);
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            line-height: 1.8;
        }}

        .game-summary p {{
            margin: 0.75rem 0;
        }}

        .traitor-text {{
            color: var(--accent-red);
            font-weight: bold;
        }}

        .faithful-text {{
            color: var(--accent-green);
            font-weight: bold;
        }}

        .outcome {{
            padding: 1rem;
            border-radius: 8px;
            margin-top: 1rem;
            font-size: 1.1rem;
        }}

        .traitor-outcome {{
            background: rgba(233, 69, 96, 0.2);
            border-left: 4px solid var(--accent-red);
        }}

        .faithful-outcome {{
            background: rgba(42, 157, 143, 0.2);
            border-left: 4px solid var(--accent-green);
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
        <h1>THE TRAITORS</h1>
        <p class="subtitle">LLM-Powered Game Simulator</p>
        {mode_badge}
    </header>

    <div class="container">
        <section>
            <h2>About The Game</h2>
            <p>The Traitors is a social deduction game based on the hit TV show. Players are secretly assigned roles as either <strong>Faithful</strong> or <strong>Traitors</strong>. The Faithful must work together to identify and banish the Traitors, while the Traitors must deceive, manipulate, and eliminate the Faithful without being caught.</p>

            <div class="rules-grid" style="margin-top: 1.5rem;">
                <div class="rule-card">
                    <h4>Role Assignment</h4>
                    <p>At the start, players are randomly assigned as Traitors or Faithful. Only Traitors know who the other Traitors are.</p>
                </div>
                <div class="rule-card">
                    <h4>Discussion Phase</h4>
                    <p>All players discuss, share observations, and voice suspicions. This is where alliances form and accusations fly.</p>
                </div>
                <div class="rule-card">
                    <h4>Voting Phase</h4>
                    <p>Players vote to banish someone they suspect is a Traitor. The player with the most votes is eliminated and their role revealed.</p>
                </div>
                <div class="rule-card">
                    <h4>Night Phase</h4>
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
                <div class="winner-text">{winner_text} WIN!</div>
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

            <h3>What Happened</h3>
            {game_summary}
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

    # Check if we have an API key for real LLM mode
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if api_key:
        print("Running with real LLM agents (Claude Haiku)...\n")
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        game = TraitorsGame(
            contestants=EXAMPLE_CONTESTANTS,
            num_traitors=3,  # 3 traitors among 12 players
            num_rounds=5,    # 5 rounds for more gameplay
            client=client,
            log_callback=log_capture,
        )
        used_real_llm = True
    else:
        print("No API key found, running in demo mode...\n")
        game = DemoGame(
            contestants=EXAMPLE_CONTESTANTS,
            num_traitors=3,  # 3 traitors among 12 players
            num_rounds=5,    # 5 rounds for more gameplay
            log_callback=log_capture,
            seed=42,
        )
        used_real_llm = False

    results = game.run()

    # Add players to results for HTML generation
    results["players"] = game.state.players
    results["messages"] = game.state.messages
    results["private_thoughts"] = getattr(game.state, 'private_thoughts', [])
    results["votes"] = game.state.votes

    # Generate HTML
    html_content = generate_html(results, game_log, used_real_llm)

    # Write to file
    with open("index.html", "w") as f:
        f.write(html_content)

    print("\n" + "=" * 60)
    print("HTML report generated: index.html")
    print("=" * 60)


if __name__ == "__main__":
    main()
