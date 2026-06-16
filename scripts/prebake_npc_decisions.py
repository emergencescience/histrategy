#!/usr/bin/env python3
"""Pre-bake Q0 NPC decisions for all scenarios.

Generates npc_decisions_q0.json files for each scenario by running
the NPCDecisionEngine against the initial world state.

Usage:
    python scripts/prebake_npc_decisions.py [--scenario rome-triumvirate] [--lang en,zh]
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def load_initial_world_state(scenario: str, faction_id: str):
    """Load initial WorldState for a scenario without creating a room.

    Returns WorldState object.
    """
    from histrategy.engine.scenario_loader import ScenarioLoader

    loader = ScenarioLoader(scenario)
    ws = loader.build_world_state(player_faction_id=faction_id)
    return ws


def generate_decisions(scenario: str, langs: list[str]) -> dict:
    """Generate Q0 NPC decisions for all faction+lang combos.

    Uses NPCDecisionEngine directly — no room creation needed.
    """
    from histrategy.engine.scenario_loader import ScenarioLoader
    from histrategy.llm.adapter import LLMAdapter
    from histrategy.llm.npc_decision_engine import NPCDecisionEngine

    # Get LLM adapter
    llm = LLMAdapter()
    if not llm.is_available:
        print("ERROR: No LLM API key available. Set DEEPSEEK_API_KEY or similar.")
        sys.exit(1)

    # Get all playable faction IDs
    loader = ScenarioLoader(scenario)
    factions = loader.load_factions()
    faction_ids = [fid for fid, f in factions.items() if not f.get("npc_only", False)]
    print(
        f"Scenario {scenario}: {len(faction_ids)} factions × "
        f"{len(langs)} langs = {len(faction_ids) * len(langs)} decisions"
    )

    results: dict[str, dict[str, dict]] = {}

    for lang in langs:
        print(f"\n--- lang={lang} ---")
        # Create a fresh world state for each lang (deterministic initial state)
        ws = load_initial_world_state(scenario, faction_ids[0])

        for fid in faction_ids:
            engine = NPCDecisionEngine(
                llm=llm,
                language=lang,
                scenario=scenario,
            )
            decision_text, commands = engine.generate(
                world_state=ws,
                faction_id=fid,
                turn_memory=[],
                room_id="",  # empty → skip DB write
                quarter_number=0,
            )

            if fid not in results:
                results[fid] = {}
            results[fid][lang] = {
                "decision_text": decision_text,
                "commands": commands,
            }
            print(f"  {fid}/{lang}: ✓ ({len(decision_text)} chars, {len(commands)} commands)")

    return results


def main():
    parser = argparse.ArgumentParser(description="Pre-bake NPC Q0 decisions")
    parser.add_argument("--scenario", default=None, help="Scenario slug (default: all)")
    parser.add_argument("--lang", default="en,zh", help="Languages comma-separated (default: en,zh)")
    args = parser.parse_args()

    langs = [l.strip() for l in args.lang.split(",")]

    scenarios_dir = Path(__file__).parent.parent / "scenarios"
    available = [
        d.name for d in scenarios_dir.iterdir()
        if d.is_dir() and (d / "scenario.toml").exists()
    ]
    scenarios = [args.scenario] if args.scenario else available

    for scenario in scenarios:
        output_path = scenarios_dir / scenario / "npc_decisions_q0.json"

        print(f"\n{'='*60}")
        print(f"Pre-baking NPC decisions for: {scenario}")
        print(f"{'='*60}")

        from datetime import datetime, timezone
        decisions = generate_decisions(scenario, langs)

        output = {
            "scenario": scenario,
            "quarter": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": os.environ.get("LLM_MODEL", "deepseek-v4-pro"),
            "decisions": decisions,
        }

        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\nSaved: {output_path} ({output_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
