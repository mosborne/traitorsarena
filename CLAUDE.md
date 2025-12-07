# The Traitors - LLM Game Simulator

An LLM-powered simulator for "The Traitors" TV show. Each contestant is controlled by an AI agent with a unique personality.

## Quick Start

```bash
# Run a single game
python main.py

# Run batch games with a config
python run_games.py --config configs/baseline.json

# Fast test mode (no LLM calls, random decisions)
python -c "
from traitors import TraitorsGame
from main import EXAMPLE_CONTESTANTS
game = TraitorsGame(contestants=EXAMPLE_CONTESTANTS[:8], num_traitors=2, test_mode=True)
game.run()
"
```

## Key Files

| File | Purpose |
|------|---------|
| `traitors/game.py` | Main game engine - runs discussion, voting, murder phases |
| `traitors/agent.py` | LLM agent that generates player responses and decisions |
| `traitors/types.py` | Data models (Player, GameState, etc.) |
| `traitors/prompts.py` | System prompt templates for game rules |
| `main.py` | Entry point with 19 example contestants |
| `run_games.py` | Batch runner for multiple games with HTML output |
| `configs/` | Game configuration files |
| `prompts/` | Custom player personality prompts |
| `runs/` | HTML output from game runs |

## Game Format (UK Celebrity Traitors)

- **19 contestants**, 3 traitors (~16%)
- **Rounds 1-8**: Regular play (discussion -> vote with role reveal -> murder)
- **Finale (round 9+)**: No murders, pouch voting (END_GAME vs BANISH_AGAIN)
- **Prize pool**: £100,000

## TraitorsGame Parameters

```python
TraitorsGame(
    contestants=list,      # List of {name, personality_prompt} dicts
    num_traitors=3,        # Number of traitors to assign
    finale_round=8,        # Round after which finale begins
    test_mode=False,       # True = random decisions, no LLM calls
    client=None,           # Optional custom Anthropic client
    log_callback=None,     # Optional logging function
)
```

## Testing Changes

Use `test_mode=True` for instant testing without API calls:

```python
game = TraitorsGame(
    contestants=EXAMPLE_CONTESTANTS,
    num_traitors=3,
    finale_round=3,  # Early finale for faster testing
    test_mode=True,  # No LLM calls
)
results = game.run()
```

## HTML Output

After running `run_games.py`, view results at:
- `index.html` - All game runs
- `runs/<timestamp>/index.html` - Specific run with individual game links
- `players.html` - Player personality guide
