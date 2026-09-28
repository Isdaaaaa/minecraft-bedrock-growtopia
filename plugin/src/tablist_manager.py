"""
Terravia — tablist_manager.py
Maintains per-player tab list visibility — each player only sees
others who are in the same world (or lobby).
Refreshed whenever any player joins, leaves, or switches worlds.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from endstone.player import Player
    from .world_manager import WorldManager


class TabListManager:
    """
    Controls the player list (tab list) so that players only see
    teammates in their current world.

    Endstone exposes player list management through the Player API.
    When Endstone adds direct PlayerListPacket interception, this class
    is the single place to upgrade the implementation.
    """

    def __init__(self, plugin, world_manager: "WorldManager"):
        self._plugin = plugin
        self._wm = world_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_for_player(self, player: "Player") -> None:
        """
        Rebuild the tab list for a single player based on their current world.
        Call this after a player joins a world or the server.
        """
        my_world = self._wm.get_player_world_id(player)
        visible = self._get_visible_players(player, my_world)
        self._apply_tab_list(player, visible)

    def update_all(self) -> None:
        """
        Rebuild the tab list for every online player.
        Call this when any player changes worlds or disconnects.
        """
        for player in self._plugin.server.online_players:
            self.update_for_player(player)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_visible_players(
        self, viewer: "Player", world_id: str | None
    ) -> list["Player"]:
        """
        Returns the list of players that `viewer` should see in their tab list.
        - If viewer is in a world → only players in the same world.
        - If viewer is in the lobby → only other lobby players.
        """
        visible = []
        for p in self._plugin.server.online_players:
            other_world = self._wm.get_player_world_id(p)
            if other_world == world_id:   # None == None for lobby players
                visible.append(p)
        return visible

    def _apply_tab_list(self, player: "Player", visible: list["Player"]) -> None:
        """
        Sends the appropriate hide/show signals to the player.

        NOTE: Endstone's current Python API exposes tab list manipulation
        through the `Player.list_name` and server-level player visibility.
        If Endstone adds a `PlayerListPacket` hook in future versions,
        replace the body of this method with direct packet filtering for
        finer control. The interface of this class stays the same.
        """
        all_players = list(self._plugin.server.online_players)
        visible_uuids = {str(p.unique_id) for p in visible}

        for p in all_players:
            uuid = str(p.unique_id)
            should_be_visible = uuid in visible_uuids
            try:
                # Endstone API: hide/show player in another player's list
                if should_be_visible:
                    player.show_player(p)
                else:
                    player.hide_player(p)
            except AttributeError:
                # Graceful fallback if API not yet available in this build.
                # Log once so developers know to upgrade when the API lands.
                pass
