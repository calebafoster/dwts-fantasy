from flask import Flask, render_template, request, redirect, url_for, flash, session
from functions import (
    init_db, login_or_create, get_player, get_unclaimed_contestants, get_roster,
    draft_contestant, submit_prediction, get_current_week, get_active_contestants,
    get_all_contestants, get_prediction, add_contestant, set_contestant_points_this_week,
    eliminate_contestant, set_final_place, start_first_week, finalize_week, finish_season,
    get_standings, get_leaderboard,
)

app = Flask(__name__)
app.secret_key = "dwts-fantasy-secret-key"

init_db()
start_first_week()


@app.before_request
def require_login():
    if request.endpoint not in ("login",) and not session.get("player_id"):
        return redirect(url_for("login"))


def current_player():
    return get_player(session["player_id"])


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form["name"].strip()
        password = request.form["password"]
        player, error = login_or_create(name, password)
        if error:
            return render_template("login.html", error=error)
        session["player_id"] = player["id"]
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    player = current_player()
    roster = get_roster(player["id"])
    week_number = get_current_week()
    prediction = get_prediction(player["id"], week_number) if week_number else None
    return render_template(
        "index.html",
        player=player,
        roster=roster,
        unclaimed=get_unclaimed_contestants(),
        active_contestants=get_active_contestants(),
        week_number=week_number,
        prediction=prediction,
        leaderboard=get_leaderboard(),
    )


@app.route("/draft", methods=["POST"])
def draft_route():
    contestant_id = int(request.form["contestant_id"])
    try:
        cost = draft_contestant(session["player_id"], contestant_id)
        if cost:
            flash(f"Drafted for {cost:.1f} points.")
        else:
            flash("Drafted.")
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("index"))


@app.route("/predict", methods=["POST"])
def predict_route():
    week_number = get_current_week()
    highest_id = int(request.form["highest_id"])
    loser_id = int(request.form["loser_id"])
    submit_prediction(session["player_id"], week_number, highest_id, loser_id)
    flash("Prediction submitted.")
    return redirect(url_for("index"))


@app.route("/standings")
def standings():
    return render_template("standings.html", standings=get_standings(), leaderboard=get_leaderboard())


def require_admin():
    if not current_player()["is_admin"]:
        return redirect(url_for("index"))


@app.route("/admin")
def admin():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response
    return render_template(
        "admin.html",
        week_number=get_current_week(),
        contestants=get_all_contestants(),
    )


@app.route("/admin/add-contestant", methods=["POST"])
def admin_add_contestant():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response
    add_contestant(request.form["name"].strip(), request.form.get("partner", "").strip() or None)
    flash("Contestant added.")
    return redirect(url_for("admin"))


@app.route("/admin/set-points", methods=["POST"])
def admin_set_points():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response
    contestant_id = int(request.form["contestant_id"])
    points = float(request.form["points"])
    set_contestant_points_this_week(contestant_id, points)
    flash("Points set.")
    return redirect(url_for("admin"))


@app.route("/admin/eliminate", methods=["POST"])
def admin_eliminate():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response
    contestant_id = int(request.form["contestant_id"])
    eliminate_contestant(contestant_id)
    flash("Contestant eliminated.")
    return redirect(url_for("admin"))


@app.route("/admin/set-final-place", methods=["POST"])
def admin_set_final_place():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response
    contestant_id = int(request.form["contestant_id"])
    final_place = int(request.form["final_place"])
    set_final_place(contestant_id, final_place)
    flash("Final place recorded.")
    return redirect(url_for("admin"))


@app.route("/admin/finalize-week", methods=["POST"])
def admin_finalize_week():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response
    highest_id = int(request.form["highest_id"])
    loser_ids = [int(x) for x in request.form.getlist("loser_ids")]
    double_elimination = bool(request.form.get("double_elimination"))
    try:
        finalize_week(highest_id, loser_ids, double_elimination)
        flash("Week finalized.")
    except ValueError as e:
        flash(str(e))
    return redirect(url_for("admin"))


@app.route("/admin/finish-season", methods=["POST"])
def admin_finish_season():
    redirect_response = require_admin()
    if redirect_response:
        return redirect_response
    finish_season()
    flash("Season-end bonuses applied.")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9902, debug=True)
