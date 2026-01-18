"""LLM-powered agent for playing The Traitors."""

import anthropic
import random
import re
import time
from datetime import datetime
from typing import Callable, Optional, Union

from .types import Player, GameState, Message, Role, PlayerStatus, LLMInteraction
from .cost import TokenUsage
from . import prompts


def parse_combined_response(response: str) -> tuple[str, str]:
    """Parse a combined response into statement and thoughts.

    Returns (statement, thoughts) tuple.
    """
    statement_match = re.search(r'<statement>\s*(.*?)\s*</statement>', response, re.DOTALL)
    thoughts_match = re.search(r'<thoughts>\s*(.*?)\s*</thoughts>', response, re.DOTALL)

    statement = statement_match.group(1).strip() if statement_match else response.strip()
    thoughts = thoughts_match.group(1).strip() if thoughts_match else ""

    return statement, thoughts


class Agent:
    """An LLM-powered contestant in The Traitors game."""

    DEFAULT_MODEL = "claude-3-5-haiku-20241022"

    def __init__(
        self,
        player: Player,
        client: Optional[anthropic.Anthropic] = None,
        model: Optional[str] = None,
        api_callback: Optional[Callable] = None,
    ):
        self.player = player
        self.client = client or anthropic.Anthropic()
        self.model = model or self.DEFAULT_MODEL
        self.api_callback = api_callback  # Called after each API call with (player, action_type, usage, duration_ms)

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
        """Build the system prompt for this agent using templates (legacy string version)."""
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

    def _build_cached_system_prompt(self, game_state: GameState) -> str:
        """Build system prompt string for API calls.

        Note: System prompt caching not effective (~300-400 tokens, under 1024 minimum).
        User message caching (conversation history) works in later rounds when history
        exceeds 1024 tokens.
        """
        prize_pool = game_state.prize_pool
        num_traitors = game_state.num_traitors
        total_players = len(game_state.players)

        # Build role-specific content
        if self.player.is_traitor:
            other_traitors = [
                p.name for p in game_state.alive_traitors
                if p.name != self.player.name
            ]
            if other_traitors:
                role_content = prompts.SYSTEM_PROMPT_ROLE_TRAITOR.format(
                    other_traitors=', '.join(other_traitors)
                )
            else:
                role_content = prompts.SYSTEM_PROMPT_ROLE_SOLO_TRAITOR
        else:
            role_content = prompts.SYSTEM_PROMPT_ROLE_FAITHFUL

        # Build player identity with personality
        identity_content = prompts.SYSTEM_PROMPT_PLAYER_IDENTITY.format(
            player_name=self.player.name,
            personality=self.player.personality_prompt
        )

        # Build dynamic state
        alive_players = [p.name for p in game_state.alive_players]

        eliminated_details = []
        for player in game_state.players.values():
            if not player.is_alive:
                if player.status == PlayerStatus.BANISHED:
                    if player.eliminated_round and player.eliminated_round > game_state.finale_round:
                        eliminated_details.append(f"{player.name} - BANISHED (role unknown - finale)")
                    else:
                        eliminated_details.append(f"{player.name} - BANISHED (revealed: {player.role.value.upper()})")
                else:
                    eliminated_details.append(f"{player.name} - MURDERED (was {player.role.value.upper()})")

        eliminated_str = "\n  ".join(eliminated_details) if eliminated_details else "None yet"

        finale_status = ""
        if game_state.is_finale:
            finale_status = "\n⚠️  FINALE: Roles are NO LONGER revealed when players are banished! No more murders."

        dynamic_content = prompts.SYSTEM_PROMPT_DYNAMIC_STATE.format(
            num_traitors=num_traitors,
            total_players=total_players,
            prize_pool=prize_pool,
            current_round=game_state.current_round,
            alive_players=', '.join(alive_players),
            eliminated_str=eliminated_str,
            endgame_status=finale_status,
            last_revealed_round=game_state.finale_round,
            endgame_round=game_state.finale_round + 1
        )

        # Combine all content into a single system prompt string
        static_content = f"{prompts.SYSTEM_PROMPT_STATIC_RULES}\n\n{identity_content}\n\n{role_content}"
        return f"{static_content}\n\n{dynamic_content}"

    def _build_static_system_prompt(self) -> str:
        """Build static system prompt - identical for all players.

        This enables cache sharing across players since the system prompt
        is the same for everyone.
        """
        return prompts.SYSTEM_PROMPT_STATIC_RULES

    def _build_player_context(self, game_state: GameState) -> str:
        """Build player-specific context (identity + role + state).

        This goes AFTER the cached history in the user message, enabling
        cache sharing across all players.
        """
        prize_pool = game_state.prize_pool
        num_traitors = game_state.num_traitors
        total_players = len(game_state.players)

        # Build role-specific info
        if self.player.is_traitor:
            other_traitors = [
                p.name for p in game_state.alive_traitors
                if p.name != self.player.name
            ]
            if other_traitors:
                role_info = f"YOUR SECRET ROLE: TRAITOR\nFellow traitors: {', '.join(other_traitors)}"
            else:
                role_info = "YOUR SECRET ROLE: TRAITOR (you are the last one!)"
        else:
            role_info = "YOUR ROLE: FAITHFUL"

        # Build game state info
        alive_players = [p.name for p in game_state.alive_players]

        eliminated_details = []
        for player in game_state.players.values():
            if not player.is_alive:
                if player.status == PlayerStatus.BANISHED:
                    if player.eliminated_round and player.eliminated_round > game_state.finale_round:
                        eliminated_details.append(f"{player.name} - BANISHED (role unknown - finale)")
                    else:
                        eliminated_details.append(f"{player.name} - BANISHED (revealed: {player.role.value.upper()})")
                else:
                    eliminated_details.append(f"{player.name} - MURDERED (was {player.role.value.upper()})")

        eliminated_str = "\n  ".join(eliminated_details) if eliminated_details else "None yet"

        finale_status = ""
        if game_state.is_finale:
            finale_status = "\n⚠️  FINALE: Roles are NO LONGER revealed when players are banished! No more murders."

        game_state_str = f"""GAME SETUP: {num_traitors} traitors hidden among {total_players} players. Prize pool: ${prize_pool:,}
Round {game_state.current_round}
Players alive: {', '.join(alive_players)}
Eliminated:
  {eliminated_str}{finale_status}"""

        return prompts.PLAYER_CONTEXT_TEMPLATE.format(
            player_name=self.player.name,
            personality=self.player.personality_prompt,
            role_info=role_info,
            game_state=game_state_str
        )

    def _build_cached_user_message(
        self,
        player_context: str,
        prompt: str,
        cached_history: Optional[str] = None
    ) -> Union[list, str]:
        """Build user message with cached history block.

        Structure when cached_history provided:
          [Block 1: History - cached]
          [Block 2: Player context + Prompt - not cached]

        This enables cache sharing across all players since the history
        prefix is identical and player-specific content comes after.
        """
        if cached_history:
            return [
                {
                    "type": "text",
                    "text": cached_history,
                    "cache_control": {"type": "ephemeral"}
                },
                {
                    "type": "text",
                    "text": f"{player_context}\n\n{prompt}"
                }
            ]
        # No caching - include everything in regular message
        return f"{player_context}\n\n{prompt}"

    def _format_current_round_history(self, game_state: GameState) -> str:
        """Format only the current round's messages (dynamic part of history).

        Used during discussion phases where previous rounds are cached separately.
        This formats only messages from the current round, which changes after each speaker.
        """
        current_round = game_state.current_round

        if self.player.is_traitor:
            messages = [m for m in game_state.messages if m.round_num == current_round]
        else:
            messages = [m for m in game_state.messages if m.round_num == current_round and not m.is_private]

        if not messages:
            return f"\n--- ROUND {current_round} DISCUSSION ---\n(No messages yet this round)"

        formatted = [f"\n--- ROUND {current_round} DISCUSSION ---"]
        for msg in messages:
            prefix = "[PRIVATE TRAITOR CHAT] " if msg.is_private else ""
            formatted.append(f"{prefix}{msg.speaker}: {msg.content}")

        return "\n".join(formatted)

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
        model: Optional[str] = None,
        usage: Optional[TokenUsage] = None,
        duration_ms: float = 0,
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
            timestamp=datetime.now().isoformat(),
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            cache_creation_tokens=usage.cache_creation_tokens if usage else 0,
            cache_read_tokens=usage.cache_read_tokens if usage else 0,
        )
        game_state.llm_interactions.append(interaction)

        # Notify callback if set
        if self.api_callback and usage:
            self.api_callback(
                self.player.name,
                action_type,
                usage,
                duration_ms,
                model or self.model,
            )

    def _extract_usage(self, response) -> TokenUsage:
        """Extract token usage from an Anthropic API response."""
        usage = response.usage
        return TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0,
            cache_read_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0,
        )

    def generate_discussion(self, game_state: GameState, instruction: str = "") -> str:
        """Generate a discussion statement from this agent.

        Note: Discussion doesn't use cached history since it changes after each speaker.
        """
        # Static system prompt (same for all players - enables cache sharing)
        system = self._build_static_system_prompt()

        # Player-specific context (goes in user message)
        player_context = self._build_player_context(game_state)

        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_names = [p.name for p in game_state.alive_players]

        discussion_prompt = f"""{round_context}DISCUSSION HISTORY:
{history}

ROUND {game_state.current_round} - PUBLIC DISCUSSION
Players in the game: {', '.join(alive_names)}

Your turn to speak. {instruction}
Respond with your statement only (1-3 sentences, in character)."""

        user_message = f"{player_context}\n\n{discussion_prompt}"

        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )
        duration_ms = (time.time() - start_time) * 1000

        result = response.content[0].text.strip()
        usage = self._extract_usage(response)
        self._log_interaction(game_state, "discussion", system, user_message, result, usage=usage, duration_ms=duration_ms)
        return result

    def generate_combined_discussion(
        self,
        game_state: GameState,
        turn_number: int,
        max_turns: int,
        instruction: str = "",
        cached_previous_rounds: Optional[str] = None
    ) -> tuple[str, str]:
        """Generate a discussion statement with private thoughts in one response.

        Returns (statement, thoughts) tuple. Statement may be "PASS" if player has nothing to add.

        Args:
            game_state: Current game state
            turn_number: Current speaking turn (1 to max_turns)
            max_turns: Maximum speaking turns per round
            instruction: Specific instruction for this turn
            cached_previous_rounds: Pre-built history from rounds 1 to N-1 (for caching)
        """
        # Static system prompt (same for all players - enables cache sharing)
        system = self._build_static_system_prompt()

        # Player-specific context (goes after cached block in user message)
        player_context = self._build_player_context(game_state)

        round_context = self._get_round_context(game_state)
        alive_names = [p.name for p in game_state.alive_players]

        # Build the discussion prompt
        discussion_prompt = f"""ROUND {game_state.current_round} - PUBLIC DISCUSSION
Players: {', '.join(alive_names)}
Turn: {turn_number} of {max_turns}

{instruction}

If you have nothing new to add, respond with PASS as your statement.

Format your response EXACTLY like this:
<statement>[Your public statement OR "PASS"]</statement>
<thoughts>[Brief: who you suspect and why]</thoughts>"""

        if cached_previous_rounds:
            # Use split caching: previous rounds cached, current round + player context dynamic
            current_round_history = self._format_current_round_history(game_state)

            # Cache: previous rounds history
            # Dynamic: player context + current round + prompt
            cached_block = f"{round_context}DISCUSSION HISTORY (previous rounds):\n{cached_previous_rounds}"
            dynamic_block = f"{player_context}\n\nDISCUSSION HISTORY (current round):\n{current_round_history}\n\n{discussion_prompt}"

            user_content = [
                {
                    "type": "text",
                    "text": cached_block,
                    "cache_control": {"type": "ephemeral"}
                },
                {
                    "type": "text",
                    "text": dynamic_block
                }
            ]
            user_message_for_log = f"{cached_block}\n\n{dynamic_block}"
        else:
            # No caching (round 1) - use full history formatting
            history = self._format_conversation_history(game_state)
            user_content = f"""{player_context}

{round_context}DISCUSSION HISTORY:
{history}

{discussion_prompt}"""
            user_message_for_log = user_content

        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_content}]
        )
        duration_ms = (time.time() - start_time) * 1000

        result = response.content[0].text.strip()
        usage = self._extract_usage(response)
        self._log_interaction(game_state, "combined_discussion", system, user_message_for_log, result, usage=usage, duration_ms=duration_ms)

        statement, thoughts = parse_combined_response(result)
        return statement, thoughts

    def generate_private_thoughts(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate private thoughts before voting - reveals the player's internal reasoning.

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across all voting players
        """
        # Static system prompt (same for all players - enables cache sharing)
        system = self._build_static_system_prompt()

        # Player-specific context (goes after cached block in user message)
        player_context = self._build_player_context(game_state)

        # History: use cached or format fresh
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        # Build prompt (history is now separate from the prompt itself)
        thoughts_prompt = f"""{round_context}DISCUSSION HISTORY:
{history}

PRIVATE THOUGHTS - Who do you suspect most?
Players: {', '.join(voteable)}

(1 sentence max)"""

        # User message: [cached history] + [context + prompt]
        if cached_history:
            user_content = self._build_cached_user_message(
                player_context=player_context,
                prompt=thoughts_prompt,
                cached_history=f"{round_context}DISCUSSION HISTORY:\n{history}"
            )
            user_message_for_log = f"{player_context}\n\n{thoughts_prompt}"
        else:
            user_content = f"{player_context}\n\n{thoughts_prompt}"
            user_message_for_log = user_content

        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=100,
            system=system,
            messages=[{"role": "user", "content": user_content}]
        )
        duration_ms = (time.time() - start_time) * 1000

        result = response.content[0].text.strip()
        usage = self._extract_usage(response)
        self._log_interaction(game_state, "private_thoughts", system, user_message_for_log, result, usage=usage, duration_ms=duration_ms)
        return result

    def generate_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a vote for who to banish.

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across all voting players
        """
        # Static system prompt (same for all players - enables cache sharing)
        system = self._build_static_system_prompt()

        # Player-specific context (goes after cached block in user message)
        player_context = self._build_player_context(game_state)

        # History: use cached or format fresh
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        # Build prompt (history is now separate from the prompt itself)
        vote_prompt = f"""DISCUSSION HISTORY:
{history}

VOTING TIME - You must vote to banish ONE player.
Eligible players (still alive): {', '.join(voteable)}

Based on the discussion and your strategy, who do you vote to banish?
Respond with ONLY the player's name, nothing else."""

        # User message: [cached history] + [context + prompt]
        if cached_history:
            user_content = self._build_cached_user_message(
                player_context=player_context,
                prompt=vote_prompt,
                cached_history=f"DISCUSSION HISTORY:\n{history}"
            )
            # For logging, we want the full message as a string
            user_message_for_log = f"{player_context}\n\n{vote_prompt}"
        else:
            user_content = f"{player_context}\n\n{vote_prompt}"
            user_message_for_log = user_content

        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=50,
            system=system,
            messages=[{"role": "user", "content": user_content}]
        )
        duration_ms = (time.time() - start_time) * 1000

        vote = response.content[0].text.strip()
        usage = self._extract_usage(response)
        self._log_interaction(game_state, "vote", system, user_message_for_log, vote, usage=usage, duration_ms=duration_ms)

        # Validate the vote is a valid player name
        for name in voteable:
            if name.lower() in vote.lower():
                return name

        # Fallback to first available player if parsing failed
        return voteable[0] if voteable else ""

    def generate_murder_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a vote for who to murder (traitors only).

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across traitors
        """
        if not self.player.is_traitor:
            raise ValueError("Only traitors can vote to murder")

        # Static system prompt (same for all players - enables cache sharing)
        system = self._build_static_system_prompt()

        # Player-specific context (goes after cached block in user message)
        player_context = self._build_player_context(game_state)

        # History: use cached or format fresh
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)

        targets = [p.name for p in game_state.alive_faithful]

        # Build prompt
        murder_prompt = f"""DISCUSSION HISTORY:
{history}

TRAITOR NIGHT PHASE - Choose a faithful player to murder tonight.
Available targets: {', '.join(targets)}

Who do you vote to murder? Respond with ONLY the name."""

        # User message: [cached history] + [context + prompt]
        if cached_history:
            user_content = self._build_cached_user_message(
                player_context=player_context,
                prompt=murder_prompt,
                cached_history=f"DISCUSSION HISTORY:\n{history}"
            )
            user_message_for_log = f"{player_context}\n\n{murder_prompt}"
        else:
            user_content = f"{player_context}\n\n{murder_prompt}"
            user_message_for_log = user_content

        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=50,
            system=system,
            messages=[{"role": "user", "content": user_content}]
        )
        duration_ms = (time.time() - start_time) * 1000

        vote = response.content[0].text.strip()
        usage = self._extract_usage(response)
        self._log_interaction(game_state, "murder_vote", system, user_message_for_log, vote, usage=usage, duration_ms=duration_ms)

        # Validate the vote
        for name in targets:
            if name.lower() in vote.lower():
                return name

        return targets[0] if targets else ""

    def generate_traitor_discussion(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate private traitor discussion (night phase).

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across traitors
        """
        if not self.player.is_traitor:
            raise ValueError("Only traitors can participate in traitor discussion")

        # Static system prompt (same for all players - enables cache sharing)
        system = self._build_static_system_prompt()

        # Player-specific context (goes after cached block in user message)
        player_context = self._build_player_context(game_state)

        # History: use cached or format fresh
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        other_traitors = [
            p.name for p in game_state.alive_traitors
            if p.name != self.player.name
        ]
        targets = [p.name for p in game_state.alive_faithful]

        other_traitor_text = f"Your fellow traitor(s): {', '.join(other_traitors)}" if other_traitors else "You are the only traitor left."

        # Build prompt
        traitor_prompt = f"""{round_context}DISCUSSION HISTORY:
{history}

SECRET TRAITOR MEETING - The faithful cannot hear this.
{other_traitor_text}
Potential targets: {', '.join(targets)}

Speak freely. (2-3 sentences)"""

        # User message: [cached history] + [context + prompt]
        if cached_history:
            user_content = self._build_cached_user_message(
                player_context=player_context,
                prompt=traitor_prompt,
                cached_history=f"{round_context}DISCUSSION HISTORY:\n{history}"
            )
            user_message_for_log = f"{player_context}\n\n{traitor_prompt}"
        else:
            user_content = f"{player_context}\n\n{traitor_prompt}"
            user_message_for_log = user_content

        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_content}]
        )
        duration_ms = (time.time() - start_time) * 1000

        result = response.content[0].text.strip()
        usage = self._extract_usage(response)
        self._log_interaction(game_state, "traitor_discussion", system, user_message_for_log, result, usage=usage, duration_ms=duration_ms)
        return result

    def generate_end_game_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> bool:
        """Generate a vote on whether to end the game or continue playing.

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across all voting players

        Returns True to END the game, False to CONTINUE playing.
        """
        # Static system prompt (same for all players - enables cache sharing)
        system = self._build_static_system_prompt()

        # Player-specific context (goes after cached block in user message)
        player_context = self._build_player_context(game_state)

        # History: use cached or format fresh
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
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

        # Build prompt
        end_game_prompt = f"""{round_context}DISCUSSION HISTORY:
{history}

END GAME VOTE - Should the game end now?
PRIZE POOL: ${prize_pool:,}
Players remaining: {alive_count}
Traitors revealed (banished): {len(revealed_traitors)}
Faithful wrongly banished: {len(revealed_faithful)}

OUTCOMES:
- END + traitors remain = Traitors take ${prize_pool:,}, faithful get $0
- END + all traitors caught = Faithful split ${prize_pool:,} (${faithful_share:,} each)
- CONTINUE = Game continues, traitors murder one faithful tonight

Maximize your expected prize money. Vote END or CONTINUE.
Respond with only END or CONTINUE."""

        # User message: [cached history] + [context + prompt]
        if cached_history:
            user_content = self._build_cached_user_message(
                player_context=player_context,
                prompt=end_game_prompt,
                cached_history=f"{round_context}DISCUSSION HISTORY:\n{history}"
            )
            user_message_for_log = f"{player_context}\n\n{end_game_prompt}"
        else:
            user_content = f"{player_context}\n\n{end_game_prompt}"
            user_message_for_log = user_content

        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=20,
            system=system,
            messages=[{"role": "user", "content": user_content}]
        )
        duration_ms = (time.time() - start_time) * 1000

        vote_text = response.content[0].text.strip().upper()
        usage = self._extract_usage(response)
        self._log_interaction(game_state, "end_game_vote", system, user_message_for_log, vote_text, usage=usage, duration_ms=duration_ms)
        return "END" in vote_text

    def generate_finale_pouch_choice(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a pouch choice for the UK-style finale fire pit vote.

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across all voting players

        Returns "END_GAME" to end the game or "BANISH_AGAIN" to force another banishment.
        """
        # Static system prompt (same for all players - enables cache sharing)
        system = self._build_static_system_prompt()

        # Player-specific context (goes after cached block in user message)
        player_context = self._build_player_context(game_state)

        # History: use cached or format fresh
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
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

        # Build prompt
        finale_prompt = f"""{round_context}

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

        # User message: [cached history] + [context + prompt]
        if cached_history:
            user_content = self._build_cached_user_message(
                player_context=player_context,
                prompt=finale_prompt,
                cached_history=f"{round_context}\n\nThe conversation so far:\n{history}"
            )
            user_message_for_log = f"{player_context}\n\n{finale_prompt}"
        else:
            user_content = f"{player_context}\n\n{finale_prompt}"
            user_message_for_log = user_content

        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=20,
            system=system,
            messages=[{"role": "user", "content": user_content}]
        )
        duration_ms = (time.time() - start_time) * 1000

        choice_text = response.content[0].text.strip().upper()
        usage = self._extract_usage(response)
        self._log_interaction(game_state, "finale_pouch_choice", system, user_message_for_log, choice_text, usage=usage, duration_ms=duration_ms)

        # Parse the response
        if "BANISH" in choice_text:
            return "BANISH_AGAIN"
        return "END_GAME"


class OpenAICompatibleAgent(Agent):
    """Agent using any OpenAI-compatible API (Ollama, Gemini, etc.).

    This base class works with any API that follows the OpenAI chat completions format.
    Subclasses just need to specify base_url and api_key.
    """

    def __init__(
        self,
        player: Player,
        model: str,
        base_url: str,
        api_key: str = "dummy",
        api_callback: Optional[Callable] = None,
    ):
        self.player = player
        self.model = model
        self.base_url = base_url
        self.api_callback = api_callback
        # Import here to avoid requiring openai for anthropic-only users
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def _call_llm(self, system: str, user_message: str, max_tokens: int) -> tuple[str, Optional[TokenUsage], float]:
        """Call the OpenAI-compatible LLM API. Returns (text, usage, duration_ms)."""
        start_time = time.time()
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message}
            ]
        )
        duration_ms = (time.time() - start_time) * 1000

        # Extract usage from OpenAI format
        usage = None
        if response.usage:
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
                cache_creation_tokens=0,
                cache_read_tokens=0,
            )

        # Extract response text with safety checks
        text = ""
        if response.choices and len(response.choices) > 0:
            content = response.choices[0].message.content
            if content:
                text = content.strip()

        return text, usage, duration_ms

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

        result, usage, duration_ms = self._call_llm(system, user_message, 200)
        self._log_interaction(game_state, "discussion", system, user_message, result, model=self.model, usage=usage, duration_ms=duration_ms)
        return result

    def generate_combined_discussion(
        self,
        game_state: GameState,
        turn_number: int,
        max_turns: int,
        instruction: str = "",
        cached_previous_rounds: Optional[str] = None
    ) -> tuple[str, str]:
        """Generate a discussion statement with private thoughts in one response.

        Note: OllamaAgent doesn't use Anthropic's caching, so cached_previous_rounds is ignored.
        """
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_names = [p.name for p in game_state.alive_players]

        user_message = prompts.COMBINED_DISCUSSION_PROMPT.format(
            round_context=round_context,
            history=history,
            current_round=game_state.current_round,
            alive_names=', '.join(alive_names),
            turn_number=turn_number,
            max_turns=max_turns,
            instruction=instruction
        )

        result, usage, duration_ms = self._call_llm(system, user_message, 200)
        self._log_interaction(game_state, "combined_discussion", system, user_message, result, model=self.model, usage=usage, duration_ms=duration_ms)

        statement, thoughts = parse_combined_response(result)
        return statement, thoughts

    def generate_private_thoughts(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate private thoughts before voting."""
        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = prompts.PRIVATE_THOUGHTS_PROMPT.format(
            round_context=round_context,
            history=history,
            voteable=', '.join(voteable)
        )

        result, usage, duration_ms = self._call_llm(system, user_message, 100)
        self._log_interaction(game_state, "private_thoughts", system, user_message, result, model=self.model, usage=usage, duration_ms=duration_ms)
        return result

    def generate_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a vote for who to banish."""
        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = prompts.VOTE_PROMPT.format(
            history=history,
            voteable=', '.join(voteable)
        )

        vote, usage, duration_ms = self._call_llm(system, user_message, 50)
        self._log_interaction(game_state, "vote", system, user_message, vote, model=self.model, usage=usage, duration_ms=duration_ms)

        # Validate the vote is a valid player name
        for name in voteable:
            if name.lower() in vote.lower():
                return name

        return voteable[0] if voteable else ""

    def generate_murder_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a vote for who to murder (traitors only)."""
        if not self.player.is_traitor:
            raise ValueError("Only traitors can vote to murder")

        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)

        targets = [p.name for p in game_state.alive_faithful]

        user_message = prompts.MURDER_VOTE_PROMPT.format(
            history=history,
            targets=', '.join(targets)
        )

        vote, usage, duration_ms = self._call_llm(system, user_message, 50)
        self._log_interaction(game_state, "murder_vote", system, user_message, vote, model=self.model, usage=usage, duration_ms=duration_ms)

        for name in targets:
            if name.lower() in vote.lower():
                return name

        return targets[0] if targets else ""

    def generate_traitor_discussion(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate private traitor discussion (night phase)."""
        if not self.player.is_traitor:
            raise ValueError("Only traitors can participate in traitor discussion")

        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
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

        result, usage, duration_ms = self._call_llm(system, user_message, 200)
        self._log_interaction(game_state, "traitor_discussion", system, user_message, result, model=self.model, usage=usage, duration_ms=duration_ms)
        return result

    def generate_end_game_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> bool:
        """Generate a vote on whether to end the game or continue."""
        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
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

        vote_text, usage, duration_ms = self._call_llm(system, user_message, 20)
        self._log_interaction(game_state, "end_game_vote", system, user_message, vote_text, model=self.model, usage=usage, duration_ms=duration_ms)
        return "END" in vote_text.upper()

    def generate_finale_pouch_choice(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a pouch choice for the UK-style finale fire pit vote."""
        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
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

        choice_text, usage, duration_ms = self._call_llm(system, user_message, 20)
        self._log_interaction(game_state, "finale_pouch_choice", system, user_message, choice_text, model=self.model, usage=usage, duration_ms=duration_ms)

        if "BANISH" in choice_text.upper():
            return "BANISH_AGAIN"
        return "END_GAME"


class OllamaAgent(OpenAICompatibleAgent):
    """Agent using local Ollama for LLM inference.

    Uses Ollama's OpenAI-compatible API for free local inference.
    Backward-compatible wrapper around OpenAICompatibleAgent.

    Setup:
        1. Install Ollama: brew install ollama
        2. Pull a model: ollama pull llama3.2
        3. Start server: ollama serve
    """

    def __init__(
        self,
        player: Player,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434/v1",
        api_callback: Optional[Callable] = None,
    ):
        super().__init__(
            player=player,
            model=model,
            base_url=base_url,
            api_key="ollama",
            api_callback=api_callback,
        )


class GeminiAgent(Agent):
    """Agent using Google Gemini via native SDK with context caching.

    Uses the native google-genai SDK for access to context caching,
    which provides ~75% cost reduction on cached tokens.

    Requirements:
        - Python 3.10+ (google-genai has typing incompatibilities with 3.9)
        - google-genai package: pip install google-genai

    Setup:
        1. Get API key from Google AI Studio: https://aistudio.google.com/
        2. Set GEMINI_API_KEY environment variable
    """

    def __init__(
        self,
        player: Player,
        model: str = "gemini-2.0-flash-lite",
        api_key: Optional[str] = None,
        api_callback: Optional[Callable] = None,
        enable_caching: bool = True,
    ):
        import os
        import sys

        # Check Python version before importing google-genai
        if sys.version_info < (3, 10):
            raise RuntimeError(
                f"GeminiAgent requires Python 3.10+ (you have {sys.version_info.major}.{sys.version_info.minor}). "
                "The google-genai package has typing incompatibilities with Python 3.9. "
                "Please use Python 3.10 or later, or use a different agent type."
            )

        try:
            from google import genai
            from .gemini_cache import GeminiCacheManager
        except ImportError as e:
            raise ImportError(
                "google-genai package required for GeminiAgent. "
                "Install with: pip install google-genai"
            ) from e

        self.player = player
        self.model = model
        self.api_callback = api_callback
        self.enable_caching = enable_caching

        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ValueError("GEMINI_API_KEY environment variable required")

        self.client = genai.Client(api_key=key)
        self._cache_manager = GeminiCacheManager(self.client, model) if enable_caching else None

    def _extract_usage(self, response) -> TokenUsage:
        """Extract token usage from a Gemini API response."""
        usage = response.usage_metadata
        return TokenUsage(
            input_tokens=usage.prompt_token_count or 0,
            output_tokens=usage.candidates_token_count or 0,
            cache_creation_tokens=getattr(usage, 'cache_creation_input_token_count', 0) or 0,
            cache_read_tokens=getattr(usage, 'cached_content_token_count', 0) or 0,
        )

    def _call_llm(
        self,
        system: str,
        user_message: str,
        max_tokens: int,
        cached_history: Optional[str] = None
    ) -> tuple[str, Optional[TokenUsage], float]:
        """Call the Gemini LLM API with optional caching.

        Args:
            system: System prompt
            user_message: The user message/prompt
            max_tokens: Maximum tokens in response
            cached_history: Optional pre-built history for caching

        Returns:
            (response_text, usage, duration_ms)
        """
        from google.genai import types

        start_time = time.time()

        # Try to use caching if enabled and history provided
        cache_name = None
        if cached_history and self._cache_manager:
            cache_name = self._cache_manager.get_or_create_cache(system, cached_history)

        if cache_name:
            # Use cached content - only send the dynamic part
            response = self.client.models.generate_content(
                model=self.model,
                contents=user_message,
                config=types.GenerateContentConfig(
                    cached_content=cache_name,
                    max_output_tokens=max_tokens,
                )
            )
        else:
            # No caching - send full request
            full_content = f"{cached_history}\n\n{user_message}" if cached_history else user_message
            response = self.client.models.generate_content(
                model=self.model,
                contents=full_content,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                )
            )

        duration_ms = (time.time() - start_time) * 1000

        # Extract response text
        text = ""
        if response.candidates and len(response.candidates) > 0:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                text = candidate.content.parts[0].text or ""
        text = text.strip()

        # Extract usage
        usage = None
        if response.usage_metadata:
            usage = self._extract_usage(response)

        return text, usage, duration_ms

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

        result, usage, duration_ms = self._call_llm(system, user_message, 200)
        self._log_interaction(game_state, "discussion", system, user_message, result, model=self.model, usage=usage, duration_ms=duration_ms)
        return result

    def generate_combined_discussion(
        self,
        game_state: GameState,
        turn_number: int,
        max_turns: int,
        instruction: str = "",
        cached_previous_rounds: Optional[str] = None
    ) -> tuple[str, str]:
        """Generate a discussion statement with private thoughts in one response."""
        system = self._build_system_prompt(game_state)
        history = self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        alive_names = [p.name for p in game_state.alive_players]

        user_message = prompts.COMBINED_DISCUSSION_PROMPT.format(
            round_context=round_context,
            history=history,
            current_round=game_state.current_round,
            alive_names=', '.join(alive_names),
            turn_number=turn_number,
            max_turns=max_turns,
            instruction=instruction
        )

        # Use cached_previous_rounds for caching if provided
        result, usage, duration_ms = self._call_llm(
            system, user_message, 200,
            cached_history=cached_previous_rounds
        )
        self._log_interaction(game_state, "combined_discussion", system, user_message, result, model=self.model, usage=usage, duration_ms=duration_ms)

        statement, thoughts = parse_combined_response(result)
        return statement, thoughts

    def generate_private_thoughts(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate private thoughts before voting."""
        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
        round_context = self._get_round_context(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = prompts.PRIVATE_THOUGHTS_PROMPT.format(
            round_context=round_context,
            history=history,
            voteable=', '.join(voteable)
        )

        result, usage, duration_ms = self._call_llm(system, user_message, 100, cached_history=cached_history)
        self._log_interaction(game_state, "private_thoughts", system, user_message, result, model=self.model, usage=usage, duration_ms=duration_ms)
        return result

    def generate_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a vote for who to banish."""
        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)

        voteable = [p.name for p in game_state.alive_players if p.name != self.player.name]

        user_message = prompts.VOTE_PROMPT.format(
            history=history,
            voteable=', '.join(voteable)
        )

        vote, usage, duration_ms = self._call_llm(system, user_message, 50, cached_history=cached_history)
        self._log_interaction(game_state, "vote", system, user_message, vote, model=self.model, usage=usage, duration_ms=duration_ms)

        # Validate the vote is a valid player name
        for name in voteable:
            if name.lower() in vote.lower():
                return name

        return voteable[0] if voteable else ""

    def generate_murder_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a vote for who to murder (traitors only)."""
        if not self.player.is_traitor:
            raise ValueError("Only traitors can vote to murder")

        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)

        targets = [p.name for p in game_state.alive_faithful]

        user_message = prompts.MURDER_VOTE_PROMPT.format(
            history=history,
            targets=', '.join(targets)
        )

        vote, usage, duration_ms = self._call_llm(system, user_message, 50, cached_history=cached_history)
        self._log_interaction(game_state, "murder_vote", system, user_message, vote, model=self.model, usage=usage, duration_ms=duration_ms)

        for name in targets:
            if name.lower() in vote.lower():
                return name

        return targets[0] if targets else ""

    def generate_traitor_discussion(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate private traitor discussion (night phase)."""
        if not self.player.is_traitor:
            raise ValueError("Only traitors can participate in traitor discussion")

        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
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

        result, usage, duration_ms = self._call_llm(system, user_message, 200, cached_history=cached_history)
        self._log_interaction(game_state, "traitor_discussion", system, user_message, result, model=self.model, usage=usage, duration_ms=duration_ms)
        return result

    def generate_end_game_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> bool:
        """Generate a vote on whether to end the game or continue."""
        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
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

        vote_text, usage, duration_ms = self._call_llm(system, user_message, 20, cached_history=cached_history)
        self._log_interaction(game_state, "end_game_vote", system, user_message, vote_text, model=self.model, usage=usage, duration_ms=duration_ms)
        return "END" in vote_text.upper()

    def generate_finale_pouch_choice(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a pouch choice for the UK-style finale fire pit vote."""
        system = self._build_system_prompt(game_state)
        history = cached_history if cached_history is not None else self._format_conversation_history(game_state)
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

        choice_text, usage, duration_ms = self._call_llm(system, user_message, 20, cached_history=cached_history)
        self._log_interaction(game_state, "finale_pouch_choice", system, user_message, choice_text, model=self.model, usage=usage, duration_ms=duration_ms)

        if "BANISH" in choice_text.upper():
            return "BANISH_AGAIN"
        return "END_GAME"

    def cleanup(self) -> None:
        """Clean up any active caches. Call at end of game."""
        if self._cache_manager:
            self._cache_manager.cleanup()


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

    def generate_combined_discussion(
        self,
        game_state: GameState,
        turn_number: int,
        max_turns: int,
        instruction: str = "",
        cached_previous_rounds: Optional[str] = None
    ) -> tuple[str, str]:
        """Return empty statement and thoughts, or PASS on later turns.

        Note: TestAgent ignores cached_previous_rounds since it doesn't call LLMs.
        """
        # On turn 1, return empty statement; on later turns, 50% chance to pass
        if turn_number > 1 and random.random() < 0.5:
            return "PASS", ""
        return "", ""

    def generate_private_thoughts(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Return empty thoughts."""
        return ""

    def generate_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Vote for a random alive player (not self)."""
        candidates = [p.name for p in game_state.alive_players if p.name != self.player.name]
        return random.choice(candidates) if candidates else self.player.name

    def generate_murder_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Vote to murder a random faithful player."""
        faithful = [p.name for p in game_state.alive_faithful]
        return random.choice(faithful) if faithful else ""

    def generate_traitor_discussion(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Return empty traitor discussion."""
        return ""

    def generate_end_game_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> bool:
        """Random vote on whether to end the game."""
        return random.choice([True, False])

    def generate_finale_pouch_choice(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Random pouch choice for finale.

        Traitors prefer END_GAME (70% chance) since it helps them win.
        Faithful prefer BANISH_AGAIN (60% chance) to catch remaining traitors.
        """
        if self.player.is_traitor:
            return "END_GAME" if random.random() < 0.7 else "BANISH_AGAIN"
        else:
            return "BANISH_AGAIN" if random.random() < 0.6 else "END_GAME"
