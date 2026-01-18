#!/usr/bin/env python3
"""
The Traitors - LLM Game Simulator

This simulates The Traitors TV show with LLM-powered contestants.
Each contestant is defined by a personality prompt that shapes their behavior.

Usage:
    python main.py

Requires:
    - ANTHROPIC_API_KEY environment variable
"""

import json
from pathlib import Path

from traitors import TraitorsGame


# Default contestant files (the standard 19-player roster)
DEFAULT_CONTESTANT_FILES = [
    "marcus.json", "sofia.json", "derek.json", "elena.json",
    "jaylen.json", "priya.json", "terrence.json", "aaliyah.json",
    "victor.json", "camille.json", "rashid.json", "gloria.json",
    "olivia.json", "nathan.json", "simone.json", "wesley.json",
    "dahlia.json", "carlos.json", "freya.json"
]


def load_contestants(filenames: list[str] = None) -> list[dict]:
    """Load contestants from prompt files in the prompts/ directory."""
    prompts_dir = Path(__file__).parent / "prompts"
    if filenames is None:
        filenames = DEFAULT_CONTESTANT_FILES

    contestants = []
    for filename in filenames:
        path = prompts_dir / filename
        if not path.exists():
            raise ValueError(f"Prompt file not found: {filename}")

        with open(path) as f:
            data = json.load(f)

        contestants.append({
            "name": data["name"],
            "personality_prompt": data["personality_prompt"]
        })
    return contestants


# Backward compatibility: load default contestants at module level
EXAMPLE_CONTESTANTS = load_contestants()


def main():
    """Run a sample game of The Traitors."""
    print("=" * 60)
    print("THE TRAITORS - LLM GAME SIMULATOR")
    print("=" * 60)
    print()
    print("This simulator runs The Traitors game with AI contestants.")
    print("Each contestant has a unique personality that influences their")
    print("behavior during discussions, voting, and (for traitors) murder.")
    print()

    # Load all 19 contestants for a realistic game
    contestants = load_contestants()

    print(f"Contestants: {', '.join(c['name'] for c in contestants)}")
    print()

    # Create and run the game
    game = TraitorsGame(
        contestants=contestants,
        num_traitors=3,  # 3 traitors among 12 players (realistic ratio)
    )

    results = game.run()

    # Print summary
    print("\n" + "=" * 60)
    print("GAME SUMMARY")
    print("=" * 60)
    print(f"Winner: {results['winner'].upper()}")
    print(f"Rounds played: {results['rounds_played']}")
    print(f"Survivors: {', '.join(results['survivors'])}")
    print(f"Traitors were: {', '.join(results['traitors'])}")
    print(f"Faithful were: {', '.join(results['faithful'])}")

    return results


if __name__ == "__main__":
    main()
