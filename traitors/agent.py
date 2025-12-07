"""LLM-powered agent for playing The Traitors."""

import anthropic
from datetime import datetime
from typing import Optional

from .types import Player, GameState, Message, Role, PlayerStatus, LLMInteraction


class Agent:
    """An LLM-powered contestant in The Traitors game."""

    def __init__(self, player: Player, client: Optional[anthropic.Anthropic] = None):
        self.player = player
        self.client = client or anthropic.Anthropic()

    def _get_round_events(self, game_state: GameState) -> dict[int, list[str]]:
        """Get elimination events organized by round."""
        events: dict[int, list[str]] = {}

        for player in game_state.players.values():
            if not player.is_alive:
                # Determine which round they were eliminated
                # Banishments happen during voting, murders happen at night
                # We track this by looking at the votes and when players died
                round_num = 1  # Default

                if player.status == PlayerStatus.BANISHED:
                    # Find the vote that banished them
                    for vote in game_state.votes:
                        if vote.target == player.name:
                            round_num = vote.round_num
                            break
                    event = f"🗳️ {player.name} was BANISHED (revealed as {player.role.value.upper()})"
                else:  # MURDERED
                    # Murders happen at night after the round's voting
                    # Find the round by checking messages
                    for msg in reversed(game_state.messages):
                        if msg.is_private and msg.round_num > 0:
                            round_num = msg.round_num
                            break
                    event = f"💀 {player.name} was MURDERED overnight (they were {player.role.value.upper()})"

                if round_num not in events:
                    events[round_num] = []
                events[round_num].append(event)

        return events

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
Your fellow traitor(s) still alive: {', '.join(other_traitors)}
Your goal: Avoid being banished while eliminating the faithful one by one.
Strategy: Deceive the faithful players. Deflect suspicion from yourself and fellow traitors.
During public discussions, act like a faithful player while subtly casting doubt on others.
"""
            else:
                role_info = """
YOUR SECRET ROLE: TRAITOR (you are the last one - any other traitors were already caught)
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
"""

        alive_players = [p.name for p in game_state.alive_players]

        # Build detailed elimination history with strategic context
        eliminated_details = []
        revealed_traitors = []
        murdered_faithful = []
        wrongly_banished = []

        for player in game_state.players.values():
            if not player.is_alive:
                if player.status == PlayerStatus.BANISHED:
                    eliminated_details.append(f"{player.name} - BANISHED (revealed as {player.role.value.upper()})")
                    if player.is_traitor:
                        revealed_traitors.append(player.name)
                    else:
                        wrongly_banished.append(player.name)
                else:  # MURDERED
                    eliminated_details.append(f"{player.name} - MURDERED (was {player.role.value.upper()})")
                    murdered_faithful.append(player.name)

        eliminated_str = "\n  ".join(eliminated_details) if eliminated_details else "None yet"

        # Build strategic analysis hints based on eliminations
        strategic_hints = []
        if revealed_traitors:
            strategic_hints.append(f"REVEALED TRAITORS: {', '.join(revealed_traitors)} - Analyze who defended them, voted with them, or they tried to protect")
        if murdered_faithful:
            strategic_hints.append(f"MURDERED (by traitors): {', '.join(murdered_faithful)} - Their suspicions were likely correct. Who did they suspect? Who did they trust?")
        if wrongly_banished:
            strategic_hints.append(f"WRONGLY BANISHED (were faithful): {', '.join(wrongly_banished)} - Who pushed hardest to banish them? That person may be a traitor")

        strategic_context = "\n".join(strategic_hints) if strategic_hints else ""

        return f"""You are a contestant in "The Traitors", a social deduction reality game show simulation.
This is a GAME - you should fully commit to your role and play strategically to win.

CHARACTER INFORMATION:
Name: {self.player.name}
Personality: {self.player.personality_prompt}

{role_info}

CURRENT GAME STATE (Round {game_state.current_round}):
Players still alive: {', '.join(alive_players)}
Players eliminated:
  {eliminated_str}

{strategic_context}

CRITICAL RULES:
- You can only VOTE for living players, but departed players' behavior is CRUCIAL EVIDENCE
- When a player is eliminated, their role is REVEALED - use this information!
- Analyze: Who defended revealed traitors? Who voted with them? Who did murdered players suspect?
- Stay in character as {self.player.name}
- Keep responses concise (1-3 sentences)
- If you're a traitor, NEVER explicitly reveal your role in public discussions
- Play to WIN - this is a competitive game
"""

    def _format_conversation_history(self, game_state: GameState) -> str:
        """Format the conversation history for context, including round events."""
        if self.player.is_traitor:
            messages = game_state.get_traitor_messages()
        else:
            messages = game_state.get_public_messages()

        round_events = self._get_round_events(game_state)

        if not messages and not round_events:
            return "No discussion has happened yet."

        formatted = []
        current_round = 0

        for msg in messages:
            if msg.round_num != current_round:
                # Before starting new round, add events from previous round
                if current_round > 0 and current_round in round_events:
                    formatted.append(f"\n--- END OF ROUND {current_round} ---")
                    for event in round_events[current_round]:
                        formatted.append(event)

                current_round = msg.round_num
                formatted.append(f"\n--- ROUND {current_round} DISCUSSION ---")

            prefix = "[PRIVATE TRAITOR CHAT] " if msg.is_private else ""
            formatted.append(f"{prefix}{msg.speaker}: {msg.content}")

        # Add final round events if we're past them
        if current_round > 0 and current_round in round_events and current_round < game_state.current_round:
            formatted.append(f"\n--- END OF ROUND {current_round} ---")
            for event in round_events[current_round]:
                formatted.append(event)

        return "\n".join(formatted)

    def _build_voting_history_context(self, game_state: GameState) -> str:
        """Build context about voting patterns, especially involving revealed traitors."""
        if not game_state.votes:
            return ""

        # Find revealed traitors
        revealed_traitors = {p.name for p in game_state.players.values()
                           if not p.is_alive and p.status == PlayerStatus.BANISHED and p.is_traitor}

        if not revealed_traitors:
            return ""

        # Analyze voting patterns with revealed traitors
        traitor_allies = {}  # Who voted same as traitors
        traitor_defenders = {}  # Who voted against banishing traitors

        for vote in game_state.votes:
            # Track who revealed traitors voted for (their targets were likely faithful)
            if vote.voter in revealed_traitors:
                if vote.voter not in traitor_allies:
                    traitor_allies[vote.voter] = []
                traitor_allies[vote.voter].append(f"Round {vote.round_num}: voted for {vote.target}")

        context_parts = []
        for traitor, votes in traitor_allies.items():
            context_parts.append(f"REVEALED TRAITOR {traitor}'s votes: {'; '.join(votes)}")

        if context_parts:
            return "VOTING HISTORY OF REVEALED TRAITORS (their targets were likely faithful threats):\n" + "\n".join(context_parts) + "\n\n"
        return ""

    def _get_round_context(self, game_state: GameState) -> str:
        """Get context about what happened in previous rounds."""
        if game_state.current_round == 1:
            return ""

        context_parts = []
        for player in game_state.players.values():
            if not player.is_alive:
                if player.status == PlayerStatus.BANISHED:
                    context_parts.append(f"{player.name} was banished and revealed to be a {player.role.value.upper()}")
                else:
                    context_parts.append(f"{player.name} was murdered by the traitors (was {player.role.value.upper()})")

        result = ""
        if context_parts:
            result = "WHAT HAPPENED SO FAR:\n- " + "\n- ".join(context_parts) + "\n\n"

        # Add voting history context
        result += self._build_voting_history_context(game_state)

        return result

    def _log_interaction(
        self,
        game_state: GameState,
        action_type: str,
        system_prompt: str,
        user_message: str,
        response: str,
        model: str = "claude-3-5-haiku-20241022"
    ) -> None:
        """Log an LLM interaction for debugging/transparency."""
        interaction = LLMInteraction(
            player=self.player.name,
            action_type=action_type,
            round_num=game_state.current_round,
            system_prompt=system_prompt,
            user_message=user_message,
            response=response,
            model=model,
            timestamp=datetime.now().isoformat()
        )
        game_state.llm_interactions.append(interaction)

    def generate_discussion(self, game_state: GameState, prompt: str = "") -> str:
        """Generate a discussion statement from this agent."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_names = [p.name for p in game_state.alive_players]

        user_message = f"""{round_context}DISCUSSION HISTORY:
{history}

ROUND {game_state.current_round} - PUBLIC DISCUSSION
Players still in the game: {', '.join(alive_names)}

Your turn to speak. {prompt}
STRATEGIC TIP: Reference departed players' revealed roles and past behavior as evidence. Who aligned with revealed traitors? What did murdered players suspect before they were silenced?
What do you say to the group? (1-3 sentences, in character)
Respond with your statement only, no quotation marks or name prefix."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        result = response.content[0].text.strip()
        self._log_interaction(game_state, "discussion", system, user_message, result)
        return result

    def generate_private_thoughts(self, game_state: GameState) -> str:
        """Generate private thoughts before voting - reveals the player's internal reasoning."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        if self.player.is_traitor:
            role_context = """You're a TRAITOR thinking privately about who to vote for.
Consider: Who is most dangerous to you? Who can you frame? How can you protect your fellow traitor(s)?
You might vote for a faithful player to eliminate them, or strategically vote with the group to avoid suspicion.
Be careful - if other traitors were revealed, the faithful may be analyzing who aligned with them."""
        else:
            role_context = """You're FAITHFUL thinking privately about who might be a traitor.
CRITICAL ANALYSIS TO PERFORM:
- Who defended or voted alongside any REVEALED TRAITORS? (Major red flag!)
- What did MURDERED players suspect before the traitors silenced them? (Their suspicions were likely correct!)
- Who pushed to banish players who turned out to be FAITHFUL? (Traitors eliminate threats)
- Are there voting patterns or alliances that span multiple revealed traitors?
Trust the evidence from revealed roles - it's your most reliable information."""

        user_message = f"""{round_context}DISCUSSION HISTORY:
{history}

PRIVATE THOUGHTS (not spoken aloud - your internal reasoning before voting)
Players you can vote for (those still alive): {', '.join(voteable)}

{role_context}

Analyze the living players, using departed players' revealed roles as evidence. Who do you suspect and why?
Keep it to 2-4 sentences."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=250,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        result = response.content[0].text.strip()
        self._log_interaction(game_state, "private_thoughts", system, user_message, result)
        return result

    def generate_vote(self, game_state: GameState) -> str:
        """Generate a vote for who to banish."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = f"""DISCUSSION HISTORY:
{history}

VOTING TIME - You must vote to banish ONE player.
Eligible players (still alive): {', '.join(voteable)}

Based on the discussion and your strategy, who do you vote to banish?
Respond with ONLY the player's name, nothing else."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=50,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        vote = response.content[0].text.strip()
        self._log_interaction(game_state, "vote", system, user_message, vote)

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
Available targets (faithful players still alive): {', '.join(targets)}

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
        self._log_interaction(game_state, "murder_vote", system, user_message, vote)

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
        round_context = self._get_round_context(game_state)

        other_traitors = [
            p.name for p in game_state.alive_traitors
            if p.name != self.player.name
        ]
        targets = [p.name for p in game_state.alive_faithful]

        other_traitor_text = f"Your fellow traitor(s): {', '.join(other_traitors)}" if other_traitors else "You are the only traitor left."

        user_message = f"""{round_context}DISCUSSION HISTORY:
{history}

SECRET TRAITOR MEETING - The faithful players cannot hear this conversation.
{other_traitor_text}
Potential murder targets (faithful players still alive): {', '.join(targets)}

This is your private strategy session. Speak freely about:
- Which faithful players suspect you or your allies?
- Who should be eliminated tonight and why?
- How to deflect suspicion in tomorrow's discussion?

Speak in character as {self.player.name}. Keep it to 2-3 sentences."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        result = response.content[0].text.strip()
        self._log_interaction(game_state, "traitor_discussion", system, user_message, result)
        return result

    def generate_end_game_vote(self, game_state: GameState) -> bool:
        """Generate a vote on whether to end the game or continue playing.

        Returns True to END the game, False to CONTINUE playing.
        """
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_count = len(game_state.alive_players)

        # Count known traitors (those who were banished and revealed)
        revealed_traitors = [p for p in game_state.players.values()
                           if p.status == PlayerStatus.BANISHED and p.is_traitor]
        revealed_faithful = [p for p in game_state.players.values()
                            if p.status == PlayerStatus.BANISHED and not p.is_traitor]

        if self.player.is_traitor:
            strategy_hint = """As a TRAITOR, consider:
- If the game ends now AND there are still traitors alive (including you), TRAITORS WIN!
- You WANT the game to end while you're still alive
- Vote to END if you think you can get away with it
- Only vote CONTINUE if you're worried about being caught first"""
        else:
            strategy_hint = f"""As FAITHFUL, consider:
- If the game ends and ANY traitors remain, they win everything
- {len(revealed_traitors)} traitor(s) have been caught so far
- There could still be traitors among the {alive_count} remaining players
- Vote END only if you're confident all traitors are gone
- Vote CONTINUE if you suspect there are still traitors hiding"""

        user_message = f"""{round_context}DISCUSSION HISTORY:
{history}

END GAME VOTE - Should the game end now?
Players remaining: {alive_count}
Traitors revealed (banished): {len(revealed_traitors)}
Faithful wrongly banished: {len(revealed_faithful)}

{strategy_hint}

If you vote END and traitors remain: TRAITORS WIN
If you vote END and all traitors are gone: FAITHFUL WIN and split the prize

Based on your role and what you know, do you vote to END the game or CONTINUE playing?
Respond with only END or CONTINUE."""

        response = self.client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=20,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        vote_text = response.content[0].text.strip().upper()
        self._log_interaction(game_state, "end_game_vote", system, user_message, vote_text)
        return "END" in vote_text
