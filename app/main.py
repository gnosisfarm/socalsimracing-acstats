# app/main.py
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import sqlite3
import json
import os

from .db import ensure_db, get_conn

ensure_db()
app = FastAPI(title="ACStats")

# ---------------------------------------------
# Track name translation
# ---------------------------------------------
TRACK_MAP_FILE = "app/track_names.json"

def load_track_name_map():
    if not os.path.exists(TRACK_MAP_FILE):
        return {}
    with open(TRACK_MAP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

TRACK_NAME_MAP = load_track_name_map()

def display_track(track_id: str) -> str:
    return TRACK_NAME_MAP.get(track_id, track_id.replace("_", " ").title())

# ---------------------------------------------
# Logging middleware (XFF + client IP)
# ---------------------------------------------
@app.middleware("http")
async def log_xff(request: Request, call_next):
    xff = request.headers.get("x-forwarded-for")
    real_ip = request.client.host
    ua = request.headers.get("user-agent", "unknown")
    print(f"[REQ] IP={real_ip} XFF={xff} UA={ua} -> {request.method} {request.url}")
    response = await call_next(request)
    return response

# ---------------------------------------------
# Serve static pages
# ---------------------------------------------
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=HTMLResponse)
def home():
    with open("app/static/home.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard():
    with open("app/static/leaderboard.html", "r", encoding="utf-8") as f:
        return f.read()

# ---------------------------------------------
# Helpers
# ---------------------------------------------
def row_to_dict(row, cols):
    return {k: row[idx] for idx, k in enumerate(cols)}

def format_laptime(ms: int):
    ms = int(ms)
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{minutes}:{seconds:02d}.{millis:03d}"

# ---------------------------------------------
# Fastest lap per player per car on a given track
# ---------------------------------------------
@app.get("/api/top/{track}")
def top_for_track(track: str, limit: int = 100):
    conn = get_conn()
    c = conn.cursor()

    q = """
    WITH best_laps AS (
        SELECT player_id, car_id, track_id, MIN(laptime_ms) AS best_ms
        FROM lap_times
        WHERE track_id = (SELECT id FROM tracks WHERE name = ?)
        GROUP BY player_id, car_id, track_id
    )
    SELECT p.name AS player,
           c.model AS car,
           t.name AS track,
           b.best_ms AS laptime_ms,
           l.timestamp AS timestamp
    FROM best_laps b
    JOIN lap_times l
      ON l.player_id = b.player_id
     AND l.car_id = b.car_id
     AND l.track_id = b.track_id
     AND l.laptime_ms = b.best_ms
    JOIN players p ON p.id = b.player_id
    JOIN cars c ON c.id = b.car_id
    JOIN tracks t ON t.id = b.track_id
    ORDER BY b.best_ms ASC
    LIMIT ?
    """

    c.execute(q, (track, limit))
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()

    result = []
    for r in rows:
        d = row_to_dict(r, cols)
        d["laptime"] = format_laptime(d["laptime_ms"])
        d["track_name"] = display_track(d["track"])
        result.append(d)

    return result

# ---------------------------------------------
# Top lap per track (main page)
# ---------------------------------------------
@app.get("/api/top_all")
def top_all_tracks():
    conn = get_conn()
    c = conn.cursor()

    q = """
    WITH best_per_track AS (
        SELECT track_id, MIN(laptime_ms) AS best_ms
        FROM lap_times
        GROUP BY track_id
    )
    SELECT t.name AS track,
           p.name AS player,
           c.model AS car,
           l.laptime_ms,
           l.timestamp
    FROM best_per_track b
    JOIN lap_times l
      ON l.track_id = b.track_id
     AND l.laptime_ms = b.best_ms
    JOIN players p ON p.id = l.player_id
    JOIN cars c ON c.id = l.car_id
    JOIN tracks t ON t.id = l.track_id
    ORDER BY t.name ASC
    """

    c.execute(q)
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()

    result = {}
    for r in rows:
        d = row_to_dict(r, cols)
        d["laptime"] = format_laptime(d["laptime_ms"])
        track_id = d.pop("track")
        d["track_name"] = display_track(track_id)
        result[track_id] = d

    return result

# ---------------------------------------------
# Track list (for dropdown)
# ---------------------------------------------
@app.get("/api/tracks")
def list_tracks():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name FROM tracks ORDER BY name ASC")
    rows = c.fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "name": display_track(r[0])
        }
        for r in rows
    ]

# ---------------------------------------------
# Player laps
# ---------------------------------------------
@app.get("/api/player/{player}")
def laps_for_player(player: str):
    conn = get_conn()
    c = conn.cursor()

    q = """
    SELECT p.name as player,
           c.model as car,
           t.name as track,
           l.laptime_ms,
           l.timestamp
    FROM lap_times l
    JOIN players p ON p.id = l.player_id
    JOIN cars c ON c.id = l.car_id
    JOIN tracks t ON t.id = l.track_id
    WHERE p.name = ?
    ORDER BY l.laptime_ms ASC
    LIMIT 200
    """

    c.execute(q, (player,))
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()

    result = []
    for r in rows:
        d = row_to_dict(r, cols)
        d["laptime"] = format_laptime(d["laptime_ms"])
        d["track_name"] = display_track(d["track"])
        result.append(d)

    return result

# ---------------------------------------------
# Overall leaderboard
# ---------------------------------------------
@app.get("/api/leaderboard")
def overall_leaderboard(limit: int = 50):
    conn = get_conn()
    c = conn.cursor()

    q = """
    SELECT p.name as player,
           MIN(l.laptime_ms) as best_ms,
           COUNT(*) as laps
    FROM lap_times l
    JOIN players p ON p.id = l.player_id
    GROUP BY p.id
    ORDER BY best_ms ASC
    LIMIT ?
    """

    c.execute(q, (limit,))
    rows = c.fetchall()
    cols = [d[0] for d in c.description]
    conn.close()

    result = []
    for r in rows:
        d = row_to_dict(r, cols)
        d["best_laptime"] = format_laptime(d["best_ms"])
        result.append(d)

    return result
