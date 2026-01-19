"""
Static prompt templates for The Traitors game.

All game rules and mechanics are defined here as templates with placeholders
that get filled in at runtime. This keeps all static content in one place
for easy maintenance and iteration.

Template placeholders use {placeholder_name} format for string interpolation.
"""

# =============================================================================
# GAME RULES - Comprehensive explanation of all mechanics
# =============================================================================

GAME_RULES = """THE TRAITORS - GAME RULES

OVERVIEW:
The Traitors is a social deduction game. Some players are secretly Traitors,
while others are Faithful. The Faithful must identify and banish all Traitors.
The Traitors must avoid detection while eliminating the Faithful.

SETUP:
- {num_traitors} player(s) are secretly assigned as Traitors
- {num_faithful} player(s) are Faithful
- Total of {total_players} players
- Prize pool: ${prize_pool:,}

REGULAR ROUNDS (1-{last_revealed_round}):
1. DISCUSSION PHASE
   - All players discuss openly (3 speaking turns each)
   - Anyone can accuse, defend, or share observations
   - Traitors must blend in and deflect suspicion
   - Say "PASS" if you have nothing to add

2. VOTING PHASE (BANISHMENT)
   - Each player votes to banish one other player
   - Player with most votes is banished (ties broken randomly)
   - Banished player's role is REVEALED to all

3. NIGHT PHASE (TRAITOR MEETING)
   - Traitors meet secretly (3 speaking turns each)
   - Discuss strategy and choose one Faithful to murder
   - Murdered player is eliminated (role revealed to all)

FINALE (Round {endgame_round}+):
The finale works differently - there are NO MORE MURDERS.

1. DISCUSSION PHASE - Same as regular rounds

2. VOTING PHASE (BANISHMENT)
   - Banished player's role is NOT revealed (uncertainty until game ends)

3. POUCH VOTE (END GAME vs BANISH AGAIN)
   - After each banishment, players vote on whether to end the game
   - END_GAME: Game ends immediately, prizes awarded based on who remains
   - BANISH_AGAIN: Continue to another vote (no night phase - traitors cannot murder)
   - This repeats until players vote to end or only 2 players remain

WIN CONDITIONS:
- FAITHFUL WIN: All Traitors have been banished
- TRAITORS WIN: Traitors equal or outnumber Faithful, OR game ends with Traitor(s) alive

PRIZE DISTRIBUTION:
- If Faithful win: Surviving Faithful split the ${prize_pool:,} equally
- If Traitors win: Surviving Traitors take ALL the money; Faithful get $0
"""

# =============================================================================
# ROLE-SPECIFIC INFORMATION
# =============================================================================

TRAITOR_ROLE_INFO = """YOUR SECRET ROLE: TRAITOR
Your fellow traitor(s) still alive: {other_traitors}
Your goal: MAXIMIZE YOUR EXPECTED PRIZE MONEY.
- If game ends with you alive: You split ${prize_pool:,} with fellow traitors (${traitor_share:,} each)
- If you're banished: You get $0
- Each night, traitors secretly murder one faithful player

CRITICAL RULE: NEVER reveal your role OR your fellow traitors' identities to the faithful. This is strictly forbidden.
"""

SOLO_TRAITOR_ROLE_INFO = """YOUR SECRET ROLE: TRAITOR (you are the last one)
Your goal: MAXIMIZE YOUR EXPECTED PRIZE MONEY.
- If game ends with you alive: You take the ENTIRE ${prize_pool:,}!
- If you're banished: You get $0
- Each night, you secretly murder one faithful player
"""

FAITHFUL_ROLE_INFO = """YOUR ROLE: FAITHFUL
Your goal: MAXIMIZE YOUR EXPECTED PRIZE MONEY.
- If ALL traitors eliminated when game ends: Surviving faithful split ${prize_pool:,} (~${faithful_share:,} each)
- If ANY traitor remains when game ends: Traitors steal EVERYTHING, you get $0
"""

# =============================================================================
# SYSTEM PROMPT TEMPLATES - Separated for prompt caching
# =============================================================================

# Static game rules - cached first (same for all players, all games)
SYSTEM_PROMPT_STATIC_RULES = """=== THE TRAITORS - GAME RULES ===

REGULAR ROUNDS:
1. DISCUSSION - All players discuss openly (3 speaking turns each), share suspicions
2. BANISHMENT VOTE - Vote to banish one player (most votes = banished, role REVEALED)
3. NIGHT - Traitors meet secretly (3 speaking turns each), then murder one faithful

FINALE (after role reveal stops):
1. DISCUSSION - Same as regular rounds
2. BANISHMENT VOTE - Role NOT revealed (uncertainty until game ends)
3. POUCH VOTE - Players vote END_GAME or BANISH_AGAIN
   - NO night phase in finale - traitors cannot murder
   - Repeats until players end the game or 2 players remain

WIN CONDITIONS:
- FAITHFUL WIN: All traitors are banished
- TRAITORS WIN: Traitors >= Faithful count, OR game ends with traitor(s) alive

PRIZE MONEY:
- Faithful win: Surviving faithful split the prize equally
- Traitors win: Surviving traitors take ALL money (faithful get $0)

BEHAVIOR:
- Vote only for living players
- Stay in character, keep responses to 1-3 sentences
- If traitor: NEVER reveal your role or fellow traitors' identities publicly
================="""

# Player identity template - cached per player (personality is stable)
SYSTEM_PROMPT_PLAYER_IDENTITY = """You are {player_name} in "The Traitors", a social deduction game.
Personality: {personality}"""

# Role information templates - cached per role type
SYSTEM_PROMPT_ROLE_TRAITOR = """YOUR SECRET ROLE: TRAITOR
Your fellow traitor(s) still alive: {other_traitors}
Your goal: MAXIMIZE YOUR EXPECTED PRIZE MONEY.
- If game ends with you alive: You split the prize with fellow traitors
- If you're banished: You get $0
- Each night, traitors secretly murder one faithful player

CRITICAL RULE: NEVER reveal your role OR your fellow traitors' identities to the faithful. This is strictly forbidden."""

SYSTEM_PROMPT_ROLE_SOLO_TRAITOR = """YOUR SECRET ROLE: TRAITOR (you are the last one)
Your goal: MAXIMIZE YOUR EXPECTED PRIZE MONEY.
- If game ends with you alive: You take the ENTIRE prize pool!
- If you're banished: You get $0
- Each night, you secretly murder one faithful player"""

SYSTEM_PROMPT_ROLE_FAITHFUL = """YOUR ROLE: FAITHFUL
Your goal: MAXIMIZE YOUR EXPECTED PRIZE MONEY.
- If ALL traitors eliminated when game ends: Surviving faithful split the prize
- If ANY traitor remains when game ends: Traitors steal EVERYTHING, you get $0"""

# Dynamic game state template - changes each round, NOT cached
SYSTEM_PROMPT_DYNAMIC_STATE = """
GAME SETUP: {num_traitors} traitors hidden among {total_players} players. Prize pool: ${prize_pool:,}
Role reveal rule: Rounds 1-{last_revealed_round} reveal roles, Round {endgame_round}+ (ENDGAME) does not

CURRENT STATE (Round {current_round}):
Players alive: {alive_players}
Eliminated:
  {eliminated_str}
{endgame_status}"""

# =============================================================================
# PLAYER CONTEXT TEMPLATE - Goes AFTER cached history in user message
# =============================================================================

# This template is used to inject player-specific information into the user message
# AFTER the cached history block, enabling cache sharing across all players.
PLAYER_CONTEXT_TEMPLATE = """=== YOUR IDENTITY ===
You are {player_name}.
Personality: {personality}

{role_info}

=== CURRENT GAME STATE ===
{game_state}"""

# Legacy template for backwards compatibility
SYSTEM_PROMPT_TEMPLATE = """You are {player_name} in "The Traitors", a social deduction game.
Personality: {personality}

=== GAME RULES ===
SETUP: {num_traitors} traitors hidden among {total_players} players. Prize pool: $10,000.

REGULAR ROUNDS (1-{last_revealed_round}):
1. DISCUSSION - All players discuss openly, share suspicions
2. BANISHMENT VOTE - Vote to banish one player (most votes = banished, role REVEALED)
3. NIGHT - Traitors secretly murder one faithful

FINALE (Round {endgame_round}+):
1. DISCUSSION - Same as regular rounds
2. BANISHMENT VOTE - Role NOT revealed (uncertainty until game ends)
3. POUCH VOTE - Players vote END_GAME or BANISH_AGAIN
   - NO night phase in finale - traitors cannot murder
   - Repeats until players end game or 2 players remain

WIN CONDITIONS:
- FAITHFUL WIN: All traitors are banished
- TRAITORS WIN: Traitors >= Faithful count, OR game ends with traitor(s) alive

PRIZE MONEY:
- Faithful win: Surviving faithful split the prize equally
- Traitors win: Surviving traitors take ALL money (faithful get $0)
=================

{role_info}

CURRENT STATE (Round {current_round}):
Players alive: {alive_players}
Eliminated:
  {eliminated_str}
{endgame_status}

BEHAVIOR:
- Vote only for living players
- Stay in character, keep responses to 1-3 sentences
- If traitor: NEVER reveal your role or fellow traitors' identities publicly
"""

# =============================================================================
# ACTION PROMPTS - Specific prompts for each action type
# =============================================================================

DISCUSSION_PROMPT = """{round_context}DISCUSSION HISTORY:
{history}

ROUND {current_round} - PUBLIC DISCUSSION
Players in the game: {alive_names}

Your turn to speak. {instruction}
Respond with your statement only (1-3 sentences, in character)."""

PRIVATE_THOUGHTS_PROMPT = """{round_context}DISCUSSION HISTORY:
{history}

PRIVATE THOUGHTS - Who do you suspect most?
Players: {voteable}

(1 sentence max)"""

VOTE_PROMPT = """DISCUSSION HISTORY:
{history}

VOTING TIME - You must vote to banish ONE player.
Eligible players (still alive): {voteable}

Based on the discussion and your strategy, who do you vote to banish?

Format your response EXACTLY like this:
<vote>[Player name]</vote>
<thoughts>[Brief: why you're voting for them]</thoughts>"""

MURDER_VOTE_PROMPT = """DISCUSSION HISTORY:
{history}

TRAITOR NIGHT PHASE - Choose a faithful player to murder tonight.
Available targets: {targets}

Who do you vote to murder?

Format your response EXACTLY like this:
<vote>[Player name]</vote>
<thoughts>[Brief: why this target is the best choice]</thoughts>"""

TRAITOR_DISCUSSION_PROMPT = """{round_context}DISCUSSION HISTORY:
{history}

=== SECRET TRAITOR MEETING (NIGHT PHASE) ===
This is a PRIVATE discussion. Only traitors can see this.
The faithful are asleep and cannot hear you.

{other_traitor_text}
Potential murder targets: {targets}
Turn: {turn_number} of {max_turns}

Discuss strategy: who to murder, how to deflect suspicion tomorrow.

Format your response EXACTLY like this:
<statement>[Your discussion contribution (2-3 sentences)]</statement>
<thoughts>[Brief: your true strategic thinking]</thoughts>"""

END_GAME_VOTE_PROMPT = """{round_context}DISCUSSION HISTORY:
{history}

END GAME VOTE - Should the game end now?
PRIZE POOL: ${prize_pool:,}
Players remaining: {alive_count}
Traitors revealed (banished): {revealed_traitors}
Faithful wrongly banished: {revealed_faithful}

OUTCOMES:
- END + traitors remain = Traitors take ${prize_pool:,}, faithful get $0
- END + all traitors caught = Faithful split ${prize_pool:,} (${faithful_share:,} each)
- CONTINUE = Game continues, traitors murder one faithful tonight

Maximize your expected prize money. Vote END or CONTINUE.
Respond with only END or CONTINUE."""

# =============================================================================
# COMBINED DISCUSSION - Public statement + private thoughts in one response
# =============================================================================

COMBINED_DISCUSSION_PROMPT = """{round_context}DISCUSSION HISTORY:
{history}

ROUND {current_round} - PUBLIC DISCUSSION
Players: {alive_names}
Turn: {turn_number} of {max_turns}

{instruction}

If you have nothing new to add, respond with PASS as your statement.

Format your response EXACTLY like this:
<statement>[Your public statement OR "PASS"]</statement>
<thoughts>[Brief: who you suspect and why]</thoughts>"""

