#!/usr/bin/env python3
"""
Contestant management with prompt tracking.

This module loads contestant prompts from the prompts/ directory and tracks
their performance across game runs.
"""

import json
import os
from pathlib import Path
from typing import Optional

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(filename: str) -> dict:
    """Load a contestant prompt from the prompts directory."""
    path = PROMPTS_DIR / filename
    with open(path) as f:
        data = json.load(f)
    return {
        "name": data["name"],
        "personality_prompt": data["personality_prompt"],
        "_prompt_file": filename,
        "_version": data.get("version", "1.0"),
    }


def save_prompt_stats(filename: str, stats: dict):
    """Update stats for a prompt after a game."""
    path = PROMPTS_DIR / filename
    with open(path) as f:
        data = json.load(f)

    data["stats"] = stats

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_all_prompts() -> list[dict]:
    """Load all prompt files from the prompts directory."""
    prompts = []
    for f in PROMPTS_DIR.glob("*.json"):
        try:
            prompts.append(load_prompt(f.name))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not load {f.name}: {e}")
    return prompts


def get_prompt_stats(filename: str) -> dict:
    """Get current stats for a prompt."""
    path = PROMPTS_DIR / filename
    with open(path) as f:
        data = json.load(f)
    return data.get("stats", {})


# New improved contestants based on game analysis
IMPROVED_CONTESTANTS = [
    # Morgan: Balanced coalition-builder (improved v1)
    load_prompt("improved_v1.json") if (PROMPTS_DIR / "improved_v1.json").exists() else {
        "name": "Morgan",
        "personality_prompt": """You are Morgan, a 40-year-old crisis negotiator.
You focus on building trust early and tracking concrete evidence like voting patterns.
You ask direct questions when suspicious but lead with empathy rather than aggression.""",
    },
]

# Experimental contestants for A/B testing
EXPERIMENTAL_CONTESTANTS = []

for prompt_file in ["experimental_aggressive.json", "experimental_social.json"]:
    if (PROMPTS_DIR / prompt_file).exists():
        EXPERIMENTAL_CONTESTANTS.append(load_prompt(prompt_file))


def create_test_roster(
    include_original: int = 9,
    include_improved: int = 1,
    include_experimental: int = 2,
) -> list[dict]:
    """
    Create a roster mixing original and new contestants.

    This allows A/B testing of prompts while maintaining game balance.
    Default: 9 original + 1 improved + 2 experimental = 12 contestants
    """
    from main import EXAMPLE_CONTESTANTS

    roster = []

    # Add original contestants
    roster.extend(EXAMPLE_CONTESTANTS[:include_original])

    # Add improved contestants
    roster.extend(IMPROVED_CONTESTANTS[:include_improved])

    # Add experimental contestants
    roster.extend(EXPERIMENTAL_CONTESTANTS[:include_experimental])

    return roster


if __name__ == "__main__":
    # Test loading
    print("Available prompts:")
    for p in get_all_prompts():
        print(f"  - {p['name']} (v{p.get('_version', '?')})")

    print("\nTest roster:")
    for c in create_test_roster():
        print(f"  - {c['name']}")
