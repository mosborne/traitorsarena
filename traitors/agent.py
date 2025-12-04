"""LLM-powered agent for playing The Traitors."""

import anthropic
from typing import Optional

from .types import Player, GameState, Message, Role


class Agent:
    """An LLM-powered contestant in The Traitors game."""

    def __init__(self, player: Player, client: Optional[anthropic.Anthropic] = None):
        self.player = player
        self.client = client or anthropic.Anthropic()

    def _build_system_prompt(self, game_state: GameState) -> str:
        """Build the system prompt for this agent."""
        role_info = ""
        if self.player.is_traitor:
            other_traitors = [
                p.name for p in game_state.alive_traitors
                if p.name != self.player.name
            ]
            if other_traitors:
                role_info = f"""
You are a TRAITOR. Your fellow traitor(s): {', '.join(other_traitors)}.
Your goal is to avoid being banished while the traitors eliminate the faithful one by one.
You must deceive the faithful players and deflect suspicion away from yourself and your fellow traitors.
During discussions, act like a faithful player while subtly casting doubt on others.
"""
            else:
                role_info = """
You are a TRAITOR. You are the only traitor remaining.
Your goal is to avoid being banished and survive to win the game.
You must deceive the faithful players and deflect suspicion.
During discussions, act like a faithful player while subtly casting doubt on others.
"""
        else:
            role_info = """
You are FAITHFUL. Your goal is to identify and banish the traitors.
Watch for suspicious behavior, inconsistencies, and defensive reactions.
Work with other faithful players to figure out who the traitors are.
"""

        alive_players = [p.name for p in game_state.alive_players]
        eliminated = [
            f"{p.name} ({p.status.value})"
            for p in game_state.players.values()
            if not p.is_alive
        ]

        return f"""You are playing The Traitors, a social deduction game.
Your name is: {self.player.name}
Your personality: {self.player.personality_prompt}

{role_info}

Current round: {game_state.current_round} of {game_state.max_rounds}
Alive players: {', '.join(alive_players)}
Eliminated players: {', '.join(eliminated) if eliminated else 'None yet'}

IMPORTANT RULES:
- Stay in character as {self.player.name} with your defined personality
- Keep your responses concise (1-3 sentences for discussions)
- Never explicitly reveal your role if you're a traitor
- Base your accusations on observed behavior from the conversation
"""

    def _format_conversation_history(self, game_state: GameState) -> str:
        """Format the conversation history for context."""
        if self.player.is_traitor:
            messages = game_state.get_traitor_messages()
        else:
            messages = game_state.get_public_messages()

        if not messages:
            return "No discussion has happened yet."

        formatted = []
        current_round = 0
        for msg in messages:
            if msg.round_num != current_round:
                current_round = msg.round_num
                formatted.append(f"\n--- Round {current_round} ---")
            prefix = "[PRIVATE] " if msg.is_private else ""
            formatted.append(f"{prefix}{msg.speaker}: {msg.content}")

        return "\n".join(formatted)

    def generate_discussion(self, game_state: GameState, prompt: str = "") -> str:
        """Generate a discussion statement from this agent."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        user_message = f"""Previous discussion:
{history}

It's your turn to speak in the discussion. {prompt}
Respond with what you want to say to the group (1-3 sentences, stay in character).
Just provide your statement directly, no need for quotes or prefixes."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        return response.content[0].text.strip()

    def generate_vote(self, game_state: GameState) -> str:
        """Generate a vote for who to banish."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = f"""Previous discussion:
{history}

It's time to vote. You must vote to banish ONE player.
Eligible players to vote for: {', '.join(voteable)}

Based on the discussion and your role, who do you vote to banish?
Respond with ONLY the name of the player you're voting for, nothing else."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        vote = response.content[0].text.strip()

        # Validate the vote is a valid player name
        for name in voteable:
            if name.lower() in vote.lower():
                return name

        # Fallback to first available player if parsing failed
        return voteable[0] if voteable else ""

    def generate_murder_vote(self, game_state: GameState) -> str:
        """Generate a vote for who to murder (traitors only)."""
        if not self.player.is_traitor:
            raise ValueError("Only traitors can vote to murder")

        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        targets = [p.name for p in game_state.alive_faithful]

        user_message = f"""Previous discussion:
{history}

TRAITOR NIGHT PHASE: You must secretly choose a faithful player to murder tonight.
Available targets (faithful players): {', '.join(targets)}

Consider:
- Who is most likely to expose you?
- Who is leading the investigation against traitors?
- Strategic elimination to reduce opposition

Who do you vote to murder? Respond with ONLY the name, nothing else."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        vote = response.content[0].text.strip()

        # Validate the vote
        for name in targets:
            if name.lower() in vote.lower():
                return name

        return targets[0] if targets else ""

    def generate_traitor_discussion(self, game_state: GameState) -> str:
        """Generate private traitor discussion (night phase)."""
        if not self.player.is_traitor:
            raise ValueError("Only traitors can participate in traitor discussion")

        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        targets = [p.name for p in game_state.alive_faithful]

        user_message = f"""Previous discussion (including your private traitor chat):
{history}

PRIVATE TRAITOR MEETING: Discuss strategy with your fellow traitor(s).
Faithful players you could target tonight: {', '.join(targets)}

Share your thoughts on:
- Who suspects you/other traitors?
- Who should be eliminated tonight?
- Strategy for the next round's discussion

Keep it brief (1-2 sentences). This is private - faithful players cannot see this."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        return response.content[0].text.strip()
