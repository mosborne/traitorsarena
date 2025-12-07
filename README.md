# The Traitors - LLM Game Simulator

A simulator for "The Traitors" TV show format, powered by LLM agents. Each contestant is controlled by an AI with a customizable personality prompt, creating dynamic and unpredictable social deduction gameplay.

## How It Works

The game follows the TV show format:

1. **Role Assignment**: Players are secretly assigned as either Traitors or Faithful
2. **Discussion Phase**: All players discuss, share suspicions, and try to identify traitors
3. **Voting Phase**: Players vote to banish someone they suspect is a traitor
4. **Night Phase**: Traitors secretly meet and choose a Faithful player to murder
5. **Win Conditions**:
   - **Faithful win** if they banish all Traitors
   - **Traitors win** if they survive until the end or outnumber the Faithful

## Installation

```bash
pip install -r requirements.txt
```

## Usage

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY="your-api-key"
```

Run a game with the example contestants:

```bash
python main.py
```

### Custom Contestants

Create your own contestants by defining personality prompts:

```python
from traitors import TraitorsGame

contestants = [
    {
        "name": "Alice",
        "personality_prompt": "You are Alice, a cautious and analytical thinker..."
    },
    {
        "name": "Bob",
        "personality_prompt": "You are Bob, a charismatic risk-taker..."
    },
    # Add more contestants (minimum 4 recommended)
]

game = TraitorsGame(
    contestants=contestants,
    num_traitors=3,       # Number of traitors to assign
    finale_round=8,       # Finale begins after this round
)

results = game.run()
```

### Batch Game Runs

Run multiple games with a config file:

```bash
python run_games.py --config configs/baseline.json

# Run games in parallel for faster execution
python run_games.py --config configs/baseline.json --parallel 4
```

Game results are saved as JSON in `runs/<timestamp>/` and viewable at `index.html`.

### Test Mode

For fast testing without LLM API calls:

```python
game = TraitorsGame(
    contestants=contestants,
    num_traitors=2,
    finale_round=3,
    test_mode=True,  # Random decisions, no API calls
)
```

### Configuration Options

- `contestants`: List of dicts with `name` and `personality_prompt`
- `num_traitors`: Number of traitors (default: 3)
- `finale_round`: Round after which finale/endgame begins (default: 8)
- `test_mode`: Use random decisions instead of LLM calls (default: False)
- `client`: Optional custom Anthropic client
- `log_callback`: Optional function for custom logging

## Example Output

```
============================================================
THE TRAITORS - GAME SIMULATION
============================================================
Players: Marcus, Sofia, Derek, Elena, Jaylen, Priya
Rounds: 3

ROLE ASSIGNMENT (Secret)
  Marcus: FAITHFUL
  Sofia: TRAITOR
  Derek: FAITHFUL
  Elena: FAITHFUL
  Jaylen: TRAITOR
  Priya: FAITHFUL

############################################################
ROUND 1
############################################################

DISCUSSION PHASE
----------------------------------------

Marcus: I've been watching everyone's reactions carefully...

[Game continues with discussion, voting, and night phases]

============================================================
GAME OVER
============================================================
WINNER: THE FAITHFUL!
```

## Project Structure

```
traitors/
├── __init__.py     # Package exports
├── types.py        # Data models (Player, GameState, etc.)
├── agent.py        # LLM agent implementation (Agent and TestAgent)
├── game.py         # Main game engine
└── prompts.py      # System prompt templates
main.py             # Entry point with 19 example contestants
run_games.py        # Batch runner with JSON/HTML output
data_store.py       # JSON data storage functions
configs/            # Game configuration files
prompts/            # Custom player personality prompts
runs/               # Game run data (JSON + HTML)
data/runs.json      # Global index of all runs
index.html          # Dynamic web interface (loads from JSON)
run.html            # Run summary viewer
game.html           # Game transcript viewer
```

## Data Storage

Game results are stored as JSON for easy querying and analysis:

- `data/runs.json` - Global index of all runs
- `runs/<id>/run.json` - Run summary with contestant stats
- `runs/<id>/game_*.json` - Individual game data (rounds, votes, messages)

## License

MIT
