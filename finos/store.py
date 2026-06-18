"""
Persistence layer for fin-os.

A small SQLite-backed store (stdlib only) that turns fin-os from a single
in-memory session into a platform: many named scenarios, each with its own
saved config and chat history, surviving server restarts.

Two tables:
  scenarios(id, name, config_json, created_at, updated_at)
  messages(id, scenario_id, role, text, created_at)

Engine configs contain `date` objects; they are converted to/from ISO strings
on the way in/out so the stored JSON is portable and round-trips cleanly.

The DB path defaults to ~/.fin-os/finos.db and can be overridden with the
FINOS_DB environment variable (used by tests).
"""
import copy
import json
import os
import sqlite3
import threading
from datetime import date, datetime


def default_db_path():
    return os.environ.get("FINOS_DB") or os.path.join(os.path.expanduser("~"), ".fin-os", "finos.db")


# ---------------------------------------------------------------------------
# Config <-> JSON (date-aware)
# ---------------------------------------------------------------------------

def _encode_dates(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"not serializable: {type(obj)}")


def config_to_json(config):
    """Serialize an engine config (with date objects) to a plain JSON string."""
    return json.dumps(config, default=_encode_dates)


def _parse_date_field(d, key):
    v = d.get(key)
    if isinstance(v, str):
        try:
            d[key] = date.fromisoformat(v)
        except ValueError:
            pass


def config_from_json(text):
    """Parse a stored JSON string back to an engine config, restoring date objects."""
    config = json.loads(text) if isinstance(text, str) else copy.deepcopy(text)

    sim = config.get("simulation", {})
    _parse_date_field(sim, "start_date")

    streams = config.get("cashflow_streams", {})
    for s in list(streams.get("income", [])) + list(streams.get("expenses", [])):
        _parse_date_field(s, "start_date")
        _parse_date_field(s, "end_date")

    instruments = config.get("instruments", {})
    for d in instruments.get("debts", []):
        _parse_date_field(d, "start_date")
        sched = d.get("apr_schedule")
        if isinstance(sched, dict):
            _parse_date_field(sched, "promo_end")
    for a in instruments.get("accounts", []):
        sched = a.get("rate_schedule")
        if isinstance(sched, dict):
            _parse_date_field(sched, "promo_end")

    return config


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    """Thread-safe SQLite store for scenarios and chat messages."""

    def __init__(self, path=None):
        self.path = path or default_db_path()
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scenarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)

    # --- scenarios -------------------------------------------------------

    def create_scenario(self, name, config):
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO scenarios (name, config_json) VALUES (?, ?)",
                (name, config_to_json(config)),
            )
            return cur.lastrowid

    def list_scenarios(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, created_at, updated_at FROM scenarios ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_scenario(self, scenario_id):
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, config_json, created_at, updated_at FROM scenarios WHERE id = ?",
                (scenario_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "config": config_from_json(row["config_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_config(self, scenario_id, config):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE scenarios SET config_json = ?, updated_at = datetime('now') WHERE id = ?",
                (config_to_json(config), scenario_id),
            )

    def rename_scenario(self, scenario_id, name):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE scenarios SET name = ?, updated_at = datetime('now') WHERE id = ?",
                (name, scenario_id),
            )

    def delete_scenario(self, scenario_id):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE scenario_id = ?", (scenario_id,))
            conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))

    def count_scenarios(self):
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM scenarios").fetchone()["n"]

    # --- messages --------------------------------------------------------

    def add_message(self, scenario_id, role, text):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (scenario_id, role, text) VALUES (?, ?, ?)",
                (scenario_id, role, text),
            )

    def get_messages(self, scenario_id):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT role, text FROM messages WHERE scenario_id = ? ORDER BY id ASC",
                (scenario_id,),
            ).fetchall()
            return [{"role": r["role"], "text": r["text"]} for r in rows]

    def clear_messages(self, scenario_id):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE scenario_id = ?", (scenario_id,))
