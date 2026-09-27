"""
GrowWorld — shard_manager.py
Manages slot allocation across pre-defined dimension shards.

Strategy: spiral outward from origin (0,0) within each shard so the
most-visited worlds cluster near the center of coordinate space,
keeping floating-point precision at its best.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

from .models import WorldSlot, SLOT_SIZE, MAX_SLOT_IDX, SLOTS_PER_SHARD, TOTAL_SHARDS

if TYPE_CHECKING:
    from .database import Database


class ShardManager:
    """
    Finds the next free (shard, slot_x, slot_z) for a new world.
    Iterates shards 0 → 9 in order; within each shard allocates in a
    deterministic spiral so slots fill from the origin outward.
    """

    def __init__(self, db: "Database"):
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allocate_slot(self) -> Optional[WorldSlot]:
        """
        Returns the next free WorldSlot across all shards,
        or None if every shard is completely full (shouldn't happen in practice).
        """
        for shard_id in range(TOTAL_SHARDS):
            slot = self._next_free_slot_in_shard(shard_id)
            if slot is not None:
                self._db.increment_shard_allocated(shard_id, slot.slot_x, slot.slot_z)
                return slot
        return None   # All ~238 million slots exhausted — practically impossible

    def shard_info(self) -> list[dict]:
        """Returns a summary of all shards for admin inspection."""
        result = []
        for shard_id in range(TOTAL_SHARDS):
            allocated = self._db.get_shard_allocated(shard_id)
            result.append({
                "shard_id":  shard_id,
                "allocated": allocated,
                "capacity":  SLOTS_PER_SHARD,
                "pct_full":  round(allocated / SLOTS_PER_SHARD * 100, 4),
            })
        return result

    # ------------------------------------------------------------------
    # Spiral allocation
    # ------------------------------------------------------------------

    def _next_free_slot_in_shard(self, shard_id: int) -> Optional[WorldSlot]:
        """
        Walk a square spiral from (0,0) outward until a free slot is found.
        This keeps worlds clustered near origin for best float precision.
        """
        allocated = self._db.get_shard_allocated(shard_id)
        if allocated >= SLOTS_PER_SHARD:
            return None   # Shard is full, skip to next

        # Spiral: right → down → left → up → right …
        x, z = 0, 0
        dx, dz = 1, 0
        steps = 1
        step_count = 0
        turns = 0

        # Walk up to SLOTS_PER_SHARD positions looking for a free one.
        # In practice the first unchecked position is almost always free.
        for _ in range(SLOTS_PER_SHARD):
            if abs(x) <= MAX_SLOT_IDX and abs(z) <= MAX_SLOT_IDX:
                if not self._db.is_slot_occupied(shard_id, x, z):
                    return WorldSlot(shard_id, x, z)

            # Advance spiral
            x += dx
            z += dz
            step_count += 1

            if step_count == steps:
                step_count = 0
                # Turn left (rotate 90°)
                dx, dz = -dz, dx
                turns += 1
                if turns % 2 == 0:
                    steps += 1

        return None   # Should not reach here
