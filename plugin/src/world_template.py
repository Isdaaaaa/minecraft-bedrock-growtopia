"""
GrowWorld — world_template.py
Defines and applies the block layout for a freshly created world slot.

World vertical layout:
  Y  128      → Bedrock ceiling (sky cap, like Growtopia's sky limit)
  Y  127-1    → Air (build space, 127 blocks tall)
  Y  0        → Grass Block  ← surface / ground level
  Y -1 to -4  → Dirt (4 layers)
  Y -5 to -19 → Stone
  Y -20 to -61→ Deep Stone (deepslate)
  Y -62 to -64→ Bedrock floor (3 layers)

Horizontal: 256×256 playable blocks per world slot.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from endstone.level import Dimension
    from .models import WorldSlot

# ---------------------------------------------------------------------------
# Block type identifiers (Bedrock namespaced IDs)
# ---------------------------------------------------------------------------
BLOCK_BEDROCK    = "minecraft:bedrock"
BLOCK_DEEPSLATE  = "minecraft:deepslate"
BLOCK_STONE      = "minecraft:stone"
BLOCK_DIRT       = "minecraft:dirt"
BLOCK_GRASS      = "minecraft:grass_block"
BLOCK_AIR        = "minecraft:air"

# ---------------------------------------------------------------------------
# Y-level constants
# ---------------------------------------------------------------------------

Y_BEDROCK_FLOOR_BOTTOM = -64   # Lowest block of the world
Y_BEDROCK_FLOOR_TOP    = -62   # Top of the 3-layer bedrock floor
Y_DEEPSTONE_BOTTOM     = -61
Y_DEEPSTONE_TOP        = -20
Y_STONE_BOTTOM         = -19
Y_STONE_TOP            = -5
Y_DIRT_BOTTOM          = -4
Y_DIRT_TOP             = -1
Y_SURFACE              = 0     # Grass layer — "ground level"
Y_BUILD_MAX            = 127   # Top of usable air space
Y_CEILING              = 128   # Bedrock sky ceiling

# Total vertical space a player can build in:
# Y_CEILING (128) - Y_SURFACE (0) = 128 blocks above ground
# Y_SURFACE (0)   - Y_BEDROCK_FLOOR_BOTTOM (-64) = 64 blocks underground
# Net usable: 128 above + 0 surface + 4 dirt + 15 stone + 42 deep stone = 192 blocks

# ---------------------------------------------------------------------------
# Layer definitions — list of (y_min, y_max_inclusive, block_id)
# ---------------------------------------------------------------------------
LAYER_SPEC: list[tuple[int, int, str]] = [
    (Y_BEDROCK_FLOOR_BOTTOM, Y_BEDROCK_FLOOR_TOP, BLOCK_BEDROCK),
    (Y_DEEPSTONE_BOTTOM,     Y_DEEPSTONE_TOP,     BLOCK_DEEPSLATE),
    (Y_STONE_BOTTOM,         Y_STONE_TOP,         BLOCK_STONE),
    (Y_DIRT_BOTTOM,          Y_DIRT_TOP,          BLOCK_DIRT),
    (Y_SURFACE,              Y_SURFACE,           BLOCK_GRASS),
    # Y1 to Y127 is air — no blocks needed (void default)
    (Y_CEILING,              Y_CEILING,           BLOCK_BEDROCK),
]


class WorldTemplate:
    """
    Generates the initial block layout for a new player world.

    Called once when a world is first created. Iterates over the
    256×256 playable area and sets blocks column by column.

    NOTE: This is intentionally synchronous and chunked.
    For large-scale generation, consider offloading to an async task
    using Endstone's scheduler to avoid tick stalls.
    """

    def __init__(self, plugin):
        self._plugin = plugin

    def generate(self, dimension: "Dimension", slot: "WorldSlot") -> None:
        """
        Fills the playable area of `slot` in `dimension` with the
        standard Growtopia-like layer stack.
        """
        min_x = slot.playable_min_x
        max_x = slot.playable_max_x
        min_z = slot.playable_min_z
        max_z = slot.playable_max_z

        self._plugin.logger.info(
            f"[WorldTemplate] Generating terrain for slot "
            f"({slot.slot_x},{slot.slot_z}) shard={slot.shard_id} "
            f"area=({min_x},{min_z})→({max_x},{max_z})"
        )

        # Place blocks layer by layer
        for y_min, y_max, block_id in LAYER_SPEC:
            for y in range(y_min, y_max + 1):
                for x in range(min_x, max_x + 1):
                    for z in range(min_z, max_z + 1):
                        try:
                            block = dimension.get_block(x, y, z)
                            block.set_type(block_id)
                        except Exception as e:
                            self._plugin.logger.warning(
                                f"[WorldTemplate] Failed to place {block_id} "
                                f"at ({x},{y},{z}): {e}"
                            )

        self._plugin.logger.info(
            f"[WorldTemplate] Done generating slot ({slot.slot_x},{slot.slot_z})"
        )

    def generate_async(self, dimension: "Dimension", slot: "WorldSlot") -> None:
        """
        Schedules terrain generation in small batches each tick to avoid
        server lag on world creation. Preferred over generate() on live servers.
        """
        min_x = slot.playable_min_x
        max_x = slot.playable_max_x
        min_z = slot.playable_min_z
        max_z = slot.playable_max_z

        # Flatten all placement jobs into a queue
        jobs: list[tuple[int, int, int, str]] = []
        for y_min, y_max, block_id in LAYER_SPEC:
            for y in range(y_min, y_max + 1):
                for x in range(min_x, max_x + 1):
                    for z in range(min_z, max_z + 1):
                        jobs.append((x, y, z, block_id))

        BATCH_SIZE = 4096   # Blocks placed per tick (tune to taste)
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
                    # Schedule next batch next tick
                    scheduler.run_task_later(self._plugin, process_batch, delay=1)
                    return
            # All done
            self._plugin.logger.info(
                f"[WorldTemplate] Async generation complete for "
                f"slot ({slot.slot_x},{slot.slot_z})"
            )

        scheduler.run_task(self._plugin, process_batch)
