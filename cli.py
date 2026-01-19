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
from datetime import datetime
from dotenv import load_dotenv

# Load .env file from project directory
load_dotenv()
import json
import random
import sys
from pathlib import Path

from data_store import save_game_json, save_run_json, update_runs_index
from run_games import generate_run_analysis
from typing import Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text

from main import EXAMPLE_CONTESTANTS
from traitors import TraitorsGame, TestAgent, Agent, OllamaAgent, GeminiAgent
from traitors.cost import CostTracker, TokenUsage, MODEL_PRICING, fetch_admin_spending, get_admin_key

# Map provider names to agent classes
PROVIDER_MAP = {
    "anthropic": Agent,
    "ollama": OllamaAgent,
    "gemini": GeminiAgent,
    "test": TestAgent,
}

# Default models per provider
DEFAULT_MODELS = {
    "anthropic": "claude-3-5-haiku-20241022",
    "ollama": "llama3.2",
    "gemini": "gemini-2.0-flash-lite",
    "test": None,
}
from traitors.events import EventType, GameEvent, APICallEvent
import re

console = Console()


def clean_content(text: str) -> str:
    """Remove XML-style and markdown-style tags from LLM responses.

    Handles various malformed tag styles:
    - <statement>...</statement>
    - [statement]...[/statement]
    - **Statement:** ...
    - **thoughts:**
    - etc.
    """
    if not text:
        return ""

    # Remove XML-style tags (various bracket styles)
    text = re.sub(r'</?(?:statement|statements|thoughts|vote|stament)s?>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[/?(?:statement|statements|thoughts|vote|stament|pass)s?\]', '', text, flags=re.IGNORECASE)

    # Remove markdown bold tags around tag names
    text = re.sub(r'\*\*(?:Statement|Thoughts|Vote|PASS)s?:?\*\*\s*', '', text, flags=re.IGNORECASE)

    # Remove standalone tag-like patterns
    text = re.sub(r'\*\s+(?:thoughts|statement):?\*\s*', '', text, flags=re.IGNORECASE)

    # Remove malformed mixed tags like <thoughts]>
    text = re.sub(r'<\w+\]>', '', text)

    return text.strip()

# UK Traitors format: always 19 players per game
PLAYERS_PER_GAME = 19

# Build lookup for original contestants
ORIGINAL_CONTESTANTS = {c["name"]: c for c in EXAMPLE_CONTESTANTS}


def load_config(config_path: str) -> dict:
    """Load a game configuration file."""
    with open(config_path) as f:
        return json.load(f)


def load_all_contestants(default_model: str = None) -> list:
    """Load all contestants from the prompts directory."""
    prompts_dir = Path(__file__).parent / "prompts"
    contestants = []

    for path in sorted(prompts_dir.glob("*.json")):
        with open(path) as f:
            data = json.load(f)

        contestant = {
            "name": data["name"],
            "personality_prompt": data["personality_prompt"],
        }
        if default_model:
            contestant["model"] = default_model
        contestants.append(contestant)

    return contestants


def load_contestants_from_config(config: dict) -> list:
    """
    Load contestants based on config specification.

    Supports:
    - "player_pool": "all" - load all players from prompts directory
    - "player_pool": [...] - load specific players from pool list
    - "contestants": [...] - load specific contestants

    Each contestant entry can be:
    - {"source": "original", "name": "Marcus"} - use original contestant
    - {"source": "original", "name": "Marcus", "model": "llama3.2"} - with specific model
    - {"source": "prompt", "file": "improved_v1.json"} - use prompt file
    - {"file": "player.json"} - shorthand for prompt file (run_games.py format)
    """
    default_model = config.get("default_model")

    # Support "player_pool": "all"
    if config.get("player_pool") == "all":
        return load_all_contestants(default_model)

    # Support "player_pool": [...] with {"file": "..."} entries (run_games.py format)
    if "player_pool" in config and isinstance(config["player_pool"], list):
        prompts_dir = Path(__file__).parent / "prompts"
        contestants = []
        for entry in config["player_pool"]:
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
            contestant_model = entry.get("model", default_model)
            if contestant_model:
                contestant["model"] = contestant_model
            contestants.append(contestant)
        return contestants

    # Original format: "contestants": [...]
    prompts_dir = Path(__file__).parent / "prompts"
    contestants = []

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
        contestant_names: list[str],
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

        # Player tracking
        self.all_players: list[str] = contestant_names.copy()
        self.eliminated: dict[str, dict] = {}  # {name: {"type": str, "role": str, "round": int}}

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

        # Activity log for the feed
        self.activity_log: list[dict] = []
        self.max_activity_lines = 20  # Max entries to display

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
            # Add phase change to activity log
            self.activity_log.append({
                "type": "phase_change",
                "player": "",
                "content": f"--- {self.current_phase.upper()} PHASE ---",
            })

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
            # Track elimination details for player display
            player_name = event.data.get("player", "")
            if player_name:
                self.eliminated[player_name] = {
                    "type": event.data.get("type", "banished"),
                    "role": event.data.get("role", "faithful"),
                    "round": event.round_num,
                }
                # Add to activity log
                elim_type = event.data.get("type", "banished")
                role = event.data.get("role", "")
                if event.data.get("role_revealed"):
                    self.activity_log.append({
                        "type": "elimination",
                        "player": player_name,
                        "content": f"was {elim_type.upper()} - revealed as {role.upper()}",
                    })
                else:
                    self.activity_log.append({
                        "type": "elimination",
                        "player": player_name,
                        "content": f"was {elim_type.upper()}",
                    })

        elif event.event_type == EventType.DISCUSSION_TURN:
            self.activity_log.append({
                "type": "discussion",
                "player": event.data.get("player", ""),
                "content": event.data.get("statement", ""),
                "thoughts": event.data.get("thoughts", ""),
                "is_pass": event.data.get("is_pass", False),
            })

        elif event.event_type == EventType.VOTE_CAST:
            voter = event.data.get("voter", "")
            target = event.data.get("target", "")
            vote_type = event.data.get("vote_type", "banish")
            if vote_type == "pouch":
                self.activity_log.append({
                    "type": "pouch",
                    "player": voter,
                    "content": f"threw {target}",
                })
            elif vote_type == "murder":
                self.activity_log.append({
                    "type": "murder_vote",
                    "player": voter,
                    "content": f"votes to murder {target}",
                })
            else:
                self.activity_log.append({
                    "type": "vote",
                    "player": voter,
                    "content": f"voted for {target}",
                })

        elif event.event_type == EventType.GAME_END:
            self.game_ended = True
            self.winner = event.data.get("winner")

    def render(self) -> Layout:
        """Render the current state as a Rich Layout with compact header, player list, and activity feed."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        # Header: Compact status line with all key info
        if self.game_ended:
            winner_color = "red" if self.winner == "traitors" else "green"
            status = Text(f"GAME OVER - {self.winner.upper()} WIN!", style=f"bold {winner_color}")
        else:
            status = Text()
            # Round
            if self.is_finale:
                status.append(f"FINALE R{self.current_round}", style="bold yellow")
            else:
                status.append(f"Round {self.current_round}", style="bold cyan")
            status.append(" │ ", style="dim")
            # Phase with progress
            status.append(self.current_phase.upper(), style="bold")
            if self.phase_progress_total > 0:
                progress_pct = min(100, int(100 * self.phase_progress_current / self.phase_progress_total))
                status.append(f" {self.phase_progress_current}/{self.phase_progress_total}", style="dim")
                # Mini progress bar
                filled = int(progress_pct / 10)
                bar = "▓" * filled + "░" * (10 - filled)
                status.append(f" [{bar}]", style="dim")
            status.append(" │ ", style="dim")
            # Players alive
            status.append(f"{self.alive_count}/{self.num_players} alive", style="green" if self.alive_count > self.num_players // 2 else "yellow")
            status.append(" │ ", style="dim")
            # Traitors
            traitor_text = f"{self.alive_traitors} traitor{'s' if self.alive_traitors != 1 else ''}"
            status.append(traitor_text, style="red")
            status.append(" │ ", style="dim")
            # Cost
            status.append(f"${self.cost_tracker.total_cost:.4f} ({self.cost_tracker.api_calls})", style="dim")

        layout["header"].update(Panel(status, title="The Traitors", border_style="blue"))

        # Main: Narrow players (left) + wide activity (right)
        layout["main"].split_row(
            Layout(name="players", ratio=1, minimum_size=20),
            Layout(name="activity", ratio=4),
        )

        layout["players"].update(self._render_players_panel())
        layout["activity"].update(self._render_activity_panel())

        # Footer: Cache stats + ETA
        footer_parts = []

        # Cache stats
        cache_read = self.cost_tracker.total_usage.cache_read_tokens
        if cache_read > 0:
            if cache_read >= 1_000_000:
                footer_parts.append(f"Cache: {cache_read / 1_000_000:.1f}M read")
            else:
                footer_parts.append(f"Cache: {cache_read / 1_000:.0f}K read")

        # Balance if provided
        if self.starting_balance is not None:
            remaining = self.starting_balance - self.cost_tracker.total_cost
            footer_parts.append(f"Balance: ${remaining:.2f}")

        # ETA based on API call times
        if self.api_call_times and self.estimated_calls_remaining > 0:
            avg_time_ms = sum(self.api_call_times) / len(self.api_call_times)
            eta_seconds = (avg_time_ms * self.estimated_calls_remaining) / 1000
            if eta_seconds > 60:
                footer_parts.append(f"ETA: ~{eta_seconds/60:.1f} min")
            else:
                footer_parts.append(f"ETA: ~{eta_seconds:.0f} sec")

        footer_text = " │ ".join(footer_parts) if footer_parts else "Running..."
        layout["footer"].update(Panel(Text(footer_text, style="dim")))

        return layout

    def _render_players_panel(self) -> Panel:
        """Render players as a single-column list."""
        table = Table(show_header=False, box=None, padding=(0, 0))
        table.add_column("Player", width=18)

        # Alive first (traitors highlighted), then eliminated
        alive_entries = []
        eliminated_entries = []

        for name in self.all_players:
            is_traitor = name in self.traitor_names
            is_current = name == self.current_player

            if name in self.eliminated:
                # Eliminated player
                info = self.eliminated[name]
                icon = "💀" if info["type"] == "murdered" else "⛔"
                role = "T" if info["role"] == "traitor" else "F"
                text = f"[dim]{icon} {name} ({role})[/]"
                eliminated_entries.append((text, is_traitor))
            else:
                # Alive player
                icon = "🔴" if is_traitor else "🟢"
                marker = " ←" if is_current else ""
                style = "red" if is_traitor else "green"
                text = f"[{style}]{icon} {name}{marker}[/]"
                alive_entries.append((text, is_traitor))

        # Sort: traitors first among alive
        alive_entries.sort(key=lambda x: (not x[1], x[0]))

        # Add all entries
        for text, _ in alive_entries:
            table.add_row(text)
        for text, _ in eliminated_entries:
            table.add_row(text)

        return Panel(table, title="Players", border_style="green")

    def _render_activity_panel(self) -> Panel:
        """Render scrolling activity feed with latest highlighted."""
        lines = []

        # Show last N entries, newest first
        recent = list(reversed(self.activity_log[-self.max_activity_lines:]))

        for i, entry in enumerate(recent):
            player = entry.get("player", "")
            content = clean_content(entry.get("content", ""))
            thoughts = clean_content(entry.get("thoughts", ""))
            entry_type = entry.get("type", "")
            is_pass = entry.get("is_pass", False)

            if i == 0:  # Latest - highlighted
                if entry_type == "phase_change":
                    lines.append(Text(content, style="bold magenta"))
                elif entry_type == "discussion":
                    if is_pass:
                        lines.append(Text(f"{player}: ", style="bold cyan") + Text("[PASS]", style="dim"))
                    else:
                        lines.append(Text(f"{player}: ", style="bold cyan") + Text(f'"{content}"'))
                        if thoughts:
                            # Truncate thoughts if too long
                            thought_preview = thoughts[:100] + "..." if len(thoughts) > 100 else thoughts
                            lines.append(Text(f"  💭 {thought_preview}", style="dim italic"))
                elif entry_type == "vote":
                    lines.append(Text(f"🗳️  {player} ", style="bold yellow") + Text(content))
                elif entry_type == "murder_vote":
                    lines.append(Text(f"🗡️  {player} ", style="bold red") + Text(content))
                elif entry_type == "pouch":
                    lines.append(Text(f"🎒 {player} ", style="bold magenta") + Text(content))
                elif entry_type == "elimination":
                    lines.append(Text(f"⚡ {player} {content}", style="bold red"))
                else:
                    lines.append(Text(f"{player}: {content}", style="bold"))
            else:  # Older - dimmed
                if entry_type == "phase_change":
                    lines.append(Text(content, style="dim magenta"))
                elif entry_type == "discussion":
                    if is_pass:
                        lines.append(Text(f"{player}: [PASS]", style="dim"))
                    else:
                        # Truncate content for older entries
                        preview = content[:80] + "..." if len(content) > 80 else content
                        lines.append(Text(f'{player}: "{preview}"', style="dim"))
                elif entry_type == "vote":
                    lines.append(Text(f"🗳️  {player} {content}", style="dim"))
                elif entry_type == "murder_vote":
                    lines.append(Text(f"🗡️  {player} {content}", style="dim"))
                elif entry_type == "pouch":
                    lines.append(Text(f"🎒 {player} {content}", style="dim"))
                elif entry_type == "elimination":
                    lines.append(Text(f"⚡ {player} {content}", style="dim"))

        if not lines:
            lines.append(Text("Waiting for game to start...", style="dim italic"))

        return Panel(Group(*lines), title="Activity", border_style="blue")

    def __rich__(self) -> Layout:
        """Called by Rich Live on each refresh."""
        return self.render()


def ensure_ollama_running() -> bool:
    """Check if Ollama is running, and start it if not. Returns True if ready."""
    import subprocess
    import socket
    import time

    def is_ollama_running():
        """Check if Ollama server is responding."""
        try:
            with socket.create_connection(("localhost", 11434), timeout=1):
                return True
        except (socket.error, socket.timeout):
            return False

    if is_ollama_running():
        return True

    console.print("[yellow]Ollama not running. Starting...[/]")

    # Try to start ollama serve in background
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        console.print("[red]Error: 'ollama' command not found. Install from https://ollama.ai[/]")
        return False

    # Wait for it to be ready (up to 10 seconds)
    for i in range(20):
        time.sleep(0.5)
        if is_ollama_running():
            console.print("[green]Ollama started.[/]")
            return True

    console.print("[red]Error: Ollama failed to start within 10 seconds.[/]")
    return False


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
    agent_class=None,
    model: Optional[str] = None,
    enable_caching: bool = True,
) -> tuple[dict, float, float, list[str]]:
    """Run a single game with Rich live display. Returns (results, game_cost, game_duration_sec, game_log)."""
    import time
    game_start_time = time.time()

    # Create display
    display = RichGameDisplay(
        num_players=len(contestants),
        contestant_names=[c["name"] for c in contestants],
        starting_balance=starting_balance,
        admin_spending=admin_spending,
        model=model or "claude-3-5-haiku-20241022",
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
            agent_class=agent_class,
            model=model,
            enable_caching=enable_caching,
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

    game_duration_sec = time.time() - game_start_time
    return results, game_cost, game_duration_sec, game_log


def render_run_summary(
    num_games: int,
    faithful_wins: int,
    traitor_wins: int,
    total_cost: float,
    total_duration: float,
    avg_rounds: float,
    contestant_stats: dict,
) -> Panel:
    """Render a Rich Panel with run summary statistics."""
    # Calculate win rate
    win_rate = (faithful_wins / num_games * 100) if num_games > 0 else 0

    # Build summary text
    summary_lines = [
        f"[bold]Games:[/] {num_games}",
        f"[bold]Faithful Wins:[/] [green]{faithful_wins}[/]  |  [bold]Traitor Wins:[/] [red]{traitor_wins}[/]",
        f"[bold]Faithful Win Rate:[/] {win_rate:.0f}%",
        f"[bold]Avg Rounds:[/] {avg_rounds:.1f}",
    ]

    if total_cost > 0:
        summary_lines.append(f"[bold]Total Cost:[/] ${total_cost:.4f}")

    if total_duration > 0:
        duration_min = total_duration / 60
        summary_lines.append(f"[bold]Total Duration:[/] {duration_min:.1f} min")

    # Build top earners table
    if contestant_stats:
        # Sort by total_prize descending
        sorted_stats = sorted(
            contestant_stats.items(),
            key=lambda x: x[1].get("total_prize", 0),
            reverse=True
        )[:5]

        if sorted_stats and sorted_stats[0][1].get("total_prize", 0) > 0:
            summary_lines.append("")
            summary_lines.append("[bold]Top 5 Earners:[/]")

            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
            table.add_column("Player", style="cyan")
            table.add_column("Prize", justify="right", style="yellow")
            table.add_column("Wins", justify="right")
            table.add_column("Games", justify="right")

            for key, stats in sorted_stats:
                name = stats.get("name", key)
                prize = stats.get("total_prize", 0)
                wins = stats.get("wins", 0)
                games = stats.get("games_played", 0)
                table.add_row(name, f"£{prize:,}", str(wins), str(games))

            # Create group with text and table
            text_content = "\n".join(summary_lines)
            return Panel(
                Group(Text.from_markup(text_content), table),
                title="Run Summary",
                border_style="blue",
            )

    return Panel(
        "\n".join(summary_lines),
        title="Run Summary",
        border_style="blue",
    )


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
        default=None,
        help="Number of games to run (default: from config or 1)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show full game log output"
    )
    parser.add_argument(
        "--save", "-s",
        action="store_true",
        help="Save game results to runs/ directory"
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

    # Determine provider and model from config
    provider = config.get("provider", "anthropic")
    agent_class = PROVIDER_MAP.get(provider, Agent)
    model = config.get("default_model") or DEFAULT_MODELS.get(provider)
    enable_caching = config.get("enable_caching", True)

    console.print(f"[bold]The Traitors - Game Simulator[/]")
    console.print(f"Config: {config.get('name', 'unnamed')}")
    console.print(f"Provider: {provider} (model: {model})")
    console.print(f"Players: {len(contestant_pool)} in pool, {players_per_game} per game")
    console.print(f"Traitors: {num_traitors}")
    console.print(f"Finale: Round {finale_round + 1}+")
    if provider == "gemini":
        cache_status = "[green]enabled[/]" if enable_caching else "[yellow]disabled[/]"
        console.print(f"Caching: {cache_status}")
    console.print()

    # Fetch admin spending if key is available (Anthropic only)
    admin_spending = None
    if provider == "anthropic":
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
    elif provider == "gemini":
        console.print("[dim]Tip: View Gemini usage at https://aistudio.google.com/usage[/]")
    elif provider == "ollama":
        if not ensure_ollama_running():
            sys.exit(1)
    console.print()

    # Determine number of games (CLI arg takes precedence over config)
    num_games = args.num_games if args.num_games else config.get("num_games", 1)

    # Check balance and warn if low
    estimated_total = 0.25 * num_games
    check_balance_warning(args.balance, estimated_total)

    # Track cumulative balance across games
    current_balance = args.balance

    # Track run totals
    run_total_cost = 0.0
    run_total_duration = 0.0

    # Set up save directory if saving
    run_id = None
    run_dir = None
    games_data = []
    games_costs = []  # Per-game cost tracking
    games_durations = []  # Per-game duration tracking
    if args.save:
        run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[dim]Saving to {run_dir}/[/]")
        console.print()

    # Track win tallies
    faithful_wins = 0
    traitor_wins = 0

    for game_num in range(1, num_games + 1):
        if num_games > 1:
            console.print(f"\n[bold cyan]Game {game_num}/{num_games}[/]")

        # Select contestants for this game
        if len(contestant_pool) > PLAYERS_PER_GAME:
            contestants = select_contestants_for_game(contestant_pool)
        else:
            contestants = contestant_pool.copy()

        # Run game
        results, game_cost, game_duration, game_log = run_game_with_display(
            contestants=contestants,
            num_traitors=num_traitors,
            finale_round=finale_round,
            starting_balance=current_balance,
            test_mode=args.test_mode,
            verbose=args.verbose,
            admin_spending=admin_spending,
            agent_class=agent_class,
            model=model,
            enable_caching=enable_caching,
        )

        # Track wins
        if results["winner"] == "faithful":
            faithful_wins += 1
        else:
            traitor_wins += 1

        # Track costs and durations
        run_total_cost += game_cost
        run_total_duration += game_duration
        games_costs.append(game_cost)
        games_durations.append(game_duration)

        # Update balance for next game
        if current_balance is not None:
            current_balance -= game_cost

        # Save game data if requested
        if args.save:
            games_data.append(results)
            save_game_json(str(run_dir), game_num, results, game_log, game_cost, game_duration)
            pool_size = len(contestant_pool) if len(contestant_pool) > PLAYERS_PER_GAME else None
            save_run_json(str(run_dir), run_id, config, games_data, contestant_pool, pool_size,
                         games_costs, games_durations)
            update_runs_index("runs", "data")
            console.print(f"[dim]Saved game {game_num} to {run_dir}/[/]")

        # Show progress for multi-game runs
        if num_games > 1:
            console.print(f"[dim]Progress: Faithful {faithful_wins}, Traitors {traitor_wins}[/]")

        console.print()

    # Generate analysis and display summary after run completes
    if args.save:
        import os
        # Load run.json to get stats
        run_json_path = run_dir / "run.json"
        if run_json_path.exists():
            with open(run_json_path) as f:
                run_data = json.load(f)

            # Generate AI analysis if ANTHROPIC_API_KEY is set
            if os.environ.get("ANTHROPIC_API_KEY") and not args.test_mode:
                console.print("[dim]Generating run analysis with Claude Opus...[/]")
                try:
                    analysis = generate_run_analysis(run_data["stats"], run_data["contestant_stats"])
                    run_data["analysis"] = analysis
                    with open(run_json_path, "w") as f:
                        json.dump(run_data, f, indent=2)
                    console.print("[dim]Analysis saved.[/]")
                except Exception as e:
                    console.print(f"[yellow]Analysis generation failed: {e}[/]")

            # Display run summary
            avg_rounds = run_data["stats"].get("avg_rounds", 0)
            contestant_stats = run_data.get("contestant_stats", {})
            summary_panel = render_run_summary(
                num_games=num_games,
                faithful_wins=faithful_wins,
                traitor_wins=traitor_wins,
                total_cost=run_total_cost,
                total_duration=run_total_duration,
                avg_rounds=avg_rounds,
                contestant_stats=contestant_stats,
            )
            console.print(summary_panel)

        console.print(f"[bold]View results:[/] run.html?run={run_id}")

    elif num_games > 1:
        # Display summary for multi-game runs even without --save
        avg_rounds = sum(len(g.get("rounds", [])) for g in games_data) / num_games if games_data else 0
        summary_panel = render_run_summary(
            num_games=num_games,
            faithful_wins=faithful_wins,
            traitor_wins=traitor_wins,
            total_cost=run_total_cost,
            total_duration=run_total_duration,
            avg_rounds=avg_rounds,
            contestant_stats={},  # No stats available without --save
        )
        console.print(summary_panel)


if __name__ == "__main__":
    main()
