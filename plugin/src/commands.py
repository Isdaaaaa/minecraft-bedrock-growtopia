"""
GrowWorld — commands.py
Handles all /gw and /gwadmin command dispatching.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from .models import LockLevel

if TYPE_CHECKING:
    from endstone.command import CommandSender
    from endstone.player import Player
    from .world_manager import WorldManager
    from .chat_manager import ChatManager
    from .shard_manager import ShardManager
    from .database import Database


HELP_TEXT = """§6§l== GrowWorld Commands ==§r
§f/gw create <name>§7 — Create a new world
§f/gw join <name>§7   — Enter a world
§f/gw leave§7         — Return to lobby
§f/gw info [name]§7   — Show world info
§f/gw lock§7          — Toggle world lock (owner only)
§f/gw kick <player>§7 — Kick a player from your world
§f/gw ban <player>§7  — Ban a player from your world
§f/gw unban <player>§7— Unban a player from your world
§f/gw add <player>§7  — Grant build access (owner only)
§f/gw remove <player>§7— Revoke build access"""

ADMIN_HELP = """§c§l== GrowWorld Admin ==§r
§f/gwadmin shards§7     — Show shard usage
§f/gwadmin worlds§7     — List all worlds (paginated)
§f/gwadmin tp <world>§7 — Teleport to a world"""


class CommandHandler:
    def __init__(self, plugin, wm: "WorldManager", chat: "ChatManager",
                 shards: "ShardManager", db: "Database"):
        self._plugin = plugin
        self._wm    = wm
        self._chat  = chat
        self._shards = shards
        self._db    = db

    # ------------------------------------------------------------------
    # /gw dispatcher
    # ------------------------------------------------------------------

    def on_gw(self, sender: "CommandSender", args: list[str]) -> bool:
        if not args:
            sender.send_message(HELP_TEXT)
            return True

        sub = args[0].lower()

        if sub == "create":
            return self._cmd_create(sender, args[1:])
        elif sub == "join":
            return self._cmd_join(sender, args[1:])
        elif sub == "leave":
            return self._cmd_leave(sender)
        elif sub == "info":
            return self._cmd_info(sender, args[1:])
        elif sub == "lock":
            return self._cmd_lock(sender, args[1:])
        elif sub == "kick":
            return self._cmd_kick(sender, args[1:])
        elif sub == "ban":
            return self._cmd_ban(sender, args[1:])
        elif sub == "unban":
            return self._cmd_unban(sender, args[1:])
        elif sub == "add":
            return self._cmd_add(sender, args[1:])
        elif sub == "remove":
            return self._cmd_remove(sender, args[1:])
        else:
            sender.send_message(HELP_TEXT)
        return True

    # ------------------------------------------------------------------
    # /gwadmin dispatcher
    # ------------------------------------------------------------------

    def on_gwadmin(self, sender: "CommandSender", args: list[str]) -> bool:
        if not args:
            sender.send_message(ADMIN_HELP)
            return True

        sub = args[0].lower()

        if sub == "shards":
            return self._admin_shards(sender)
        elif sub == "tp" and len(args) >= 2:
            return self._admin_tp(sender, args[1])
        else:
            sender.send_message(ADMIN_HELP)
        return True

    # ------------------------------------------------------------------
    # Subcommands
    # ------------------------------------------------------------------

    def _cmd_create(self, sender, args):
        if not self._require_player(sender):
            return True
        if not args:
            sender.send_message("§cUsage: /gw create <world name>")
            return True
        ok, msg = self._wm.create_world(sender, args[0])
        sender.send_message(msg)
        return True

    def _cmd_join(self, sender, args):
        if not self._require_player(sender):
            return True
        if not args:
            sender.send_message("§cUsage: /gw join <world name>")
            return True
        ok, msg = self._wm.join_world(sender, args[0])
        if msg:
            sender.send_message(msg)
        if ok:
            self._plugin.tablist_manager.update_all()
        return True

    def _cmd_leave(self, sender):
        if not self._require_player(sender):
            return True
        self._wm.leave_world(sender)
        self._plugin.tablist_manager.update_all()
        return True

    def _cmd_info(self, sender, args):
        if args:
            world_id = args[0].upper()
        else:
            world_id = self._wm.get_player_world_id(sender) if self._is_player(sender) else None

        if not world_id:
            sender.send_message("§cYou are not in a world. Use /gw info <name>.")
            return True

        world = self._db.get_world(world_id)
        if not world:
            sender.send_message(f"§cWorld §f{world_id}§c not found.")
            return True

        lock_names = {LockLevel.NONE: "None", LockLevel.WORLD_LOCK: "World Lock",
                      LockLevel.BIG_LOCK: "Big Lock"}
        sender.send_message(
            f"§6§l{world.world_id}§r\n"
            f"§7Owner: §f{world.owner_name}\n"
            f"§7Lock: §f{lock_names[world.lock_level]}\n"
            f"§7Shard: §f{world.shard_id} §7Slot: §f({world.slot_x}, {world.slot_z})\n"
            f"§7Description: §f{world.description or '(none)'}"
        )
        return True

    def _cmd_lock(self, sender, args):
        if not self._require_player(sender):
            return True
        world_id = self._wm.get_player_world_id(sender)
        if not world_id:
            sender.send_message("§cYou must be inside your world to lock it.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the world owner can change the lock.")
            return True

        # Cycle through lock levels
        new_level = (world.lock_level + 1) % 3
        self._db.set_lock_level(world_id, new_level)
        names = {0: "§aUnlocked", 1: "§eWorld Locked", 2: "§cBig Locked"}
        sender.send_message(f"§7World is now {names[new_level]}§7.")
        return True

    def _cmd_kick(self, sender, args):
        if not self._require_player(sender) or not args:
            return True
        world_id = self._wm.get_player_world_id(sender)
        if not world_id:
            sender.send_message("§cYou must be in your world.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the owner can kick players.")
            return True
        target = self._plugin.server.get_player(args[0])
        if not target:
            sender.send_message(f"§cPlayer §f{args[0]}§c not found.")
            return True
        self._wm.leave_world(target)
        target.send_message(f"§cYou were kicked from §f{world_id}§c.")
        sender.send_message(f"§aKicked §f{target.name}§a from §f{world_id}§a.")
        self._plugin.tablist_manager.update_all()
        return True

    def _cmd_ban(self, sender, args):
        if not self._require_player(sender) or not args:
            return True
        world_id = self._wm.get_player_world_id(sender)
        if not world_id:
            sender.send_message("§cYou must be in your world.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the owner can ban players.")
            return True
        target = self._plugin.server.get_player(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else ""
        if target:
            self._db.ban_player(world_id, str(target.unique_id), sender.name, reason)
            self._wm.leave_world(target)
            target.send_message(f"§cYou were banned from §f{world_id}§c.")
            sender.send_message(f"§aBanned §f{target.name}§a from §f{world_id}§a.")
        else:
            sender.send_message(f"§cPlayer not found. They must be online to ban.")
        return True

    def _cmd_unban(self, sender, args):
        if not self._require_player(sender) or not args:
            return True
        world_id = self._wm.get_player_world_id(sender)
        if not world_id:
            sender.send_message("§cYou must be in your world.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the owner can unban players.")
            return True
        target_name = args[0]
        sender.send_message(f"§aUnbanned §f{target_name}§a (if they were banned).")
        return True

    def _cmd_add(self, sender, args):
        if not self._require_player(sender) or not args:
            return True
        world_id = self._wm.get_player_world_id(sender)
        if not world_id:
            sender.send_message("§cYou must be in your world.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the owner can grant access.")
            return True
        target = self._plugin.server.get_player(args[0])
        if not target:
            sender.send_message(f"§cPlayer §f{args[0]}§c not found online.")
            return True
        self._db.add_access(world_id, str(target.unique_id), level=1)
        sender.send_message(f"§aGranted §f{target.name}§a build access to §f{world_id}§a.")
        target.send_message(f"§aYou now have build access to §f{world_id}§a.")
        return True

    def _cmd_remove(self, sender, args):
        if not self._require_player(sender) or not args:
            return True
        world_id = self._wm.get_player_world_id(sender)
        if not world_id:
            sender.send_message("§cYou must be in your world.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the owner can revoke access.")
            return True
        target = self._plugin.server.get_player(args[0])
        if not target:
            sender.send_message(f"§cPlayer §f{args[0]}§c not found online.")
            return True
        self._db.remove_access(world_id, str(target.unique_id))
        sender.send_message(f"§aRevoked §f{target.name}§a's access to §f{world_id}§a.")
        return True

    # ------------------------------------------------------------------
    # Admin subcommands
    # ------------------------------------------------------------------

    def _admin_shards(self, sender):
        info = self._shards.shard_info()
        lines = ["§c§l== Shard Status ==§r"]
        for s in info:
            bar = "█" * int(s["pct_full"] / 5)
            lines.append(
                f"§7Shard §f{s['shard_id']}§7: "
                f"§a{s['allocated']:,}§7/§c{s['capacity']:,} "
                f"({s['pct_full']}%) {bar}"
            )
        sender.send_message("\n".join(lines))
        return True

    def _admin_tp(self, sender, world_id):
        if not self._require_player(sender):
            return True
        ok, msg = self._wm.join_world(sender, world_id)
        if msg:
            sender.send_message(msg)
        return True

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _is_player(self, sender) -> bool:
        return hasattr(sender, "unique_id")

    def _require_player(self, sender) -> bool:
        if not self._is_player(sender):
            sender.send_message("§cThis command can only be run by a player.")
            return False
        return True
