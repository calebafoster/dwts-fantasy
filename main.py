import argparse
from functions import *
from werkzeug.security import generate_password_hash

parser = argparse.ArgumentParser(description="DWTS Fantasy admin CLI")
subparsers = parser.add_subparsers(dest="command")

subparsers.add_parser("overview", aliases=["o"], help="Print db overview")
subparsers.add_parser("init-db", help="Create tables if they don't exist")
subparsers.add_parser("start-week", help="Start week 1 if no weeks exist yet")

p = subparsers.add_parser("add-player", help="Create a player account")
p.add_argument("name")
p.add_argument("password")
p.add_argument("--admin", action="store_true")

rp = subparsers.add_parser("reset-password", help="Clear a player's password; they set a new one on next login")
rp.add_argument("name")

c = subparsers.add_parser("add-contestant", aliases=["c"], help="Add a contestant")
c.add_argument("name")
c.add_argument("--partner", default=None)

sp = subparsers.add_parser("set-points", help="Set a contestant's points for the active week")
sp.add_argument("contestant_id", type=int)
sp.add_argument("points", type=float)

el = subparsers.add_parser("eliminate", help="Eliminate a contestant")
el.add_argument("contestant_id", type=int)
el.add_argument("--final-place", type=int, default=None)

fw = subparsers.add_parser("finalize-week", help="Score and close out the active week")
fw.add_argument("highest_id", type=int)
fw.add_argument("loser_ids", type=int, nargs="+")
fw.add_argument("--double-elimination", action="store_true")

subparsers.add_parser("finish-season", help="Apply season-end placement bonuses")

args = parser.parse_args()

if args.command in ("overview", "o", None):
    overview()
elif args.command == "init-db":
    init_db()
elif args.command == "start-week":
    start_first_week()
elif args.command == "add-player":
    conn = get_conn()
    conn.execute(
        "INSERT INTO players (name, password_hash, is_admin) VALUES (?, ?, ?)",
        (args.name, generate_password_hash(args.password), int(args.admin)),
    )
    conn.commit()
    conn.close()
elif args.command == "reset-password":
    success, error = clear_password(args.name)
    print(error if error else f'Password cleared for "{args.name}". They\'ll set a new one on next login.')
elif args.command in ("add-contestant", "c"):
    add_contestant(args.name, args.partner)
elif args.command == "set-points":
    set_contestant_points_this_week(args.contestant_id, args.points)
elif args.command == "eliminate":
    triggered = eliminate_contestant(args.contestant_id, args.final_place)
    if triggered:
        print("Reserve pool is empty — full-roster players must drop one contestant.")
elif args.command == "finalize-week":
    finalize_week(args.highest_id, args.loser_ids, args.double_elimination)
elif args.command == "finish-season":
    finish_season()
