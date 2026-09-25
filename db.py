import sqlite3
from flask import g
import config


def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db:
        db.close()


def get_setting(db, key):
    return float(db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0])
