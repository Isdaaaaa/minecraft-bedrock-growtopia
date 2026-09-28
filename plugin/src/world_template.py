"""
Terravia — world_template.py
Generates the initial block layout for a freshly created world slot.

Vertical layout (no ceiling — open sky):
  Y 320      Vanilla sky limit (open)
  Y 195+     Air (block placement blocked via plugin above Y194)
  Y 194      Build cap — 256 blocks above bedrock floor
  Y 1–193    Build air space
  Y 0        Grass block ← ground level
  Y -1 to -4 Dirt (4 layers)
  Y -5 to -19 Stone (15 layers)
  Y -20 to -61 Deepslate (42 layers)
  Y -62 to -64 Bedrock floor (3 layers, unbreakable)

Horizontal: 256×256 playable blocks per world slot.
Total build space when cleared: 256×256×256 blocks.

Surface extras (added per new world):
  - Gravel patches (3-5 × 3×3 on surface)
  - Oak trees (4-6, simple trunk+leaves)

Underground extras (per new world):
  - Coal ore veins (40 clusters, Y-5 to Y-19)
  - Iron ore veins (20 clusters, Y-10 to Y-19)
  - Gold ore veins (6 clusters, Y-50 to Y-61)
  - Diamond ore veins (2 clusters, Y-58 to Y-64)
  - Water pockets (2-3 small, Y-40 to Y-55)
  - Lava pockets (1-2 small, Y-50 to Y-61)
"""

from __future__ import annotations
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from endstone.level import Dimension
    from .models import WorldSlot

# ---------------------------------------------------------------------------
# Block IDs
# ---------------------------------------------------------------------------
BLOCK_BEDROCK   = "minecraft:bedrock"
BLOCK_DEEPSLATE = "minecraft:deepslate"
BLOCK_STONE     = "minecraft:stone"
BLOCK_DIRT      = "minecraft:dirt"
BLOCK_GRASS     = "minecraft:grass_block"
BLOCK_GRAVEL    = "minecraft:gravel"
BLOCK_COAL_ORE  = "minecraft:coal_ore"
BLOCK_IRON_ORE  = "minecraft:iron_ore"
BLOCK_GOLD_ORE  = "minecraft:gold_ore"
BLOCK_DIAMOND   = "minecraft:diamond_ore"
BLOCK_WATER     = "minecraft:water"
BLOCK_LAVA      = "minecraft:lava"
BLOCK_OAK_LOG   = "minecraft:oak_log"
BLOCK_OAK_LEAF  = "minecraft:oak_leaves"
BLOCK_AIR       = "minecraft:air"

# ---------------------------------------------------------------------------
# Y-level constants (exported for world_manager boundary checks)
# ---------------------------------------------------------------------------
Y_BEDROCK_FLOOR_BOTTOM = -64
Y_BEDROCK_FLOOR_TOP    = -62
Y_DEEPSLATE_BOTTOM     = -61
Y_DEEPSLATE_TOP        = -20
Y_STONE_BOTTOM         = -19
Y_STONE_TOP            = -5
Y_DIRT_BOTTOM          = -4
Y_DIRT_TOP             = -1
Y_SURFACE              = 0
Y_BUILD_MIN            = -61   # First non-bedrock layer
Y_BUILD_MAX            = 194   # 256 blocks above Y_BUILD_MIN (inclusive)

# ---------------------------------------------------------------------------
# Base layer spec  — (y_min, y_max_inclusive, block_id)
# ---------------------------------------------------------------------------
LAYER_SPEC: list[tuple[int, int, str]] = [
    (Y_BEDROCK_FLOOR_BOTTOM, Y_BEDROCK_FLOOR_TOP, BLOCK_BEDROCK),
    (Y_DEEPSLATE_BOTTOM,     Y_DEEPSLATE_TOP,     BLOCK_DEEPSLATE),
    (Y_STONE_BOTTOM,         Y_STONE_TOP,         BLOCK_STONE),
    (Y_DIRT_BOTTOM,          Y_DIRT_TOP,          BLOCK_DIRT),
    (Y_SURFACE,              Y_SURFACE,           BLOCK_GRASS),
]

# Batch size for async generation (blocks per tick)
# At 20 tps, 16 384 blocks/tick → ~260 ticks (~13 s) for base layers
BATCH_SIZE = 16_384


class WorldTemplate:
    """
    Generates the initial block layout for a new player world slot.
    Uses async batched placement (BATCH_SIZE blocks/tick) to avoid lag spikes.
    """

    def __init__(self, plugin):
        self._plugin = plugin

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def generate_async(self, dimension: "Dimension", slot: "WorldSlot") -> None:
        """Queue all block placements and process them across ticks."""
        min_x, max_x = slot.playable_min_x, slot.playable_max_x
        min_z, max_z = slot.playable_min_z, slot.playable_max_z

        jobs: list[tuple[int, int, int, str]] = []

        # 1. Base layers
        self._add_base_layers(jobs, min_x, max_x, min_z, max_z)

        # 2. Surface patches (gravel)
        self._add_surface_patches(jobs, min_x, max_x, min_z, max_z)

        # 3. Underground ores
        self._add_ores(jobs, min_x, max_x, min_z, max_z)

        # 4. Water & lava pockets
        self._add_fluid_pockets(jobs, min_x, max_x, min_z, max_z)

        # 5. Trees (added last so logs overwrite grass properly)
        self._add_trees(jobs, min_x, max_x, min_z, max_z)

        self._plugin.logger.info(
            f"[WorldTemplate] Queued {len(jobs):,} block ops for "
            f"slot ({slot.slot_x},{slot.slot_z}) shard={slot.shard_id}"
        )

        scheduler = self._plugin.server.scheduler
        job_iter  = iter(jobs)

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
                f"[WorldTemplate] Generation complete for "
                f"slot ({slot.slot_x},{slot.slot_z})"
            )

        scheduler.run_task(self._plugin, process_batch)

    # Synchronous fallback (dev/offline use only)
    def generate(self, dimension: "Dimension", slot: "WorldSlot") -> None:
        min_x, max_x = slot.playable_min_x, slot.playable_max_x
        min_z, max_z = slot.playable_min_z, slot.playable_max_z
        jobs: list[tuple[int, int, int, str]] = []
        self._add_base_layers(jobs, min_x, max_x, min_z, max_z)
        self._add_surface_patches(jobs, min_x, max_x, min_z, max_z)
        self._add_ores(jobs, min_x, max_x, min_z, max_z)
        self._add_fluid_pockets(jobs, min_x, max_x, min_z, max_z)
        self._add_trees(jobs, min_x, max_x, min_z, max_z)
        for x, y, z, block_id in jobs:
            try:
                dimension.get_block(x, y, z).set_type(block_id)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Layer builders
    # ------------------------------------------------------------------

    def _add_base_layers(self, jobs, min_x, max_x, min_z, max_z):
        for y_min, y_max, block_id in LAYER_SPEC:
            for y in range(y_min, y_max + 1):
                for x in range(min_x, max_x + 1):
                    for z in range(min_z, max_z + 1):
                        jobs.append((x, y, z, block_id))

    def _add_surface_patches(self, jobs, min_x, max_x, min_z, max_z):
        """Scatter gravel patches on the grass surface for visual variety."""
        patch_count = random.randint(3, 6)
        for _ in range(patch_count):
            cx = random.randint(min_x + 5, max_x - 5)
            cz = random.randint(min_z + 5, max_z - 5)
            r  = random.randint(1, 2)   # radius 1–2 → 3×3 or 5×5 patch
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    if abs(dx) + abs(dz) <= r + 1:   # rough circle
                        jobs.append((cx + dx, Y_SURFACE, cz + dz, BLOCK_GRAVEL))

    def _add_ores(self, jobs, min_x, max_x, min_z, max_z):
        """Place ore clusters at appropriate depths."""
        specs = [
            # (block, vein_count, vein_max_radius, y_min, y_max)
            (BLOCK_COAL_ORE, 40, 1, Y_STONE_BOTTOM, Y_STONE_TOP),
            (BLOCK_IRON_ORE, 20, 1, Y_STONE_BOTTOM - 5, Y_STONE_TOP),
            (BLOCK_GOLD_ORE,  6, 1, Y_DEEPSLATE_BOTTOM, -40),
            (BLOCK_DIAMOND,   2, 0, Y_DEEPSLATE_BOTTOM, -55),
        ]
        for block_id, veins, radius, y_low, y_high in specs:
            y_low_clamped  = max(y_low,  Y_BUILD_MIN)
            y_high_clamped = min(y_high, Y_STONE_TOP)
            if y_low_clamped > y_high_clamped:
                y_low_clamped, y_high_clamped = y_high, y_low  # swap for deepslate range
            for _ in range(veins):
                cx = random.randint(min_x + 2, max_x - 2)
                cy = random.randint(y_low_clamped, y_high_clamped)
                cz = random.randint(min_z + 2, max_z - 2)
                # Place a small cluster
                vein_size = random.randint(1, max(1, radius * 2 + 1))
                for i in range(vein_size):
                    ox = random.randint(-radius, radius)
                    oy = random.randint(-radius, radius)
                    oz = random.randint(-radius, radius)
                    # Only replace stone/deepslate (not bedrock)
                    ty = cy + oy
                    if Y_BEDROCK_FLOOR_TOP < ty <= Y_STONE_TOP:
                        jobs.append((cx + ox, ty, cz + oz, block_id))

    def _add_fluid_pockets(self, jobs, min_x, max_x, min_z, max_z):
        """Place small water and lava pockets deep in the deepslate layer."""
        # Water pockets — Y -40 to -50
        for _ in range(random.randint(2, 3)):
            cx = random.randint(min_x + 8, max_x - 8)
            cz = random.randint(min_z + 8, max_z - 8)
            cy = random.randint(-50, -40)
            # 2×2×2 pocket carved into deepslate
            for dx in range(2):
                for dy in range(2):
                    for dz in range(2):
                        jobs.append((cx + dx, cy + dy, cz + dz, BLOCK_WATER))

        # Lava pockets — Y -55 to -61 (very deep)
        for _ in range(random.randint(1, 2)):
            cx = random.randint(min_x + 8, max_x - 8)
            cz = random.randint(min_z + 8, max_z - 8)
            cy = random.randint(-61, -55)
            for dx in range(2):
                for dy in range(1):   # 2×1×2 (flatter, less dramatic)
                    for dz in range(2):
                        jobs.append((cx + dx, cy + dy, cz + dz, BLOCK_LAVA))

    def _add_trees(self, jobs, min_x, max_x, min_z, max_z):
        """
        Scatter 4–6 simple oak trees on the surface.
        Each tree: 4-log trunk (Y1–Y4) + layered leaf canopy.
        Keeps 6 blocks from world edge and 7 blocks between trees.
        """
        tree_count = random.randint(4, 6)
        placed: list[tuple[int, int]] = []

        attempts = 0
        while len(placed) < tree_count and attempts < 200:
            attempts += 1
            tx = random.randint(min_x + 6, max_x - 6)
            tz = random.randint(min_z + 6, max_z - 6)

            # Enforce minimum spacing
            too_close = any(
                abs(tx - px) < 7 and abs(tz - pz) < 7
                for px, pz in placed
            )
            if too_close:
                continue

            placed.append((tx, tz))
            trunk_height = random.randint(4, 5)

            # Trunk
            for y in range(1, trunk_height + 1):
                jobs.append((tx, y, tz, BLOCK_OAK_LOG))

            # Canopy: 3×3 at top two layers, 5×5 one below, single block above
            top_y = trunk_height
            leaf_layers = [
                (top_y + 1, 2),   # y=top+1, radius 2 → 5×5 with corners missing
                (top_y + 2, 1),   # y=top+2, radius 1 → 3×3
                (top_y + 3, 1),   # y=top+3, 3×3
                (top_y + 4, 0),   # y=top+4, single leaf
            ]
            for ly, r in leaf_layers:
                for dx in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        # Skip corners for large radius (rounder look)
                        if r >= 2 and abs(dx) == r and abs(dz) == r:
                            continue
                        lx, lz = tx + dx, tz + dz
                        if min_x <= lx <= max_x and min_z <= lz <= max_z:
                            jobs.append((lx, ly, lz, BLOCK_OAK_LEAF))
