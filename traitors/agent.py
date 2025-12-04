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
YOUR SECRET ROLE: TRAITOR
Your fellow traitor(s): {', '.join(other_traitors)}
Your goal: Avoid being banished while eliminating the faithful one by one.
Strategy: Deceive the faithful players. Deflect suspicion from yourself and fellow traitors.
During public discussions, act like a faithful player while subtly casting doubt on others.
You and your fellow traitors are competing to be the ultimate winner, but must cooperate to survive.
"""
            else:
                role_info = """
YOUR SECRET ROLE: TRAITOR (you are the last one)
Your goal: Avoid being banished and survive to win the game.
Strategy: Deceive the faithful players. Deflect suspicion onto others.
During public discussions, act like a faithful player while subtly casting doubt on others.
"""
        else:
            role_info = """
YOUR ROLE: FAITHFUL
Your goal: Identify and banish the traitors before they eliminate you.
Strategy: Watch for suspicious behavior, inconsistencies, and defensive reactions.
Work with other faithful players to figure out who the traitors are.
Trust your instincts but verify with evidence from the discussions.
"""

        alive_players = [p.name for p in game_state.alive_players]
        eliminated = [
            f"{p.name} ({p.status.value})"
            for p in game_state.players.values()
            if not p.is_alive
        ]

        return f"""You are a contestant in "The Traitors", a social deduction reality game show simulation.
This is a GAME - you should fully commit to your role and play strategically to win.

CHARACTER INFORMATION:
Name: {self.player.name}
Personality: {self.player.personality_prompt}

{role_info}

GAME STATE:
Current round: {game_state.current_round} of {game_state.max_rounds}
Alive players: {', '.join(alive_players)}
Eliminated: {', '.join(eliminated) if eliminated else 'None yet'}

IMPORTANT:
- Stay in character as {self.player.name}
- Keep responses concise (1-3 sentences)
- If you're a traitor, NEVER explicitly reveal your role in public discussions
- Base accusations on observed behavior from conversations
- Play to WIN - this is a competitive game
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
            prefix = "[PRIVATE TRAITOR CHAT] " if msg.is_private else ""
            formatted.append(f"{prefix}{msg.speaker}: {msg.content}")

        return "\n".join(formatted)

    def generate_discussion(self, game_state: GameState, prompt: str = "") -> str:
        """Generate a discussion statement from this agent."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        user_message = f"""DISCUSSION HISTORY:
{history}

PUBLIC DISCUSSION - Your turn to speak. {prompt}
What do you say to the group? (1-3 sentences, in character)
Respond with your statement only, no quotation marks or name prefix."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        return response.content[0].text.strip()

    def generate_private_thoughts(self, game_state: GameState) -> str:
        """Generate private thoughts before voting - reveals the player's internal reasoning."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        if self.player.is_traitor:
            role_context = """You're a TRAITOR thinking privately about who to vote for.
Consider: Who is most dangerous to you? Who can you frame? How can you protect your fellow traitor(s)?
You might vote for a faithful player to eliminate them, or strategically vote with the group to avoid suspicion."""
        else:
            role_context = """You're FAITHFUL thinking privately about who might be a traitor.
Consider: Who has been acting suspiciously? Who has been deflecting? Who seems too eager or too quiet?
Trust your gut but also consider the evidence from discussions."""

        user_message = f"""DISCUSSION HISTORY:
{history}

PRIVATE THOUGHTS (not spoken aloud - your internal reasoning before voting)
Players you could vote for: {', '.join(voteable)}

{role_context}

Share your private thoughts about each player and who you're leaning toward voting for.
Be honest in your internal monologue - analyze each player's behavior and your suspicions.
Keep it to 2-4 sentences."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=250,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        return response.content[0].text.strip()

    def generate_vote(self, game_state: GameState) -> str:
        """Generate a vote for who to banish."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = f"""DISCUSSION HISTORY:
{history}

VOTING TIME - You must vote to banish ONE player.
Eligible players: {', '.join(voteable)}

Based on the discussion and your strategy, who do you vote to banish?
Respond with ONLY the player's name, nothing else."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
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

        user_message = f"""DISCUSSION HISTORY:
{history}

TRAITOR NIGHT PHASE - Choose a faithful player to murder tonight.
Available targets: {', '.join(targets)}

Strategic considerations:
- Who is most likely to expose you tomorrow?
- Who is leading the investigation?
- Who would be a strategic elimination?

Who do you vote to murder? Respond with ONLY the name."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
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

        other_traitors = [
            p.name for p in game_state.alive_traitors
            if p.name != self.player.name
        ]
        targets = [p.name for p in game_state.alive_faithful]

        other_traitor_text = f"Your fellow traitor(s): {', '.join(other_traitors)}" if other_traitors else "You are the only traitor left."

        user_message = f"""DISCUSSION HISTORY:
{history}

SECRET TRAITOR MEETING - The faithful players cannot hear this conversation.
{other_traitor_text}
Potential murder targets (faithful players): {', '.join(targets)}

This is your private strategy session. Speak freely about:
- Which faithful players suspect you or your allies?
- Who should be eliminated tonight and why?
- How to deflect suspicion in tomorrow's discussion?
- Any observations about the faithful players' alliances?

Remember: You're competing with your fellow traitor(s) for the ultimate win, but you need each other to survive.
Speak in character as {self.player.name}. Keep it to 2-3 sentences."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        return response.content[0].text.strip()
