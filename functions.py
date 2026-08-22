import os
import sqlite3
import json
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.environ.get("DB_PATH", "dwts.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    season_points REAL NOT NULL DEFAULT 0,
    points_this_week REAL NOT NULL DEFAULT 0,
    mult_this_week REAL NOT NULL DEFAULT 1.0,
    submitted_this_week INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contestants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    partner TEXT,
    claimant INTEGER REFERENCES players(id),
    eliminated INTEGER NOT NULL DEFAULT 0,
    points_this_week REAL NOT NULL DEFAULT 0,
    points_lifetime REAL NOT NULL DEFAULT 0,
    final_place INTEGER
);

CREATE TABLE IF NOT EXISTS draft_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    contestant_id INTEGER NOT NULL REFERENCES contestants(id),
    week_assigned INTEGER NOT NULL,
    week_ended INTEGER,
    purchase_cost REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    week_number INTEGER NOT NULL,
    predicted_highest_id INTEGER REFERENCES contestants(id),
    predicted_loser_id INTEGER REFERENCES contestants(id),
    highest_correct INTEGER,
    loser_correct INTEGER,
    UNIQUE(player_id, week_number)
);

CREATE TABLE IF NOT EXISTS weeks (
    week_number INTEGER PRIMARY KEY,
    finalized INTEGER NOT NULL DEFAULT 0,
    double_elimination INTEGER NOT NULL DEFAULT 0,
    participating_contestants TEXT,
    highest_contestant_id INTEGER REFERENCES contestants(id),
    loser_contestant_ids TEXT
);

CREATE TABLE IF NOT EXISTS weekly_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_number INTEGER NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    base_points REAL NOT NULL,
    multiplier_applied REAL NOT NULL,
    points_total REAL NOT NULL,
    cumulative_points REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_contestant_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_number INTEGER NOT NULL,
    contestant_id INTEGER NOT NULL REFERENCES contestants(id),
    points REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,
    event_time TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PLACEMENT_BONUS = {1: 0.75, 2: 0.5, 3: 0.25}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def log_event(conn, event_name):
    conn.execute("INSERT INTO event_log (event_name) VALUES (?)", (event_name,))


def get_active_week_number(conn):
    row = conn.execute("SELECT MIN(week_number) FROM weeks WHERE finalized = 0").fetchone()
    return row[0] if row and row[0] is not None else None


def get_current_week():
    conn = get_conn()
    week_number = get_active_week_number(conn)
    conn.close()
    return week_number


def get_active_contestants():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM contestants WHERE eliminated = 0 ORDER BY name"
    ).fetchall()
    conn.close()
    return rows


def get_all_contestants():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT contestants.*, players.name AS claimant_name
        FROM contestants LEFT JOIN players ON contestants.claimant = players.id
        ORDER BY contestants.name
        """
    ).fetchall()
    conn.close()
    return rows


def get_prediction(player_id, week_number):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM predictions WHERE player_id = ? AND week_number = ?",
        (player_id, week_number),
    ).fetchone()
    conn.close()
    return row


# ---------- auth ----------

def login_or_create(name, password):
    """Returns (player_row, error). Creates a new player if the name doesn't exist yet.
    A player whose password was cleared by an admin (password_hash == "") sets a new
    password on their next login, same as a brand-new account."""
    conn = get_conn()
    player = conn.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()
    if player is None:
        conn.execute(
            "INSERT INTO players (name, password_hash) VALUES (?, ?)",
            (name, generate_password_hash(password)),
        )
        log_event(conn, f'New player "{name}" created')
        conn.commit()
        player = conn.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()
        conn.close()
        return player, None

    if player["password_hash"] == "":
        conn.execute(
            "UPDATE players SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), player["id"]),
        )
        log_event(conn, f'Password set for "{name}" after admin reset')
        conn.commit()
        player = conn.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
        conn.close()
        return player, None

    if check_password_hash(player["password_hash"], password):
        conn.close()
        return player, None

    conn.close()
    return None, "Wrong password."


def clear_password(name):
    """Returns (success, error). Admin-driven recovery: clears the stored hash so the
    player sets a brand-new password on their next login attempt."""
    conn = get_conn()
    player = conn.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()
    if player is None:
        conn.close()
        return False, f'No player named "{name}".'

    conn.execute("UPDATE players SET password_hash = ? WHERE id = ?", ("", player["id"]))
    log_event(conn, f'Password cleared for "{name}" by admin')
    conn.commit()
    conn.close()
    return True, None


def get_player(player_id):
    conn = get_conn()
    player = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    conn.close()
    return player


# ---------- drafting ----------

def get_unclaimed_contestants():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM contestants WHERE claimant IS NULL AND eliminated = 0 ORDER BY name"
    ).fetchall()
    conn.close()
    return rows


def get_roster(player_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM contestants WHERE claimant = ? ORDER BY name", (player_id,)
    ).fetchall()
    conn.close()
    return rows


def get_redraft_cost(conn):
    row = conn.execute(
        """
        SELECT points FROM weekly_contestant_results
        WHERE week_number = (SELECT MAX(week_number) FROM weekly_contestant_results)
        ORDER BY points ASC LIMIT 1
        """
    ).fetchone()
    return row["points"] if row else 0.0


def draft_contestant(player_id, contestant_id):
    """Fills an empty roster slot. A player's first two picks ever are free;
    every pick after that is priced at the lowest contestant score from the
    most recently completed week. Returns the cost charged."""
    conn = get_conn()
    contestant = conn.execute("SELECT * FROM contestants WHERE id = ?", (contestant_id,)).fetchone()
    if contestant is None:
        conn.close()
        raise ValueError("Contestant not found.")
    if contestant["claimant"] is not None:
        conn.close()
        raise ValueError("That contestant has already been drafted.")

    roster_count = conn.execute(
        "SELECT COUNT(*) FROM contestants WHERE claimant = ?", (player_id,)
    ).fetchone()[0]
    if roster_count >= 2:
        conn.close()
        raise ValueError("You already have two drafted contestants.")

    picks_so_far = conn.execute(
        "SELECT COUNT(*) FROM draft_history WHERE player_id = ?", (player_id,)
    ).fetchone()[0]
    is_initial_pick = picks_so_far < 2
    cost = 0.0 if is_initial_pick else get_redraft_cost(conn)

    current_week = get_active_week_number(conn) or 1

    conn.execute("UPDATE contestants SET claimant = ? WHERE id = ?", (player_id, contestant_id))
    conn.execute(
        """
        INSERT INTO draft_history (player_id, contestant_id, week_assigned, purchase_cost)
        VALUES (?, ?, ?, ?)
        """,
        (player_id, contestant_id, current_week, cost),
    )
    if cost:
        conn.execute(
            "UPDATE players SET season_points = season_points - ? WHERE id = ?", (cost, player_id)
        )
    log_event(conn, f'Player {player_id} drafted contestant {contestant_id} for {cost} points')
    conn.commit()
    conn.close()
    return cost


# ---------- predictions ----------

def submit_prediction(player_id, week_number, highest_id, loser_id):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO predictions (player_id, week_number, predicted_highest_id, predicted_loser_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id, week_number) DO UPDATE SET
            predicted_highest_id = excluded.predicted_highest_id,
            predicted_loser_id = excluded.predicted_loser_id
        """,
        (player_id, week_number, highest_id, loser_id),
    )
    conn.execute("UPDATE players SET submitted_this_week = 1 WHERE id = ?", (player_id,))
    conn.commit()
    conn.close()


# ---------- admin: contestants ----------

def add_contestant(name, partner=None):
    conn = get_conn()
    conn.execute("INSERT INTO contestants (name, partner) VALUES (?, ?)", (name, partner))
    log_event(conn, f'Contestant "{name}" added')
    conn.commit()
    conn.close()


def set_contestant_points_this_week(contestant_id, points):
    conn = get_conn()
    conn.execute(
        "UPDATE contestants SET points_this_week = ?, points_lifetime = points_lifetime + ? WHERE id = ?",
        (points, points, contestant_id),
    )
    conn.commit()
    conn.close()


def set_final_place(contestant_id, final_place):
    """Records a contestant's final standing without touching `eliminated` or
    `claimant` — used for the top finishers at the finale, who were never
    eliminated and must stay claimed so the season-end bonus can find them."""
    conn = get_conn()
    conn.execute("UPDATE contestants SET final_place = ? WHERE id = ?", (final_place, contestant_id))
    log_event(conn, f"Contestant {contestant_id} placed {final_place}")
    conn.commit()
    conn.close()


def eliminate_contestant(contestant_id, final_place=None):
    conn = get_conn()
    current_week = get_active_week_number(conn) or 1
    conn.execute(
        "UPDATE contestants SET eliminated = 1, final_place = ? WHERE id = ?",
        (final_place, contestant_id),
    )
    conn.execute(
        "UPDATE draft_history SET week_ended = ? WHERE contestant_id = ? AND week_ended IS NULL",
        (current_week, contestant_id),
    )
    conn.execute("UPDATE contestants SET claimant = NULL WHERE id = ?", (contestant_id,))
    log_event(conn, f"Contestant {contestant_id} eliminated")
    conn.commit()
    conn.close()


# ---------- admin: weeks ----------

def start_first_week():
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) FROM weeks").fetchone()
    if row[0] == 0:
        conn.execute("INSERT INTO weeks (week_number, finalized, double_elimination) VALUES (1, 0, 0)")
        log_event(conn, "Week 1 started")
        conn.commit()
    conn.close()


def finalize_week(highest_contestant_id, loser_contestant_ids, double_elimination=False):
    """Scores the active week from each contestant's current `points_this_week`,
    applies prediction multipliers, updates season totals, and opens the next week."""
    conn = get_conn()
    week_number = get_active_week_number(conn)
    if week_number is None:
        conn.close()
        raise ValueError("No active week to finalize.")

    conn.execute(
        """
        UPDATE weeks SET highest_contestant_id = ?, loser_contestant_ids = ?, double_elimination = ?
        WHERE week_number = ?
        """,
        (highest_contestant_id, json.dumps(loser_contestant_ids), int(double_elimination), week_number),
    )

    contestants = conn.execute("SELECT id, points_this_week FROM contestants").fetchall()
    for c in contestants:
        conn.execute(
            "INSERT INTO weekly_contestant_results (week_number, contestant_id, points) VALUES (?, ?, ?)",
            (week_number, c["id"], c["points_this_week"]),
        )

    players = conn.execute("SELECT * FROM players").fetchall()
    for p in players:
        roster = conn.execute(
            "SELECT points_this_week FROM contestants WHERE claimant = ?", (p["id"],)
        ).fetchall()
        base_points = sum(r["points_this_week"] for r in roster)

        pred = conn.execute(
            "SELECT * FROM predictions WHERE player_id = ? AND week_number = ?",
            (p["id"], week_number),
        ).fetchone()

        multiplier = 1.0
        if pred:
            highest_correct = int(pred["predicted_highest_id"] == highest_contestant_id)
            loser_correct = int(pred["predicted_loser_id"] in loser_contestant_ids)
            multiplier += 0.2 * highest_correct + 0.2 * loser_correct
            conn.execute(
                "UPDATE predictions SET highest_correct = ?, loser_correct = ? WHERE id = ?",
                (highest_correct, loser_correct, pred["id"]),
            )

        points_total = base_points * multiplier
        new_season_points = p["season_points"] + points_total

        conn.execute(
            """
            UPDATE players SET points_this_week = ?, mult_this_week = ?, season_points = ?,
                submitted_this_week = 0
            WHERE id = ?
            """,
            (points_total, multiplier, new_season_points, p["id"]),
        )
        conn.execute(
            """
            INSERT INTO weekly_results
                (week_number, player_id, base_points, multiplier_applied, points_total, cumulative_points)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (week_number, p["id"], base_points, multiplier, points_total, new_season_points),
        )

    conn.execute("UPDATE contestants SET points_this_week = 0")
    conn.execute("UPDATE weeks SET finalized = 1 WHERE week_number = ?", (week_number,))
    conn.execute(
        "INSERT INTO weeks (week_number, finalized, double_elimination) VALUES (?, 0, 0)",
        (week_number + 1,),
    )
    log_event(conn, f"Week {week_number} finalized")
    conn.commit()
    conn.close()


def finish_season():
    """Applies the one-time season-end top-3 placement bonus to each player's season total."""
    conn = get_conn()
    players = conn.execute("SELECT * FROM players").fetchall()
    for p in players:
        roster = conn.execute(
            "SELECT final_place FROM contestants WHERE claimant = ?", (p["id"],)
        ).fetchall()
        bonus = sum(PLACEMENT_BONUS.get(r["final_place"], 0.0) for r in roster)
        factor = 1.0 + bonus
        if factor != 1.0:
            new_total = p["season_points"] * factor
            conn.execute("UPDATE players SET season_points = ? WHERE id = ?", (new_total, p["id"]))
    log_event(conn, "Season-end placement bonuses applied")
    conn.commit()
    conn.close()


# ---------- standings ----------

def get_standings():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT wr.week_number, p.name, wr.points_total, wr.cumulative_points
        FROM weekly_results wr
        JOIN players p ON wr.player_id = p.id
        ORDER BY wr.week_number, wr.cumulative_points DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_leaderboard():
    conn = get_conn()
    rows = conn.execute(
        "SELECT name, season_points FROM players ORDER BY season_points DESC"
    ).fetchall()
    conn.close()
    return rows


def overview():
    conn = get_conn()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'sqlite_sequence'"
    ).fetchall()
    for (table,) in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        print(f"{table} ({count} rows): {', '.join(cols)}")
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():
            print(f"  {tuple(row)}")
        print()
    conn.close()
