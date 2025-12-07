"""Core types and data models for the Traitors game."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(Enum):
    """Player roles in the game."""
    FAITHFUL = "faithful"
    TRAITOR = "traitor"


class PlayerStatus(Enum):
    """Current status of a player."""
    ALIVE = "alive"
    BANISHED = "banished"  # Voted out during the day
    MURDERED = "murdered"  # Killed by traitors at night


class GamePhase(Enum):
    """Current phase of the game."""
    SETUP = "setup"
    DISCUSSION = "discussion"
    VOTING = "voting"
    NIGHT = "night"
    ENDED = "ended"


@dataclass
class Player:
    """A player in the Traitors game."""
    name: str
    personality_prompt: str
    role: Role = Role.FAITHFUL
    status: PlayerStatus = PlayerStatus.ALIVE

    @property
    def is_alive(self) -> bool:
        return self.status == PlayerStatus.ALIVE

    @property
    def is_traitor(self) -> bool:
        return self.role == Role.TRAITOR


@dataclass
class Message:
    """A message spoken during discussion."""
    speaker: str
    content: str
    round_num: int
    is_private: bool = False  # True for traitor-only messages


@dataclass
class Vote:
    """A vote to banish a player."""
    voter: str
    target: str
    round_num: int


@dataclass
class PrivateThought:
    """A player's private thoughts before voting."""
    player: str
    content: str
    round_num: int


@dataclass
class LLMInteraction:
    """Record of a single LLM API call for debugging/transparency."""
    player: str
    action_type: str  # e.g., "discussion", "private_thoughts", "vote", "murder_vote", "traitor_discussion", "end_game_vote"
    round_num: int
    system_prompt: str
    user_message: str
    response: str
    model: str = "claude-3-5-haiku-20241022"
    timestamp: str = ""  # ISO format timestamp


@dataclass
class GameState:
    """Current state of the game."""
    players: dict[str, Player] = field(default_factory=dict)
    messages: list[Message] = field(default_factory=list)
    votes: list[Vote] = field(default_factory=list)
    private_thoughts: list[PrivateThought] = field(default_factory=list)
    llm_interactions: list[LLMInteraction] = field(default_factory=list)
    current_round: int = 1
    current_phase: GamePhase = GamePhase.SETUP
    winner: Optional[str] = None  # "traitors" or "faithful" or None

    @property
    def alive_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.is_alive]

    @property
    def alive_traitors(self) -> list[Player]:
        return [p for p in self.alive_players if p.is_traitor]

    @property
    def alive_faithful(self) -> list[Player]:
        return [p for p in self.alive_players if not p.is_traitor]

    def get_public_messages(self, up_to_round: Optional[int] = None) -> list[Message]:
        """Get all public messages up to a given round."""
        if up_to_round is None:
            up_to_round = self.current_round
        return [m for m in self.messages if not m.is_private and m.round_num <= up_to_round]

    def get_traitor_messages(self, up_to_round: Optional[int] = None) -> list[Message]:
        """Get all messages including private traitor discussions."""
        if up_to_round is None:
            up_to_round = self.current_round
        return [m for m in self.messages if m.round_num <= up_to_round]
