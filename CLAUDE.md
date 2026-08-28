# Overview
This is an app that will be hosted on my orangepi homeserver, where users will log in and predict the winners of Dancing with the Stars nights, accumulate points based on picks they've drafted, and predict the loser for the night as well.
This project is going to be a python backend, utilizing a number of libraries:
    - Flask
    - sqlite
    - more as they come up

# Admin
The admin will need to have a different user account where they can input the data, and change user data as needed, and progress the week count.

# Users
Users will need a number of buttons and fields where they can make their weekly guesses, as well as pick new draft picks as needed.
Users will need to create a log in if their name is not present in the list on first time log in.
Passwords must be stored hashed (e.g. werkzeug's `generate_password_hash`), never in plaintext.

The initial draft itself happens outside the app (e.g. everyone picking live together). The app doesn't run or referee that draft — on a player's first log in, they simply select their two already-agreed-upon contestants from the roster themselves. This is honor system for this year: the app only stops a contestant from being claimed twice (data integrity), it doesn't enforce draft order, turns, or eligibility beyond that.

# Scoring Rules
- **Weekly base points**: each week, a player earns points equal to the sum of the points their two drafted contestants scored that week.
- **Prediction bonuses**: if the player's "highest scorer" prediction for the week is correct, add 0.2 to that week's multiplier. If the player's "loser" prediction for the week is correct, add another 0.2. These stack additively, so a player who gets both right that week scores at a 1.4x multiplier; one right is 1.2x; neither is 1.0x. This is true on double-elimination weeks too — a player still submits exactly one highest-scorer prediction and one loser prediction, regardless of how many contestants actually go home that week.
- **Weekly points total** = base points × that week's multiplier. This feeds `mult this week` / `points this week` on the Players table and accumulates into the player's season total.
- **Redrafting**: when a player's drafted contestant is eliminated, the player picks a new contestant to fill the empty slot. Weekly base points are always computed from whichever contestant the player held *that particular week* (see `DraftHistory` below), not their current pick.
- **Redraft cost**: filling an empty slot (exchanging or adding a contestant after the initial draft) isn't free — the player must "purchase" the new contestant for a number of points equal to the lowest individual contestant score from the most recently completed week. That cost is deducted directly from the player's season point total at the time of the redraft. The initial season-opening draft is free (there's no prior week's score to price it against).
- **Season-end placement bonus**: once the season ends and every contestant has a `final place`, for each of a player's drafted contestants (current holdings only — a contestant that reaches the finale was never eliminated, so this only ever applies to a player's final two picks) that finished in the top 3, add a bonus on top of a base of 1.0: 1st place +0.75, 2nd place +0.5, 3rd place +0.25. These bonuses add together (e.g. drafting both the 1st and 3rd place finishers gives a 1 + 0.75 + 0.25 = 2.0x factor). Multiply the player's full season point total by this combined factor exactly once, at the end of the season.
- **Reserve pool exhaustion (forced drop)**: every player starts with a roster of 2 slots (`roster_size`). Whenever an elimination leaves the reserve pool (unclaimed, non-eliminated contestants) at zero, every player currently holding 2 contestants is flagged `pending_forced_drop` and must choose one of their two contestants to release back to the pool for free before doing anything else in the app. Releasing a contestant this way permanently caps that player's `roster_size` at 1 for the rest of the season — there's no immediate refill/redraft as part of this action. This exists to keep the game playable as the pool of active contestants naturally shrinks toward the end of the season.
- **Zero-points prediction fallback**: on a week where a player's normal base points (sum of their currently-held contestants' points that week) come out to exactly 0 — whether from an empty roster or a held contestant scoring 0 — and the player got *both* the highest-scorer and loser predictions correct that week, they're credited flat points equal to that week's lowest individual contestant score, with no multiplier applied (i.e. this bypasses the normal 1.0/1.2/1.4x prediction-bonus multiplier entirely). Getting only one of the two predictions right does not trigger this fallback — the player still scores 0 for the week in that case.

# Database
Players table:
    - id (primary key)
    - name
    - password_hash
    - is_admin (bool)
    - season points (cumulative total across the season, before the season-end placement bonus is applied)
    - points this week
    - mult this week (this week's multiplier: 1.0 base, +0.2 per correct prediction — see Scoring Rules)
    - submitted for this week (bool)
    - roster size (int, default 2 — how many contestant slots this player has; drops to 1 permanently after a forced drop, see Scoring Rules)
    - pending forced drop (bool — set when the reserve pool hits zero while this player holds 2 contestants; blocks all other actions until they resolve it)

Contestants table:
    - id (primary key)
    - name
    - partner
    - claimant (FK -> Players.id, nullable — the player currently holding this contestant's draft slot)
    - eliminated (bool)
    - points this week
    - points lifetime
    - final place (nullable until the season ends)

DraftHistory table:
    - id (primary key)
    - player_id (FK -> Players)
    - contestant_id (FK -> Contestants)
    - week assigned
    - week ended (nullable while the assignment is still active)
    - purchase cost (points deducted for this assignment; 0 for the initial season-opening draft, otherwise the lowest individual contestant score from the most recently completed week — see Scoring Rules)
    - Records every draft/redraft so weekly scoring can always tell which contestant a player held during any given past week.

Predictions table:
    - id (primary key)
    - player_id (FK -> Players)
    - week number
    - predicted highest-scorer contestant_id (FK -> Contestants)
    - predicted loser contestant_id (FK -> Contestants)
    - highest correct (bool, set once the week is finalized)
    - loser correct (bool, set once the week is finalized)
    - One row per player per week.

Weeks table:
    - week number (primary key)
    - finalized (bool)
    - double elimination (bool)
    - participating contestants (JSON list of contestant ids dancing that week)
    - highest contestant_id (FK -> Contestants — the actual highest scorer, entered by admin)
    - loser contestant_ids (JSON list of contestant ids — normally one entry, two on a double-elimination week)

WeeklyResults table:
    - id (primary key)
    - week number
    - player_id (FK -> Players)
    - base points (sum of that week's drafted-contestant points, pre-multiplier)
    - multiplier applied
    - points total (base points × multiplier applied)
    - cumulative points (running season total through this week, pre season-end bonus)
    - History table that the Standings page reads from, since Players/Contestants only ever hold "this week" snapshot values.

WeeklyContestantResults table:
    - id (primary key)
    - week number
    - contestant_id (FK -> Contestants)
    - points (that contestant's score for that specific week)
    - History table needed for two things: (1) computing a player's base points for a past week from whichever contestant they held that week, and (2) pricing redrafts off "the lowest individual contestant score from the most recently completed week" (see Scoring Rules) — `Contestants.points this week` alone gets overwritten every week and can't answer either question.

Event log table:
    - event name
    - time and date

# Standings Page
There should be a standings page, displaying the week by week standings, backed by the WeeklyResults table.

# Running the app
Dependencies live in `.venv` (created by `setup.py`), not system Python — always invoke through the venv:
```bash
.venv/bin/python app.py            # dev server on :9902
.venv/bin/python main.py --help    # admin CLI, list all commands
.venv/bin/python main.py <cmd> --help  # help for a specific command
```
Or run `source .venv/bin/activate` once per shell session and drop the `.venv/bin/` prefix.

# Project Structure
Modeled after ~/Projects/budget-app: flat structure, no ORM, no migrations.
    - `app.py` — Flask app and routes. Routes are thin: pull form/session data, call a `functions.py` function, flash a message, redirect. Auth uses `session["player_id"]`, checked in a `before_request` hook (login/signup exempt). Admin-only routes additionally check `players.is_admin`.
    - `functions.py` — all business logic and schema. Every function opens its own `sqlite3.connect(DB_PATH)` (row_factory = sqlite3.Row), does its work, commits, closes. `init_db()` creates all tables (`CREATE TABLE IF NOT EXISTS`) directly from a schema string — schema changes are made by editing that string and/or ad-hoc migration scripts, same as budget-app.
    - `main.py` — argparse CLI that imports from `functions.py`, giving the admin command-line access to the same logic the web app uses (creating the admin account, entering weekly scores, finalizing a week, etc.) without needing the browser.
    - `templates/` — `login.html` (combined login/first-time-signup form), `index.html` (a player's roster, draft/redraft controls, this week's prediction form), `forced_drop.html` (shown instead of `index.html` when a player has a pending forced drop — see Scoring Rules), `standings.html` (week-by-week standings from `WeeklyResults`), `admin.html` (add contestants, enter weekly points, finalize the week, season-end bonus).
    - `requirements.txt` — `flask`, `gunicorn`.
    - `setup.py` — one-time deploy bootstrap for a new machine (e.g. the orangepi): creates `.venv`, installs `requirements.txt`, calls `init_db()`/`start_first_week()`, and prompts to create the admin account if one doesn't exist yet. Safe to re-run.
    - `deploy/dwts-fantasy.service` — systemd unit that runs gunicorn (from `.venv`) bound to `127.0.0.1:9902`, install with `systemctl enable --now dwts-fantasy`.
    - `deploy/dwts-fantasy.nginx.conf` — nginx server block that reverse-proxies to that gunicorn address; nginx/systemd front the app in production, `app.py`'s own dev server is local-only.
    - `dwts.db` — SQLite database file (gitignored, created by `init_db()`).
