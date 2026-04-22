#!/usr/bin/env python3
"""User management CLI for the soundboard.

Usage:
  python manage.py adduser <username>
  python manage.py passwd  <username>
  python manage.py remove  <username>
  python manage.py list
"""
import getpass
import sqlite3
import sys
from pathlib import Path
from werkzeug.security import generate_password_hash

USERS_DB = Path("users.db")


def conn():
    c = sqlite3.connect(USERS_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )""")
    c.commit()
    return c


def prompt_password(label="Password"):
    pw  = getpass.getpass(f"{label}: ")
    pw2 = getpass.getpass("Confirm: ")
    if pw != pw2:
        print("Passwords do not match.")
        sys.exit(1)
    if not pw:
        print("Password cannot be empty.")
        sys.exit(1)
    return pw


def cmd_adduser(username):
    pw = prompt_password()
    c = conn()
    try:
        c.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(pw))
        )
        c.commit()
        print(f"User '{username}' created.")
    except sqlite3.IntegrityError:
        print(f"User '{username}' already exists.")
        sys.exit(1)


def cmd_passwd(username):
    pw = prompt_password("New password")
    c = conn()
    cur = c.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (generate_password_hash(pw), username)
    )
    c.commit()
    if cur.rowcount:
        print(f"Password updated for '{username}'.")
    else:
        print(f"User '{username}' not found.")
        sys.exit(1)


def cmd_remove(username):
    c = conn()
    cur = c.execute("DELETE FROM users WHERE username = ?", (username,))
    c.commit()
    if cur.rowcount:
        print(f"User '{username}' removed.")
    else:
        print(f"User '{username}' not found.")
        sys.exit(1)


def cmd_list():
    rows = conn().execute("SELECT username FROM users ORDER BY username").fetchall()
    if rows:
        for r in rows:
            print(r[0])
    else:
        print("No users. Run: python manage.py adduser <username>")


COMMANDS = {
    "adduser": cmd_adduser,
    "passwd":  cmd_passwd,
    "remove":  cmd_remove,
    "list":    cmd_list,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 else 1)

    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif len(sys.argv) < 3:
        print(f"Usage: python manage.py {cmd} <username>")
        sys.exit(1)
    else:
        COMMANDS[cmd](sys.argv[2])
