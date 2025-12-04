"""Demo mode for running the game without an API key."""

import random
from typing import Optional, Callable
from collections import Counter

from .types import Player, GameState, GamePhase, Role, PlayerStatus, Message, Vote


# Pre-written responses for each personality type
DEMO_RESPONSES = {
    "Marcus": {
        "discussion": [
            "I've been observing everyone's body language. Some people seem more nervous than others when the topic of traitors comes up.",
            "Let's think about this logically. Who has been deflecting the most? That's often a sign of guilt.",
            "I noticed some inconsistencies in what was said earlier. We should press on those points.",
        ],
        "accusation": [
            "Based on my observations, I find {target}'s behavior suspicious. They've been too quiet at strategic moments.",
            "The evidence points to {target}. Their reactions don't add up.",
        ],
        "defense": [
            "I understand the suspicion, but consider the facts objectively. I've been trying to find the truth just like everyone else.",
            "If I were a traitor, would I be this methodical in my approach? I'm building a case, not hiding.",
        ],
    },
    "Sofia": {
        "discussion": [
            "I'm getting a strange feeling about some people here. Call it intuition, but something feels off.",
            "Can we all just be honest with each other? I believe in giving people a chance to explain themselves.",
            "I want to trust everyone, but we need to work together to find the truth.",
        ],
        "accusation": [
            "I hate to say this, but {target} hasn't been genuine with us. I can sense it.",
            "Something about {target}'s energy feels deceptive to me. I'm sorry, but I have to speak up.",
        ],
        "defense": [
            "I would never betray this group. You can see in my eyes that I'm being sincere.",
            "Please, look at how I've been trying to connect with everyone. That's not traitor behavior.",
        ],
    },
    "Derek": {
        "discussion": [
            "Look, we need to be smart about this. The traitors are playing us against each other.",
            "I've been in competitive situations before. I know manipulation when I see it.",
            "Let's cut to the chase - someone here is lying, and I think I know who.",
        ],
        "accusation": [
            "I'm going to be direct - {target} has been playing a game within the game. Wake up, people!",
            "{target} is too smooth, too calculated. That's exactly how a traitor would act.",
        ],
        "defense": [
            "Come on, you're falling for the real traitors' trap by targeting me. I'm on your side!",
            "Think about it - would a traitor be this bold? I'm confident because I'm innocent.",
        ],
    },
    "Elena": {
        "discussion": [
            "I've been watching and listening. Sometimes the quietest observations reveal the most.",
            "Let's not rush to judgment. The traitors want us to act emotionally, not rationally.",
            "In my experience, truth reveals itself to those who are patient.",
        ],
        "accusation": [
            "After careful consideration, I believe {target} has not been truthful with us.",
            "The patterns of behavior I've observed point to {target}. I don't say this lightly.",
        ],
        "defense": [
            "I've lived long enough to know that wisdom and patience are not signs of guilt.",
            "Consider my actions, not just words. I've been trying to guide us to the truth.",
        ],
    },
    "Jaylen": {
        "discussion": [
            "Okay, I might be new to this, but something definitely feels wrong here!",
            "I can't hide how I feel - I'm frustrated that we haven't figured this out yet!",
            "Why are some people so calm? Shouldn't we all be more worried about the traitors?",
        ],
        "accusation": [
            "I know I might be jumping the gun, but {target} has been acting super suspicious!",
            "Call me crazy, but {target} is giving off major traitor vibes right now!",
        ],
        "defense": [
            "What? Me? I wear my heart on my sleeve! How could I possibly be hiding something?",
            "You can literally see every emotion on my face. Does this look like a traitor to you?",
        ],
    },
    "Priya": {
        "discussion": [
            "Let's approach this strategically. What do we actually know versus what we're assuming?",
            "In business, you learn to spot deception quickly. Someone here isn't adding up.",
            "We need to make a decision and commit to it. Hesitation helps the traitors.",
        ],
        "accusation": [
            "The risk-reward analysis points to {target}. They've been minimizing their exposure.",
            "I'm making an executive decision here - {target} needs to answer for their behavior.",
        ],
        "defense": [
            "I've built my career on integrity. Accusing me is a waste of our limited time.",
            "Look at my track record in this game. I've been driving us toward the truth.",
        ],
    },
}

TRAITOR_DISCUSSION = [
    "We need to deflect attention. Let's create some chaos between the faithful.",
    "I think {target} is getting too close to the truth. They should be our next target.",
    "Let's both vote for different people to avoid suspicion.",
    "Stay calm and act natural. We can't let them see us sweat.",
]


class DemoGame:
    """A demo version of the game that doesn't require API calls."""

    def __init__(
        self,
        contestants: list[dict],
        num_traitors: int = 1,
        num_rounds: int = 3,
        log_callback: Optional[Callable[[str], None]] = None,
        seed: Optional[int] = None,
    ):
        if seed is not None:
            random.seed(seed)

        self.log = log_callback or print
        self.num_traitors = num_traitors

        self.state = GameState(max_rounds=num_rounds)

        for contestant in contestants:
            player = Player(
                name=contestant["name"],
                personality_prompt=contestant["personality_prompt"],
            )
            self.state.players[player.name] = player

        self.discussion_index: dict[str, int] = {c["name"]: 0 for c in contestants}

    def _assign_roles(self) -> None:
        player_names = list(self.state.players.keys())
        traitor_names = random.sample(player_names, self.num_traitors)

        for name in traitor_names:
            self.state.players[name].role = Role.TRAITOR

        self.log("\n" + "=" * 60)
        self.log("ROLE ASSIGNMENT (Secret - players don't know each other's roles)")
        self.log("=" * 60)
        for player in self.state.players.values():
            self.log(f"  {player.name}: {player.role.value.upper()}")

    def _get_response(self, player: Player, response_type: str, target: Optional[str] = None) -> str:
        responses = DEMO_RESPONSES.get(player.name, DEMO_RESPONSES["Marcus"])
        options = responses.get(response_type, responses["discussion"])

        idx = self.discussion_index[player.name] % len(options)
        self.discussion_index[player.name] += 1

        response = options[idx]
        if target and "{target}" in response:
            response = response.replace("{target}", target)
        return response

    def _check_win_condition(self) -> Optional[str]:
        alive_traitors = self.state.alive_traitors
        alive_faithful = self.state.alive_faithful

        if not alive_traitors:
            return "faithful"
        if not alive_faithful:
            return "traitors"
        if len(alive_traitors) >= len(alive_faithful):
            return "traitors"

        return None

    def _run_discussion_phase(self) -> None:
        self.state.current_phase = GamePhase.DISCUSSION

        self.log("\n" + "-" * 40)
        self.log(f"ROUND {self.state.current_round} - DISCUSSION PHASE")
        self.log("-" * 40)

        alive_players = list(self.state.alive_players)
        random.shuffle(alive_players)

        for i, player in enumerate(alive_players):
            # Sometimes accuse, sometimes just discuss
            if i > 0 and random.random() > 0.5:
                others = [p for p in self.state.alive_players if p.name != player.name]
                target = random.choice(others)
                statement = self._get_response(player, "accusation", target.name)
            else:
                statement = self._get_response(player, "discussion")

            message = Message(
                speaker=player.name,
                content=statement,
                round_num=self.state.current_round,
            )
            self.state.messages.append(message)
            self.log(f"\n{player.name}: {statement}")

    def _run_voting_phase(self) -> Optional[str]:
        self.state.current_phase = GamePhase.VOTING

        self.log("\n" + "-" * 40)
        self.log("VOTING PHASE - Who will be banished?")
        self.log("-" * 40)

        votes: dict[str, str] = {}
        alive_players = self.state.alive_players

        for player in alive_players:
            # Traitors try to vote for faithful, faithful vote somewhat randomly
            others = [p for p in alive_players if p.name != player.name]

            if player.is_traitor:
                # Traitors prefer to vote for faithful who are suspicious of them
                faithful_others = [p for p in others if not p.is_traitor]
                if faithful_others:
                    target = random.choice(faithful_others)
                else:
                    target = random.choice(others)
            else:
                target = random.choice(others)

            votes[player.name] = target.name

            vote = Vote(
                voter=player.name,
                target=target.name,
                round_num=self.state.current_round,
            )
            self.state.votes.append(vote)
            self.log(f"  {player.name} votes for: {target.name}")

        vote_counts = Counter(votes.values())
        max_votes = max(vote_counts.values())
        top_voted = [name for name, count in vote_counts.items() if count == max_votes]

        if len(top_voted) > 1:
            banished_name = random.choice(top_voted)
            self.log(f"\nTIE! Random selection from: {', '.join(top_voted)}")
        else:
            banished_name = top_voted[0]

        if banished_name in self.state.players:
            banished = self.state.players[banished_name]
            banished.status = PlayerStatus.BANISHED

            self.log(f"\n{'=' * 40}")
            self.log(f"BANISHED: {banished_name}")
            self.log(f"They were a: {banished.role.value.upper()}")
            self.log(f"{'=' * 40}")

            return banished_name

        return None

    def _run_night_phase(self) -> Optional[str]:
        self.state.current_phase = GamePhase.NIGHT

        alive_traitors = self.state.alive_traitors
        alive_faithful = self.state.alive_faithful

        if not alive_traitors or not alive_faithful:
            return None

        self.log("\n" + "-" * 40)
        self.log("NIGHT PHASE - Traitors meet in secret...")
        self.log("-" * 40)

        # Traitor discussion
        if len(alive_traitors) > 1:
            for traitor in alive_traitors:
                target = random.choice(alive_faithful)
                discussion = random.choice(TRAITOR_DISCUSSION).replace("{target}", target.name)

                message = Message(
                    speaker=traitor.name,
                    content=discussion,
                    round_num=self.state.current_round,
                    is_private=True,
                )
                self.state.messages.append(message)
                self.log(f"\n[TRAITOR] {traitor.name}: {discussion}")

        # Pick a victim
        victim = random.choice(alive_faithful)

        for traitor in alive_traitors:
            self.log(f"\n[MURDER VOTE] {traitor.name} votes to kill: {victim.name}")

        victim.status = PlayerStatus.MURDERED

        self.log(f"\n{'=' * 40}")
        self.log(f"MURDERED: {victim.name}")
        self.log("The faithful mourn their loss...")
        self.log(f"{'=' * 40}")

        return victim.name

    def run(self) -> dict:
        self.log("\n" + "=" * 60)
        self.log("THE TRAITORS - GAME SIMULATION")
        self.log("=" * 60)
        self.log(f"Players: {', '.join(self.state.players.keys())}")
        self.log(f"Rounds: {self.state.max_rounds}")

        self._assign_roles()

        while self.state.current_round <= self.state.max_rounds:
            self.log(f"\n{'#' * 60}")
            self.log(f"ROUND {self.state.current_round}")
            self.log(f"{'#' * 60}")
            self.log(f"Alive: {', '.join(p.name for p in self.state.alive_players)}")

            self._run_discussion_phase()
            self._run_voting_phase()

            winner = self._check_win_condition()
            if winner:
                self.state.winner = winner
                break

            if self.state.current_round < self.state.max_rounds:
                self._run_night_phase()

                winner = self._check_win_condition()
                if winner:
                    self.state.winner = winner
                    break

            self.state.current_round += 1

        self.state.current_phase = GamePhase.ENDED

        if not self.state.winner:
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
            "messages": self.state.messages,
            "votes": self.state.votes,
            "players": self.state.players,
        }

    def _print_final_results(self) -> None:
        self.log("\n" + "=" * 60)
        self.log("GAME OVER")
        self.log("=" * 60)

        self.log(f"\nWINNER: THE {self.state.winner.upper()}!")

        self.log("\nFinal Player Status:")
        for player in self.state.players.values():
            status = "SURVIVED" if player.is_alive else player.status.value.upper()
            role = player.role.value.upper()
            self.log(f"  {player.name}: {role} - {status}")

        self.log("\n" + "=" * 60)
