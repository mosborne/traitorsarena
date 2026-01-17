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
| `traitors/prompts.py` | Modular prompt components for game rules (supports caching) |
| `main.py` | Entry point with 19 example contestants |
| `run_games.py` | Batch runner for multiple games with JSON/HTML output |
| `data_store.py` | JSON serialization and storage functions |
| `configs/` | Game configuration files |
| `prompts/` | Custom player personality prompts |
| `runs/` | Game run data (JSON + HTML files) |
| `data/runs.json` | Global index of all runs |

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
    agent_class=None,      # Optional: Agent, OllamaAgent, or TestAgent
    model=None,            # Optional model name (e.g., "claude-3-5-haiku-20241022")
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

## Prompt Caching

The simulator uses Anthropic's prompt caching for efficiency:

- **Static rules** - Cached once (identical for all players/games)
- **Player identity/role** - Cached per player (changes when traitors die)
- **Conversation history** - Built once per voting phase, shared across all voters
- **Dynamic game state** - NOT cached (changes each round)

This reduces API costs and latency, especially in later rounds with longer history.

## Data & Output

Game results are stored as JSON and rendered dynamically:

**JSON Data:**
- `data/runs.json` - Global index of all runs
- `runs/<id>/run.json` - Run summary with contestant stats
- `runs/<id>/game_*.json` - Individual game transcripts

**HTML Viewers:**
- `index.html` - All game runs (loads from `data/runs.json`)
- `run.html?run=<id>` - Run summary (loads from `run.json`)
- `game.html?run=<id>&game=<n>` - Game transcript (loads from `game_*.json`)
- `players.html` - Player personality guide

**Note:** View via a web server (e.g., `python -m http.server`) for dynamic loading.
