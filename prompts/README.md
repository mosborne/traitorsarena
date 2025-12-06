# Contestant Prompts

This directory contains contestant prompt definitions with metadata for tracking effectiveness.

## Structure

Each prompt file is a JSON file with:
- `name`: Contestant name
- `version`: Prompt version (for iteration tracking)
- `personality_prompt`: The actual prompt text
- `design_notes`: Why this prompt was designed this way
- `hypothesis`: What we expect this prompt to achieve

## Analysis from 10-Game Run (2025-12-06_08-39-11)

### Key Findings

**Most banished as Faithful (wrongly targeted):**
- Victor: 5x - "comfortable with deception" makes him suspicious
- Derek: 4x - charismatic/persuasive reads as manipulative
- Camille: 3x - theatrical style seems untrustworthy

**Most murdered by Traitors (seen as threats):**
- Rashid: 3x - data scientist tracking patterns
- Terrence: 2x - military officer, analytical
- Gloria: 2x - retired judge, weighing evidence

**Most often assigned as Traitor:**
- Jaylen: 6x (enthusiastic/impulsive works well for traitors)
- Priya: 4x (strategic/confident)
- Gloria: 4x (authoritative)

### Design Principles

**For Faithful effectiveness:**
1. Build coalitions early - safety in numbers
2. Track voting patterns explicitly
3. Demand specific explanations from suspects
4. Be consistent in behavior across rounds
5. Avoid being too analytical (murder target)
6. Avoid appearing deceptive (banishment target)

**For Traitor effectiveness:**
1. Act empathetic and trustworthy
2. Build alliances with Faithful players
3. Redirect suspicion skillfully
4. Target analytical players for murder
5. Vote with majority initially to blend in
6. Create chaos and division among Faithful
