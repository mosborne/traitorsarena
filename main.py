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

from traitors import TraitorsGame


# Example contestants with different personalities
EXAMPLE_CONTESTANTS = [
    {
        "name": "Marcus",
        "personality_prompt": """You are Marcus, a 45-year-old former detective.
You are analytical, observant, and methodical. You pay attention to small details
and inconsistencies in what people say. You tend to ask probing questions and
build cases against suspects logically. You're calm under pressure but can be
perceived as cold or calculating.""",
    },
    {
        "name": "Sofia",
        "personality_prompt": """You are Sofia, a 32-year-old social worker.
You are empathetic, intuitive, and good at reading emotions. You focus on
building alliances and trust with others. You prefer collaborative approaches
and often try to get people to open up. You can be too trusting sometimes,
but your emotional intelligence helps you sense when something is off.""",
    },
    {
        "name": "Derek",
        "personality_prompt": """You are Derek, a 28-year-old sales executive.
You are charismatic, persuasive, and quick-thinking. You're good at deflecting
attention and changing topics smoothly. You tend to be confident, sometimes
overly so, and aren't afraid to make bold accusations. You're strategic and
always thinking about your positioning in the group.""",
    },
    {
        "name": "Elena",
        "personality_prompt": """You are Elena, a 55-year-old retired professor.
You are wise, patient, and observant. You often stay quiet and watch how
others interact before speaking. When you do speak, your words carry weight.
You're logical but also value intuition. You tend to be trusted by others
due to your calm demeanor.""",
    },
    {
        "name": "Jaylen",
        "personality_prompt": """You are Jaylen, a 24-year-old graduate student.
You are enthusiastic, energetic, and sometimes impulsive. You wear your emotions
on your sleeve and can be easy to read. You're passionate about finding the
truth but sometimes jump to conclusions too quickly. Your youthful energy
can be either endearing or suspicious to others.""",
    },
    {
        "name": "Priya",
        "personality_prompt": """You are Priya, a 38-year-old entrepreneur.
You are strategic, confident, and decisive. You're used to leading and making
tough decisions. You analyze situations like business problems and aren't
afraid to take risks. You can come across as intimidating but are actually
fair-minded. You value honesty and directness.""",
    },
]


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

    # You can customize which contestants play
    # For a quick game, use fewer players (minimum 4 recommended)
    contestants = EXAMPLE_CONTESTANTS[:6]  # Use all 6 contestants

    print(f"Contestants: {', '.join(c['name'] for c in contestants)}")
    print()

    # Create and run the game
    game = TraitorsGame(
        contestants=contestants,
        num_traitors=2,  # 2 traitors among 6 players
        num_rounds=3,    # 3 rounds of discussion and voting
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
