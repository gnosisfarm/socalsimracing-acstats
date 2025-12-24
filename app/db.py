# app/db.py
import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "app/data/ac_laptimes.db")
SCHEMA_SQL = """
 PRAGMA foreign_keys = ON;
 CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
 );
 CREATE TABLE IF NOT EXISTS cars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT UNIQUE NOT NULL
 );
 CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
 );
 CREATE TABLE IF NOT EXISTS lap_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    car_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    laptime_ms INTEGER NOT NULL,
    timestamp DATETIME DEFAULT (datetime('now')),
    FOREIGN KEY(player_id) REFERENCES players(id),
    FOREIGN KEY(car_id) REFERENCES cars(id),
    FOREIGN KEY(track_id) REFERENCES tracks(id)
 );
 """
def ensure_db():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)