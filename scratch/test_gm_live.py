import os
import sys
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from histrategy.llm.adapter import LLMAdapter
from histrategy.llm.game_master import GameMaster
from histrategy.engine.game import create_initial_world

def test_live():
    # Print environment variables (masked API key)
    print("DEEPSEEK_API_KEY:", os.environ.get("DEEPSEEK_API_KEY", "")[:10] + "...")
    print("OPENAI_API_BASE:", os.environ.get("OPENAI_API_BASE", ""))
    print("LLM_MODEL:", os.environ.get("LLM_MODEL", ""))

    adapter = LLMAdapter()
    print("Adapter available:", adapter.is_available)
    print("Adapter provider name:", adapter.provider_name)
    print("Adapter model:", adapter.model)
    print("Adapter api_base:", adapter.api_base)

    gm = GameMaster(adapter)
    state = create_initial_world("shu")

    print("\n--- Testing generate_intro ---")
    try:
        player = state.get_player_faction()
        from histrategy.state.world_state import HISTORICAL_TIMELINE_190
        intro_context = (
            f"## 游戏开局\n\n"
            f"剧本：{state.scenario}\n"
            f"时间：{state.year}年春季\n\n"
            f"玩家势力：{player.name}\n"
            f"- 兵力：{player.strength:,}\n"
            f"- 经济：{player.economy}/100\n"
            f"- 民心：{player.morale}/100\n"
            f"- 资金：{player.treasury:,}\n"
            f"- 粮草：{player.food:,}\n"
            f"- 首都：{player.capital}\n"
            f"- 领地：{', '.join(player.territories)}\n\n"
            f"历史背景：{HISTORICAL_TIMELINE_190[0]}\n\n"
            f"请以说书人/军师的口吻，生成三国志略的开局叙事（以Markdown格式书写，建议分为‘天下大势’与‘主公处境’两部分，有历史感，300-600字）。\n"
            f"生成3-5条其他NPC势力的开局动向（放在npc_reactions列表中），以及4个极具历史厚重感、切合局势的开局选择（放在choices列表中）。"
        )
        from histrategy.llm.game_master import GAMEMASTER_INTRO_SYSTEM
        messages = [
            {"role": "system", "content": GAMEMASTER_INTRO_SYSTEM},
            {"role": "user", "content": intro_context},
        ]
        
        result = adapter.chat_structured(
            messages,
            response_format={"type": "json_object"},
            temperature=0.85,
            max_tokens=4096,
        )
        print("Success generate_intro! Result keys:", result.keys())
        print("Narrative:", result.get("narrative")[:100] if result.get("narrative") else None)
    except Exception as e:
        print("Error in generate_intro:")
        traceback.print_exc()

    print("\n--- Testing generate_plan_mode ---")
    try:
        plan = gm.generate_plan_mode(state)
        print("Success generate_plan_mode! Dialogue length:", len(plan.get("court_dialogue", "")))
        print("Plan dialogue:", plan.get("court_dialogue")[:200] if plan.get("court_dialogue") else None)
    except Exception as e:
        print("Error in generate_plan_mode:")
        traceback.print_exc()

if __name__ == "__main__":
    test_live()
