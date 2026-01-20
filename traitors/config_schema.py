"""Configuration schema and validation for game configs."""

import json
import logging
from enum import Enum
from pathlib import Path
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


class Provider(str, Enum):
    """Supported LLM providers."""
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    GEMINI = "gemini"
    TEST = "test"


# Default models per provider
DEFAULT_MODELS = {
    Provider.ANTHROPIC: "claude-3-5-haiku-20241022",
    Provider.OLLAMA: "llama3.2",
    Provider.GEMINI: "gemini-2.0-flash-lite",
    Provider.TEST: None,
}


class ContestantFile(BaseModel):
    """A contestant defined by a prompt file."""
    file: str = Field(..., description="Path to JSON file in prompts/ directory")
    model: Optional[str] = Field(None, description="Optional per-player model override")


class ContestantOriginal(BaseModel):
    """A contestant from the original EXAMPLE_CONTESTANTS list."""
    source: Literal["original"]
    name: str = Field(..., description="Name of original contestant")
    model: Optional[str] = Field(None, description="Optional per-player model override")


class ContestantPromptFile(BaseModel):
    """A contestant loaded from a prompt file (explicit source)."""
    source: Literal["prompt"]
    file: str = Field(..., description="Path to JSON file in prompts/ directory")
    model: Optional[str] = Field(None, description="Optional per-player model override")


# Union type for contestant entries
ContestantEntry = Union[ContestantFile, ContestantOriginal, ContestantPromptFile]


class GameConfig(BaseModel):
    """Configuration for running Traitors games.

    Supports multiple ways to specify players:
    - player_pool: "all" - Load all players from prompts/ directory
    - player_pool: [{"file": "..."}] - Load specific players from prompt files
    - contestants: [...] - Legacy format supporting original or prompt sources

    Example configs:
        # All players from prompts/
        {"name": "test", "player_pool": "all"}

        # Specific prompt files
        {"name": "test", "player_pool": [{"file": "marcus.json"}, {"file": "sofia.json"}]}

        # Legacy format with original contestants
        {"name": "test", "contestants": [{"source": "original", "name": "Marcus"}]}
    """

    # Required
    name: str = Field(..., description="Config name for identification")

    # Optional metadata
    description: Optional[str] = Field(None, description="Human-readable description")

    # Provider settings
    provider: Provider = Field(Provider.ANTHROPIC, description="LLM provider to use")
    default_model: Optional[str] = Field(None, description="Default model (uses provider default if not set)")
    enable_caching: bool = Field(True, description="Enable prompt caching where supported")

    # Game settings
    num_games: int = Field(1, ge=1, description="Number of games to run")
    num_traitors: int = Field(3, ge=1, description="Number of traitors per game")
    finale_round: int = Field(8, ge=1, description="Round after which finale begins")

    # Player specification (mutually exclusive)
    player_pool: Optional[Union[Literal["all"], List[ContestantFile]]] = Field(
        None,
        description="'all' to use all players from prompts/, or list of prompt files"
    )
    contestants: Optional[List[ContestantEntry]] = Field(
        None,
        description="Legacy format: list of contestant specifications"
    )

    @model_validator(mode='after')
    def validate_player_specification(self) -> 'GameConfig':
        """Ensure exactly one player specification method is used."""
        has_pool = self.player_pool is not None
        has_contestants = self.contestants is not None

        if not has_pool and not has_contestants:
            raise ValueError(
                "Must specify players using either 'player_pool' or 'contestants'. "
                "Use 'player_pool': 'all' to use all players from prompts/ directory."
            )

        if has_pool and has_contestants:
            raise ValueError(
                "Cannot use both 'player_pool' and 'contestants'. Choose one."
            )

        return self

    @field_validator('num_traitors')
    @classmethod
    def validate_traitors(cls, v: int) -> int:
        """Validate number of traitors is reasonable."""
        if v < 1:
            raise ValueError("Must have at least 1 traitor")
        if v > 5:
            logger.warning(f"High number of traitors ({v}) - game balance may be affected")
        return v

    @field_validator('finale_round')
    @classmethod
    def validate_finale_round(cls, v: int) -> int:
        """Validate finale round is reasonable."""
        if v < 1:
            raise ValueError("Finale round must be at least 1")
        if v > 15:
            logger.warning(f"Late finale round ({v}) - games may run very long")
        return v

    def get_effective_model(self) -> Optional[str]:
        """Get the effective model to use, applying provider defaults."""
        if self.default_model:
            return self.default_model
        # Convert string provider back to enum for lookup
        provider = Provider(self.provider) if isinstance(self.provider, str) else self.provider
        return DEFAULT_MODELS.get(provider)

    class Config:
        """Pydantic config."""
        use_enum_values = True


def load_and_validate_config(config_path: str) -> GameConfig:
    """Load and validate a game configuration file.

    Args:
        config_path: Path to JSON config file

    Returns:
        Validated GameConfig object

    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config is invalid JSON
        pydantic.ValidationError: If config doesn't match schema
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path) as f:
        raw_config = json.load(f)

    # Validate and return
    config = GameConfig(**raw_config)

    logger.info(f"Loaded config '{config.name}' with provider={config.provider}")
    return config


def validate_config_dict(config_dict: dict) -> GameConfig:
    """Validate a config dictionary.

    Args:
        config_dict: Configuration as a dictionary

    Returns:
        Validated GameConfig object

    Raises:
        pydantic.ValidationError: If config doesn't match schema
    """
    return GameConfig(**config_dict)
