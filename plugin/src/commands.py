"""
Terravia — commands.py
Handles all /join, /world, and /wadmin command dispatching.
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


WORLD_HELP = """§6§l== World Commands ==§r
§f/join <NAME>§7        — Enter or create a world
§f/world leave§7        — Return to the Hub
§f/world info [name]§7  — Show world info
§f/world lock§7         — Cycle: Unlocked → World Lock → Big Lock
§f/world add <player>§7 — Grant build access (owner only)
§f/world remove <p>§7   — Revoke build access (owner only)
§f/world kick <player>§7— Kick from your world (owner only)
§f/world ban <player>§7 — Ban from your world (owner only)
§f/world unban <p>§7    — Unban from your world (owner only)"""

ADMIN_HELP = """§c§l== Admin Commands ==§r
§f/wadmin shards§7      — Show fill level of all 10 dimension shards
§f/wadmin tp <name>§7   — Teleport to any world (bypasses lock/ban)"""


class CommandHandler:
    def __init__(self, plugin, wm: "WorldManager", chat: "ChatManager",
                 shards: "ShardManager", db: "Database"):
        self._plugin = plugin
        self._wm    = wm
        self._chat  = chat
        self._shards = shards
        self._db    = db

    # ------------------------------------------------------------------
    # /join <NAME>  — primary world entry (join or create)
    # ------------------------------------------------------------------

    def on_join(self, sender: "CommandSender", args: list[str]) -> bool:
        if not self._require_player(sender):
            return True
        if not args:
            sender.send_message("§cUsage: §f/join <WORLD NAME>")
            return True
        return self._cmd_join_or_create(sender, args[0])

    # ------------------------------------------------------------------
    # /world <subcommand>
    # ------------------------------------------------------------------

    def on_world(self, sender: "CommandSender", args: list[str]) -> bool:
        if not args:
            sender.send_message(WORLD_HELP)
            return True

        sub = args[0].lower()

        if sub == "leave":
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
        elif sub == "help":
            sender.send_message(WORLD_HELP)
        else:
            sender.send_message(
                f"§cUnknown subcommand: §f{args[0]}§c. "
                f"Did you mean §f/join {args[0]}§c?"
            )
        return True

    # ------------------------------------------------------------------
    # /wadmin <subcommand>
    # ------------------------------------------------------------------

    def on_wadmin(self, sender: "CommandSender", args: list[str]) -> bool:
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
    # Subcommand implementations
    # ------------------------------------------------------------------

    def _cmd_join_or_create(self, sender, world_name: str):
        ok, msg = self._wm.join_or_create(sender, world_name)
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
            sender.send_message("§cYou are not in a world. Use §f/world info <name>§c.")
            return True

        world = self._db.get_world(world_id)
        if not world:
            sender.send_message(f"§cWorld §f{world_id}§c not found.")
            return True

        lock_names = {
            LockLevel.NONE:       "§aUnlocked",
            LockLevel.WORLD_LOCK: "§eWorld Lock",
            LockLevel.BIG_LOCK:   "§cBig Lock",
        }
        sender.send_message(
            f"§6§l{world.world_id}§r\n"
            f"§7Owner: §f{world.owner_name}\n"
            f"§7Lock:  {lock_names[world.lock_level]}\n"
            f"§7Shard: §f{world.shard_id}§7  Slot: §f({world.slot_x}, {world.slot_z})\n"
            f"§7Description: §f{world.description or '(none)'}"
        )
        return True

    def _cmd_lock(self, sender, args):
        if not self._require_player(sender):
            return True
        world_id = self._wm.get_player_world_id(sender)
        if not world_id:
            sender.send_message("§cYou must be inside your world to change its lock.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the world owner can change the lock.")
            return True

        new_level = (world.lock_level + 1) % 3
        self._db.set_lock_level(world_id, new_level)
        names = {0: "§aUnlocked", 1: "§eWorld Locked", 2: "§cBig Locked"}
        sender.send_message(f"§7{world_id} is now {names[new_level]}§7.")
        return True

    def _cmd_kick(self, sender, args):
        if not self._require_player(sender) or not args:
            return True
        world_id = self._wm.get_player_world_id(sender)
        if not world_id:
            sender.send_message("§cYou must be in your world to kick players.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the owner can kick players.")
            return True
        target = self._plugin.server.get_player(args[0])
        if not target:
            sender.send_message(f"§cPlayer §f{args[0]}§c not found.")
            return True
        if self._wm.get_player_world_id(target) != world_id:
            sender.send_message(f"§f{target.name}§c is not in your world.")
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
            sender.send_message("§cYou must be in your world to ban players.")
            return True
        world = self._db.get_world(world_id)
        if str(sender.unique_id) != world.owner_uuid:
            sender.send_message("§cOnly the owner can ban players.")
            return True
        target = self._plugin.server.get_player(args[0])
        if not target:
            sender.send_message("§cPlayer must be online to ban.")
            return True
        reason = " ".join(args[1:]) if len(args) > 1 else ""
        self._db.ban_player(world_id, str(target.unique_id), sender.name, reason)
        if self._wm.get_player_world_id(target) == world_id:
            self._wm.leave_world(target)
        target.send_message(f"§cYou were banned from §f{world_id}§c.")
        sender.send_message(f"§aBanned §f{target.name}§a from §f{world_id}§a.")
        self._plugin.tablist_manager.update_all()
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
        # Note: unban by name requires a UUID lookup; basic version accepts online players
        target = self._plugin.server.get_player(args[0])
        if not target:
            sender.send_message(f"§cPlayer §f{args[0]}§c must be online to unban.")
            return True
        self._db.unban_player(world_id, str(target.unique_id))
        sender.send_message(f"§aUnbanned §f{target.name}§a from §f{world_id}§a.")
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
            filled = int(s["pct_full"] / 5)
            bar = "§a" + "█" * filled + "§7" + "░" * (20 - filled)
            lines.append(
                f"§7Shard §f{s['shard_id']}§7: "
                f"§f{s['allocated']:,}§7/§8{s['capacity']:,} "
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
        if ok:
            self._plugin.tablist_manager.update_all()
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
