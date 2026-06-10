"""Tests for StateBridge — engine command execution and world state queries."""

import tempfile

from histrategy_agent.session import GameSessionManager
from histrategy_agent.state_bridge import StateBridge
from histrategy_engine import Command


class TestStateBridgeCommands:
    """Tests for command execution through StateBridge."""

    def setup_method(self):
        tmp = tempfile.TemporaryDirectory()
        self.tmp = tmp
        mgr = GameSessionManager(data_dir=tmp.name)
        self.session = mgr.get_or_create("feishu", "chat_bridge", "shu", "207")
        self.bridge = StateBridge(self.session.world_state)

    def teardown_method(self):
        self.tmp.cleanup()

    def test_execute_info(self):
        result = self.bridge.execute_command(Command(type="info", params={}, faction_id="shu"))
        assert result["success"] is True
        assert "刘备" in result["message"] or "shu" in result["message"]

    def test_get_world_snapshot(self):
        snapshot = self.bridge.get_world_snapshot("shu")
        assert snapshot["faction_id"] == "shu"
        assert snapshot["faction_name"] == "刘备"
        assert snapshot["year"] == 207
        assert snapshot["territory_count"] == 1  # shu starts with xinye only
        assert snapshot["total_troops"] == 5000
        assert "xinye" in [t["id"] for t in snapshot["territories"]]

    def test_get_world_snapshot_nonexistent_faction(self):
        snapshot = self.bridge.get_world_snapshot("nonexistent")
        assert "error" in snapshot

    def test_execute_recruit_success(self):
        faction = self.session.world_state.factions["shu"]
        initial_treasury = faction.treasury
        result = self.bridge.execute_command(
            Command(
                type="recruit",
                params={"unit_type": "infantry", "amount": 500},
                faction_id="shu",
            )
        )
        assert result["success"] is True
        assert "招募" in result["message"]
        assert faction.treasury < initial_treasury  # money spent

        # Verify troops increased
        total = sum(a.total_troops for a in self.session.world_state.armies.values() if a.faction_id == "shu")
        assert total == 5500

    def test_execute_recruit_invalid_unit_type(self):
        result = self.bridge.execute_command(
            Command(
                type="recruit",
                params={"unit_type": "rocket", "amount": 100},
                faction_id="shu",
            )
        )
        assert result["success"] is False
        assert "未知兵种" in result["message"]

    def test_execute_move_no_target(self):
        result = self.bridge.execute_command(Command(type="move", params={}, faction_id="shu"))
        assert result["success"] is False
        assert "指定" in result["message"]

    def test_execute_attack_no_target(self):
        result = self.bridge.execute_command(Command(type="attack", params={}, faction_id="shu"))
        assert result["success"] is False
        assert "指定" in result["message"]

    def test_execute_develop(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_dev2", "cao", "207")
            bridge = StateBridge(session.world_state)
            faction = session.world_state.factions["cao"]
            territory = session.world_state.territories["xuchang"]
            initial_dev = territory.development
            initial_treasury = faction.treasury

            result = bridge.execute_command(Command(type="develop", params={"target": "xuchang"}, faction_id="cao"))
            assert result["success"] is True
            assert territory.development == initial_dev + 10
            assert faction.treasury < initial_treasury

    def test_execute_tax(self):
        faction = self.session.world_state.factions["shu"]
        initial_treasury = faction.treasury

        result = self.bridge.execute_command(Command(type="tax", params={"rate": 0.3}, faction_id="shu"))
        assert result["success"] is True
        assert faction.tax_rate == 0.3
        # Should have collected revenue
        assert "获得税收" in result["message"]

    def test_execute_tax_invalid_rate(self):
        result = self.bridge.execute_command(Command(type="tax", params={"rate": 0.9}, faction_id="shu"))
        assert result["success"] is False
        assert "0.1" in result["message"] or "0.5" in result["message"]

    def test_execute_diplomacy_ally(self):
        result = self.bridge.execute_command(
            Command(
                type="diplomacy",
                params={"target": "wu", "action": "ally"},
                faction_id="shu",
            )
        )
        assert result["success"] is True
        assert "结盟" in result["message"]

        # Verify alliance created
        faction = self.session.world_state.factions["shu"]
        assert "wu" in faction.allies
        assert faction.relations["wu"] >= 50

    def test_execute_diplomacy_break_ally(self):
        # First ally, then break
        self.bridge.execute_command(
            Command(
                type="diplomacy",
                params={"target": "wu", "action": "ally"},
                faction_id="shu",
            )
        )
        result = self.bridge.execute_command(
            Command(
                type="diplomacy",
                params={"target": "wu", "action": "break_ally"},
                faction_id="shu",
            )
        )
        assert result["success"] is True
        assert "解盟" in result["message"] or "解除" in result["message"]

        faction = self.session.world_state.factions["shu"]
        assert "wu" not in faction.allies

    def test_execute_unknown_command(self):
        result = self.bridge.execute_command(Command(type="dance", params={}, faction_id="shu"))
        assert result["success"] is False
        assert "未知" in result["message"] or "命令" in result["message"]

    def test_execute_info_gives_snapshot(self):
        result = self.bridge.execute_command(Command(type="info", params={}, faction_id="cao"))
        assert result["success"] is True
        snapshot = result["result"]
        assert snapshot["territory_count"] == 6  # Cao has 6 territories
        assert "许昌" in [t["name"] for t in snapshot["territories"]]

    def test_advance_npc_factions_returns_actions(self):
        npc_actions = self.bridge.advance_npc_factions()
        assert len(npc_actions) > 0
        # Each NPC faction should have actions
        for na in npc_actions:
            assert "faction_id" in na
            assert na["faction_id"] != "shu"  # player faction excluded
            assert isinstance(na["actions"], list)

    def test_get_territory_map(self):
        tmap = self.bridge.get_territory_map()
        assert isinstance(tmap, dict)
        assert "xinye" in tmap
        assert "wancheng" in tmap
        assert "wancheng" in tmap["xinye"] or tmap["xinye"] == ["wancheng", "xiangyang"]


class TestStateBridgeEdgeCases:
    """Edge cases and error handling."""

    def test_nonexistent_faction_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = GameSessionManager(data_dir=tmp)
            session = mgr.get_or_create("feishu", "chat_edge", "shu", "207")
            bridge = StateBridge(session.world_state)

            result = bridge.execute_command(Command(type="recruit", params={"amount": 100}, faction_id="nobody"))
            assert result["success"] is False
            assert "不存在" in result["message"]
