"""
Terravia — models.py
Data models representing worlds, players, and shards.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time


# ---------------------------------------------------------------------------
# World slot spatial constants
# ---------------------------------------------------------------------------

SLOT_SIZE    = 4096   # Total block footprint of one world slot (X and Z)
WORLD_SIZE   = 256    # Playable area within each slot
BUFFER       = (SLOT_SIZE - WORLD_SIZE) // 2   # 1920 — void gap on each side
SPAWN_Y      = 64     # Default Y level for player spawn inside a world

# Maximum safe grid index per axis (stay within ±10,000,000 blocks)
MAX_COORD    = 10_000_000
MAX_SLOT_IDX = MAX_COORD // SLOT_SIZE          # 2441
SLOTS_PER_SHARD = (MAX_SLOT_IDX * 2 + 1) ** 2  # ~23.8 million per shard

# Pre-defined shard dimension identifiers.
# Shard 0 = overworld (vanilla), shards 1-9 = custom terravia dimensions.
SHARD_DIMENSIONS = {
    0: "minecraft:overworld",
    1: "terravia:shard_1",
    2: "terravia:shard_2",
    3: "terravia:shard_3",
    4: "terravia:shard_4",
    5: "terravia:shard_5",
    6: "terravia:shard_6",
    7: "terravia:shard_7",
    8: "terravia:shard_8",
    9: "terravia:shard_9",
}

# The hub is a dedicated dimension — NOT a shard.
# New players always land here first (tutorial / START world equivalent).
HUB_DIMENSION_ID = "terravia:hub"

# Hub spawn point (centre of a pre-built hub structure in the hub dimension)
HUB_SPAWN_X: float = 0.5
HUB_SPAWN_Y: float = 1.0
HUB_SPAWN_Z: float = 0.5

TOTAL_SHARDS = len(SHARD_DIMENSIONS)


# ---------------------------------------------------------------------------
# Lock levels (mirrors Growtopia's locking system)
# ---------------------------------------------------------------------------

class LockLevel:
    NONE        = 0   # Anyone can build
    WORLD_LOCK  = 1   # Only owner + access list can build
    BIG_LOCK    = 2   # Only owner can build (no access list)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class WorldSlot:
    """
    Represents the spatial address of a world within a shard.
    Slot (shard, slot_x, slot_z) maps to a fixed region in that dimension.
    """
    shard_id: int
    slot_x:   int   # Grid index (can be negative)
    slot_z:   int   # Grid index (can be negative)

    @property
    def dimension_id(self) -> str:
        return SHARD_DIMENSIONS[self.shard_id]

    @property
    def origin_x(self) -> int:
        """World-space X of the south-west corner of this slot."""
        return self.slot_x * SLOT_SIZE

    @property
    def origin_z(self) -> int:
        """World-space Z of the south-west corner of this slot."""
        return self.slot_z * SLOT_SIZE

    @property
    def playable_min_x(self) -> int:
        return self.origin_x + BUFFER

    @property
    def playable_max_x(self) -> int:
        return self.origin_x + BUFFER + WORLD_SIZE

    @property
    def playable_min_z(self) -> int:
        return self.origin_z + BUFFER

    @property
    def playable_max_z(self) -> int:
        return self.origin_z + BUFFER + WORLD_SIZE

    @property
    def spawn_x(self) -> float:
        return self.origin_x + SLOT_SIZE / 2

    @property
    def spawn_z(self) -> float:
        return self.origin_z + SLOT_SIZE / 2

    def contains(self, x: float, z: float) -> bool:
        """Returns True if the given coordinates fall within the playable area."""
        return (self.playable_min_x <= x <= self.playable_max_x and
                self.playable_min_z <= z <= self.playable_max_z)


@dataclass
class Terravia:
    """
    A player-owned world, analogous to a Growtopia world.
    """
    world_id:      str            # Unique name (e.g. "PARKOUR", "START")
    owner_uuid:    str
    owner_name:    str
    shard_id:      int
    slot_x:        int
    slot_z:        int
    created_at:    float = field(default_factory=time.time)
    last_visited:  float = field(default_factory=time.time)
    lock_level:    int   = LockLevel.NONE
    description:   str   = ""
    is_public:     bool  = True

    @property
    def slot(self) -> WorldSlot:
        return WorldSlot(self.shard_id, self.slot_x, self.slot_z)

    @property
    def display_name(self) -> str:
        lock_icon = {
            LockLevel.NONE:       "",
            LockLevel.WORLD_LOCK: "🔒 ",
            LockLevel.BIG_LOCK:   "🔐 ",
        }.get(self.lock_level, "")
        return f"{lock_icon}{self.world_id}"


@dataclass
class PlayerSession:
    """Tracks which world a connected player is currently in."""
    player_uuid:      str
    player_name:      str
    current_world_id: Optional[str] = None   # None = in lobby/spawn
