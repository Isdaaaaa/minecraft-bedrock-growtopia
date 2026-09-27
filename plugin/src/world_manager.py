"""
GrowWorld — world_manager.py
Core world lifecycle: creation, joining, leaving, permission checks,
world border enforcement, and chunk sending restriction.
"""

from __future__ import annotations
import re
import time
from typing import Optional, Dict, TYPE_CHECKING

from .models import GrowWorld, PlayerSession, WorldSlot, LockLevel, SPAWN_Y
from .database import Database
from .shard_manager import ShardManager

if TYPE_CHECKING:
    from endstone.player import Player
    from endstone.event.block import BlockBreakEvent, BlockPlaceEvent


# World name validation — alphanumeric only, 3-24 chars, uppercase (like Growtopia)
_WORLD_NAME_RE = re.compile(r'^[A-Z0-9]{3,24}$')

WORLD_ENTRY_MESSAGE = "§a§lEntering §r§a{world_id}§r§7 — owned by §f{owner}"
WORLD_LEAVE_MESSAGE = "§7Left §f{world_id}§7."
NO_PERMISSION_MESSAGE = "§cYou don't have permission to do that here."


class WorldManager:
    """
    Manages world creation, player routing, and in-world permissions.
    One instance lives for the lifetime of the plugin.
    """

    def __init__(self, plugin, db: Database, shard_manager: ShardManager):
        self._plugin = plugin
        self._db = db
        self._shards = shard_manager

        # In-memory session map: player_uuid → PlayerSession
        self._sessions: Dict[str, PlayerSession] = {}

    # ------------------------------------------------------------------
    # World creation
    # ------------------------------------------------------------------

    def create_world(self, owner: "Player", world_id: str) -> tuple[bool, str]:
        """
        Creates a new world. Returns (success, message).
        """
        world_id = world_id.upper()

        if not _WORLD_NAME_RE.match(world_id):
            return False, "§cWorld name must be 3-24 alphanumeric characters."

        if self._db.world_exists(world_id):
            return False, f"§cWorld §f{world_id}§c already exists."

        slot = self._shards.allocate_slot()
        if slot is None:
            return False, "§cNo world slots available. Contact an admin."

        world = GrowWorld(
            world_id=world_id,
            owner_uuid=str(owner.unique_id),
            owner_name=owner.name,
            shard_id=slot.shard_id,
            slot_x=slot.slot_x,
            slot_z=slot.slot_z,
        )
        self._db.create_world(world)

        self._plugin.logger.info(
            f"World '{world_id}' created by {owner.name} "
            f"at shard={slot.shard_id} slot=({slot.slot_x},{slot.slot_z})"
        )
        return True, f"§aWorld §f{world_id}§a created! Use §f/gw join {world_id}§a to enter."

    # ------------------------------------------------------------------
    # Joining / leaving
    # ------------------------------------------------------------------

    def join_world(self, player: "Player", world_id: str) -> tuple[bool, str]:
        """Teleports a player into the given world."""
        world_id = world_id.upper()
        world = self._db.get_world(world_id)

        if world is None:
            return False, f"§cWorld §f{world_id}§c does not exist."

        if self._db.is_banned(world_id, str(player.unique_id)):
            return False, f"§cYou are banned from §f{world_id}§c."

        if not world.is_public:
            uuid = str(player.unique_id)
            is_owner = uuid == world.owner_uuid
            access = self._db.get_access_level(world_id, uuid)
            if not is_owner and access == 0:
                return False, f"§c{world_id}§c is private."

        # Teleport to the world's spawn point
        slot = world.slot
        self._teleport_to_world(player, slot)

        # Update session
        session = PlayerSession(
            player_uuid=str(player.unique_id),
            player_name=player.name,
            current_world_id=world_id,
        )
        self._sessions[str(player.unique_id)] = session
        self._db.set_player_session(session)
        self._db.update_last_visited(world_id)

        player.send_message(
            WORLD_ENTRY_MESSAGE.format(world_id=world_id, owner=world.owner_name)
        )
        return True, ""

    def leave_world(self, player: "Player") -> None:
        """Sends a player back to the server lobby/spawn."""
        world_id = self.get_player_world_id(player)
        if world_id:
            player.send_message(WORLD_LEAVE_MESSAGE.format(world_id=world_id))

        session = self._get_or_create_session(player)
        session.current_world_id = None
        self._sessions[str(player.unique_id)] = session
        self._db.set_player_session(session)

        # Teleport back to server lobby (0, 64, 0 in overworld)
        self._teleport_to_lobby(player)

    # ------------------------------------------------------------------
    # Player session helpers
    # ------------------------------------------------------------------

    def on_player_join(self, player: "Player") -> None:
        """Called when a player connects to the server."""
        session = PlayerSession(
            player_uuid=str(player.unique_id),
            player_name=player.name,
            current_world_id=None,   # Start in lobby
        )
        self._sessions[str(player.unique_id)] = session
        self._db.set_player_session(session)

    def on_player_quit(self, player: "Player") -> None:
        """Called when a player disconnects."""
        uuid = str(player.unique_id)
        self._sessions.pop(uuid, None)
        self._db.remove_player_session(uuid)

    def get_player_world_id(self, player: "Player") -> Optional[str]:
        session = self._sessions.get(str(player.unique_id))
        return session.current_world_id if session else None

    def get_players_in_world(self, world_id: str) -> list["Player"]:
        """Returns all currently online players in the given world."""
        result = []
        for p in self._plugin.server.online_players:
            if self.get_player_world_id(p) == world_id:
                result.append(p)
        return result

    def are_in_same_world(self, a: "Player", b: "Player") -> bool:
        return self.get_player_world_id(a) == self.get_player_world_id(b)

    # ------------------------------------------------------------------
    # Permission checks (called from block events)
    # ------------------------------------------------------------------

    def check_block_permission(self, event, action: str) -> None:
        """
        Cancels block break/place if the player lacks permission in that world.
        Also enforces the world boundary — players cannot build outside the
        256×256 playable area.
        """
        player = event.player
        block = event.block
        world_id = self.get_player_world_id(player)

        if world_id is None:
            # Player is in lobby — no building allowed
            event.cancelled = True
            player.send_message(NO_PERMISSION_MESSAGE)
            return

        world = self._db.get_world(world_id)
        if world is None:
            event.cancelled = True
            return

        slot = world.slot

        # Boundary check — outside the 256×256 playable area
        bx, bz = block.x, block.z
        if not slot.contains(bx, bz):
            event.cancelled = True
            player.send_message("§cYou cannot build outside this world's boundaries.")
            return

        # Permission check based on lock level
        uuid = str(player.unique_id)
        is_owner = uuid == world.owner_uuid
        access = self._db.get_access_level(world_id, uuid)

        if world.lock_level == LockLevel.NONE:
            return   # Anyone can build

        if world.lock_level == LockLevel.WORLD_LOCK:
            if is_owner or access >= 1:
                return
            event.cancelled = True
            player.send_message(f"§c{world_id}§c is locked. You don't have build access.")
            return

        if world.lock_level == LockLevel.BIG_LOCK:
            if is_owner:
                return
            event.cancelled = True
            player.send_message(f"§c{world_id}§c has a Big Lock. Only the owner can build.")
            return

    # ------------------------------------------------------------------
    # Chunk sending restriction
    # ------------------------------------------------------------------

    def should_send_chunk(self, player: "Player", chunk_x: int, chunk_z: int) -> bool:
        """
        Returns False if a chunk belongs to a different world than the player's.
        Used to prevent freecam or edge-case chunk leaks across world boundaries.
        """
        world_id = self.get_player_world_id(player)
        if world_id is None:
            return True   # Lobby — no restriction

        world = self._db.get_world(world_id)
        if world is None:
            return True

        slot = world.slot
        block_x = chunk_x * 16
        block_z = chunk_z * 16

        # Allow chunks within the slot's full footprint (including the buffer gap)
        in_slot_x = slot.origin_x <= block_x < slot.origin_x + 4096
        in_slot_z = slot.origin_z <= block_z < slot.origin_z + 4096
        return in_slot_x and in_slot_z

    # ------------------------------------------------------------------
    # Teleportation helpers
    # ------------------------------------------------------------------

    def _teleport_to_world(self, player: "Player", slot: WorldSlot) -> None:
        from endstone.util import Vector
        player.teleport(player.location.__class__(
            player.location.world,
            slot.spawn_x,
            SPAWN_Y,
            slot.spawn_z,
            yaw=0.0,
            pitch=0.0,
        ))

    def _teleport_to_lobby(self, player: "Player") -> None:
        from endstone.util import Vector
        loc = player.location
        player.teleport(loc.__class__(loc.world, 0.5, SPAWN_Y, 0.5, 0.0, 0.0))

    def _get_or_create_session(self, player: "Player") -> PlayerSession:
        uuid = str(player.unique_id)
        if uuid not in self._sessions:
            self._sessions[uuid] = PlayerSession(
                player_uuid=uuid,
                player_name=player.name,
                current_world_id=None,
            )
        return self._sessions[uuid]
