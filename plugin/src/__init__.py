"""
GrowWorld — __init__.py
Main Endstone plugin entry point. Wires all subsystems together.
"""

from __future__ import annotations

from endstone.plugin import Plugin
from endstone.event import event_handler
from endstone.event.player import (
    PlayerJoinEvent,
    PlayerQuitEvent,
    PlayerChatEvent,
    PlayerMoveEvent,
)
from endstone.event.block import BlockBreakEvent, BlockPlaceEvent

from .database import Database
from .models import SLOT_SIZE, BUFFER, WORLD_SIZE
from .shard_manager import ShardManager
from .world_manager import WorldManager
from .chat_manager import ChatManager
from .tablist_manager import TabListManager
from .commands import CommandHandler


class GrowWorldPlugin(Plugin):
    api_version = "0.5"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_enable(self) -> None:
        self.logger.info("GrowWorld starting up…")

        # Persistence
        self.db = Database(self.data_folder)

        # Subsystems
        self.shard_manager  = ShardManager(self.db)
        self.world_manager  = WorldManager(self, self.db, self.shard_manager)
        self.chat_manager   = ChatManager(self, self.world_manager)
        self.tablist_manager = TabListManager(self, self.world_manager)
        self.cmd_handler    = CommandHandler(
            self,
            self.world_manager,
            self.chat_manager,
            self.shard_manager,
            self.db,
        )

        # Register all event listeners
        self.register_events(self)

        self.logger.info(
            f"GrowWorld ready. "
            f"Slot size: {SLOT_SIZE}×{SLOT_SIZE} blocks | "
            f"Playable: {WORLD_SIZE}×{WORLD_SIZE} | "
            f"Buffer: {BUFFER} blocks | "
            f"Shards: 10 pre-defined"
        )

    def on_disable(self) -> None:
        self.db.close()
        self.logger.info("GrowWorld shut down.")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def on_command(self, sender, command, args):
        name = command.name.lower()
        if name == "gw":
            return self.cmd_handler.on_gw(sender, list(args))
        if name == "gwadmin":
            return self.cmd_handler.on_gwadmin(sender, list(args))
        return False

    # ------------------------------------------------------------------
    # Events — Player lifecycle
    # ------------------------------------------------------------------

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent) -> None:
        player = event.player
        self.world_manager.on_player_join(player)
        # Wait 2 seconds (40 ticks) for client to finish loading, then send to hub
        self.server.scheduler.run_task_later(
            self,
            lambda: self.world_manager.send_to_hub(player),
            delay=40,
        )
        # Update tab lists after a short delay
        self.server.scheduler.run_task_later(
            self, lambda: self.tablist_manager.update_all(), delay=60
        )

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        self.world_manager.on_player_quit(event.player)
        self.tablist_manager.update_all()

    # ------------------------------------------------------------------
    # Events — Chat
    # ------------------------------------------------------------------

    @event_handler
    def on_player_chat(self, event: PlayerChatEvent) -> None:
        self.chat_manager.handle_chat(event)

    # ------------------------------------------------------------------
    # Events — Block interactions (permission + boundary)
    # ------------------------------------------------------------------

    @event_handler
    def on_block_break(self, event: BlockBreakEvent) -> None:
        self.world_manager.check_block_permission(event, "break")

    @event_handler
    def on_block_place(self, event: BlockPlaceEvent) -> None:
        self.world_manager.check_block_permission(event, "place")

    # ------------------------------------------------------------------
    # Events — Movement boundary enforcement
    # ------------------------------------------------------------------

    @event_handler
    def on_player_move(self, event: PlayerMoveEvent) -> None:
        """
        Prevents players from walking beyond their world's playable boundary.
        Teleports them back to the nearest in-bounds position.
        """
        player = event.player
        world_id = self.world_manager.get_player_world_id(player)
        if world_id is None:
            return   # Lobby — no boundary

        world = self.db.get_world(world_id)
        if world is None:
            return

        slot = world.slot
        to = event.to
        x, z = to.x, to.z

        if not slot.contains(x, z):
            # Clamp back to inside the boundary
            clamped_x = max(slot.playable_min_x, min(x, slot.playable_max_x - 1))
            clamped_z = max(slot.playable_min_z, min(z, slot.playable_max_z - 1))
            event.cancelled = True
            player.teleport(to.__class__(
                to.world, clamped_x, to.y, clamped_z, to.yaw, to.pitch
            ))
