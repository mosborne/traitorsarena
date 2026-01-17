#!/usr/bin/env python3
"""
Rich CLI Game Executor with Cost Monitoring

A terminal-based game executor with visual progress, cost tracking, and budget monitoring.

Usage:
    python cli.py -c configs/quick.json
    python cli.py -c configs/quick.json --balance 10.00
    python cli.py -c configs/quick.json --test-mode
"""

import argparse
from dotenv import load_dotenv

# Load .env file from project directory
load_dotenv()
import json
import random
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text

from main import EXAMPLE_CONTESTANTS
from traitors import TraitorsGame, TestAgent, Agent
from traitors.cost import CostTracker, TokenUsage, MODEL_PRICING, fetch_admin_spending, get_admin_key
from traitors.events import EventType, GameEvent, APICallEvent

console = Console()

# UK Traitors format: always 19 players per game
PLAYERS_PER_GAME = 19

# Build lookup for original contestants
ORIGINAL_CONTESTANTS = {c["name"]: c for c in EXAMPLE_CONTESTANTS}


def load_config(config_path: str) -> dict:
    """Load a game configuration file."""
    with open(config_path) as f:
        return json.load(f)


def load_contestants_from_config(config: dict) -> list:
    """
    Load contestants based on config specification.

    Each contestant entry can be:
    - {"source": "original", "name": "Marcus"} - use original contestant
    - {"source": "original", "name": "Marcus", "model": "llama3.2"} - with specific model
    - {"source": "prompt", "file": "improved_v1.json"} - use prompt file
    """
    prompts_dir = Path(__file__).parent / "prompts"
    contestants = []
    default_model = config.get("default_model")

    for entry in config.get("contestants", []):
        source = entry.get("source", "original")
        contestant_model = entry.get("model", default_model)

        if source == "original":
            name = entry["name"]
            if name not in ORIGINAL_CONTESTANTS:
                raise ValueError(f"Unknown original contestant: {name}")
            contestant = ORIGINAL_CONTESTANTS[name].copy()
            if contestant_model:
                contestant["model"] = contestant_model
            contestants.append(contestant)

        elif source == "prompt":
            prompt_file = entry["file"]
            path = prompts_dir / prompt_file
            if not path.exists():
                raise ValueError(f"Prompt file not found: {prompt_file}")

            with open(path) as f:
                data = json.load(f)

            contestant = {
                "name": data["name"],
                "personality_prompt": data["personality_prompt"],
            }
            if contestant_model:
                contestant["model"] = contestant_model
            contestants.append(contestant)
        else:
            raise ValueError(f"Unknown source type: {source}")

    return contestants


def select_contestants_for_game(pool: list, target_size: int = PLAYERS_PER_GAME) -> list:
    """Randomly select players from pool for a single game."""
    if len(pool) <= target_size:
        return pool.copy()
    return random.sample(pool, target_size)


class RichGameDisplay:
    """Manages the Rich live terminal display for game progress and costs."""

    def __init__(
        self,
        num_players: int,
        starting_balance: Optional[float] = None,
        model: str = "claude-3-5-haiku-20241022",
        admin_spending: Optional[dict] = None,
    ):
        self.num_players = num_players
        self.starting_balance = starting_balance
        self.model = model
        self.admin_spending = admin_spending

        # Game state
        self.current_round = 0
        self.current_phase = "setup"
        self.alive_count = num_players
        self.alive_traitors = 0
        self.is_finale = False
        self.game_started = False
        self.game_ended = False
        self.winner = None
        self.traitor_names: list[str] = []

        # Live progress tracking
        self.current_player = ""
        self.current_action = ""
        self.phase_progress_current = 0
        self.phase_progress_total = 0

        # Cost tracking
        self.cost_tracker = CostTracker(model=model)

        # For ETA calculation
        self.api_call_times: list[float] = []
        self.estimated_calls_remaining = self._estimate_total_calls(num_players)

    def _estimate_total_calls(self, num_players: int, num_rounds: int = 8) -> int:
        """Estimate total API calls for a full game."""
        # Per round: ~3 discussion turns per player + 1 vote per player + traitor night activity
        # This is a rough estimate
        calls_per_round = 4 * num_players + 6
        return calls_per_round * num_rounds

    def handle_event(self, event: GameEvent) -> None:
        """Handle game events and update display state."""
        if event.event_type == EventType.GAME_START:
            self.game_started = True
            self.num_players = event.data.get("num_players", self.num_players)
            self.alive_traitors = event.data.get("num_traitors", 3)
            self.traitor_names = event.data.get("traitor_names", [])

        elif event.event_type == EventType.ROUND_START:
            self.current_round = event.round_num
            self.alive_count = event.data.get("alive_count", self.alive_count)
            self.alive_traitors = event.data.get("alive_traitors", self.alive_traitors)
            self.is_finale = event.data.get("is_finale", False)

        elif event.event_type == EventType.PHASE_CHANGE:
            self.current_phase = event.data.get("phase", self.current_phase)
            # Reset progress tracking for new phase
            self.current_player = ""
            self.current_action = ""
            self.phase_progress_current = 0
            # Estimate total based on phase type
            phase = self.current_phase.lower()
            if phase == "voting":
                self.phase_progress_total = self.alive_count
            elif phase == "murder":
                self.phase_progress_total = self.alive_traitors
            elif phase == "discussion":
                # Discussion has multiple turns per player
                self.phase_progress_total = self.alive_count * 3
            else:
                self.phase_progress_total = 0

        elif event.event_type == EventType.API_CALL:
            if isinstance(event, APICallEvent):
                self.cost_tracker.add_usage(event.usage, event.duration_ms)
                if event.duration_ms > 0:
                    self.api_call_times.append(event.duration_ms)
                # Update estimate of remaining calls
                if self.cost_tracker.api_calls > 0:
                    self.estimated_calls_remaining = max(0, self.estimated_calls_remaining - 1)
                # Track current player and action for live progress
                if event.player:
                    self.current_player = event.player
                if event.action_type:
                    self.current_action = event.action_type
                self.phase_progress_current += 1

        elif event.event_type == EventType.PLAYER_ELIMINATED:
            self.alive_count = max(0, self.alive_count - 1)
            if event.data.get("role") == "traitor" and event.data.get("role_revealed", False):
                self.alive_traitors = max(0, self.alive_traitors - 1)

        elif event.event_type == EventType.GAME_END:
            self.game_ended = True
            self.winner = event.data.get("winner")

    def render(self) -> Layout:
        """Render the current state as a Rich Layout."""
        layout = Layout()

        # Top row: Game state and progress
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        # Header
        if self.game_ended:
            winner_color = "red" if self.winner == "traitors" else "green"
            header_text = Text(f"GAME OVER - {self.winner.upper()} WIN!", style=f"bold {winner_color}")
        elif self.is_finale:
            header_text = Text(f"FINALE - Round {self.current_round}", style="bold yellow")
        else:
            header_text = Text(f"Round {self.current_round} - {self.current_phase.upper()}", style="bold cyan")

        layout["header"].update(Panel(header_text, title="The Traitors"))

        # Main area: Split into game info and cost panels
        layout["main"].split_row(
            Layout(name="game_info", ratio=1),
            Layout(name="cost_info", ratio=1),
        )

        # Game info panel
        game_table = Table(show_header=False, box=None, padding=(0, 1))
        game_table.add_column("Label", style="dim")
        game_table.add_column("Value")

        game_table.add_row("Players", f"{self.alive_count}/{self.num_players} alive")
        game_table.add_row("Traitors", f"{self.alive_traitors} remaining" if self.alive_traitors > 0 else "All eliminated")
        game_table.add_row("Phase", self.current_phase.title())
        game_table.add_row("Round", str(self.current_round))

        # Live progress: current player and action
        if self.current_player:
            action_text = {
                "discussion": "speaking",
                "vote": "voting",
                "murder_vote": "choosing target",
                "pouch_vote": "voting",
            }.get(self.current_action, "thinking")
            game_table.add_row("", "")  # spacer
            game_table.add_row("[bold cyan]▶[/]", f"[cyan]{self.current_player} {action_text}...[/]")

        # Progress bar
        if self.phase_progress_total > 0:
            progress = min(1.0, self.phase_progress_current / self.phase_progress_total)
            filled = int(progress * 10)
            bar = "█" * filled + "░" * (10 - filled)
            game_table.add_row("", f"[dim][{bar}] {self.phase_progress_current}/{self.phase_progress_total}[/]")

        layout["game_info"].update(Panel(game_table, title="Game State"))

        # Cost info panel
        cost_table = Table(show_header=False, box=None, padding=(0, 1))
        cost_table.add_column("Label", style="dim")
        cost_table.add_column("Value")

        game_cost = self.cost_tracker.total_cost

        # Show admin spending if available
        if self.admin_spending and not self.admin_spending.get("error"):
            cost_table.add_row("Last 7 days", f"${self.admin_spending['total_cost_usd']:.2f}")
            cost_table.add_row("Today", f"${self.admin_spending['today_cost_usd']:.2f}")
            cost_table.add_row("This game", f"${game_cost:.4f}")
        else:
            cost_table.add_row("This game", f"${game_cost:.4f}")
            cost_table.add_row("API Calls", str(self.cost_tracker.api_calls))
            cost_table.add_row("Input Tokens", f"{self.cost_tracker.total_usage.input_tokens:,}")
            cost_table.add_row("Output Tokens", f"{self.cost_tracker.total_usage.output_tokens:,}")

            if self.cost_tracker.total_usage.cache_read_tokens > 0:
                cost_table.add_row("Cache Hits", f"{self.cost_tracker.total_usage.cache_read_tokens:,} tokens")

        # Show remaining balance if provided
        if self.starting_balance is not None:
            remaining = self.starting_balance - game_cost
            cost_table.add_row("", "")  # Spacer
            cost_table.add_row("Remaining", f"${remaining:.2f}")

        layout["cost_info"].update(Panel(cost_table, title="Cost Tracking"))

        # Footer: Balance and ETA info
        footer_parts = []

        if self.starting_balance is not None:
            remaining = self.starting_balance - game_cost
            footer_parts.append(f"Balance: ${self.starting_balance:.2f} → ${remaining:.2f}")

        # ETA based on API call times
        if self.api_call_times and self.estimated_calls_remaining > 0:
            avg_time_ms = sum(self.api_call_times) / len(self.api_call_times)
            eta_seconds = (avg_time_ms * self.estimated_calls_remaining) / 1000
            if eta_seconds > 60:
                footer_parts.append(f"ETA: ~{eta_seconds/60:.1f} min")
            else:
                footer_parts.append(f"ETA: ~{eta_seconds:.0f} sec")

        footer_text = " | ".join(footer_parts) if footer_parts else "Running..."
        layout["footer"].update(Panel(Text(footer_text, style="dim"), title=""))

        return layout

    def __rich__(self) -> Layout:
        """Called by Rich Live on each refresh."""
        return self.render()


def check_balance_warning(balance: Optional[float], estimated_cost: float = 0.25) -> None:
    """Check if balance might be insufficient and warn user."""
    if balance is not None and balance < estimated_cost:
        console.print(f"[yellow]Warning: Balance ${balance:.2f} may be insufficient for a full game (~${estimated_cost:.2f})[/]")
        console.print()
    elif balance is not None:
        console.print(f"[dim]Starting balance: ${balance:.2f}[/]")
        console.print()


def run_game_with_display(
    contestants: list[dict],
    num_traitors: int = 3,
    finale_round: int = 8,
    starting_balance: Optional[float] = None,
    test_mode: bool = False,
    verbose: bool = False,
    admin_spending: Optional[dict] = None,
) -> tuple[dict, float]:
    """Run a single game with Rich live display. Returns (results, game_cost)."""

    # Create display
    display = RichGameDisplay(
        num_players=len(contestants),
        starting_balance=starting_balance,
        admin_spending=admin_spending,
    )

    # Game log for verbose mode
    game_log: list[str] = []

    def log_handler(msg: str) -> None:
        game_log.append(msg)
        if verbose:
            console.print(msg)

    # Quiet log handler for display mode (we show the display instead)
    quiet_log = (lambda msg: game_log.append(msg)) if not verbose else log_handler

    # Run game with live display
    with Live(display, refresh_per_second=4, console=console) as live:
        game = TraitorsGame(
            contestants=contestants,
            num_traitors=num_traitors,
            finale_round=finale_round,
            log_callback=quiet_log,
            test_mode=test_mode,
            event_callback=display.handle_event,
        )
        results = game.run()

    # Print final summary
    game_cost = display.cost_tracker.total_cost
    summary_lines = [
        f"[bold]Winner: {results['winner'].upper()}[/]",
        f"Rounds: {results['rounds_played']}",
        f"Survivors: {', '.join(results['survivors'])}",
        f"Traitors: {', '.join(results['traitors'])}",
        f"",
        f"[dim]Game Cost: ${game_cost:.4f} ({display.cost_tracker.api_calls} API calls)[/]",
    ]

    if starting_balance is not None:
        remaining = starting_balance - game_cost
        summary_lines.append(f"[dim]Remaining: ${remaining:.2f}[/]")

    console.print()
    console.print(Panel(
        "\n".join(summary_lines),
        title="Game Complete",
        border_style="green" if results['winner'] == 'faithful' else "red",
    ))

    return results, game_cost


def main():
    parser = argparse.ArgumentParser(
        description="Run The Traitors game with rich terminal display and cost monitoring"
    )
    parser.add_argument(
        "--config", "-c",
        required=True,
        help="Path to game configuration file (JSON)"
    )
    parser.add_argument(
        "--balance", "-b",
        type=float,
        help="Your current Anthropic credit balance in $ (for tracking)"
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run without API calls (random decisions)"
    )
    parser.add_argument(
        "--num-games", "-n",
        type=int,
        default=1,
        help="Number of games to run (default: 1)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full game log output"
    )

    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/]")
        sys.exit(1)

    # Load contestants
    try:
        contestant_pool = load_contestants_from_config(config)
    except Exception as e:
        console.print(f"[red]Error loading contestants: {e}[/]")
        sys.exit(1)

    num_traitors = config.get("num_traitors", 3)
    finale_round = config.get("finale_round", 8)
    players_per_game = min(len(contestant_pool), PLAYERS_PER_GAME)

    console.print(f"[bold]The Traitors - Game Simulator[/]")
    console.print(f"Config: {config.get('name', 'unnamed')}")
    console.print(f"Players: {len(contestant_pool)} in pool, {players_per_game} per game")
    console.print(f"Traitors: {num_traitors}")
    console.print(f"Finale: Round {finale_round + 1}+")
    console.print()

    # Fetch admin spending if key is available
    admin_spending = None
    admin_key = get_admin_key()
    if admin_key:
        console.print("[dim]Fetching spending data...[/]", end="")
        admin_spending = fetch_admin_spending(admin_key)
        if admin_spending.get("error"):
            console.print(f" [yellow]{admin_spending['error']}[/]")
            admin_spending = None
        else:
            console.print(f" [green]OK[/]")
            console.print(f"[dim]Last 7 days: ${admin_spending['total_cost_usd']:.2f} | Today: ${admin_spending['today_cost_usd']:.2f}[/]")
    else:
        console.print("[dim]Tip: Set ANTHROPIC_ADMIN_KEY to see spending data[/]")
    console.print()

    # Check balance and warn if low
    estimated_total = 0.25 * args.num_games
    check_balance_warning(args.balance, estimated_total)

    # Track cumulative balance across games
    current_balance = args.balance

    for game_num in range(1, args.num_games + 1):
        if args.num_games > 1:
            console.print(f"\n[bold cyan]Game {game_num}/{args.num_games}[/]")

        # Select contestants for this game
        if len(contestant_pool) > PLAYERS_PER_GAME:
            contestants = select_contestants_for_game(contestant_pool)
        else:
            contestants = contestant_pool.copy()

        # Run game
        results, game_cost = run_game_with_display(
            contestants=contestants,
            num_traitors=num_traitors,
            finale_round=finale_round,
            starting_balance=current_balance,
            test_mode=args.test_mode,
            verbose=args.verbose,
            admin_spending=admin_spending,
        )

        # Update balance for next game
        if current_balance is not None:
            current_balance -= game_cost

        console.print()


if __name__ == "__main__":
    main()
