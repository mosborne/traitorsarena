"""Agent factory for creating agent instances.

This module provides a factory pattern for creating agent instances,
consolidating the instantiation logic that was previously scattered
across game.py.
"""

from typing import Callable, Optional, Type

from .types import Player
from .base_agent import BaseAgent


# Registry of agent classes and their configuration
_AGENT_REGISTRY: dict[str, dict] = {}


def register_agent(
    name: str,
    agent_class: Type[BaseAgent],
    default_model: Optional[str] = None,
    requires_client: bool = True,
    extra_kwargs: Optional[dict] = None,
) -> None:
    """Register an agent class in the factory.

    Args:
        name: Unique identifier for the agent type
        agent_class: The agent class to instantiate
        default_model: Default model name for this agent type
        requires_client: Whether this agent requires an Anthropic client
        extra_kwargs: Additional default kwargs for instantiation
    """
    _AGENT_REGISTRY[name] = {
        "class": agent_class,
        "default_model": default_model,
        "requires_client": requires_client,
        "extra_kwargs": extra_kwargs or {},
    }


def get_registered_agents() -> list[str]:
    """Get list of registered agent type names."""
    return list(_AGENT_REGISTRY.keys())


def get_agent_info(name: str) -> Optional[dict]:
    """Get registration info for an agent type."""
    return _AGENT_REGISTRY.get(name)


def create_agent(
    agent_type: str,
    player: Player,
    model: Optional[str] = None,
    api_callback: Optional[Callable] = None,
    client=None,
    **kwargs,
) -> BaseAgent:
    """Create an agent instance using the factory.

    Args:
        agent_type: Name of the registered agent type
        player: Player this agent will control
        model: Optional model override (uses default if not specified)
        api_callback: Optional callback for API usage tracking
        client: Optional Anthropic client (only used for Anthropic agents)
        **kwargs: Additional kwargs passed to the agent constructor

    Returns:
        Configured agent instance

    Raises:
        ValueError: If agent_type is not registered
    """
    if agent_type not in _AGENT_REGISTRY:
        registered = ", ".join(get_registered_agents())
        raise ValueError(
            f"Unknown agent type: {agent_type}. "
            f"Registered types: {registered}"
        )

    info = _AGENT_REGISTRY[agent_type]
    agent_class = info["class"]
    effective_model = model or player.model or info["default_model"]

    # Merge default extra kwargs with provided kwargs
    merged_kwargs = {**info["extra_kwargs"], **kwargs}

    # Special case for TestAgent which has minimal constructor
    if agent_type == "test":
        return agent_class(player=player, client=client)

    # Build constructor arguments based on agent type
    if info["requires_client"]:
        # Anthropic-style agent
        return agent_class(
            player=player,
            client=client,
            model=effective_model,
            api_callback=api_callback,
            **merged_kwargs,
        )
    else:
        # Other agents (Ollama, Gemini)
        return agent_class(
            player=player,
            model=effective_model,
            api_callback=api_callback,
            **merged_kwargs,
        )


def create_agent_from_class(
    agent_class: Type[BaseAgent],
    player: Player,
    model: Optional[str] = None,
    api_callback: Optional[Callable] = None,
    client=None,
    enable_caching: bool = True,
    **kwargs,
) -> BaseAgent:
    """Create an agent instance directly from a class.

    This is a fallback for when a specific agent class is provided
    instead of using the registry.

    Args:
        agent_class: The agent class to instantiate
        player: Player this agent will control
        model: Optional model name
        api_callback: Optional callback for API usage tracking
        client: Optional Anthropic client
        enable_caching: Whether to enable caching (for agents that support it)
        **kwargs: Additional kwargs passed to the agent constructor

    Returns:
        Configured agent instance
    """
    # Import here to avoid circular imports
    from .agent import Agent, TestAgent, OllamaAgent, GeminiAgent, OpenAICompatibleAgent

    effective_model = model or player.model

    if agent_class == TestAgent:
        return TestAgent(player=player, client=client)

    elif agent_class == OllamaAgent:
        return OllamaAgent(
            player=player,
            model=effective_model or "llama3.2",
            api_callback=api_callback,
            **kwargs,
        )

    elif agent_class == GeminiAgent:
        return GeminiAgent(
            player=player,
            model=effective_model or "gemini-2.0-flash-lite",
            api_callback=api_callback,
            enable_caching=enable_caching,
            **kwargs,
        )

    elif issubclass(agent_class, OpenAICompatibleAgent):
        # Generic OpenAI-compatible agent
        return agent_class(
            player=player,
            model=effective_model,
            api_callback=api_callback,
            **kwargs,
        )

    else:
        # Default: Anthropic Agent
        return agent_class(
            player=player,
            client=client,
            model=effective_model or Agent.DEFAULT_MODEL,
            api_callback=api_callback,
            **kwargs,
        )


# Register built-in agents
def _register_builtin_agents():
    """Register all built-in agent types."""
    # Import here to avoid circular imports at module load time
    from .agent import Agent, TestAgent, OllamaAgent, GeminiAgent

    register_agent(
        name="anthropic",
        agent_class=Agent,
        default_model="claude-3-5-haiku-20241022",
        requires_client=True,
    )

    register_agent(
        name="test",
        agent_class=TestAgent,
        default_model=None,
        requires_client=False,
    )

    register_agent(
        name="ollama",
        agent_class=OllamaAgent,
        default_model="llama3.2",
        requires_client=False,
    )

    register_agent(
        name="gemini",
        agent_class=GeminiAgent,
        default_model="gemini-2.0-flash-lite",
        requires_client=False,
        extra_kwargs={"enable_caching": True},
    )


# Initialize registry on module load
_register_builtin_agents()
