"""
GrowWorld — chat_manager.py
Intercepts all player chat and re-routes it to only players
in the same world. Server-wide broadcasts bypass this entirely.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from endstone.event.player import PlayerChatEvent
    from .world_manager import WorldManager

# Chat format per context
WORLD_CHAT_FORMAT  = "§7[§a{world}§7] §f{name}§7: §r{message}"
LOBBY_CHAT_FORMAT  = "§7[§eLobby§7] §f{name}§7: §r{message}"


class ChatManager:
    """
    Cancels the default global chat broadcast and re-sends the message
    only to players sharing the same world as the sender.
    Players in the lobby hear only other lobby players.
    """

    def __init__(self, plugin, world_manager: "WorldManager"):
        self._plugin = plugin
        self._wm = world_manager

    def handle_chat(self, event: "PlayerChatEvent") -> None:
        event.cancelled = True   # Stop the default global broadcast

        player     = event.player
        message    = event.message
        sender_wid = self._wm.get_player_world_id(player)

        if sender_wid:
            formatted = WORLD_CHAT_FORMAT.format(
                world=sender_wid,
                name=player.name,
                message=message,
            )
            # Send only to co-inhabitants of the same world
            for target in self._wm.get_players_in_world(sender_wid):
                target.send_message(formatted)
        else:
            # Sender is in the lobby — broadcast to all lobby players
            formatted = LOBBY_CHAT_FORMAT.format(
                name=player.name,
                message=message,
            )
            for target in self._plugin.server.online_players:
                if self._wm.get_player_world_id(target) is None:
                    target.send_message(formatted)

        # Always echo to server console for logging
        self._plugin.logger.info(f"[CHAT] {formatted}")

    def broadcast_to_world(self, world_id: str, message: str) -> None:
        """Send a message to everyone currently inside a specific world."""
        for player in self._wm.get_players_in_world(world_id):
            player.send_message(message)

    def server_broadcast(self, message: str) -> None:
        """
        True server-wide broadcast — reaches ALL players regardless of world.
        Use for announcements, maintenance warnings, etc.
        """
        self._plugin.server.broadcast_message(message)
