"""
Terravia — world_template.py
Defines and applies the block layout for a freshly created world slot.

World vertical layout:
  Y  320      → Vanilla sky limit (open — no ceiling, full creative freedom)
  Y  195+     → Air (no block placement allowed above Y194 via plugin)
  Y  194      → Top of buildable space  ← 256 blocks above Y-61
  Y  1-193    → Air (build space above ground)
  Y  0        → Grass Block  ← surface / ground level
  Y -1 to -4  → Dirt (4 layers)
  Y -5 to -19 → Stone
  Y -20 to -61→ Deepslate
  Y -62 to -64→ Bedrock floor (3 layers, unbreakable)

Vertical build space:
  Y-61 (first non-bedrock) → Y194 (top cap) = exactly 256 blocks
  Horizontal: 256×256 playable blocks per world slot.
  Total world space when cleared (excl. bedrock): 256 × 256 × 256 blocks.

No physical ceiling block — the sky stays open for aesthetics.
Build height is enforced by the plugin's block event listener.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from endstone.level import Dimension
    from .models import WorldSlot

# ---------------------------------------------------------------------------
# Block type identifiers (Bedrock namespaced IDs)
# ---------------------------------------------------------------------------
BLOCK_BEDROCK   = "minecraft:bedrock"
BLOCK_DEEPSLATE = "minecraft:deepslate"
BLOCK_STONE     = "minecraft:stone"
BLOCK_DIRT      = "minecraft:dirt"
BLOCK_GRASS     = "minecraft:grass_block"

# ---------------------------------------------------------------------------
# Y-level constants  (exported so world_manager can enforce the build cap)
# ---------------------------------------------------------------------------

Y_BEDROCK_FLOOR_BOTTOM = -64   # Hard floor — bottom of the world
Y_BEDROCK_FLOOR_TOP    = -62   # Top of the 3-layer bedrock floor
Y_DEEPSLATE_BOTTOM     = -61
Y_DEEPSLATE_TOP        = -20
Y_STONE_BOTTOM         = -19
Y_STONE_TOP            = -5
Y_DIRT_BOTTOM          = -4
Y_DIRT_TOP             = -1
Y_SURFACE              = 0     # Grass layer — "ground level"

# Build limits — enforced by plugin, NOT by a physical block ceiling.
# Y_BUILD_MIN is the first row above bedrock; Y_BUILD_MAX is the top cap.
# Y_BUILD_MAX - Y_BUILD_MIN + 1 = 194 - (-61) + 1 = 256 exactly.
Y_BUILD_MIN    = -61   # First non-bedrock, freely breakable layer
Y_BUILD_MAX    = 194   # Inclusive top cap (256-block vertical space)

# ---------------------------------------------------------------------------
# Layer definitions — (y_min, y_max_inclusive, block_id)
# NO ceiling row — the sky stays open.
# ---------------------------------------------------------------------------
LAYER_SPEC: list[tuple[int, int, str]] = [
    (Y_BEDROCK_FLOOR_BOTTOM, Y_BEDROCK_FLOOR_TOP, BLOCK_BEDROCK),
    (Y_DEEPSLATE_BOTTOM,     Y_DEEPSLATE_TOP,     BLOCK_DEEPSLATE),
    (Y_STONE_BOTTOM,         Y_STONE_TOP,         BLOCK_STONE),
    (Y_DIRT_BOTTOM,          Y_DIRT_TOP,           BLOCK_DIRT),
    (Y_SURFACE,              Y_SURFACE,            BLOCK_GRASS),
    # Y1 → Y194: air  (default void — no blocks needed)
    # Y195+:     air  (accessible to fly/look, but block placement blocked)
]


class WorldTemplate:
    """
    Generates the initial block layout for a new player world.

    Called once when a world is first created. The result is a 256×256 flat
    terrain with open sky — players see stars/clouds, not a bedrock ceiling.

    Use generate_async() on live servers to avoid tick stalls.
    """

    def __init__(self, plugin):
        self._plugin = plugin

    def generate(self, dimension: "Dimension", slot: "WorldSlot") -> None:
        """Synchronous generation — fine for offline/dev, avoid on live servers."""
        min_x, max_x = slot.playable_min_x, slot.playable_max_x
        min_z, max_z = slot.playable_min_z, slot.playable_max_z

        self._plugin.logger.info(
            f"[WorldTemplate] Generating terrain for slot "
            f"({slot.slot_x},{slot.slot_z}) shard={slot.shard_id}"
        )

        for y_min, y_max, block_id in LAYER_SPEC:
            for y in range(y_min, y_max + 1):
                for x in range(min_x, max_x + 1):
                    for z in range(min_z, max_z + 1):
                        try:
                            dimension.get_block(x, y, z).set_type(block_id)
                        except Exception as e:
                            self._plugin.logger.warning(
                                f"[WorldTemplate] Failed at ({x},{y},{z}): {e}"
                            )

        self._plugin.logger.info(
            f"[WorldTemplate] Done for slot ({slot.slot_x},{slot.slot_z})"
        )

    def generate_async(self, dimension: "Dimension", slot: "WorldSlot") -> None:
        """
        Batched per-tick generation — preferred on live servers.
        Places BATCH_SIZE blocks per tick, yielding control between batches.
        """
        min_x, max_x = slot.playable_min_x, slot.playable_max_x
        min_z, max_z = slot.playable_min_z, slot.playable_max_z

        jobs: list[tuple[int, int, int, str]] = []
        for y_min, y_max, block_id in LAYER_SPEC:
            for y in range(y_min, y_max + 1):
                for x in range(min_x, max_x + 1):
                    for z in range(min_z, max_z + 1):
                        jobs.append((x, y, z, block_id))

        BATCH_SIZE = 4096
        scheduler  = self._plugin.server.scheduler
        job_iter   = iter(jobs)

        def process_batch():
            count = 0
            for x, y, z, block_id in job_iter:
                try:
                    dimension.get_block(x, y, z).set_type(block_id)
                except Exception:
                    pass
                count += 1
                if count >= BATCH_SIZE:
                    scheduler.run_task_later(self._plugin, process_batch, delay=1)
                    return
            self._plugin.logger.info(
                f"[WorldTemplate] Async generation complete for "
                f"slot ({slot.slot_x},{slot.slot_z}) shard={slot.shard_id}"
            )

        scheduler.run_task(self._plugin, process_batch)
