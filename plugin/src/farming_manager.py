"""
Terravia — farming_manager.py
Handles seed planting, growth ticks, splicing, harvesting,
crafting disablement, Miner's Gloves Haste effect, and discovery tooltips.
"""

from __future__ import annotations
import json
import math
import os
import random
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from endstone.player import Player
    from endstone.event.block import BlockBreakEvent
    from endstone.event.player import PlayerInteractEvent
    from endstone.level import Dimension

# ---------------------------------------------------------------------------
# Seedling visual blocks (vanilla — no custom block needed yet)
# ---------------------------------------------------------------------------
# Normal seedling  → minecraft:wheat        (growth stages 0–7)
# Splicing seedling → minecraft:nether_wart  (growth stages 0–3, maps to 0–7)
SEEDLING_BLOCK     = "minecraft:wheat"
SPLICING_BLOCK     = "minecraft:nether_wart"
SEEDLING_MAX_STAGE = 7   # Fully grown at stage 7
SPLICING_MAX_STAGE = 3   # Fully grown at stage 3 (nether wart)

# How many times the scheduler calls tick() per grow_time_minutes
GROWTH_TICKS       = 8   # 8 ticks = 8 stages (0→7 for wheat)

# Internal seed type prefix used in item custom data
SEED_TAG_PREFIX    = "terravia_seed:"

# Rarity grow-time table (minutes)
RARITY_GROW_TIME   = {
    "common":    5,
    "uncommon":  15,
    "rare":      45,
    "very_rare": 120,
    "legendary": 480,
}

# Rarity drop table (min, max, redrop_chance)
RARITY_DROPS = {
    "common":    (1, 4, 0.40),
    "uncommon":  (1, 3, 0.30),
    "rare":      (1, 2, 0.20),
    "very_rare": (1, 2, 0.12),
    "legendary": (1, 1, 0.05),
}

# Blocks that liquids / bedrock — fist cannot break these
UNBREAKABLE_BLOCKS = {
    "minecraft:bedrock",
    "minecraft:water",
    "minecraft:lava",
    "minecraft:flowing_water",
    "minecraft:flowing_lava",
}


class FarmingManager:
    """
    Central system for Terravia's farming and splicing loop.

    Responsibilities:
    - Load blocks.json and splice_recipes.json
    - Handle seed planting (right-click dirt with seed)
    - Handle splicing (right-click seedling with second seed)
    - Advance growth stages on a per-minute scheduler tick
    - Handle harvest (break fully grown seedling)
    - Cancel vanilla crafting
    - Cancel fist breaking of bedrock/liquids
    - Apply Miner's Gloves Haste effect each tick
    - Update item discovery tooltips
    """

    def __init__(self, plugin, db):
        self._plugin = plugin
        self._db     = db
        self._blocks: dict  = {}
        self._recipes: dict = {}
        self._load_configs()
        self._schedule_growth_tick()

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_configs(self) -> None:
        base = os.path.join(
            os.path.dirname(__file__), "..", "..", "config"
        )
        blocks_path  = os.path.join(base, "blocks.json")
        recipes_path = os.path.join(base, "splice_recipes.json")

        with open(blocks_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            # Strip metadata keys starting with _
            self._blocks = {k: v for k, v in raw.items() if not k.startswith("_")}

        with open(recipes_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            self._recipes = {k: v for k, v in raw.items() if not k.startswith("_")}

        self._plugin.logger.info(
            f"[Farming] Loaded {len(self._blocks)} blocks, "
            f"{len(self._recipes)} splice recipes."
        )

    # ------------------------------------------------------------------
    # Block break gating (fist only — no tools)
    # ------------------------------------------------------------------

    def on_block_break(self, event: "BlockBreakEvent") -> None:
        block    = event.block
        block_id = block.type

        # Bedrock and liquids are unbreakable
        if block_id in UNBREAKABLE_BLOCKS:
            event.cancelled = True
            return

        # Check if this is a seedling/splicing plant the player is harvesting
        if block_id in (SEEDLING_BLOCK, SPLICING_BLOCK):
            self._on_seedling_break(event)
            return

        # Otherwise: cancel vanilla drops and apply our custom drop logic
        event.drop_experience = False
        # Cancel the default item drop
        # (Endstone: setting drops to empty or using event.cancelled for drops)
        self._apply_block_drop(event.player, block_id)

    def _apply_block_drop(self, player: "Player", block_id: str) -> None:
        """Roll custom seed drop for a broken block."""
        seed_type = self._find_seed_by_block(block_id)
        if seed_type is None:
            return   # Block has no associated seed — no drop

        cfg = self._blocks[seed_type]
        drop_chance = cfg.get("drop_chance", 0.3)

        if random.random() < drop_chance:
            self._give_seed(player, seed_type)
            self._record_discovery(player, seed_type)

    def _find_seed_by_block(self, block_id: str) -> Optional[str]:
        """Return the seed type whose block_id matches the broken block."""
        for seed_type, cfg in self._blocks.items():
            if cfg.get("block_id") == block_id:
                return seed_type
        return None

    # ------------------------------------------------------------------
    # Planting (right-click surface block with seed in hand)
    # ------------------------------------------------------------------

    def on_player_interact(self, event: "PlayerInteractEvent") -> None:
        player = event.player
        item   = player.inventory.item_in_main_hand
        if item is None:
            return

        seed_type = self._get_seed_type_from_item(item)
        if seed_type is None:
            return   # Not holding a seed

        block = event.block  # Block the player right-clicked
        if block is None:
            return

        # Check if clicking on an existing seedling → attempt splice
        if block.type in (SEEDLING_BLOCK, SPLICING_BLOCK):
            event.cancelled = True
            self._on_splice_attempt(player, block, seed_type)
            return

        # Otherwise attempt to plant on the clicked block
        event.cancelled = True
        self._on_plant_attempt(player, block, seed_type)

    def _on_plant_attempt(self, player: "Player", surface_block, seed_type: str) -> None:
        cfg          = self._blocks[seed_type]
        valid_bases  = cfg.get("plant_on", [])
        surface_id   = surface_block.type

        if surface_id not in valid_bases:
            player.send_message(
                f"§c{cfg['display']} can't be planted on §f{surface_id}§c."
            )
            return

        # The seedling is placed one block ABOVE the surface
        x, y, z = surface_block.x, surface_block.y + 1, surface_block.z
        dim      = surface_block.dimension

        # Check nothing is already there
        target = dim.get_block(x, y, z)
        if target.type != "minecraft:air":
            player.send_message("§cThere's no room to plant here.")
            return

        # Place the seedling
        target.set_type(SEEDLING_BLOCK)
        self._set_growth_stage(dim, x, y, z, 0)

        # Record in DB
        world_id = self._plugin.world_manager.get_player_world_id(player) or "__hub__"
        self._db.plant_seed(
            world_id=world_id,
            dimension_id=str(dim.name),
            x=x, y=y, z=z,
            seed_type=seed_type,
            planted_at=time.time(),
        )

        # Consume one seed from inventory
        self._consume_seed(player)

        player.send_message(
            f"§aPlanted §f{cfg['display']}§a. "
            f"Grows in §f{self._grow_minutes(seed_type)} min§a."
        )

    # ------------------------------------------------------------------
    # Splicing (right-click seedling with a different seed)
    # ------------------------------------------------------------------

    def _on_splice_attempt(self, player: "Player", seedling_block, held_seed: str) -> None:
        x, y, z = seedling_block.x, seedling_block.y, seedling_block.z
        dim      = seedling_block.dimension
        world_id = self._plugin.world_manager.get_player_world_id(player) or "__hub__"

        existing = self._db.get_planted_seed(str(dim.name), x, y, z)
        if existing is None:
            player.send_message("§cNo seedling data found here.")
            return

        if existing["is_splicing"]:
            player.send_message("§cThis seedling is already splicing!")
            return

        base_seed  = existing["seed_type"]
        recipe_key = self._make_recipe_key(base_seed, held_seed)
        result     = self._recipes.get(recipe_key)

        if result is None:
            player.send_message(
                f"§cNo splice recipe for §f{self._display(base_seed)} "
                f"§c+ §f{self._display(held_seed)}§c."
            )
            return

        # Change visual to nether wart (splicing indicator)
        seedling_block.set_type(SPLICING_BLOCK)
        self._set_growth_stage(dim, x, y, z, 0)

        # Update DB — mark as splicing
        self._db.mark_splicing(str(dim.name), x, y, z, held_seed, result)

        # Splice takes 2× the grow time of the slower seed
        base_rarity   = self._blocks.get(base_seed, {}).get("rarity", "common")
        held_rarity   = self._blocks.get(held_seed, {}).get("rarity", "common")
        rarity_order  = ["common", "uncommon", "rare", "very_rare", "legendary"]
        slower        = max(base_rarity, held_rarity, key=lambda r: rarity_order.index(r))
        splice_mins   = RARITY_GROW_TIME[slower] * 2

        self._consume_seed(player)

        result_cfg    = self._blocks.get(result, {})
        player.send_message(
            f"§eSplicing §f{self._display(base_seed)} §e+ §f{self._display(held_seed)} "
            f"§e→ §f{result_cfg.get('display', result)}§e. "
            f"Ready in §f{splice_mins} min§e."
        )
        self._record_discovery(player, result)

    # ------------------------------------------------------------------
    # Seedling break = harvest
    # ------------------------------------------------------------------

    def _on_seedling_break(self, event: "BlockBreakEvent") -> None:
        block    = event.block
        x, y, z = block.x, block.y, block.z
        dim      = block.dimension
        player   = event.player

        record = self._db.get_planted_seed(str(dim.name), x, y, z)
        if record is None:
            # Unknown seedling — allow normal break with no drops
            return

        stage = self._get_growth_stage(dim, x, y, z)
        is_splicing = record["is_splicing"]
        max_stage   = SPLICING_MAX_STAGE if is_splicing else SEEDLING_MAX_STAGE

        if stage < max_stage:
            # Not fully grown — destroy without drops, refund seed
            event.cancelled = True
            block.set_type("minecraft:air")
            self._db.remove_planted_seed(str(dim.name), x, y, z)
            seed_type = record["seed_type"]
            self._give_seed(player, seed_type)
            player.send_message(
                f"§eUprooted §f{self._display(seed_type)}§e early — seed returned."
            )
            return

        # Fully grown — harvest!
        event.cancelled = True
        block.set_type("minecraft:air")
        self._db.remove_planted_seed(str(dim.name), x, y, z)

        if is_splicing:
            result_type = record["splice_result"]
            self._give_seed(player, result_type)
            player.send_message(
                f"§aSplice complete! Got §f{self._display(result_type)}§a."
            )
            self._record_discovery(player, result_type)
        else:
            seed_type = record["seed_type"]
            cfg       = self._blocks.get(seed_type, {})
            rarity    = cfg.get("rarity", "common")
            min_d, max_d, redrop = RARITY_DROPS[rarity]

            # Drop block(s)
            drop_count = random.randint(min_d, max_d)
            if not cfg.get("is_item", False):
                for _ in range(drop_count):
                    self._give_block(player, cfg.get("block_id", "minecraft:air"))
            else:
                self._give_item(player, cfg.get("item_id", ""))

            # Seed redrop
            if random.random() < redrop:
                self._give_seed(player, seed_type)
                player.send_message(
                    f"§aHarvested §f{self._display(seed_type)} "
                    f"§a(§f{drop_count}§a block{'s' if drop_count > 1 else ''} + seed)."
                )
            else:
                player.send_message(
                    f"§aHarvested §f{self._display(seed_type)} "
                    f"§a(§f{drop_count}§a block{'s' if drop_count > 1 else ''})."
                )

    # ------------------------------------------------------------------
    # Growth tick (called by scheduler every minute)
    # ------------------------------------------------------------------

    def _schedule_growth_tick(self) -> None:
        scheduler = self._plugin.server.scheduler
        # Run every 60 seconds (1200 ticks at 20 tps)
        scheduler.run_task_timer(
            self._plugin, self._growth_tick, delay=1200, period=1200
        )

    def _growth_tick(self) -> None:
        """Advance all planted seeds that are due for a growth stage increase."""
        now    = time.time()
        plants = self._db.get_all_planted_seeds()

        for record in plants:
            seed_type    = record["seed_type"]
            is_splicing  = record["is_splicing"]
            planted_at   = record["planted_at"]
            current_stage = record["growth_stage"]

            # Determine grow time in seconds
            if is_splicing:
                rarity     = self._blocks.get(seed_type, {}).get("rarity", "common")
                splice_key = record.get("splice_partner", "")
                p_rarity   = self._blocks.get(splice_key, {}).get("rarity", "common")
                rarity_order = ["common", "uncommon", "rare", "very_rare", "legendary"]
                slower     = max(rarity, p_rarity, key=lambda r: rarity_order.index(r))
                total_secs = RARITY_GROW_TIME[slower] * 2 * 60
                max_stage  = SPLICING_MAX_STAGE
            else:
                rarity     = self._blocks.get(seed_type, {}).get("rarity", "common")
                total_secs = RARITY_GROW_TIME[rarity] * 60
                max_stage  = SEEDLING_MAX_STAGE

            elapsed        = now - planted_at
            expected_stage = min(
                math.floor(elapsed / total_secs * (max_stage + 1)),
                max_stage
            )

            if expected_stage > current_stage:
                self._db.update_growth_stage(
                    record["dimension_id"],
                    record["x"], record["y"], record["z"],
                    expected_stage,
                )
                # Update the in-world block stage
                try:
                    level = self._plugin.server.level
                    dim   = level.get_dimension(record["dimension_id"])
                    self._set_growth_stage(
                        dim,
                        record["x"], record["y"], record["z"],
                        expected_stage,
                    )
                except Exception as e:
                    self._plugin.logger.warning(
                        f"[Farming] Failed to update stage at "
                        f"({record['x']},{record['y']},{record['z']}): {e}"
                    )

    # ------------------------------------------------------------------
    # Miner's Gloves Haste effect
    # ------------------------------------------------------------------

    def apply_gloves_effect(self, player: "Player") -> None:
        """
        Called every 5 seconds (via scheduler) per online player.
        If the player holds Miner's Gloves, apply/refresh the Haste effect.
        """
        item = player.inventory.item_in_main_hand
        if item is None:
            return

        item_id = self._get_item_id(item)
        if item_id == "terravia:basic_miners_gloves":
            player.add_effect("minecraft:haste", duration=200, amplifier=0)   # Haste I, 10s
        elif item_id == "terravia:advanced_miners_gloves":
            player.add_effect("minecraft:haste", duration=200, amplifier=1)   # Haste II, 10s

    # ------------------------------------------------------------------
    # Discovery tooltips
    # ------------------------------------------------------------------

    def update_tooltip(self, player: "Player", seed_type: str) -> None:
        """
        Rebuilds the item lore for a seed/block in the player's hand
        to show known splice recipes. Called on inventory pickup events.
        """
        if seed_type not in self._blocks:
            return

        cfg        = self._blocks[seed_type]
        rarity     = cfg.get("rarity", "common")
        grow_mins  = self._grow_minutes(seed_type)
        min_d, max_d, redrop = RARITY_DROPS[rarity]

        lore = [
            f"§7Rarity: §f{rarity.replace('_', ' ').title()}",
            f"§7Grow time: §f{grow_mins} min",
            f"§7Drops: §f{min_d}–{max_d} block(s)  §7Seed redrop: §f{int(redrop*100)}%",
            "§8─────────────────",
        ]

        # Add known splice recipes
        known_recipes = self._get_known_splices(player, seed_type)
        if known_recipes:
            lore.append("§e§lKnown Splices:")
            for partner, result in known_recipes:
                lore.append(
                    f"§7+ §f{self._display(partner)} §7→ §a{self._display(result)}"
                )
        else:
            lore.append("§8No known splices yet.")

        # Count undiscovered
        total     = self._count_splices_for(seed_type)
        discovered = len(known_recipes)
        if total > discovered:
            lore.append(f"§8? + ??? → [{total - discovered} undiscovered]")

        # Apply lore to the item in hand
        try:
            item = player.inventory.item_in_main_hand
            if item and self._get_seed_type_from_item(item) == seed_type:
                item.lore = lore
                player.inventory.item_in_main_hand = item
        except Exception:
            pass

    def _get_known_splices(
        self, player: "Player", seed_type: str
    ) -> list[tuple[str, str]]:
        """Returns list of (partner_seed, result_seed) the player has discovered."""
        discovered = set(self._db.get_player_discoveries(str(player.unique_id)))
        known = []
        for recipe_key, result in self._recipes.items():
            parts = recipe_key.split("+")
            if len(parts) != 2:
                continue
            a, b = parts
            if seed_type in (a, b):
                partner = b if a == seed_type else a
                if partner in discovered or result in discovered:
                    known.append((partner, result))
        return known

    def _count_splices_for(self, seed_type: str) -> int:
        count = 0
        for key in self._recipes:
            parts = key.split("+")
            if len(parts) == 2 and seed_type in parts:
                count += 1
        return count

    # ------------------------------------------------------------------
    # Crafting disable
    # ------------------------------------------------------------------

    def on_craft_item(self, event) -> None:
        """Cancel ALL vanilla crafting — splicing is the only crafting system."""
        event.cancelled = True
        if hasattr(event, "player"):
            event.player.send_message(
                "§cCrafting is disabled. Use §f/splice §cor find a §fSplice Bench§c."
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _give_seed(self, player: "Player", seed_type: str) -> None:
        """Give the player one seed item of the given type."""
        cfg = self._blocks.get(seed_type, {})
        try:
            item = self._plugin.server.create_item(
                "minecraft:wheat_seeds", 1
            )
            # Encode seed type in item custom name so we can decode it later
            item.custom_name = f"§r{cfg.get('display', seed_type)}"
            item.set_nbt("terravia_seed_type", seed_type)
            player.inventory.add_item(item)
        except Exception as e:
            self._plugin.logger.warning(f"[Farming] Failed to give seed {seed_type}: {e}")

    def _give_block(self, player: "Player", block_id: str) -> None:
        if not block_id or block_id == "minecraft:air":
            return
        try:
            # Convert block ID to item ID (most are the same)
            item_id = block_id.replace("minecraft:", "minecraft:")
            item = self._plugin.server.create_item(item_id, 1)
            player.inventory.add_item(item)
        except Exception as e:
            self._plugin.logger.warning(f"[Farming] Failed to give block {block_id}: {e}")

    def _give_item(self, player: "Player", item_id: str) -> None:
        if not item_id:
            return
        try:
            item = self._plugin.server.create_item(item_id, 1)
            player.inventory.add_item(item)
        except Exception as e:
            self._plugin.logger.warning(f"[Farming] Failed to give item {item_id}: {e}")

    def _consume_seed(self, player: "Player") -> None:
        item = player.inventory.item_in_main_hand
        if item and item.amount > 1:
            item.amount -= 1
            player.inventory.item_in_main_hand = item
        else:
            player.inventory.item_in_main_hand = None

    def _get_seed_type_from_item(self, item) -> Optional[str]:
        try:
            return item.get_nbt("terravia_seed_type")
        except Exception:
            return None

    def _get_item_id(self, item) -> Optional[str]:
        try:
            return item.type
        except Exception:
            return None

    def _set_growth_stage(self, dim: "Dimension", x: int, y: int, z: int, stage: int) -> None:
        try:
            block = dim.get_block(x, y, z)
            block.set_block_state("growth", stage)
        except Exception:
            pass

    def _get_growth_stage(self, dim: "Dimension", x: int, y: int, z: int) -> int:
        try:
            block = dim.get_block(x, y, z)
            return block.get_block_state("growth")
        except Exception:
            return 0

    def _make_recipe_key(self, seed_a: str, seed_b: str) -> str:
        """Alphabetical key so order doesn't matter."""
        return "+".join(sorted([seed_a, seed_b]))

    def _grow_minutes(self, seed_type: str) -> int:
        rarity = self._blocks.get(seed_type, {}).get("rarity", "common")
        return RARITY_GROW_TIME.get(rarity, 5)

    def _display(self, seed_type: str) -> str:
        return self._blocks.get(seed_type, {}).get("display", seed_type)

    def _record_discovery(self, player: "Player", seed_type: str) -> None:
        self._db.record_discovery(str(player.unique_id), seed_type)
