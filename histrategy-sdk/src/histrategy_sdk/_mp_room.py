"""MultiplayerRoom — high-level wrapper for multiplayer game flow.

Wraps ServerClient with a stateful room session for the multiplayer API.
"""

from __future__ import annotations

import time

from ._client import ServerClient


class MultiplayerRoom:
    """A stateful multiplayer room session.

    Usage:
        # Host creates a room with pre-assigned factions
        client = ServerClient(base_url="http://localhost:8080")
        result = MultiplayerRoom.create(
            client, {"caocao": "曹操", "liubei": "刘备", "sunquan": "孙权"}
        )

        # Player joins with their token
        room = MultiplayerRoom.join(
            client, result["room_id"], "caocao",
            result["player_links"][0]["player_token"]
        )

        # Player submits a decision
        resp = room.decide("发展农业，积蓄力量")
        print(resp["status"])  # "waiting" or "resolving"

        # Wait for all decisions and resolution
        final = room.wait_for_resolve(timeout=120)
        print(final["quarter"])  # advanced to next quarter
    """

    def __init__(
        self,
        client: ServerClient,
        room_id: str,
        faction: str,
        player_token: str,
        user_id: str = "",
    ):
        self.client = client
        self.room_id = room_id
        self.faction = faction  # display name (e.g. "caocao", "liubei")
        self.player_token = player_token
        self.user_id = user_id

    # ── Class Methods ─────────────────────────────────────

    @classmethod
    def create(
        cls,
        client: ServerClient,
        pre_assigned: dict[str, str] | None = None,
        scenario: str = "three-kingdoms",
        metadata: dict[str, str] | None = None,
        lang: str = "zh-CN",
    ) -> dict:
        """Host creates a multiplayer room.

        Args:
            client: ServerClient instance pointing at the histrategy server
            pre_assigned: Dict mapping faction display names to player names,
                e.g. {"caocao": "曹操", "liubei": "刘备"}
            scenario: Scenario ID (e.g. "three-kingdoms", "rome-triumvirate")
            metadata: Optional metadata (e.g. {"lang": "en"})
            lang: Language code ("zh-CN" or "en"). Merged into metadata.

        Returns:
            Dict with keys: room_id, host_token, phase, human_factions,
            player_links (list of {faction, player_name, player_token, url})
        """
        return client.create_room(
            pre_assigned=pre_assigned,
            scenario=scenario,
            metadata=metadata,
            lang=lang,
        )

    @classmethod
    def join(
        cls,
        client: ServerClient,
        room_id: str,
        faction: str,
        player_token: str = "",
        user_id: str = "",
    ) -> MultiplayerRoom:
        """Player joins a multiplayer room.

        Args:
            client: ServerClient instance
            room_id: Room ID from create()
            faction: Faction display name (e.g. "caocao", "liubei", "sunquan")
            player_token: Token from the player_links in create() response
            user_id: User ID (for host: use host_user_id from create() response)

        Returns:
            MultiplayerRoom instance ready for gameplay
        """
        resp = client.enter_room(
            room_id=room_id,
            faction=faction,
            player_token=player_token,
            user_id=user_id,
        )
        if not resp.get("ok"):
            raise RuntimeError(f"Failed to join room: {resp.get('error', 'unknown error')}")

        return cls(
            client=client,
            room_id=room_id,
            faction=faction,
            player_token=resp.get("player_token", player_token),
            user_id=resp.get("user_id", ""),
        )

    # ── Gameplay ──────────────────────────────────────────

    def decide(self, decision: str) -> dict:
        """Submit this faction's decision for the current quarter.

        Args:
            decision: Free-text decision (e.g. "发展农业，积蓄力量")

        Returns:
            Dict with ok, status ("waiting" or "resolving"),
            submitted (list of factions that have submitted),
            pending (list of factions still pending)
        """
        return self.client.submit_room_decision(
            room_id=self.room_id,
            faction_id=self.faction,
            user_id=self.user_id,
            decision=decision,
            player_token=self.player_token,
        )

    def wait_for_npc_readiness(self, timeout: int = 180) -> dict:
        """Poll until all AI NPC factions have submitted their decisions.

        Call this BEFORE submitting your own decision. Once all NPCs are ready,
        your submission will immediately trigger the quarter resolution.

        Args:
            timeout: Maximum seconds to wait (default 3 min)

        Returns:
            Room status dict when all NPCs have submitted (or timeout)

        Raises:
            TimeoutError: If NPCs don't submit within the timeout
        """
        start_time = time.monotonic()

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                raise TimeoutError(
                    f"NPC decisions not ready for room {self.room_id} within {timeout}s"
                )

            current = self.status()

            # Guard against error responses from the server
            if not current.get("ok"):
                # If the server returns an error, wait and retry
                time.sleep(2.0)
                continue

            slots = current.get("slots", {})
            pending = current.get("pending", [])

            # Check if any AI NPC still hasn't submitted
            npc_pending = []
            for fid, slot in slots.items():
                if slot.get("occupant_type") == "ai_npc" and fid in pending:
                    npc_pending.append(fid)

            if not npc_pending:
                return current

            time.sleep(2.0)

    def status(self) -> dict:
        """Get current room status.

        Returns:
            Dict with phase, quarter, submitted, pending, slots, players, etc.
        """
        return self.client.get_room_status(
            room_id=self.room_id,
            faction_id=self.faction,
        )

    def wait_for_resolve(self, timeout: int = 120) -> dict:
        """Poll room status until the current quarter resolves.

        Resolution is detected when either:
        - phase is "waiting" (not "resolving") and quarter has advanced
        - or submitted+pending lists indicate all factions have resolved

        Args:
            timeout: Maximum seconds to wait

        Returns:
            Final room status dict

        Raises:
            TimeoutError: If resolution doesn't happen within the timeout
        """
        start_time = time.monotonic()
        initial = self.status()
        initial_quarter = initial.get("quarter", 0)

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                raise TimeoutError(
                    f"Room {self.room_id} did not resolve within {timeout}s"
                )

            current = self.status()
            phase = current.get("phase", "")
            quarter = current.get("quarter", 0)
            submitted = current.get("submitted", [])
            pending = current.get("pending", [])

            # Resolution detected when:
            # - phase is back to "waiting" (not "resolving")
            # - quarter has advanced
            # - our faction is NOT in "submitted" for the new quarter
            #   (NPCs may have already submitted Q2, so "not pending" is too strict)
            is_resolved = (
                phase == "waiting"
                and quarter > initial_quarter
                and self.faction not in submitted
            )

            if is_resolved:
                return current

            time.sleep(1.0)

    def get_turns(self) -> list:
        """Get quarter turn history for this room.

        Returns:
            List of turn records, each with quarter_number, year, season,
            faction_decisions, narratives, state_changes, token_usage
        """
        resp = self.client.get_room_turns(self.room_id)
        return resp.get("turns", [])

    def get_state(self) -> dict:
        """Get the current game state for this room.

        Returns:
            Dict with room_id, quarter_number, factions (list of faction states)
        """
        return self.client.get_room_state(self.room_id)
