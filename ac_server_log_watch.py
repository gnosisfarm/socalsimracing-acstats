import sqlite3
import re
import time
from pathlib import Path
import glob
import urllib.parse

# ---------------- Config ----------------
LOG_FOLDER = r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\server\logs\session"
DB_PATH = './data/ac_laptimes.db'

Path(LOG_FOLDER).mkdir(parents=True, exist_ok=True)
Path('./data').mkdir(exist_ok=True)

# ---------------- SQLite Schema ----------------
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS cars (
    id INTEGER PRIMARY KEY,
    model TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS lap_times (
    id INTEGER PRIMARY KEY,
    player_id INTEGER,
    car_id INTEGER,
    track_id INTEGER,
    laptime_ms INTEGER,
    timestamp DATETIME DEFAULT (datetime('now')),
    FOREIGN KEY(player_id) REFERENCES players(id),
    FOREIGN KEY(car_id) REFERENCES cars(id),
    FOREIGN KEY(track_id) REFERENCES tracks(id)
);
"""

# ---------------- Regex ----------------
lap_re = re.compile(r'^LAP\s+(?P<player>.+?)\s+(?P<laptime>[\d:.]+)$')
requested_car_re = re.compile(r'^REQUESTED CAR:\s*(?P<car>.+?)(\*)?$')
driver_accepted_re = re.compile(r'^DRIVER ACCEPTED FOR CAR\s+(?P<player>.+)$')
cuts_re = re.compile(r'Cuts:\s*(\d+)', re.IGNORECASE)

# track sources
track_line_re = re.compile(r'^TRACK=(?P<track>.+)$', re.IGNORECASE)
config_line_re = re.compile(r'^CONFIG=(?P<config>.+)$', re.IGNORECASE)
info_track_re = re.compile(r'"TRACK"\s*:\s*"(?P<track>[^"]+)"', re.IGNORECASE)
info_config_re = re.compile(r'"CONFIG"\s*:\s*"(?P<config>[^"]*)"', re.IGNORECASE)

# also catch content/tracks/.../... paths (like drs_zones ini lines)
content_path_re = re.compile(r'content/tracks(?:/|\\)(?P<rest>.+)', re.IGNORECASE)

# ---------------- Helpers ----------------
def lap_to_ms(lap_str):
    parts = lap_str.split(':')
    if len(parts) == 3:
        m, s, ms = parts
        return int(m) * 60000 + int(s) * 1000 + int(ms)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60000 + int(s) * 1000
    return int(parts[0])

def clean_tokens(tokens):
    """Remove noise tokens from a split path."""
    bad = {'', '.', '..', 'csp', 'content', 'tracks', 'data', 'cfg', '0'}
    return [t for t in tokens if t and t.lower() not in bad]

def parse_track_from_string(s):
    """
    Try to extract a track and optional layout from any string:
      - handle URL-encoded strings
      - turn backslashes -> slashes
      - split and remove noise tokens
      - if remaining tokens >=2 combine last two: track-layout
      - if remaining tokens ==1 return that token
      - else return None
    """
    if not s:
        return None
    # unquote URL-encoded parts
    s = urllib.parse.unquote(s)
    s = s.replace('\\', '/')
    parts = s.split('/')
    parts = [p.strip() for p in parts if p is not None]
    parts = clean_tokens(parts)
    if not parts:
        return None
    if len(parts) >= 2:
        # Prefer last two tokens as track + layout
        track = parts[-2]
        layout = parts[-1]
        # if layout looks like file name (contains '.'), drop it
        if '.' in layout:
            layout = None
        if layout:
            return f"{track}-{layout}"
        return track
    return parts[-1]

def normalize_track(track_candidate, config_candidate):
    """
    Combine candidates from different log sources into a normalized track name.
    - prefer the most specific (track+layout)
    - fallback to single token
    - final fallback 'unknown'
    """
    # parse candidates
    t1 = parse_track_from_string(track_candidate) if track_candidate else None
    t2 = parse_track_from_string(config_candidate) if config_candidate else None

    # prefer t1, but if t1 lacks layout and t2 has layout attempt to combine
    if t1 and '-' in t1:
        return t1
    if t2 and '-' in t2:
        return t2
    if t1 and t2 and (t1 != t2):
        # try to merge: if t1 is track and t2 is layout (or vice versa)
        base1 = t1.split('-', 1)[0] if t1 else None
        base2 = t2.split('-', 1)[0] if t2 else None
        if base1 and base2 and base1 == base2:
            # bases same -> take t1 (or combine)
            return t1
    # otherwise prefer any that exist
    if t1:
        return t1
    if t2:
        return t2
    return "unknown"

def get_or_create(cur, table, column, value):
    cur.execute(f"SELECT id FROM {table} WHERE {column} = ?", (value,))
    r = cur.fetchone()
    if r:
        return r[0]
    cur.execute(f"INSERT INTO {table} ({column}) VALUES (?)", (value,))
    return cur.lastrowid

# ---------------- Initialize DB ----------------
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.executescript(SCHEMA_SQL)
conn.commit()

# ---------------- Polling State ----------------
file_positions = {}
player_car_map = {}
pending_cars_queue = []
pending_laps = []
last_lap = None

# track detection state (we'll keep the most recent observed track+config)
observed_track_candidate = None
observed_config_candidate = None

print(f"Watching for laps in: {LOG_FOLDER}")

try:
    while True:
        log_files = sorted(glob.glob(str(Path(LOG_FOLDER) / "output_*")))
        for logfile in log_files:
            if logfile not in file_positions:
                file_positions[logfile] = 0

            with open(logfile, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(file_positions[logfile])
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue

                    # --- TRACK= lines ---
                    m = track_line_re.match(line)
                    if m:
                        observed_track_candidate = m.group("track").strip()
                        # sometimes TRACK= contains full path: csp/0/../ks_nordschleife/touristenfahrten
                        # keep observed candidates and compute normalized when needed
                        continue

                    # --- CONFIG= lines (layout) ---
                    m = config_line_re.match(line)
                    if m:
                        observed_config_candidate = m.group("config").strip()
                        continue

                    # --- /INFO JSON-like lines ---
                    m = info_track_re.search(line)
                    if m:
                        observed_track_candidate = m.group("track").strip()
                    m = info_config_re.search(line)
                    if m:
                        observed_config_candidate = m.group("config").strip()

                    # --- content/tracks paths (e.g. drs_zones) ---
                    m = content_path_re.search(line)
                    if m:
                        # pass the remainder into parser
                        candidate = m.group("rest")
                        parsed = parse_track_from_string(candidate)
                        if parsed:
                            # If parsed has layout, prefer it
                            if '-' in parsed:
                                observed_track_candidate = parsed  # already normalized form
                                observed_config_candidate = None
                            else:
                                # store as track candidate if we don't already have layout
                                # keep as raw to allow later normalization with CONFIG
                                observed_track_candidate = candidate
                        # continue scanning other patterns in the same line
                        continue

                    # also scan for 'track=' inside a URL (e.g. register line)
                    if "track=" in line.lower():
                        # find substring after track= up to space or &
                        try:
                            # crude but effective
                            lower = line.lower()
                            idx = lower.index("track=")
                            after = line[idx + len("track="):]
                            # split on space or '&' or '"' or comma
                            sep = re.split(r'[\s&",\']', after, maxsplit=1)
                            token = sep[0]
                            token = urllib.parse.unquote(token)
                            parsed = parse_track_from_string(token)
                            if parsed:
                                # If token contains '-', it might already be normalized (ks_xxx-layout)
                                if '-' in parsed:
                                    observed_track_candidate = parsed
                                    observed_config_candidate = None
                                else:
                                    # token could be 'csp/0/../ks_nordschleife-touristenfahrten' => parsed handles that
                                    observed_track_candidate = token
                        except Exception:
                            pass

                    # derive normalized track name now (for use by subsequent lap events)
                    normalized_track = normalize_track(observed_track_candidate, observed_config_candidate)

                    # ---------------- Car requested ----------------
                    m = requested_car_re.match(line)
                    if m:
                        car = m.group("car").strip().rstrip('*')
                        pending_cars_queue.append({"player": None, "car": car})
                        continue

                    # ---------------- Driver accepted ----------------
                    m = driver_accepted_re.match(line)
                    if m:
                        player = m.group("player").strip()
                        if not player or player.isdigit():
                            continue

                        assigned = False
                        for pc in pending_cars_queue:
                            if pc["player"] is None:
                                pc["player"] = player
                                player_car_map[player] = pc["car"]
                                pending_cars_queue.remove(pc)
                                assigned = True
                                break
                        if not assigned:
                            player_car_map[player] = "unknown"

                        # flush pending laps for this player
                        for lap in pending_laps[:]:
                            if lap["player"] == player:
                                pid = get_or_create(cur, "players", "name", player)
                                cid = get_or_create(cur, "cars", "model", player_car_map[player])
                                tid = get_or_create(cur, "tracks", "name", lap["track"])
                                cur.execute(
                                    "INSERT INTO lap_times (player_id, car_id, track_id, laptime_ms) VALUES (?,?,?,?)",
                                    (pid, cid, tid, lap["laptime"])
                                )
                                conn.commit()
                                print(f"[PENDING FLUSH] {player} [{player_car_map[player]}] {lap['laptime']}ms @ {lap['track']}")
                                pending_laps.remove(lap)
                        continue

                    # ---------------- Cuts line ----------------
                    m = cuts_re.search(line)
                    if m:
                        if not last_lap:
                            # no lap waiting — ignore
                            continue
                        cuts = int(m.group(1))
                        pl = last_lap["player"]
                        lap_ms = last_lap["lap_ms"]
                        # compute normalized track at time of insert
                        track_for_lap = normalize_track(observed_track_candidate, observed_config_candidate)

                        if cuts == 0:
                            car = player_car_map.get(pl)
                            if car:
                                pid = get_or_create(cur, "players", "name", pl)
                                cid = get_or_create(cur, "cars", "model", car)
                                tid = get_or_create(cur, "tracks", "name", track_for_lap)
                                cur.execute(
                                    "INSERT INTO lap_times (player_id, car_id, track_id, laptime_ms) VALUES (?,?,?,?)",
                                    (pid, cid, tid, lap_ms)
                                )
                                conn.commit()
                                print(f"[LAP] {pl} [{car}] {lap_ms}ms @ {track_for_lap}")
                            else:
                                # queue until we see driver accepted / car mapping
                                pending_laps.append({
                                    "player": pl,
                                    "laptime": lap_ms,
                                    "track": track_for_lap
                                })
                                print(f"[QUEUED] {pl} {lap_ms}ms @ {track_for_lap} (waiting car)")
                        else:
                            print(f"[LAP IGNORED - CUTS {cuts}] {pl} {lap_ms}ms @ {track_for_lap}")

                        last_lap = None
                        continue

                    # ---------------- LAP parsing ----------------
                    m = lap_re.match(line)
                    if m:
                        pl = m.group("player").strip()
                        lap_ms = lap_to_ms(m.group("laptime"))
                        last_lap = {"player": pl, "lap_ms": lap_ms}
                        continue

                # update position for this file
                file_positions[logfile] = f.tell()

        time.sleep(1)

except KeyboardInterrupt:
    print("Shutting down...")
finally:
    conn.close()
