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
    num_traitors=1,  # Number of traitors to assign
    num_rounds=3,    # Number of game rounds
)

results = game.run()
```

### Configuration Options

- `contestants`: List of dicts with `name` and `personality_prompt`
- `num_traitors`: Number of traitors (default: 1)
- `num_rounds`: Maximum rounds before game ends (default: 3)
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
├── agent.py        # LLM agent implementation
└── game.py         # Main game engine
main.py             # Entry point with example contestants
```

## License

MIT
