"""Main game engine for The Traitors simulation."""

import random
from collections import Counter
from typing import Callable, Optional

import anthropic

from .types import Player, GameState, GamePhase, Role, PlayerStatus, Message, Vote, PrivateThought
from .agent import Agent


class TraitorsGame:
    """
    The Traitors game simulator.

    This simulates the TV show format where:
    - Some players are secretly Traitors, others are Faithful
    - During the day, everyone discusses and votes to banish one person
    - At night, Traitors secretly murder one Faithful player
    - Faithful win by banishing all Traitors
    - Traitors win by surviving until the end or being the last ones standing
    """

    def __init__(
        self,
        contestants: list[dict],
        num_traitors: int = 1,
        client: Optional[anthropic.Anthropic] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize a new game.

        Args:
            contestants: List of dicts with 'name' and 'personality_prompt' keys
            num_traitors: Number of traitors to assign (default 1)
            client: Anthropic client (creates new one if not provided)
            log_callback: Optional callback for logging game events
        """
        self.client = client or anthropic.Anthropic()
        self.log = log_callback or print
        self.num_traitors = num_traitors

        # Create game state
        self.state = GameState()
        self.state.num_traitors = num_traitors

        # Create players
        for contestant in contestants:
            player = Player(
                name=contestant["name"],
                personality_prompt=contestant["personality_prompt"],
            )
            self.state.players[player.name] = player

        # Create agents
        self.agents: dict[str, Agent] = {}
        for player in self.state.players.values():
            self.agents[player.name] = Agent(player, self.client)

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

        for player in alive_players:
            agent = self.agents[player.name]
            vote_to_end = agent.generate_end_game_vote(self.state)

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

        for player in alive_players:
            agent = self.agents[player.name]
            thoughts = agent.generate_private_thoughts(self.state)

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

        for player in alive_players:
            agent = self.agents[player.name]
            vote_target = agent.generate_vote(self.state)
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

            # In endgame, roles are NOT revealed (like the UK TV show finale)
            if self.state.is_endgame:
                self.log("(Role not revealed - this is the endgame)")
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

        # Traitors discuss (if more than one)
        if len(alive_traitors) > 1:
            for traitor in alive_traitors:
                agent = self.agents[traitor.name]
                discussion = agent.generate_traitor_discussion(self.state)

                message = Message(
                    speaker=traitor.name,
                    content=discussion,
                    round_num=self.state.current_round,
                    is_private=True,
                )
                self.state.messages.append(message)

                self.log(f"\n[TRAITOR] {traitor.name}: {discussion}")

        # Traitors vote on victim
        murder_votes: dict[str, str] = {}
        for traitor in alive_traitors:
            agent = self.agents[traitor.name]
            vote = agent.generate_murder_vote(self.state)
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
        Run the complete game simulation.

        The game continues until:
        1. All traitors are banished (faithful win)
        2. Traitors outnumber or equal faithful (traitors win)
        3. Players vote to end the game (traitors win if any remain, faithful win otherwise)

        Returns:
            dict with game results including winner, final state, and game log
        """
        self.log("\n" + "=" * 60)
        self.log("THE TRAITORS - GAME SIMULATION")
        self.log("=" * 60)
        self.log(f"Players: {', '.join(self.state.players.keys())}")

        # Assign roles
        self._assign_roles()

        # Main game loop - continues until win condition or players vote to end
        max_safety_rounds = 20  # Prevent infinite loops
        while self.state.current_round <= max_safety_rounds:
            self.log(f"\n{'#' * 60}")
            self.log(f"ROUND {self.state.current_round}")
            self.log(f"{'#' * 60}")
            self.log(f"Alive: {', '.join(p.name for p in self.state.alive_players)}")

            # Discussion phase
            self._run_discussion_phase()

            # Voting phase (banishment)
            self._run_voting_phase()

            # Check win condition after banishment
            winner = self._check_win_condition()
            if winner:
                self.state.winner = winner
                break

            # End game vote - do players want to stop or continue?
            if self._run_end_game_vote():
                # Players voted to end - determine winner
                if self.state.alive_traitors:
                    self.state.winner = "traitors"
                    self.log("\n⚠️  TRAITORS WERE STILL AMONG THEM!")
                else:
                    self.state.winner = "faithful"
                    self.log("\n✓ All traitors had been eliminated!")
                break

            # Night phase (traitors murder)
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
