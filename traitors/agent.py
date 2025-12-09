"""LLM-powered agent for playing The Traitors."""

import anthropic
import random
from datetime import datetime
from typing import Optional

from .types import Player, GameState, Message, Role, PlayerStatus, LLMInteraction
from . import prompts


class Agent:
    """An LLM-powered contestant in The Traitors game."""

    DEFAULT_MODEL = "claude-3-5-haiku-20241022"

    def __init__(self, player: Player, client: Optional[anthropic.Anthropic] = None, model: Optional[str] = None):
        self.player = player
        self.client = client or anthropic.Anthropic()
        self.model = model or self.DEFAULT_MODEL

    def _get_round_events(self, game_state: GameState) -> dict[int, list[str]]:
        """Get elimination events organized by round."""
        events: dict[int, list[str]] = {}

        for player in game_state.players.values():
            if not player.is_alive:
                # Use eliminated_round if available, otherwise determine from game data
                round_num = player.eliminated_round or 1

                if player.status == PlayerStatus.BANISHED:
                    # In finale, roles are NOT revealed when banished
                    if round_num > game_state.finale_round:
                        event = f"🗳️ {player.name} was BANISHED (role unknown - finale)"
                    else:
                        event = f"🗳️ {player.name} was BANISHED (revealed as {player.role.value.upper()})"
                else:  # MURDERED
                    event = f"💀 {player.name} was MURDERED overnight (they were {player.role.value.upper()})"

                if round_num not in events:
                    events[round_num] = []
                events[round_num].append(event)

        return events

    def _build_system_prompt(self, game_state: GameState) -> str:
        """Build the system prompt for this agent using templates."""
        prize_pool = game_state.prize_pool
        num_traitors = game_state.num_traitors
        total_players = len(game_state.players)

        # Build role-specific info using templates
        if self.player.is_traitor:
            other_traitors = [
                p.name for p in game_state.alive_traitors
                if p.name != self.player.name
            ]
            num_traitors_alive = len(game_state.alive_traitors)
            traitor_share = prize_pool // max(num_traitors_alive, 1)
            if other_traitors:
                role_info = prompts.TRAITOR_ROLE_INFO.format(
                    other_traitors=', '.join(other_traitors),
                    prize_pool=prize_pool,
                    traitor_share=traitor_share
                )
            else:
                role_info = prompts.SOLO_TRAITOR_ROLE_INFO.format(
                    prize_pool=prize_pool
                )
        else:
            num_alive = len(game_state.alive_players)
            faithful_share = prize_pool // max(num_alive - 1, 1)
            role_info = prompts.FAITHFUL_ROLE_INFO.format(
                prize_pool=prize_pool,
                faithful_share=faithful_share
            )

        alive_players = [p.name for p in game_state.alive_players]

        # Build elimination history
        eliminated_details = []
        for player in game_state.players.values():
            if not player.is_alive:
                if player.status == PlayerStatus.BANISHED:
                    # In finale (round > finale_round), roles are NOT revealed when banished
                    if player.eliminated_round and player.eliminated_round > game_state.finale_round:
                        eliminated_details.append(f"{player.name} - BANISHED (role unknown - finale)")
                    else:
                        eliminated_details.append(f"{player.name} - BANISHED (revealed: {player.role.value.upper()})")
                else:
                    eliminated_details.append(f"{player.name} - MURDERED (was {player.role.value.upper()})")

        eliminated_str = "\n  ".join(eliminated_details) if eliminated_details else "None yet"

        # Finale status notification
        finale_status = ""
        if game_state.is_finale:
            finale_status = "\n⚠️  FINALE: Roles are NO LONGER revealed when players are banished! No more murders."

        return prompts.SYSTEM_PROMPT_TEMPLATE.format(
            player_name=self.player.name,
            personality=self.player.personality_prompt,
            num_traitors=num_traitors,
            total_players=total_players,
            role_info=role_info,
            current_round=game_state.current_round,
            alive_players=', '.join(alive_players),
            eliminated_str=eliminated_str,
            endgame_status=finale_status,
            last_revealed_round=game_state.finale_round,
            endgame_round=game_state.finale_round + 1
        )

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

    def _get_round_context(self, game_state: GameState) -> str:
        """Get context about what happened in previous rounds."""
        if game_state.current_round == 1:
            return ""

        context_parts = []
        for player in game_state.players.values():
            if not player.is_alive:
                if player.status == PlayerStatus.BANISHED:
                    # In finale, roles are NOT revealed when banished
                    if player.eliminated_round and player.eliminated_round > game_state.finale_round:
                        context_parts.append(f"{player.name} was banished (role unknown - finale)")
                    else:
                        context_parts.append(f"{player.name} was banished (revealed: {player.role.value.upper()})")
                else:
                    context_parts.append(f"{player.name} was murdered (was {player.role.value.upper()})")

        if context_parts:
            return "Previous eliminations:\n- " + "\n- ".join(context_parts) + "\n\n"
        return ""

    def _log_interaction(
        self,
        game_state: GameState,
        action_type: str,
        system_prompt: str,
        user_message: str,
        response: str,
        model: Optional[str] = None
    ) -> None:
        """Log an LLM interaction for debugging/transparency."""
        interaction = LLMInteraction(
            player=self.player.name,
            action_type=action_type,
            round_num=game_state.current_round,
            system_prompt=system_prompt,
            user_message=user_message,
            response=response,
            model=model or self.model,
            timestamp=datetime.now().isoformat()
        )
        game_state.llm_interactions.append(interaction)

    def generate_discussion(self, game_state: GameState, instruction: str = "") -> str:
        """Generate a discussion statement from this agent."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_names = [p.name for p in game_state.alive_players]

        user_message = prompts.DISCUSSION_PROMPT.format(
            round_context=round_context,
            history=history,
            current_round=game_state.current_round,
            alive_names=', '.join(alive_names),
            instruction=instruction
        )

        response = self.client.messages.create(
            model=self.model,
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

        user_message = prompts.PRIVATE_THOUGHTS_PROMPT.format(
            round_context=round_context,
            history=history,
            voteable=', '.join(voteable)
        )

        response = self.client.messages.create(
            model=self.model,
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

        user_message = prompts.VOTE_PROMPT.format(
            history=history,
            voteable=', '.join(voteable)
        )

        response = self.client.messages.create(
            model=self.model,
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

        user_message = prompts.MURDER_VOTE_PROMPT.format(
            history=history,
            targets=', '.join(targets)
        )

        response = self.client.messages.create(
            model=self.model,
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

        user_message = prompts.TRAITOR_DISCUSSION_PROMPT.format(
            round_context=round_context,
            history=history,
            other_traitor_text=other_traitor_text,
            targets=', '.join(targets)
        )

        response = self.client.messages.create(
            model=self.model,
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

        # Count known traitors (those who were banished and revealed - not during finale)
        revealed_traitors = [p for p in game_state.players.values()
                           if p.status == PlayerStatus.BANISHED and p.is_traitor
                           and p.eliminated_round and p.eliminated_round <= game_state.finale_round]
        revealed_faithful = [p for p in game_state.players.values()
                            if p.status == PlayerStatus.BANISHED and not p.is_traitor
                            and p.eliminated_round and p.eliminated_round <= game_state.finale_round]

        prize_pool = game_state.prize_pool
        alive_faithful_count = len(game_state.alive_faithful)
        faithful_share = prize_pool // max(alive_faithful_count, 1) if alive_faithful_count > 0 else 0

        user_message = prompts.END_GAME_VOTE_PROMPT.format(
            round_context=round_context,
            history=history,
            prize_pool=prize_pool,
            alive_count=alive_count,
            revealed_traitors=len(revealed_traitors),
            revealed_faithful=len(revealed_faithful),
            faithful_share=faithful_share
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=20,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        vote_text = response.content[0].text.strip().upper()
        self._log_interaction(game_state, "end_game_vote", system, user_message, vote_text)
        return "END" in vote_text

    def generate_finale_pouch_choice(self, game_state: GameState) -> str:
        """Generate a pouch choice for the UK-style finale fire pit vote.

        Returns "END_GAME" to end the game or "BANISH_AGAIN" to force another banishment.
        """
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_count = len(game_state.alive_players)
        prize_pool = game_state.prize_pool

        # Count revealed traitors from pre-finale rounds
        revealed_traitors = [p for p in game_state.players.values()
                           if p.status == PlayerStatus.BANISHED and p.is_traitor
                           and p.eliminated_round and p.eliminated_round <= game_state.finale_round]

        # For traitors: they want to end the game to win
        # For faithful: they want to banish again if they suspect traitors remain
        if self.player.is_traitor:
            role_hint = "As a traitor, if you end the game now, you WIN and take all the money!"
        else:
            role_hint = f"As faithful, if you end the game with a traitor still hidden, they win everything. {len(revealed_traitors)} traitor(s) have been revealed so far."

        user_message = f"""{round_context}

The conversation so far:
{history}

=== FIRE PIT VOTE ===
It's the finale. You must choose one pouch to throw into the fire:
- END_GAME: End the game now. All roles will be revealed.
- BANISH_AGAIN: Force another round of voting (no role revealed after banishment).

{role_hint}

There are {alive_count} players remaining. Prize pool: ${prize_pool:,}

If ANYONE chooses BANISH_AGAIN, the group must vote again.
If EVERYONE chooses END_GAME, the game ends and roles are revealed.

Respond with exactly one word: END_GAME or BANISH_AGAIN"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=20,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )

        choice_text = response.content[0].text.strip().upper()
        self._log_interaction(game_state, "finale_pouch_choice", system, user_message, choice_text)

        # Parse the response
        if "BANISH" in choice_text:
            return "BANISH_AGAIN"
        return "END_GAME"


class OllamaAgent(Agent):
    """Agent using local Ollama for LLM inference.

    Uses Ollama's OpenAI-compatible API for free local inference.

    Setup:
        1. Install Ollama: brew install ollama
        2. Pull a model: ollama pull llama3.2
        3. Start server: ollama serve
    """

    def __init__(self, player: Player, model: str = "llama3.2", base_url: str = "http://localhost:11434/v1"):
        self.player = player
        self.model = model
        self.base_url = base_url
        # Import here to avoid requiring openai for anthropic-only users
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url, api_key="ollama")

    def _call_llm(self, system: str, user_message: str, max_tokens: int) -> str:
        """Call the local Ollama LLM."""
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message}
            ]
        )
        return response.choices[0].message.content.strip()

    def generate_discussion(self, game_state: GameState, instruction: str = "") -> str:
        """Generate a discussion statement from this agent."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_names = [p.name for p in game_state.alive_players]

        user_message = prompts.DISCUSSION_PROMPT.format(
            round_context=round_context,
            history=history,
            current_round=game_state.current_round,
            alive_names=', '.join(alive_names),
            instruction=instruction
        )

        result = self._call_llm(system, user_message, 200)
        self._log_interaction(game_state, "discussion", system, user_message, result, model=self.model)
        return result

    def generate_private_thoughts(self, game_state: GameState) -> str:
        """Generate private thoughts before voting."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = prompts.PRIVATE_THOUGHTS_PROMPT.format(
            round_context=round_context,
            history=history,
            voteable=', '.join(voteable)
        )

        result = self._call_llm(system, user_message, 250)
        self._log_interaction(game_state, "private_thoughts", system, user_message, result, model=self.model)
        return result

    def generate_vote(self, game_state: GameState) -> str:
        """Generate a vote for who to banish."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = prompts.VOTE_PROMPT.format(
            history=history,
            voteable=', '.join(voteable)
        )

        vote = self._call_llm(system, user_message, 50)
        self._log_interaction(game_state, "vote", system, user_message, vote, model=self.model)

        # Validate the vote is a valid player name
        for name in voteable:
            if name.lower() in vote.lower():
                return name

        return voteable[0] if voteable else ""

    def generate_murder_vote(self, game_state: GameState) -> str:
        """Generate a vote for who to murder (traitors only)."""
        if not self.player.is_traitor:
            raise ValueError("Only traitors can vote to murder")

        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)

        targets = [p.name for p in game_state.alive_faithful]

        user_message = prompts.MURDER_VOTE_PROMPT.format(
            history=history,
            targets=', '.join(targets)
        )

        vote = self._call_llm(system, user_message, 50)
        self._log_interaction(game_state, "murder_vote", system, user_message, vote, model=self.model)

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

        user_message = prompts.TRAITOR_DISCUSSION_PROMPT.format(
            round_context=round_context,
            history=history,
            other_traitor_text=other_traitor_text,
            targets=', '.join(targets)
        )

        result = self._call_llm(system, user_message, 200)
        self._log_interaction(game_state, "traitor_discussion", system, user_message, result, model=self.model)
        return result

    def generate_end_game_vote(self, game_state: GameState) -> bool:
        """Generate a vote on whether to end the game or continue."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_count = len(game_state.alive_players)

        revealed_traitors = [p for p in game_state.players.values()
                           if p.status == PlayerStatus.BANISHED and p.is_traitor
                           and p.eliminated_round and p.eliminated_round <= game_state.finale_round]
        revealed_faithful = [p for p in game_state.players.values()
                            if p.status == PlayerStatus.BANISHED and not p.is_traitor
                            and p.eliminated_round and p.eliminated_round <= game_state.finale_round]

        prize_pool = game_state.prize_pool
        alive_faithful_count = len(game_state.alive_faithful)
        faithful_share = prize_pool // max(alive_faithful_count, 1) if alive_faithful_count > 0 else 0

        user_message = prompts.END_GAME_VOTE_PROMPT.format(
            round_context=round_context,
            history=history,
            prize_pool=prize_pool,
            alive_count=alive_count,
            revealed_traitors=len(revealed_traitors),
            revealed_faithful=len(revealed_faithful),
            faithful_share=faithful_share
        )

        vote_text = self._call_llm(system, user_message, 20)
        self._log_interaction(game_state, "end_game_vote", system, user_message, vote_text, model=self.model)
        return "END" in vote_text.upper()

    def generate_finale_pouch_choice(self, game_state: GameState) -> str:
        """Generate a pouch choice for the UK-style finale fire pit vote."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_count = len(game_state.alive_players)
        prize_pool = game_state.prize_pool

        revealed_traitors = [p for p in game_state.players.values()
                           if p.status == PlayerStatus.BANISHED and p.is_traitor
                           and p.eliminated_round and p.eliminated_round <= game_state.finale_round]

        if self.player.is_traitor:
            role_hint = "As a traitor, if you end the game now, you WIN and take all the money!"
        else:
            role_hint = f"As faithful, if you end the game with a traitor still hidden, they win everything. {len(revealed_traitors)} traitor(s) have been revealed so far."

        user_message = f"""{round_context}

The conversation so far:
{history}

=== FIRE PIT VOTE ===
It's the finale. You must choose one pouch to throw into the fire:
- END_GAME: End the game now. All roles will be revealed.
- BANISH_AGAIN: Force another round of voting (no role revealed after banishment).

{role_hint}

There are {alive_count} players remaining. Prize pool: ${prize_pool:,}

If ANYONE chooses BANISH_AGAIN, the group must vote again.
If EVERYONE chooses END_GAME, the game ends and roles are revealed.

Respond with exactly one word: END_GAME or BANISH_AGAIN"""

        choice_text = self._call_llm(system, user_message, 20)
        self._log_interaction(game_state, "finale_pouch_choice", system, user_message, choice_text, model=self.model)

        if "BANISH" in choice_text.upper():
            return "BANISH_AGAIN"
        return "END_GAME"


class TestAgent(Agent):
    """A test agent that returns random decisions without calling the LLM.

    Useful for quickly testing game mechanics without API costs.
    """

    def __init__(self, player: Player, client: Optional[anthropic.Anthropic] = None):
        self.player = player
        self.client = None  # Don't need the client

    def generate_discussion(self, game_state: GameState, instruction: str = "") -> str:
        """Return empty discussion."""
        return ""

    def generate_private_thoughts(self, game_state: GameState) -> str:
        """Return empty thoughts."""
        return ""

    def generate_vote(self, game_state: GameState) -> str:
        """Vote for a random alive player (not self)."""
        candidates = [p.name for p in game_state.alive_players if p.name != self.player.name]
        return random.choice(candidates) if candidates else self.player.name

    def generate_murder_vote(self, game_state: GameState) -> str:
        """Vote to murder a random faithful player."""
        faithful = [p.name for p in game_state.alive_faithful]
        return random.choice(faithful) if faithful else ""

    def generate_traitor_discussion(self, game_state: GameState) -> str:
        """Return empty traitor discussion."""
        return ""

    def generate_end_game_vote(self, game_state: GameState) -> bool:
        """Random vote on whether to end the game."""
        return random.choice([True, False])

    def generate_finale_pouch_choice(self, game_state: GameState) -> str:
        """Random pouch choice for finale.

        Traitors prefer END_GAME (70% chance) since it helps them win.
        Faithful prefer BANISH_AGAIN (60% chance) to catch remaining traitors.
        """
        if self.player.is_traitor:
            return "END_GAME" if random.random() < 0.7 else "BANISH_AGAIN"
        else:
            return "BANISH_AGAIN" if random.random() < 0.6 else "END_GAME"
