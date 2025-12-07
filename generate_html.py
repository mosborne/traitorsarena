#!/usr/bin/env python3
"""Generate the HTML index page with game results."""

import html
import json
import os
from pathlib import Path
from traitors import TraitorsGame
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

    # Build the outcome narrative with prize info
    prize_pool = results.get("prize_pool", 10000)
    prize_distribution = results.get("prize_distribution", {})

    if results["winner"] == "traitors":
        surviving_traitors = [p.name for p in players.values() if p.is_alive and p.is_traitor]
        traitor_winnings = sum(prize_distribution.get(name, 0) for name in surviving_traitors)
        outcome = f"<p class='outcome traitor-outcome'>The traitors achieved victory! <strong>{', '.join(surviving_traitors)}</strong> successfully deceived the group and stole the entire <strong>${prize_pool:,}</strong> prize pool!</p>"
    else:
        surviving_faithful = [p.name for p in players.values() if p.is_alive and not p.is_traitor]
        share = prize_pool // len(surviving_faithful) if surviving_faithful else 0
        outcome = f"<p class='outcome faithful-outcome'>The faithful prevailed! They successfully identified and banished all the traitors and split the <strong>${prize_pool:,}</strong> prize pool (<strong>${share:,}</strong> each).</p>"

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


def build_rounds_table(results: dict) -> str:
    """Build a table showing game state progression after each event."""
    players = results["players"]
    votes = results.get("votes", [])
    messages = results.get("messages", [])

    # Get initial player lists
    all_traitors = [p.name for p in players.values() if p.is_traitor]
    all_faithful = [p.name for p in players.values() if not p.is_traitor]

    # Group votes by round
    votes_by_round = {}
    for vote in votes:
        if vote.round_num not in votes_by_round:
            votes_by_round[vote.round_num] = []
        votes_by_round[vote.round_num].append(vote)

    # Track banishments by round
    banished_by_round = {}
    banished_players = {p.name: p for p in players.values() if p.status == PlayerStatus.BANISHED}

    for round_num, round_votes in votes_by_round.items():
        vote_counts = {}
        for v in round_votes:
            vote_counts[v.target] = vote_counts.get(v.target, 0) + 1

        if vote_counts:
            max_votes = max(vote_counts.values())
            top_voted = [name for name, count in vote_counts.items() if count == max_votes]

            for name in top_voted:
                if name in banished_players:
                    banished_by_round[round_num] = banished_players[name]
                    break

    # Track murders by round
    murdered_players = {p.name: p for p in players.values() if p.status == PlayerStatus.MURDERED}
    murdered_by_round = {}

    traitor_msgs_by_round = {}
    for msg in messages:
        if msg.is_private:
            if msg.round_num not in traitor_msgs_by_round:
                traitor_msgs_by_round[msg.round_num] = []
            traitor_msgs_by_round[msg.round_num].append(msg.content)

    for round_num, msg_contents in traitor_msgs_by_round.items():
        combined_text = " ".join(msg_contents).lower()
        for victim_name, victim in murdered_players.items():
            if victim_name.lower() in combined_text and victim_name not in [p.name for p in murdered_by_round.values()]:
                murdered_by_round[round_num] = victim
                break

    # Fallback for unassigned murders
    unassigned_victims = [p for p in murdered_players.values() if p not in murdered_by_round.values()]
    for round_num in range(1, results["rounds_played"] + 1):
        if round_num not in murdered_by_round and unassigned_victims:
            murdered_by_round[round_num] = unassigned_victims.pop(0)

    # Build timeline of events
    rows = ""
    alive_traitors = set(all_traitors)
    alive_faithful = set(all_faithful)

    # Starting state
    rows += f"""
        <tr class="state-row">
            <td class="event-phase">Start</td>
            <td class="event-desc">Game begins</td>
            <td class="remaining-traitors"><span class="traitor-text">{len(alive_traitors)}</span> traitors</td>
            <td class="remaining-faithful"><span class="faithful-text">{len(alive_faithful)}</span> faithful</td>
            <td class="player-list">{', '.join(sorted(alive_traitors | alive_faithful))}</td>
        </tr>
    """

    for round_num in range(1, results["rounds_played"] + 1):
        # Banishment event
        banished = banished_by_round.get(round_num)
        if banished:
            if banished.name in alive_traitors:
                alive_traitors.remove(banished.name)
            elif banished.name in alive_faithful:
                alive_faithful.remove(banished.name)

            role = "TRAITOR" if banished.is_traitor else "FAITHFUL"
            role_class = "traitor-text" if banished.is_traitor else "faithful-text"
            icon = "🎭" if banished.is_traitor else "😇"

            # Get vote breakdown
            round_votes = votes_by_round.get(round_num, [])
            vote_counts = {}
            for v in round_votes:
                vote_counts[v.target] = vote_counts.get(v.target, 0) + 1
            sorted_votes = sorted(vote_counts.items(), key=lambda x: -x[1])[:3]
            vote_info = ", ".join(f"{name}: {count}" for name, count in sorted_votes)

            rows += f"""
        <tr class="banishment-row">
            <td class="event-phase">Round {round_num}<br><small>Banishment</small></td>
            <td class="event-desc">{icon} <span class='{role_class}'>{banished.name}</span> banished<br><small>Votes: {vote_info}</small></td>
            <td class="remaining-traitors"><span class="traitor-text">{len(alive_traitors)}</span> traitors</td>
            <td class="remaining-faithful"><span class="faithful-text">{len(alive_faithful)}</span> faithful</td>
            <td class="player-list">{', '.join(sorted(alive_traitors | alive_faithful))}</td>
        </tr>
            """

        # Murder event (if game continued)
        murdered = murdered_by_round.get(round_num)
        if murdered:
            if murdered.name in alive_faithful:
                alive_faithful.remove(murdered.name)

            rows += f"""
        <tr class="murder-row">
            <td class="event-phase">Round {round_num}<br><small>Night</small></td>
            <td class="event-desc">🔪 <span class='faithful-text'>{murdered.name}</span> murdered</td>
            <td class="remaining-traitors"><span class="traitor-text">{len(alive_traitors)}</span> traitors</td>
            <td class="remaining-faithful"><span class="faithful-text">{len(alive_faithful)}</span> faithful</td>
            <td class="player-list">{', '.join(sorted(alive_traitors | alive_faithful))}</td>
        </tr>
            """

    # Final state
    winner = results["winner"]
    winner_class = "traitor-text" if winner == "traitors" else "faithful-text"
    winner_label = "TRAITORS WIN" if winner == "traitors" else "FAITHFUL WIN"

    rows += f"""
        <tr class="final-row">
            <td class="event-phase">Final</td>
            <td class="event-desc"><strong class="{winner_class}">{winner_label}</strong></td>
            <td class="remaining-traitors"><span class="traitor-text">{len(alive_traitors)}</span> traitors</td>
            <td class="remaining-faithful"><span class="faithful-text">{len(alive_faithful)}</span> faithful</td>
            <td class="player-list">{', '.join(sorted(alive_traitors | alive_faithful))}</td>
        </tr>
    """

    return f"""
    <div class="rounds-table-container">
        <table class="rounds-table">
            <thead>
                <tr>
                    <th>Phase</th>
                    <th>Event</th>
                    <th>Traitors</th>
                    <th>Faithful</th>
                    <th>Remaining Players</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    """


def build_llm_interactions_html(results: dict, contestants: list) -> str:
    """Build HTML section showing LLM interaction details for each player."""
    llm_interactions = results.get("llm_interactions", [])
    if not llm_interactions:
        return "<p><em>No LLM interaction data available for this game.</em></p>"

    # Build a lookup for contestant prompts
    contestant_prompts = {c["name"]: c.get("personality_prompt", "N/A") for c in contestants}

    # Group interactions by player
    by_player = {}
    for interaction in llm_interactions:
        if interaction.player not in by_player:
            by_player[interaction.player] = []
        by_player[interaction.player].append(interaction)

    players_html = ""
    for player_name in sorted(by_player.keys()):
        interactions = by_player[player_name]
        player_obj = results["players"].get(player_name)
        is_traitor = player_obj and player_obj.is_traitor
        role_class = "traitor-text" if is_traitor else "faithful-text"
        role_label = "TRAITOR" if is_traitor else "FAITHFUL"

        # Build interaction cards for this player
        interaction_cards = ""
        for i, inter in enumerate(interactions):
            interaction_cards += f"""
            <div class="llm-interaction-card">
                <div class="llm-interaction-header" onclick="toggleInteraction(this)">
                    <span class="interaction-type">{html.escape(inter.action_type)}</span>
                    <span class="interaction-round">Round {inter.round_num}</span>
                    <span class="interaction-toggle">+</span>
                </div>
                <div class="llm-interaction-content" style="display: none;">
                    <div class="llm-section">
                        <div class="llm-section-label">System Prompt:</div>
                        <pre class="llm-text">{html.escape(inter.system_prompt)}</pre>
                    </div>
                    <div class="llm-section">
                        <div class="llm-section-label">User Message (Input):</div>
                        <pre class="llm-text">{html.escape(inter.user_message)}</pre>
                    </div>
                    <div class="llm-section">
                        <div class="llm-section-label">Response (Output):</div>
                        <pre class="llm-text llm-response">{html.escape(inter.response)}</pre>
                    </div>
                    <div class="llm-meta">
                        Model: {html.escape(inter.model)} | Timestamp: {html.escape(inter.timestamp)}
                    </div>
                </div>
            </div>
            """

        players_html += f"""
        <div class="player-interactions">
            <div class="player-interactions-header" onclick="togglePlayer(this)">
                <span class="player-name-header">{html.escape(player_name)}</span>
                <span class="{role_class}">[{role_label}]</span>
                <span class="interaction-count">{len(interactions)} interactions</span>
                <span class="player-toggle">+</span>
            </div>
            <div class="player-interactions-content" style="display: none;">
                <div class="personality-prompt-section">
                    <div class="llm-section-label">Personality Prompt:</div>
                    <pre class="llm-text personality-text">{html.escape(contestant_prompts.get(player_name, 'N/A'))}</pre>
                </div>
                {interaction_cards}
            </div>
        </div>
        """

    return f"""
    <div class="llm-interactions-container">
        {players_html}
    </div>
    """


def generate_game_html(results: dict, game_log: list[str], contestants: list = None,
                       back_link: str = None, title: str = None) -> str:
    """Generate the HTML page for a single game with results.

    Args:
        results: Game results dictionary
        game_log: List of log messages
        contestants: List of contestant dicts (defaults to EXAMPLE_CONTESTANTS)
        back_link: Optional link to navigate back (e.g., "index.html")
        title: Optional title for the page (e.g., "Game 1")
    """
    if contestants is None:
        contestants = EXAMPLE_CONTESTANTS

    page_title = f"Game: {title}" if title else "The Traitors - LLM Game Simulator"

    # Build the game log HTML
    game_log_html = "\n".join(f"<div class='log-line'>{html.escape(line)}</div>" for line in game_log)

    # Build the game summary
    game_summary = build_game_summary(results)

    # Build the rounds table
    rounds_table = build_rounds_table(results)

    # Build LLM interactions section
    llm_interactions_html = build_llm_interactions_html(results, contestants)

    # Build contestant cards
    prize_distribution = results.get("prize_distribution", {})
    contestant_cards = ""
    for contestant in contestants:
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

        # Get winnings
        winnings = prize_distribution.get(contestant["name"], 0)
        winnings_html = f"<div class='contestant-winnings {'winner' if winnings > 0 else ''}'>${winnings:,}</div>" if winnings > 0 else "<div class='contestant-winnings'>$0</div>"

        contestant_cards += f"""
        <div class="contestant-card {role} {fate_class}">
            <div class="contestant-name">{html.escape(contestant["name"])}</div>
            <div class="contestant-role">{role.upper()}</div>
            <div class="contestant-fate">{fate}</div>
            {winnings_html}
            <div class="contestant-personality">{html.escape(contestant["personality_prompt"][:150])}...</div>
        </div>
        """

    # Build round summary with messages and private thoughts
    rounds_html = ""
    current_round = 0
    in_night_phase = False  # Track if we've entered night phase for this round
    shown_banishment_for_round = set()  # Track which rounds we've shown banishment for
    shown_murder_for_round = set()  # Track which rounds we've shown murder for

    # Get private thoughts indexed by round
    thoughts_by_round = {}
    for thought in results.get("private_thoughts", []):
        if thought.round_num not in thoughts_by_round:
            thoughts_by_round[thought.round_num] = []
        thoughts_by_round[thought.round_num].append(thought)

    # Pre-calculate banishments and murders by round (same logic as build_rounds_table)
    players = results["players"]
    votes = results.get("votes", [])
    messages = results.get("messages", [])

    # Group votes by round
    votes_by_round = {}
    for vote in votes:
        if vote.round_num not in votes_by_round:
            votes_by_round[vote.round_num] = []
        votes_by_round[vote.round_num].append(vote)

    # Track banishments by round
    banished_by_round = {}
    banished_players = {p.name: p for p in players.values() if p.status == PlayerStatus.BANISHED}

    for round_num, round_votes in votes_by_round.items():
        vote_counts = {}
        for v in round_votes:
            vote_counts[v.target] = vote_counts.get(v.target, 0) + 1

        if vote_counts:
            max_votes = max(vote_counts.values())
            top_voted = [name for name, count in vote_counts.items() if count == max_votes]

            for name in top_voted:
                if name in banished_players:
                    banished_by_round[round_num] = banished_players[name]
                    break

    # Track murders by round
    murdered_players = {p.name: p for p in players.values() if p.status == PlayerStatus.MURDERED}
    murdered_by_round = {}

    traitor_msgs_by_round = {}
    for msg in messages:
        if msg.is_private:
            if msg.round_num not in traitor_msgs_by_round:
                traitor_msgs_by_round[msg.round_num] = []
            traitor_msgs_by_round[msg.round_num].append(msg.content)

    for round_num, msg_contents in traitor_msgs_by_round.items():
        combined_text = " ".join(msg_contents).lower()
        for victim_name, victim in murdered_players.items():
            if victim_name.lower() in combined_text and victim_name not in [p.name for p in murdered_by_round.values()]:
                murdered_by_round[round_num] = victim
                break

    # Fallback for unassigned murders
    unassigned_victims = [p for p in murdered_players.values() if p not in murdered_by_round.values()]
    for round_num in range(1, results["rounds_played"] + 1):
        if round_num not in murdered_by_round and unassigned_victims:
            murdered_by_round[round_num] = unassigned_victims.pop(0)

    # Helper function to build voting outcome HTML
    def build_voting_outcome(round_num):
        round_votes = votes_by_round.get(round_num, [])
        if not round_votes:
            return ""

        # Count votes
        vote_counts = {}
        for v in round_votes:
            vote_counts[v.target] = vote_counts.get(v.target, 0) + 1

        # Sort by vote count
        sorted_votes = sorted(vote_counts.items(), key=lambda x: -x[1])

        # Build vote breakdown
        vote_lines = []
        for name, count in sorted_votes:
            vote_lines.append(f"<span class='vote-target'>{html.escape(name)}</span>: {count} vote{'s' if count != 1 else ''}")

        banished = banished_by_round.get(round_num)
        banishment_html = ""
        if banished:
            role_class = "traitor-text" if banished.is_traitor else "faithful-text"
            role = "TRAITOR" if banished.is_traitor else "FAITHFUL"
            icon = "🎭" if banished.is_traitor else "😇"
            result_text = "The group caught a traitor!" if banished.is_traitor else "An innocent was wrongly banished..."
            banishment_html = f"""
            <div class="banishment-announcement {'traitor-caught' if banished.is_traitor else 'faithful-lost'}">
                <div class="banishment-icon">{icon}</div>
                <div class="banishment-text">
                    <strong class="{role_class}">{html.escape(banished.name)}</strong> has been banished!
                    <br><span class="role-reveal">Revealed as: <span class="{role_class}">{role}</span></span>
                    <br><em class="result-text">{result_text}</em>
                </div>
            </div>
            """

        return f"""
        <div class="voting-outcome">
            <div class="phase-header">🗳️ Voting Results</div>
            <div class="vote-breakdown">
                {' &nbsp;|&nbsp; '.join(vote_lines)}
            </div>
            {banishment_html}
        </div>
        """

    # Helper function to build murder outcome HTML
    def build_murder_outcome(round_num):
        murdered = murdered_by_round.get(round_num)
        if not murdered:
            return ""

        return f"""
        <div class="murder-announcement">
            <div class="murder-icon">💀</div>
            <div class="murder-text">
                <strong class="faithful-text">{html.escape(murdered.name)}</strong> was found murdered.
                <br><em class="murder-subtext">The traitors struck under cover of darkness...</em>
            </div>
        </div>
        """

    # Track which messages are discussion vs traitor night chat
    for msg in results["messages"]:
        if msg.round_num != current_round:
            # Close night phase section if we were in one
            if in_night_phase:
                # Add murder announcement at end of night phase
                if current_round not in shown_murder_for_round:
                    rounds_html += build_murder_outcome(current_round)
                    shown_murder_for_round.add(current_round)
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
                # Add voting outcome after private thoughts
                if current_round not in shown_banishment_for_round:
                    rounds_html += build_voting_outcome(current_round)
                    shown_banishment_for_round.add(current_round)
                rounds_html += "</div>"
            elif current_round > 0:
                # Still add voting outcome even without private thoughts
                if current_round not in shown_banishment_for_round:
                    rounds_html += build_voting_outcome(current_round)
                    shown_banishment_for_round.add(current_round)
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
            # Add murder announcement at end of night phase
            if current_round not in shown_murder_for_round:
                rounds_html += build_murder_outcome(current_round)
                shown_murder_for_round.add(current_round)
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
        # Add voting outcome after private thoughts
        if current_round not in shown_banishment_for_round:
            rounds_html += build_voting_outcome(current_round)
            shown_banishment_for_round.add(current_round)
        rounds_html += "</div>"

    # Determine winner styling
    winner_class = "faithful-win" if results["winner"] == "faithful" else "traitor-win"
    winner_text = "THE FAITHFUL" if results["winner"] == "faithful" else "THE TRAITORS"

    # Mode indicator
    mode_badge = '<span class="mode-badge llm">LLM-Powered (Claude Haiku)</span>'

    # Back link for navigation
    back_link_html = f'<p class="back-link"><a href="{back_link}">&larr; Back to Run Summary</a></p>' if back_link else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
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

        .back-link {{
            margin-top: 1rem;
        }}

        .back-link a {{
            color: var(--accent-gold);
            text-decoration: none;
        }}

        .back-link a:hover {{
            text-decoration: underline;
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

        .contestant-winnings {{
            font-size: 1.1rem;
            font-weight: bold;
            color: var(--text-muted);
            margin: 0.5rem 0;
        }}

        .contestant-winnings.winner {{
            color: var(--accent-gold);
            font-size: 1.3rem;
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

        .voting-outcome {{
            margin: 1.5rem 0;
            padding: 1rem;
            background: rgba(244, 162, 97, 0.1);
            border-radius: 8px;
            border: 1px solid rgba(244, 162, 97, 0.3);
        }}

        .vote-breakdown {{
            margin: 0.75rem 0;
            padding: 0.75rem;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 4px;
            font-size: 0.9rem;
        }}

        .vote-target {{
            color: var(--accent-gold);
            font-weight: bold;
        }}

        .banishment-announcement {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-top: 1rem;
            padding: 1rem;
            border-radius: 8px;
        }}

        .banishment-announcement.traitor-caught {{
            background: rgba(42, 157, 143, 0.2);
            border: 2px solid var(--accent-green);
        }}

        .banishment-announcement.faithful-lost {{
            background: rgba(233, 69, 96, 0.2);
            border: 2px solid var(--accent-red);
        }}

        .banishment-icon {{
            font-size: 2.5rem;
        }}

        .banishment-text {{
            flex: 1;
        }}

        .role-reveal {{
            font-size: 0.9rem;
            margin-top: 0.25rem;
        }}

        .result-text {{
            font-size: 0.85rem;
            color: var(--text-muted);
        }}

        .murder-announcement {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin: 1rem 0;
            padding: 1rem;
            background: rgba(233, 69, 96, 0.15);
            border: 2px solid var(--accent-red);
            border-radius: 8px;
        }}

        .murder-icon {{
            font-size: 2.5rem;
        }}

        .murder-text {{
            flex: 1;
        }}

        .murder-subtext {{
            font-size: 0.85rem;
            color: var(--text-muted);
            display: block;
            margin-top: 0.25rem;
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

        .rounds-table-container {{
            margin: 2rem 0;
            overflow-x: auto;
        }}

        .rounds-table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            overflow: hidden;
        }}

        .rounds-table th {{
            background: rgba(233, 69, 96, 0.3);
            color: var(--accent-gold);
            padding: 1rem;
            text-align: left;
            font-weight: bold;
            border-bottom: 2px solid var(--accent-red);
        }}

        .rounds-table td {{
            padding: 0.75rem 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            vertical-align: middle;
        }}

        .rounds-table tr:hover {{
            background: rgba(255,255,255,0.05);
        }}

        .rounds-table .event-phase {{
            font-weight: bold;
            color: var(--accent-gold);
            text-align: center;
            width: 100px;
        }}

        .rounds-table .event-phase small {{
            display: block;
            font-weight: normal;
            color: var(--text-muted);
            font-size: 0.75rem;
        }}

        .rounds-table .event-desc {{
            min-width: 200px;
        }}

        .rounds-table .event-desc small {{
            display: block;
            color: var(--text-muted);
            font-size: 0.8rem;
            margin-top: 0.25rem;
        }}

        .rounds-table .remaining-traitors,
        .rounds-table .remaining-faithful {{
            text-align: center;
            font-weight: bold;
            width: 90px;
        }}

        .rounds-table .player-list {{
            font-size: 0.85rem;
            color: var(--text-muted);
            max-width: 300px;
        }}

        .rounds-table .state-row {{
            background: rgba(42, 157, 143, 0.1);
        }}

        .rounds-table .banishment-row {{
            background: rgba(244, 162, 97, 0.1);
        }}

        .rounds-table .murder-row {{
            background: rgba(233, 69, 96, 0.1);
        }}

        .rounds-table .final-row {{
            background: rgba(255, 255, 255, 0.1);
            font-weight: bold;
        }}

        .rounds-table small {{
            color: var(--text-muted);
            font-size: 0.8rem;
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

        /* LLM Interactions Styles */
        .llm-interactions-container {{
            margin-top: 1rem;
        }}

        .player-interactions {{
            margin-bottom: 1rem;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            overflow: hidden;
        }}

        .player-interactions-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem;
            background: rgba(255,255,255,0.05);
            cursor: pointer;
            transition: background 0.2s;
        }}

        .player-interactions-header:hover {{
            background: rgba(255,255,255,0.1);
        }}

        .player-name-header {{
            font-weight: bold;
            font-size: 1.1rem;
            color: var(--accent-gold);
        }}

        .interaction-count {{
            margin-left: auto;
            color: var(--text-muted);
            font-size: 0.9rem;
        }}

        .player-toggle, .interaction-toggle {{
            font-weight: bold;
            color: var(--accent-gold);
            font-size: 1.2rem;
            width: 20px;
            text-align: center;
        }}

        .player-interactions-content {{
            padding: 1rem;
        }}

        .personality-prompt-section {{
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}

        .llm-interaction-card {{
            margin: 0.75rem 0;
            background: rgba(0,0,0,0.3);
            border-radius: 6px;
            overflow: hidden;
        }}

        .llm-interaction-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 0.75rem 1rem;
            background: rgba(255,255,255,0.03);
            cursor: pointer;
            transition: background 0.2s;
        }}

        .llm-interaction-header:hover {{
            background: rgba(255,255,255,0.08);
        }}

        .interaction-type {{
            font-weight: bold;
            color: var(--accent-green);
            text-transform: uppercase;
            font-size: 0.85rem;
        }}

        .interaction-round {{
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-left: auto;
        }}

        .llm-interaction-content {{
            padding: 1rem;
        }}

        .llm-section {{
            margin-bottom: 1rem;
        }}

        .llm-section-label {{
            font-weight: bold;
            color: var(--accent-gold);
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
        }}

        .llm-text {{
            background: rgba(0,0,0,0.4);
            padding: 1rem;
            border-radius: 4px;
            font-family: 'Consolas', monospace;
            font-size: 0.8rem;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            max-height: 300px;
            overflow-y: auto;
            color: var(--text-light);
            line-height: 1.4;
        }}

        .llm-response {{
            background: rgba(42, 157, 143, 0.15);
            border-left: 3px solid var(--accent-green);
        }}

        .personality-text {{
            background: rgba(244, 162, 97, 0.1);
            border-left: 3px solid var(--accent-gold);
        }}

        .llm-meta {{
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 0.5rem;
            padding-top: 0.5rem;
            border-top: 1px solid rgba(255,255,255,0.1);
        }}
    </style>
    <script>
        function togglePlayer(header) {{
            const content = header.nextElementSibling;
            const toggle = header.querySelector('.player-toggle');
            if (content.style.display === 'none') {{
                content.style.display = 'block';
                toggle.textContent = '-';
            }} else {{
                content.style.display = 'none';
                toggle.textContent = '+';
            }}
        }}

        function toggleInteraction(header) {{
            const content = header.nextElementSibling;
            const toggle = header.querySelector('.interaction-toggle');
            if (content.style.display === 'none') {{
                content.style.display = 'block';
                toggle.textContent = '-';
            }} else {{
                content.style.display = 'none';
                toggle.textContent = '+';
            }}
        }}
    </script>
</head>
<body>
    <header>
        <h1>THE TRAITORS</h1>
        <p class="subtitle">LLM-Powered Game Simulator</p>
        {mode_badge}
        {back_link_html}
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
                <div class="param"><span class="param-name">client:</span> <span class="param-value">Anthropic = None</span> - Optional Anthropic client for LLM calls</div>
                <div class="param"><span class="param-name">log_callback:</span> <span class="param-value">Callable = print</span> - Function to handle game logging</div>
            </div>

            <h3>Game Flow</h3>
            <p>The game continues until players vote to end it (after a banishment). If traitors remain when the game ends, they win. If all traitors have been banished, the faithful win.</p>

            <h3>Example Usage</h3>
            <div class="parameters" style="margin-top: 1rem;">
                <code style="display: block; white-space: pre;">from traitors import TraitorsGame

contestants = [
    {{"name": "Alice", "personality_prompt": "You are analytical and suspicious..."}},
    {{"name": "Bob", "personality_prompt": "You are charismatic and deflective..."}},
    # ... more contestants
]

game = TraitorsGame(contestants=contestants, num_traitors=2)
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
                    <div class="stat-value" style="color: var(--accent-gold);">${results.get('prize_pool', 10000):,}</div>
                    <div class="stat-label">Prize Pool</div>
                </div>
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

            <h3>Round by Round</h3>
            {rounds_table}

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
            <h2>LLM Interaction Details</h2>
            <p style="margin-bottom: 1rem; color: var(--text-muted);">
                Click on a player to see all their LLM interactions during the game.
                Each interaction shows the exact system prompt, user message, and response.
            </p>
            {llm_interactions_html}
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


def generate_players_page(output_path: str = "players.html") -> str:
    """Generate an HTML page documenting all player prompts.

    Args:
        output_path: Path to write the HTML file

    Returns:
        The generated HTML content
    """
    prompts_dir = Path(__file__).parent / "prompts"

    # Load all player JSON files
    players = []
    for json_file in sorted(prompts_dir.glob("*.json")):
        with open(json_file) as f:
            data = json.load(f)
            data["_filename"] = json_file.name
            players.append(data)

    # Sort by name
    players.sort(key=lambda p: p.get("name", "Unknown"))

    # Build player cards
    player_cards = ""
    for player in players:
        name = html.escape(player.get("name", "Unknown"))
        version = html.escape(player.get("version", "1.0"))
        design_notes = html.escape(player.get("design_notes", "No design notes available."))
        hypothesis = html.escape(player.get("hypothesis", "No hypothesis defined."))
        personality = html.escape(player.get("personality_prompt", "No personality prompt."))
        filename = html.escape(player.get("_filename", ""))
        created = html.escape(player.get("created", "Unknown"))

        # Stats
        stats = player.get("stats", {})
        games_played = stats.get("games_played", 0)
        times_traitor = stats.get("times_traitor", 0)
        times_faithful = stats.get("times_faithful", 0)
        wins_as_traitor = stats.get("wins_as_traitor", 0)
        wins_as_faithful = stats.get("wins_as_faithful", 0)
        survived = stats.get("survived", 0)
        banished = stats.get("banished", 0)
        murdered = stats.get("murdered", 0)

        # Calculate rates
        traitor_win_rate = (wins_as_traitor / times_traitor * 100) if times_traitor > 0 else 0
        faithful_win_rate = (wins_as_faithful / times_faithful * 100) if times_faithful > 0 else 0
        survival_rate = (survived / games_played * 100) if games_played > 0 else 0

        stats_html = ""
        if games_played > 0:
            stats_html = f"""
            <div class="player-stats">
                <div class="stats-row">
                    <div class="stat-item">
                        <span class="stat-value">{games_played}</span>
                        <span class="stat-label">Games</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-value">{survival_rate:.0f}%</span>
                        <span class="stat-label">Survival</span>
                    </div>
                    <div class="stat-item traitor-stat">
                        <span class="stat-value">{times_traitor}</span>
                        <span class="stat-label">As Traitor</span>
                    </div>
                    <div class="stat-item faithful-stat">
                        <span class="stat-value">{times_faithful}</span>
                        <span class="stat-label">As Faithful</span>
                    </div>
                </div>
                <div class="stats-row">
                    <div class="stat-item traitor-stat">
                        <span class="stat-value">{traitor_win_rate:.0f}%</span>
                        <span class="stat-label">Traitor Win%</span>
                    </div>
                    <div class="stat-item faithful-stat">
                        <span class="stat-value">{faithful_win_rate:.0f}%</span>
                        <span class="stat-label">Faithful Win%</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-value">{banished}</span>
                        <span class="stat-label">Banished</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-value">{murdered}</span>
                        <span class="stat-label">Murdered</span>
                    </div>
                </div>
            </div>
            """
        else:
            stats_html = '<div class="no-stats">No games played yet</div>'

        player_cards += f"""
        <div class="player-card">
            <div class="player-header">
                <h3 class="player-name">{name}</h3>
                <span class="player-version">v{version}</span>
            </div>
            <div class="player-meta">
                <span class="player-file">{filename}</span>
                <span class="player-created">Created: {created}</span>
            </div>

            <div class="player-section">
                <h4>Design Notes</h4>
                <p class="design-notes">{design_notes}</p>
            </div>

            <div class="player-section">
                <h4>Hypothesis</h4>
                <p class="hypothesis">{hypothesis}</p>
            </div>

            {stats_html}

            <details class="prompt-details">
                <summary>View Full Prompt</summary>
                <pre class="personality-prompt">{personality}</pre>
            </details>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Player Guide - The Traitors</title>
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

        .back-link {{
            margin-top: 1rem;
        }}

        .back-link a {{
            color: var(--accent-gold);
            text-decoration: none;
            border: 1px solid var(--accent-gold);
            padding: 0.3rem 0.8rem;
            border-radius: 4px;
            font-size: 0.9rem;
        }}

        .back-link a:hover {{
            background: var(--accent-gold);
            color: var(--bg-dark);
        }}

        .intro {{
            margin: 2rem 0;
            padding: 2rem;
            background: var(--bg-card);
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }}

        .intro h2 {{
            color: var(--accent-gold);
            border-bottom: 2px solid var(--accent-red);
            padding-bottom: 0.5rem;
            margin-bottom: 1rem;
        }}

        .players-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 2rem;
            margin-top: 2rem;
        }}

        .player-card {{
            background: var(--bg-card);
            border-radius: 10px;
            padding: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.1);
        }}

        .player-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}

        .player-name {{
            color: var(--accent-gold);
            font-size: 1.5rem;
            margin: 0;
        }}

        .player-version {{
            background: var(--accent-green);
            color: var(--bg-dark);
            padding: 0.2rem 0.6rem;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: bold;
        }}

        .player-meta {{
            display: flex;
            gap: 1rem;
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}

        .player-section {{
            margin-bottom: 1rem;
        }}

        .player-section h4 {{
            color: var(--accent-green);
            font-size: 0.9rem;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
        }}

        .design-notes {{
            color: var(--text-light);
            font-size: 0.95rem;
        }}

        .hypothesis {{
            color: var(--text-muted);
            font-style: italic;
            font-size: 0.9rem;
        }}

        .player-stats {{
            background: rgba(0,0,0,0.2);
            padding: 1rem;
            border-radius: 8px;
            margin: 1rem 0;
        }}

        .stats-row {{
            display: flex;
            justify-content: space-around;
            margin-bottom: 0.75rem;
        }}

        .stats-row:last-child {{
            margin-bottom: 0;
        }}

        .stat-item {{
            text-align: center;
        }}

        .stat-value {{
            display: block;
            font-size: 1.2rem;
            font-weight: bold;
            color: var(--text-light);
        }}

        .stat-label {{
            font-size: 0.7rem;
            color: var(--text-muted);
            text-transform: uppercase;
        }}

        .traitor-stat .stat-value {{
            color: var(--accent-red);
        }}

        .faithful-stat .stat-value {{
            color: var(--accent-green);
        }}

        .no-stats {{
            text-align: center;
            color: var(--text-muted);
            font-style: italic;
            padding: 1rem;
        }}

        .prompt-details {{
            margin-top: 1rem;
        }}

        .prompt-details summary {{
            cursor: pointer;
            color: var(--accent-gold);
            font-weight: bold;
            padding: 0.5rem;
            background: rgba(0,0,0,0.2);
            border-radius: 4px;
        }}

        .prompt-details summary:hover {{
            background: rgba(0,0,0,0.3);
        }}

        .personality-prompt {{
            background: rgba(0,0,0,0.4);
            padding: 1rem;
            border-radius: 4px;
            margin-top: 0.5rem;
            font-family: 'Consolas', monospace;
            font-size: 0.8rem;
            white-space: pre-wrap;
            word-wrap: break-word;
            max-height: 400px;
            overflow-y: auto;
            line-height: 1.5;
        }}

        footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-size: 0.9rem;
        }}

        @media (max-width: 600px) {{
            .players-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>PLAYER GUIDE</h1>
        <p class="subtitle">AI Contestant Prompts & Strategy Documentation</p>
        <p class="back-link"><a href="index.html">Back to Game Runs</a></p>
    </header>

    <div class="container">
        <div class="intro">
            <h2>About This Guide</h2>
            <p>This page documents all the AI player prompts used in The Traitors simulator. Each player has a unique personality and strategy embedded in their prompt. The design notes explain the reasoning behind each prompt, and the hypothesis describes what behavior we expect to see.</p>
            <p style="margin-top: 1rem; color: var(--text-muted);">Players are defined as JSON files in the <code>prompts/</code> directory. Stats are updated after each game run.</p>
        </div>

        <div class="players-grid">
            {player_cards}
        </div>
    </div>

    <footer>
        <p>The Traitors LLM Simulator - Player Documentation</p>
        <p>{len(players)} players documented</p>
    </footer>
</body>
</html>
"""

    # Write to file
    with open(output_path, "w") as f:
        f.write(html_content)

    return html_content


def main():
    # Capture game log
    game_log = []

    def log_capture(msg: str):
        game_log.append(msg)
        print(msg)

    # Require API key for LLM-powered game
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required.")
        print("Please set your API key: export ANTHROPIC_API_KEY='your-key-here'")
        return

    print("Running with LLM agents (Claude Haiku)...\n")
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    game = TraitorsGame(
        contestants=EXAMPLE_CONTESTANTS,
        num_traitors=3,  # 3 traitors among 12 players
        client=client,
        log_callback=log_capture,
    )

    results = game.run()

    # Add players to results for HTML generation
    results["players"] = game.state.players
    results["messages"] = game.state.messages
    results["private_thoughts"] = getattr(game.state, 'private_thoughts', [])
    results["votes"] = game.state.votes
    results["llm_interactions"] = getattr(game.state, 'llm_interactions', [])

    # Generate HTML
    html_content = generate_game_html(results, game_log, EXAMPLE_CONTESTANTS)

    # Write to file
    with open("index.html", "w") as f:
        f.write(html_content)

    print("\n" + "=" * 60)
    print("HTML report generated: index.html")
    print("=" * 60)


if __name__ == "__main__":
    main()
