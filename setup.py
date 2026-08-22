#!/usr/bin/env python3
"""One-time setup for deploying DWTS Fantasy to a new machine (e.g. the orangepi).

Creates a virtualenv, installs dependencies, initializes the database, and
creates the admin account. Safe to re-run: skips steps that are already done.
"""
import getpass
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(ROOT, ".venv")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python")
VENV_GUNICORN = os.path.join(VENV_DIR, "bin", "gunicorn")


def run(cmd, **kwargs):
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def ensure_venv():
    if not os.path.exists(VENV_PYTHON):
        run([sys.executable, "-m", "venv", VENV_DIR])
    run([VENV_PYTHON, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    run([VENV_PYTHON, "-m", "pip", "install", "-q", "-r", os.path.join(ROOT, "requirements.txt")])


def init_database():
    run(
        [VENV_PYTHON, "-c", "from functions import init_db, start_first_week; init_db(); start_first_week()"],
        cwd=ROOT,
    )


def ensure_admin():
    check = subprocess.run(
        [
            VENV_PYTHON, "-c",
            "from functions import get_conn; "
            "c = get_conn(); "
            "print(c.execute('SELECT COUNT(*) FROM players WHERE is_admin = 1').fetchone()[0])",
        ],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    if int(check.stdout.strip()) > 0:
        print("Admin account already exists, skipping.")
        return

    print("\nNo admin account found yet -- let's create one.")
    name = input("Admin name: ").strip()
    password = getpass.getpass("Admin password: ")
    run([VENV_PYTHON, "main.py", "add-player", name, password, "--admin"], cwd=ROOT)


def main():
    ensure_venv()
    init_database()
    ensure_admin()
    print("\nSetup complete. Run the app with:")
    print(f"  {VENV_PYTHON} app.py")
    print("or, for production, via gunicorn, e.g.:")
    print(f"  {VENV_GUNICORN} -b 0.0.0.0:9902 app:app")


if __name__ == "__main__":
    main()
