"""Main game engine for The Traitors simulation."""

import random
from collections import Counter
from typing import Callable, Optional, Type

import anthropic

from .types import Player, GameState, GamePhase, Role, PlayerStatus, Message, Vote, PouchVote, PrivateThought
from .agent import Agent, TestAgent, OllamaAgent


class TraitorsGame:
    """
    The Traitors game simulator.

    This simulates the TV show format where:
    - Some players are secretly Traitors, others are Faithful
    - During the day, everyone discusses and votes to banish one person
    - At night, Traitors secretly murder one Faithful player
    - Faithful win by banishing all Traitors
    - Traitors win by surviving until the end or being the last ones standing

    Uses Anthropic prompt caching for efficiency - shared context (conversation history)
    is built once and passed to all agents for caching.
    """

    def __init__(
        self,
        contestants: list[dict],
        num_traitors: int = 1,
        finale_round: int = 8,
        client: Optional[anthropic.Anthropic] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        test_mode: bool = False,
        agent_class: Optional[Type[Agent]] = None,
        model: Optional[str] = None,
    ):
        """
        Initialize a new game.

        Args:
            contestants: List of dicts with 'name' and 'personality_prompt' keys
            num_traitors: Number of traitors to assign (default 1)
            finale_round: Round after which finale begins (default 8, matching UK Celebrity format)
            client: Anthropic client (creates new one if not provided)
            log_callback: Optional callback for logging game events
            test_mode: If True, use TestAgent (random decisions, no LLM calls) for fast testing
            agent_class: Optional agent class to use (e.g., OllamaAgent). Overrides test_mode.
            model: Optional model name for OllamaAgent (e.g., "llama3.2")
        """
        self.test_mode = test_mode
        self.log = log_callback or print
        self.num_traitors = num_traitors
        self.model = model

        # Determine which agent class to use
        if agent_class is not None:
            AgentClass = agent_class
            # OllamaAgent doesn't use Anthropic client
            self.client = None if AgentClass == OllamaAgent else (client or anthropic.Anthropic())
        elif test_mode:
            AgentClass = TestAgent
            self.client = None
        else:
            AgentClass = Agent
            self.client = client or anthropic.Anthropic()

        # Create game state
        self.state = GameState()
        self.state.num_traitors = num_traitors
        self.state.finale_round = finale_round

        # Create players with per-player model support
        for contestant in contestants:
            # Per-player model takes precedence over game-wide model
            player_model = contestant.get("model", model)
            player = Player(
                name=contestant["name"],
                personality_prompt=contestant["personality_prompt"],
                model=player_model,
            )
            self.state.players[player.name] = player

        # Create agents based on the selected class
        self.agents: dict[str, Agent] = {}
        for player in self.state.players.values():
            if AgentClass == OllamaAgent:
                # OllamaAgent takes model parameter
                self.agents[player.name] = AgentClass(player, model=player.model or "llama3.2")
            elif AgentClass == TestAgent:
                self.agents[player.name] = AgentClass(player)
            else:
                # Standard Agent with Anthropic client and per-player model
                self.agents[player.name] = AgentClass(player, self.client, model=player.model)

    def _assign_roles(self) -> None:
        """Randomly assign traitor roles."""
        player_names = list(self.state.players.keys())
        traitor_names = random.sample(player_names, self.num_traitors)

        for name in traitor_names:
            self.state.players[name].role = Role.TRAITOR

        self.log("\n" + "=" * 60)
        self.log("ROLE ASSIGNMENT (Secret - players don't know each other's roles)")
        self.log("=" * 60)
        for player in self.state.players.values():
            self.log(f"  {player.name}: {player.role.value.upper()}")

    def _build_cached_public_history(self) -> str:
        """Build conversation history for caching (public messages only).

        Used during voting phases where all faithful players see the same history.
        This is built once and passed to all agents for prompt caching efficiency.
        """
        messages = self.state.get_public_messages()
        return self._format_history_with_events(messages)

    def _build_cached_traitor_history(self) -> str:
        """Build conversation history for caching (includes private traitor messages).

        Used during traitor meetings where all traitors see the same history.
        This is built once and passed to all traitor agents for prompt caching efficiency.
        """
        messages = self.state.get_traitor_messages()
        return self._format_history_with_events(messages)

    def _format_history_with_events(self, messages: list) -> str:
        """Format message history with round events (eliminations)."""
        round_events = self._get_round_events()

        if not messages and not round_events:
            return "No discussion has happened yet."

        formatted = []
        current_round = 0

        for msg in messages:
            if msg.round_num != current_round:
                # Before starting new round, add events from previous round
                if current_round > 0 and current_round in round_events:
                    formatted.append(f"\n--- END OF ROUND {current_round} ---")
                    for event in round_events[current_round]:
                        formatted.append(event)

                current_round = msg.round_num
                formatted.append(f"\n--- ROUND {current_round} DISCUSSION ---")

            prefix = "[PRIVATE TRAITOR CHAT] " if msg.is_private else ""
            formatted.append(f"{prefix}{msg.speaker}: {msg.content}")

        # Add final round events if we're past them
        if current_round > 0 and current_round in round_events and current_round < self.state.current_round:
            formatted.append(f"\n--- END OF ROUND {current_round} ---")
            for event in round_events[current_round]:
                formatted.append(event)

        return "\n".join(formatted)

    def _get_round_events(self) -> dict[int, list[str]]:
        """Get elimination events organized by round."""
        events: dict[int, list[str]] = {}

        for player in self.state.players.values():
            if not player.is_alive:
                round_num = player.eliminated_round or 1

                if player.status == PlayerStatus.BANISHED:
                    if round_num > self.state.finale_round:
                        event = f"🗳️ {player.name} was BANISHED (role unknown - finale)"
                    else:
                        event = f"🗳️ {player.name} was BANISHED (revealed as {player.role.value.upper()})"
                else:  # MURDERED
                    event = f"💀 {player.name} was MURDERED overnight (they were {player.role.value.upper()})"

                if round_num not in events:
                    events[round_num] = []
                events[round_num].append(event)

        return events

    def _check_win_condition(self) -> Optional[str]:
        """Check if the game has ended. Returns winner or None."""
        alive_traitors = self.state.alive_traitors
        alive_faithful = self.state.alive_faithful

        if not alive_traitors:
            return "faithful"
        if not alive_faithful:
            return "traitors"
        if len(alive_traitors) >= len(alive_faithful):
            return "traitors"

        return None

    def _run_end_game_vote(self) -> bool:
        """Run a vote on whether to end the game. Returns True if game should end."""
        self.log("\n" + "-" * 40)
        self.log("END GAME VOTE - Continue or stop?")
        self.log("-" * 40)

        end_votes = 0
        continue_votes = 0
        alive_players = self.state.alive_players

        # Build cached history once for all voters
        cached_public_history = self._build_cached_public_history()
        cached_traitor_history = self._build_cached_traitor_history()

        for player in alive_players:
            agent = self.agents[player.name]
            cached_history = cached_traitor_history if player.is_traitor else cached_public_history
            vote_to_end = agent.generate_end_game_vote(self.state, cached_history=cached_history)

            vote_str = "END" if vote_to_end else "CONTINUE"
            self.log(f"  {player.name} votes: {vote_str}")

            if vote_to_end:
                end_votes += 1
            else:
                continue_votes += 1

        self.log(f"\nResult: END {end_votes} - CONTINUE {continue_votes}")

        # Majority needed to end
        if end_votes > continue_votes:
            self.log("The group has voted to END the game!")
            return True
        else:
            self.log("The group has voted to CONTINUE playing.")
            return False

    def _run_finale_pouch_vote(self) -> bool:
        """
        Run the UK-style finale pouch voting.

        Each player chooses "END_GAME" or "BANISH_AGAIN".
        - If ANY player chose BANISH_AGAIN: run banishment vote (no role reveal)
        - If ALL chose END_GAME: game ends, roles revealed

        Returns True if game should end.
        """
        self.log("\n" + "-" * 40)
        self.log("FIRE PIT - Pouch voting...")
        self.log("Each player throws one pouch: END_GAME or BANISH_AGAIN")
        self.log("-" * 40)

        alive_players = self.state.alive_players
        choices: dict[str, str] = {}

        # Build cached history once for all voters
        cached_public_history = self._build_cached_public_history()
        cached_traitor_history = self._build_cached_traitor_history()

        for player in alive_players:
            agent = self.agents[player.name]
            cached_history = cached_traitor_history if player.is_traitor else cached_public_history
            choice = agent.generate_finale_pouch_choice(self.state, cached_history=cached_history)
            choices[player.name] = choice
            self.log(f"  {player.name} throws: {choice}")
            # Record the pouch vote
            self.state.pouch_votes.append(PouchVote(
                voter=player.name,
                choice=choice,
                round_num=self.state.current_round
            ))

        banish_count = sum(1 for c in choices.values() if c == "BANISH_AGAIN")
        end_count = len(choices) - banish_count

        self.log(f"\nResult: END_GAME {end_count} - BANISH_AGAIN {banish_count}")

        if banish_count > 0:
            # At least one player chose to banish again
            self.log("\nSomeone wants to banish again! Back to voting...")
            return False
        else:
            # All chose to end
            self.log("\nAll players chose to END the game!")
            return True

    def _run_finale_voting_phase(self) -> Optional[str]:
        """
        Run voting during finale - no role reveal.
        Returns name of banished player or None.
        """
        self.state.current_phase = GamePhase.VOTING

        self.log("\n" + "-" * 40)
        self.log("FINALE VOTING - Who will be banished?")
        self.log("-" * 40)

        votes: dict[str, str] = {}
        alive_players = self.state.alive_players

        # Build cached history once for all voters
        cached_public_history = self._build_cached_public_history()
        cached_traitor_history = self._build_cached_traitor_history()

        for player in alive_players:
            agent = self.agents[player.name]
            cached_history = cached_traitor_history if player.is_traitor else cached_public_history
            vote_target = agent.generate_vote(self.state, cached_history=cached_history)
            votes[player.name] = vote_target

            vote = Vote(
                voter=player.name,
                target=vote_target,
                round_num=self.state.current_round,
            )
            self.state.votes.append(vote)

            self.log(f"  {player.name} votes for: {vote_target}")

        # Count votes
        vote_counts = Counter(votes.values())
        if not vote_counts:
            self.log("\nNo valid votes cast!")
            return None

        max_votes = max(vote_counts.values())
        top_voted = [name for name, count in vote_counts.items() if count == max_votes]

        if len(top_voted) > 1:
            banished_name = random.choice(top_voted)
            self.log(f"\nTIE! Random selection from: {', '.join(top_voted)}")
        else:
            banished_name = top_voted[0]

        # Banish the player (no role reveal in finale)
        if banished_name in self.state.players:
            banished = self.state.players[banished_name]
            banished.status = PlayerStatus.BANISHED
            banished.eliminated_round = self.state.current_round

            self.log(f"\n{'=' * 40}")
            self.log(f"BANISHED: {banished_name}")
            self.log("(Role not revealed - this is the finale)")
            self.log(f"{'=' * 40}")

            return banished_name

        return None

    def _reveal_all_roles(self) -> None:
        """Reveal all roles at the end of the finale."""
        self.log("\n" + "=" * 60)
        self.log("FINAL REVEAL - All roles are revealed!")
        self.log("=" * 60)

        for player in self.state.players.values():
            status = "SURVIVED" if player.is_alive else player.status.value.upper()
            role = player.role.value.upper()
            self.log(f"  {player.name}: {role} ({status})")

    def _run_discussion_phase(self) -> None:
        """Run the discussion phase where players talk."""
        self.state.current_phase = GamePhase.DISCUSSION

        self.log("\n" + "-" * 40)
        self.log(f"ROUND {self.state.current_round} - DISCUSSION PHASE")
        self.log("-" * 40)

        alive_players = self.state.alive_players
        random.shuffle(alive_players)  # Randomize speaking order

        # Each player speaks once
        for i, player in enumerate(alive_players):
            agent = self.agents[player.name]

            if i == 0:
                prompt = "You're speaking first. Share your initial thoughts or suspicions."
            else:
                prompt = "Respond to what others have said or share your own observations."

            statement = agent.generate_discussion(self.state, prompt)

            message = Message(
                speaker=player.name,
                content=statement,
                round_num=self.state.current_round,
            )
            self.state.messages.append(message)

            self.log(f"\n{player.name}: {statement}")

    def _run_private_thoughts_phase(self) -> None:
        """Run the private thoughts phase where each player thinks before voting."""
        self.log("\n" + "-" * 40)
        self.log("PRIVATE THOUGHTS - What are the players thinking?")
        self.log("-" * 40)

        alive_players = self.state.alive_players

        # Build cached history once for all players (separate for traitors vs faithful)
        cached_public_history = self._build_cached_public_history()
        cached_traitor_history = self._build_cached_traitor_history()

        for player in alive_players:
            agent = self.agents[player.name]
            # Use appropriate cached history based on role
            cached_history = cached_traitor_history if player.is_traitor else cached_public_history
            thoughts = agent.generate_private_thoughts(self.state, cached_history=cached_history)

            thought = PrivateThought(
                player=player.name,
                content=thoughts,
                round_num=self.state.current_round,
            )
            self.state.private_thoughts.append(thought)

            role_tag = "[TRAITOR]" if player.is_traitor else "[FAITHFUL]"
            self.log(f"\n{role_tag} {player.name}'s thoughts: {thoughts}")

    def _run_voting_phase(self) -> Optional[str]:
        """Run the voting phase. Returns name of banished player or None."""
        self.state.current_phase = GamePhase.VOTING

        # First, private thoughts
        self._run_private_thoughts_phase()

        self.log("\n" + "-" * 40)
        self.log("VOTING PHASE - Who will be banished?")
        self.log("-" * 40)

        votes: dict[str, str] = {}
        alive_players = self.state.alive_players

        # Build cached history once for all voters
        cached_public_history = self._build_cached_public_history()
        cached_traitor_history = self._build_cached_traitor_history()

        for player in alive_players:
            agent = self.agents[player.name]
            # Use appropriate cached history based on role
            cached_history = cached_traitor_history if player.is_traitor else cached_public_history
            vote_target = agent.generate_vote(self.state, cached_history=cached_history)
            votes[player.name] = vote_target

            vote = Vote(
                voter=player.name,
                target=vote_target,
                round_num=self.state.current_round,
            )
            self.state.votes.append(vote)

            self.log(f"  {player.name} votes for: {vote_target}")

        # Count votes
        vote_counts = Counter(votes.values())
        if not vote_counts:
            self.log("\nNo valid votes cast!")
            return None

        max_votes = max(vote_counts.values())
        top_voted = [name for name, count in vote_counts.items() if count == max_votes]

        if len(top_voted) > 1:
            # Tie - random selection
            banished_name = random.choice(top_voted)
            self.log(f"\nTIE! Random selection from: {', '.join(top_voted)}")
        else:
            banished_name = top_voted[0]

        # Banish the player
        if banished_name in self.state.players:
            banished = self.state.players[banished_name]
            banished.status = PlayerStatus.BANISHED
            banished.eliminated_round = self.state.current_round

            self.log(f"\n{'=' * 40}")
            self.log(f"BANISHED: {banished_name}")

            # In finale, roles are NOT revealed (like the UK TV show)
            if self.state.is_finale:
                self.log("(Role not revealed - this is the finale)")
            else:
                self.log(f"They were a: {banished.role.value.upper()}")
            self.log(f"{'=' * 40}")

            return banished_name

        return None

    def _run_night_phase(self) -> Optional[str]:
        """Run the night phase where traitors murder. Returns victim name or None."""
        self.state.current_phase = GamePhase.NIGHT

        alive_traitors = self.state.alive_traitors
        alive_faithful = self.state.alive_faithful

        if not alive_traitors or not alive_faithful:
            return None

        self.log("\n" + "-" * 40)
        self.log("NIGHT PHASE - Traitors meet in secret...")
        self.log("-" * 40)

        # Build cached traitor history once for all traitors
        cached_traitor_history = self._build_cached_traitor_history()

        # Traitors discuss (if more than one)
        if len(alive_traitors) > 1:
            for traitor in alive_traitors:
                agent = self.agents[traitor.name]
                discussion = agent.generate_traitor_discussion(self.state, cached_history=cached_traitor_history)

                message = Message(
                    speaker=traitor.name,
                    content=discussion,
                    round_num=self.state.current_round,
                    is_private=True,
                )
                self.state.messages.append(message)

                self.log(f"\n[TRAITOR] {traitor.name}: {discussion}")

        # Traitors vote on victim - rebuild cached history to include discussion
        cached_traitor_history = self._build_cached_traitor_history()
        murder_votes: dict[str, str] = {}
        for traitor in alive_traitors:
            agent = self.agents[traitor.name]
            vote = agent.generate_murder_vote(self.state, cached_history=cached_traitor_history)
            murder_votes[traitor.name] = vote
            self.log(f"\n[MURDER VOTE] {traitor.name} votes to kill: {vote}")

        # Count votes
        vote_counts = Counter(murder_votes.values())
        if not vote_counts:
            return None

        max_votes = max(vote_counts.values())
        top_voted = [name for name, count in vote_counts.items() if count == max_votes]

        if len(top_voted) > 1:
            victim_name = random.choice(top_voted)
        else:
            victim_name = top_voted[0]

        # Murder the victim
        if victim_name in self.state.players:
            victim = self.state.players[victim_name]
            victim.status = PlayerStatus.MURDERED
            victim.eliminated_round = self.state.current_round

            self.log(f"\n{'=' * 40}")
            self.log(f"MURDERED: {victim_name}")
            self.log("The faithful mourn their loss...")
            self.log(f"{'=' * 40}")

            return victim_name

        return None

    def run(self) -> dict:
        """
        Run the complete game simulation (UK Celebrity Traitors format).

        Game structure:
        - Rounds 1-8: Regular play (discussion → voting with role reveal → murder)
        - Round 9+: Finale (discussion → voting without role reveal → pouch vote)

        The game ends when:
        1. All traitors are banished (faithful win)
        2. Traitors outnumber or equal faithful (traitors win)
        3. All players vote END_GAME in the finale pouch vote

        Returns:
            dict with game results including winner, final state, and game log
        """
        self.log("\n" + "=" * 60)
        self.log("THE TRAITORS - GAME SIMULATION")
        self.log("=" * 60)
        self.log(f"Players: {', '.join(self.state.players.keys())}")
        self.log(f"Finale begins after round {self.state.finale_round}")

        # Assign roles
        self._assign_roles()

        # Main game loop
        max_safety_rounds = 20  # Prevent infinite loops
        while self.state.current_round <= max_safety_rounds:
            self.log(f"\n{'#' * 60}")
            if self.state.is_finale:
                self.log(f"FINALE - ROUND {self.state.current_round}")
            else:
                self.log(f"ROUND {self.state.current_round}")
            self.log(f"{'#' * 60}")
            self.log(f"Alive: {', '.join(p.name for p in self.state.alive_players)}")

            # Discussion phase
            self._run_discussion_phase()

            if self.state.is_finale:
                # FINALE: Voting without role reveal, then pouch vote
                self._run_finale_voting_phase()

                # Check win condition after banishment
                winner = self._check_win_condition()
                if winner:
                    self.state.winner = winner
                    self._reveal_all_roles()
                    break

                # Pouch vote - continue until all choose END_GAME
                if self._run_finale_pouch_vote():
                    # All chose to end - reveal roles and determine winner
                    self._reveal_all_roles()
                    if self.state.alive_traitors:
                        self.state.winner = "traitors"
                        self.log("\nTRAITORS WERE STILL AMONG THEM!")
                    else:
                        self.state.winner = "faithful"
                        self.log("\nAll traitors had been eliminated!")
                    break

                # Continue to next finale round (no murder in finale)
                self.state.current_round += 1
            else:
                # REGULAR ROUNDS: Voting with role reveal, then murder
                # (UK format: no early end vote - play through all rounds until finale)
                self._run_voting_phase()

                # Check win condition after banishment
                winner = self._check_win_condition()
                if winner:
                    self.state.winner = winner
                    break

                # Night phase (traitors murder) - only in regular rounds
                self._run_night_phase()

                # Check win condition after murder
                winner = self._check_win_condition()
                if winner:
                    self.state.winner = winner
                    break

                self.state.current_round += 1

        # Game ended
        self.state.current_phase = GamePhase.ENDED

        if not self.state.winner:
            # Safety: game ended due to round limit
            if self.state.alive_traitors:
                self.state.winner = "traitors"
            else:
                self.state.winner = "faithful"

        self._print_final_results()

        return {
            "winner": self.state.winner,
            "rounds_played": self.state.current_round,
            "survivors": [p.name for p in self.state.alive_players],
            "traitors": [p.name for p in self.state.players.values() if p.is_traitor],
            "faithful": [p.name for p in self.state.players.values() if not p.is_traitor],
            "prize_pool": self.state.prize_pool,
            "prize_distribution": self.state.prize_distribution,
        }

    def _distribute_prize_money(self) -> None:
        """
        Distribute the prize money based on game outcome.

        Rules (matching the real show):
        - If FAITHFUL WIN: Surviving faithful players split the prize pool equally
        - If TRAITORS WIN: Surviving traitors take ALL the money, faithful get nothing
        """
        prize_pool = self.state.prize_pool

        # Initialize all players to $0
        for player in self.state.players.values():
            self.state.prize_distribution[player.name] = 0

        if self.state.winner == "faithful":
            # Faithful win: surviving faithful split the pot
            surviving_faithful = [p for p in self.state.alive_players if not p.is_traitor]
            if surviving_faithful:
                share = prize_pool // len(surviving_faithful)
                for player in surviving_faithful:
                    self.state.prize_distribution[player.name] = share
        else:
            # Traitors win: surviving traitors take everything
            surviving_traitors = [p for p in self.state.alive_players if p.is_traitor]
            if surviving_traitors:
                share = prize_pool // len(surviving_traitors)
                for player in surviving_traitors:
                    self.state.prize_distribution[player.name] = share

    def _print_final_results(self) -> None:
        """Print the final game results."""
        # Distribute prize money first
        self._distribute_prize_money()

        self.log("\n" + "=" * 60)
        self.log("GAME OVER")
        self.log("=" * 60)

        self.log(f"\nWINNER: THE {self.state.winner.upper()}!")

        self.log(f"\nPRIZE POOL: ${self.state.prize_pool:,}")
        self.log("\nFinal Player Status:")
        for player in self.state.players.values():
            status = "SURVIVED" if player.is_alive else player.status.value.upper()
            role = player.role.value.upper()
            winnings = self.state.prize_distribution.get(player.name, 0)
            winnings_str = f"${winnings:,}" if winnings > 0 else "$0"
            self.log(f"  {player.name}: {role} - {status} - {winnings_str}")

        self.log("\n" + "=" * 60)
