"""Abstract base class for LLM agents playing The Traitors."""

from abc import ABC, abstractmethod
from datetime import datetime
import logging
from typing import Callable, Optional

from .types import Player, GameState, PlayerStatus, LLMInteraction
from .cost import TokenUsage
from .api_utils import log_vote_parsing_failure
from . import prompts

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class defining the contract for all agent implementations.

    All agent types must implement the 8 core game methods. Common utility
    methods for prompt building, history formatting, and logging are provided
    by this base class to reduce duplication.
    """

    player: Player
    model: str
    api_callback: Optional[Callable]

    # ========================================================================
    # ABSTRACT METHODS - Must be implemented by subclasses
    # ========================================================================

    @abstractmethod
    def generate_discussion(self, game_state: GameState, instruction: str = "") -> str:
        """Generate a discussion statement from this agent.

        Args:
            game_state: Current game state
            instruction: Optional specific instruction for this turn

        Returns:
            The agent's public statement
        """
        pass

    @abstractmethod
    def generate_combined_discussion(
        self,
        game_state: GameState,
        turn_number: int,
        max_turns: int,
        instruction: str = "",
        cached_previous_rounds: Optional[str] = None
    ) -> tuple[str, str]:
        """Generate a discussion statement with private thoughts in one response.

        Args:
            game_state: Current game state
            turn_number: Current speaking turn (1 to max_turns)
            max_turns: Maximum speaking turns per round
            instruction: Specific instruction for this turn
            cached_previous_rounds: Pre-built history from rounds 1 to N-1 (for caching)

        Returns:
            Tuple of (statement, thoughts). Statement may be "PASS" if player has nothing to add.
        """
        pass

    @abstractmethod
    def generate_private_thoughts(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate private thoughts before voting.

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across all voting players

        Returns:
            The agent's private thoughts
        """
        pass

    @abstractmethod
    def generate_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> tuple[str, str]:
        """Generate a vote for who to banish.

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across all voting players

        Returns:
            Tuple of (vote_target, thoughts)
        """
        pass

    @abstractmethod
    def generate_murder_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> tuple[str, str]:
        """Generate a vote for who to murder (traitors only).

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across traitors

        Returns:
            Tuple of (vote_target, thoughts)

        Raises:
            ValueError: If called on a non-traitor agent
        """
        pass

    @abstractmethod
    def generate_traitor_discussion(
        self,
        game_state: GameState,
        cached_history: Optional[str] = None,
        turn_number: int = 1,
        max_turns: int = 3
    ) -> tuple[str, str]:
        """Generate private traitor discussion (night phase).

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across traitors
            turn_number: Current speaking turn (1 to max_turns)
            max_turns: Maximum speaking turns per traitor

        Returns:
            Tuple of (discussion_statement, thoughts)

        Raises:
            ValueError: If called on a non-traitor agent
        """
        pass

    @abstractmethod
    def generate_end_game_vote(self, game_state: GameState, cached_history: Optional[str] = None) -> bool:
        """Generate a vote on whether to end the game or continue playing.

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across all voting players

        Returns:
            True to END the game, False to CONTINUE playing
        """
        pass

    @abstractmethod
    def generate_finale_pouch_choice(self, game_state: GameState, cached_history: Optional[str] = None) -> str:
        """Generate a pouch choice for the UK-style finale fire pit vote.

        Args:
            game_state: Current game state
            cached_history: Optional pre-formatted history shared across all voting players

        Returns:
            "END_GAME" to end the game or "BANISH_AGAIN" to force another banishment
        """
        pass

    # ========================================================================
    # SHARED UTILITY METHODS - Used by all agent implementations
    # ========================================================================

    def _get_round_events(self, game_state: GameState) -> dict[int, list[str]]:
        """Get elimination events organized by round."""
        events: dict[int, list[str]] = {}

        for player in game_state.players.values():
            if not player.is_alive:
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
        eliminated_str = self._format_eliminated_details(game_state)

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
        eliminated_str = self._format_eliminated_details(game_state)

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

    def _format_eliminated_details(self, game_state: GameState) -> str:
        """Format eliminated player details for prompts."""
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

        return "\n  ".join(eliminated_details) if eliminated_details else "None yet"

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

    def _validate_vote(
        self,
        raw_response: str,
        parsed_vote: str,
        valid_candidates: list[str],
        action_type: str = "vote",
    ) -> str:
        """Validate a parsed vote against valid candidates.

        If the parsed vote doesn't match any candidate, logs the failure
        and returns a fallback (first candidate).

        Args:
            raw_response: The raw LLM response for logging
            parsed_vote: The extracted vote string
            valid_candidates: List of valid vote targets
            action_type: Type of vote for logging

        Returns:
            A valid candidate name
        """
        # Try to match the parsed vote to a valid candidate
        for name in valid_candidates:
            if name.lower() in parsed_vote.lower():
                return name

        # No match found - log the failure and use fallback
        fallback = valid_candidates[0] if valid_candidates else ""
        if fallback:
            log_vote_parsing_failure(
                raw_response=raw_response,
                parsed_vote=parsed_vote,
                valid_candidates=valid_candidates,
                fallback_used=fallback,
                player_name=self.player.name,
                action_type=action_type,
            )
        return fallback
