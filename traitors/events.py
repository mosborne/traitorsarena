"""Structured event types for game progress and API call tracking."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .cost import TokenUsage


class EventType(Enum):
    """Types of events emitted during gameplay."""
    GAME_START = "game_start"
    ROUND_START = "round_start"
    PHASE_CHANGE = "phase_change"
    API_CALL = "api_call"
    PLAYER_ELIMINATED = "player_eliminated"
    GAME_END = "game_end"
    DISCUSSION_TURN = "discussion_turn"
    VOTE_CAST = "vote_cast"


@dataclass
class GameEvent:
    """Base event emitted during gameplay."""
    event_type: EventType
    round_num: int
    data: dict = field(default_factory=dict)


@dataclass
class APICallEvent(GameEvent):
    """Event emitted after each API call with usage details."""
    usage: TokenUsage = field(default_factory=TokenUsage)
    duration_ms: float = 0
    model: str = ""
    player: str = ""
    action_type: str = ""

    def __post_init__(self):
        self.event_type = EventType.API_CALL


def game_start_event(
    num_players: int,
    num_traitors: int,
    finale_round: int,
    traitor_names: list[str],
) -> GameEvent:
    """Create a game start event."""
    return GameEvent(
        event_type=EventType.GAME_START,
        round_num=0,
        data={
            "num_players": num_players,
            "num_traitors": num_traitors,
            "finale_round": finale_round,
            "traitor_names": traitor_names,
        },
    )


def round_start_event(
    round_num: int,
    alive_players: list[str],
    alive_traitors: int,
    is_finale: bool,
) -> GameEvent:
    """Create a round start event."""
    return GameEvent(
        event_type=EventType.ROUND_START,
        round_num=round_num,
        data={
            "alive_players": alive_players,
            "alive_count": len(alive_players),
            "alive_traitors": alive_traitors,
            "is_finale": is_finale,
        },
    )


def phase_change_event(round_num: int, phase: str) -> GameEvent:
    """Create a phase change event."""
    return GameEvent(
        event_type=EventType.PHASE_CHANGE,
        round_num=round_num,
        data={"phase": phase},
    )


def player_eliminated_event(
    round_num: int,
    player_name: str,
    elimination_type: str,  # "banished" or "murdered"
    role: str,
    role_revealed: bool,
) -> GameEvent:
    """Create a player eliminated event."""
    return GameEvent(
        event_type=EventType.PLAYER_ELIMINATED,
        round_num=round_num,
        data={
            "player": player_name,
            "type": elimination_type,
            "role": role,
            "role_revealed": role_revealed,
        },
    )


def game_end_event(
    round_num: int,
    winner: str,
    survivors: list[str],
    traitors: list[str],
    faithful: list[str],
) -> GameEvent:
    """Create a game end event."""
    return GameEvent(
        event_type=EventType.GAME_END,
        round_num=round_num,
        data={
            "winner": winner,
            "survivors": survivors,
            "traitors": traitors,
            "faithful": faithful,
        },
    )


def api_call_event(
    round_num: int,
    player: str,
    action_type: str,
    model: str,
    usage: TokenUsage,
    duration_ms: float,
) -> APICallEvent:
    """Create an API call event."""
    return APICallEvent(
        event_type=EventType.API_CALL,
        round_num=round_num,
        usage=usage,
        duration_ms=duration_ms,
        model=model,
        player=player,
        action_type=action_type,
    )
