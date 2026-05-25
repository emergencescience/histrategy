import os
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from histrategy.engine.game import GameEngine
from histrategy.llm.adapter import LLMAdapter

def run_e2e_live():
    # Make sure we use the correct environment base
    adapter = LLMAdapter()
    print(f"Running E2E Live with provider: {adapter.provider_name}, model: {adapter.model}, base: {adapter.api_base}")
    
    # Initialize engine
    engine = GameEngine(llm=adapter, new_game=True)
    engine.set_player_faction("shu") # Liu Bei
    
    # Turn 0: Intro Scene
    print("\n================== INTRO SCENE ==================")
    intro = engine.get_intro_scene()
    print("NARRATIVE:\n", intro.get("narrative"))
    print("\nNPC REACTIONS:", json.dumps(intro.get("npc_actions"), ensure_ascii=False, indent=2))
    print("\nCHOICES:", json.dumps(intro.get("new_choices"), ensure_ascii=False, indent=2))
    
    # Turn 1: Plan Mode
    print("\n================== TURN 1 PLAN MODE ==================")
    plan = engine.get_plan_data()
    print("SEASON SUMMARY:", plan.get("season_summary"))
    print("\nCOURT DIALOGUE:\n", plan.get("court_dialogue"))
    print("\nSUGGESTIONS:", json.dumps(plan.get("suggestions"), ensure_ascii=False, indent=2))
    
    # Turn 1 Decision
    decision_1 = "采纳张飞的建议，由二弟云长、三弟翼德各领两千精兵，北上投奔公孙瓒，借其名势共同响应檄文，并留简雍辅佐孙乾留守平原开垦屯田。"
    print(f"\nDECISION 1: {decision_1}")
    
    print("\n================== TURN 1 COMMAND MODE ==================")
    result_1 = engine.process_turn(decision_1)
    print("AFTERMATH:\n", result_1.get("aftermath"))
    print("\nSTATE CHANGES:", json.dumps(result_1.get("state_changes"), ensure_ascii=False, indent=2))
    print("\nNPC REACTIONS:", json.dumps(result_1.get("npc_reactions"), ensure_ascii=False, indent=2))
    print("\nBUREAUCRACY:", json.dumps(result_1.get("bureaucracy"), ensure_ascii=False, indent=2))
    print("\nSEEDS:", json.dumps(result_1.get("seeds"), ensure_ascii=False, indent=2))

    # Turn 2: Plan Mode
    print("\n================== TURN 2 PLAN MODE ==================")
    plan_2 = engine.get_plan_data()
    print("SEASON SUMMARY:", plan_2.get("season_summary"))
    print("\nCOURT DIALOGUE:\n", plan_2.get("court_dialogue"))
    print("\nSUGGESTIONS:", json.dumps(plan_2.get("suggestions"), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    run_e2e_live()
