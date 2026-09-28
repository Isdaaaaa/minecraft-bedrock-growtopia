"""
Terravia — database.py
SQLite persistence layer for worlds, player sessions, and access lists.
"""

from __future__ import annotations
import sqlite3
import os
import time
from typing import Optional, List
from .models import Terravia, PlayerSession, LockLevel


class Database:
    def __init__(self, data_folder: str):
        os.makedirs(data_folder, exist_ok=True)
        db_path = os.path.join(data_folder, "terravia.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _migrate(self):
        cur = self._conn.cursor()

        cur.executescript("""
        CREATE TABLE IF NOT EXISTS worlds (
            world_id      TEXT PRIMARY KEY,
            owner_uuid    TEXT NOT NULL,
            owner_name    TEXT NOT NULL,
            shard_id      INTEGER NOT NULL,
            slot_x        INTEGER NOT NULL,
            slot_z        INTEGER NOT NULL,
            created_at    REAL NOT NULL,
            last_visited  REAL NOT NULL,
            lock_level    INTEGER NOT NULL DEFAULT 0,
            description   TEXT NOT NULL DEFAULT '',
            is_public     INTEGER NOT NULL DEFAULT 1
        );

        -- Tracks who has builder/admin access to a locked world
        CREATE TABLE IF NOT EXISTS world_access (
            world_id     TEXT NOT NULL,
            player_uuid  TEXT NOT NULL,
            access_level INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (world_id, player_uuid),
            FOREIGN KEY (world_id) REFERENCES worlds(world_id)
        );

        -- Tracks which (shard, slot_x, slot_z) combos are occupied
        CREATE TABLE IF NOT EXISTS occupied_slots (
            shard_id  INTEGER NOT NULL,
            slot_x    INTEGER NOT NULL,
            slot_z    INTEGER NOT NULL,
            world_id  TEXT NOT NULL,
            PRIMARY KEY (shard_id, slot_x, slot_z)
        );

        -- Per-shard fill counter for fast next-slot lookup
        CREATE TABLE IF NOT EXISTS shard_state (
            shard_id       INTEGER PRIMARY KEY,
            allocated      INTEGER NOT NULL DEFAULT 0,
            last_slot_x    INTEGER NOT NULL DEFAULT 0,
            last_slot_z    INTEGER NOT NULL DEFAULT 0
        );

        -- Online player session cache (cleared on plugin disable)
        CREATE TABLE IF NOT EXISTS player_sessions (
            player_uuid      TEXT PRIMARY KEY,
            player_name      TEXT NOT NULL,
            current_world_id TEXT
        );

        -- Banned players per world
        CREATE TABLE IF NOT EXISTS world_bans (
            world_id    TEXT NOT NULL,
            player_uuid TEXT NOT NULL,
            banned_by   TEXT NOT NULL,
            reason      TEXT NOT NULL DEFAULT '',
            banned_at   REAL NOT NULL,
            PRIMARY KEY (world_id, player_uuid)
        );
        """)

        # Initialise shard state rows if not present
        for shard_id in range(10):
            cur.execute(
                "INSERT OR IGNORE INTO shard_state(shard_id) VALUES (?)",
                (shard_id,)
            )

        self._conn.commit()

    # ------------------------------------------------------------------
    # World CRUD
    # ------------------------------------------------------------------

    def create_world(self, world: Terravia) -> None:
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO worlds
            (world_id, owner_uuid, owner_name, shard_id, slot_x, slot_z,
             created_at, last_visited, lock_level, description, is_public)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            world.world_id, world.owner_uuid, world.owner_name,
            world.shard_id, world.slot_x, world.slot_z,
            world.created_at, world.last_visited,
            world.lock_level, world.description, int(world.is_public)
        ))
        cur.execute("""
            INSERT INTO occupied_slots (shard_id, slot_x, slot_z, world_id)
            VALUES (?, ?, ?, ?)
        """, (world.shard_id, world.slot_x, world.slot_z, world.world_id))
        self._conn.commit()

    def get_world(self, world_id: str) -> Optional[Terravia]:
        row = self._conn.execute(
            "SELECT * FROM worlds WHERE world_id = ?", (world_id.upper(),)
        ).fetchone()
        return self._row_to_world(row) if row else None

    def world_exists(self, world_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM worlds WHERE world_id = ?", (world_id.upper(),)
        ).fetchone()
        return row is not None

    def update_last_visited(self, world_id: str) -> None:
        self._conn.execute(
            "UPDATE worlds SET last_visited = ? WHERE world_id = ?",
            (time.time(), world_id)
        )
        self._conn.commit()

    def set_lock_level(self, world_id: str, level: int) -> None:
        self._conn.execute(
            "UPDATE worlds SET lock_level = ? WHERE world_id = ?",
            (level, world_id)
        )
        self._conn.commit()

    def set_description(self, world_id: str, description: str) -> None:
        self._conn.execute(
            "UPDATE worlds SET description = ? WHERE world_id = ?",
            (description, world_id)
        )
        self._conn.commit()

    def _row_to_world(self, row: sqlite3.Row) -> Terravia:
        return Terravia(
            world_id=row["world_id"],
            owner_uuid=row["owner_uuid"],
            owner_name=row["owner_name"],
            shard_id=row["shard_id"],
            slot_x=row["slot_x"],
            slot_z=row["slot_z"],
            created_at=row["created_at"],
            last_visited=row["last_visited"],
            lock_level=row["lock_level"],
            description=row["description"],
            is_public=bool(row["is_public"]),
        )

    # ------------------------------------------------------------------
    # Shard / Slot allocation
    # ------------------------------------------------------------------

    def is_slot_occupied(self, shard_id: int, slot_x: int, slot_z: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM occupied_slots WHERE shard_id=? AND slot_x=? AND slot_z=?",
            (shard_id, slot_x, slot_z)
        ).fetchone()
        return row is not None

    def get_shard_allocated(self, shard_id: int) -> int:
        row = self._conn.execute(
            "SELECT allocated FROM shard_state WHERE shard_id = ?", (shard_id,)
        ).fetchone()
        return row["allocated"] if row else 0

    def increment_shard_allocated(self, shard_id: int, slot_x: int, slot_z: int) -> None:
        self._conn.execute("""
            UPDATE shard_state
            SET allocated = allocated + 1, last_slot_x = ?, last_slot_z = ?
            WHERE shard_id = ?
        """, (slot_x, slot_z, shard_id))
        self._conn.commit()

    # ------------------------------------------------------------------
    # World access list
    # ------------------------------------------------------------------

    def add_access(self, world_id: str, player_uuid: str, level: int = 1) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO world_access (world_id, player_uuid, access_level)
            VALUES (?, ?, ?)
        """, (world_id, player_uuid, level))
        self._conn.commit()

    def remove_access(self, world_id: str, player_uuid: str) -> None:
        self._conn.execute(
            "DELETE FROM world_access WHERE world_id=? AND player_uuid=?",
            (world_id, player_uuid)
        )
        self._conn.commit()

    def get_access_level(self, world_id: str, player_uuid: str) -> int:
        row = self._conn.execute(
            "SELECT access_level FROM world_access WHERE world_id=? AND player_uuid=?",
            (world_id, player_uuid)
        ).fetchone()
        return row["access_level"] if row else 0

    # ------------------------------------------------------------------
    # World bans
    # ------------------------------------------------------------------

    def ban_player(self, world_id: str, player_uuid: str, banned_by: str, reason: str = "") -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO world_bans
            (world_id, player_uuid, banned_by, reason, banned_at)
            VALUES (?, ?, ?, ?, ?)
        """, (world_id, player_uuid, banned_by, reason, time.time()))
        self._conn.commit()

    def unban_player(self, world_id: str, player_uuid: str) -> None:
        self._conn.execute(
            "DELETE FROM world_bans WHERE world_id=? AND player_uuid=?",
            (world_id, player_uuid)
        )
        self._conn.commit()

    def is_banned(self, world_id: str, player_uuid: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM world_bans WHERE world_id=? AND player_uuid=?",
            (world_id, player_uuid)
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Player sessions
    # ------------------------------------------------------------------

    def set_player_session(self, session: PlayerSession) -> None:
        self._conn.execute("""
            INSERT OR REPLACE INTO player_sessions
            (player_uuid, player_name, current_world_id)
            VALUES (?, ?, ?)
        """, (session.player_uuid, session.player_name, session.current_world_id))
        self._conn.commit()

    def get_player_session(self, player_uuid: str) -> Optional[PlayerSession]:
        row = self._conn.execute(
            "SELECT * FROM player_sessions WHERE player_uuid = ?", (player_uuid,)
        ).fetchone()
        if not row:
            return None
        return PlayerSession(
            player_uuid=row["player_uuid"],
            player_name=row["player_name"],
            current_world_id=row["current_world_id"],
        )

    def remove_player_session(self, player_uuid: str) -> None:
        self._conn.execute(
            "DELETE FROM player_sessions WHERE player_uuid = ?", (player_uuid,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        # Clear all sessions on shutdown (they'll repopulate on next join)
        self._conn.execute("DELETE FROM player_sessions")
        self._conn.commit()
        self._conn.close()
