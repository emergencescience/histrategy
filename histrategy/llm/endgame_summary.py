from typing import Any


def generate_chronicle(player_events: list[Any], llm_adapter: Any = None) -> str:
    """
    Generate a Chen Shou style biography summary for the player's run.
    If llm_adapter is not provided or unavailable, falls back to offline chronicle.
    """
    if not player_events:
        return "【史官曰：此子默默无闻，平生未立尺寸之功，终没于乱世之中。】"

    # Format events to string for LLM prompt
    events_str = []
    for i, e in enumerate(player_events, 1):
        if isinstance(e, dict):
            title = e.get("title", e.get("event_id", "未知事件"))
            desc = e.get("description", e.get("narrative", ""))
            events_str.append(f"第{i}阶段: 【{title}】 - {desc}")
        else:
            events_str.append(f"第{i}阶段: {e}")
    events_formatted = "\n".join(events_str)

    if llm_adapter and getattr(llm_adapter, "is_available", False):
        system_prompt = (
            "你是一位精通历史的史官。请以陈寿《三国志》的评语风格，"
            "为玩家写一篇总结传记。评语应当微言大义，点评其功过是非，"
            "语言需文雅、古风盎然，并以‘评曰’或‘史官曰’开头。"
        )
        user_prompt = (
            f"以下是玩家在该局游戏中的主要事迹经历：\n\n"
            f"{events_formatted}\n\n"
            f"请根据上述经历生成一篇符合《三国志》评语风格的传记总结。"
        )
        try:
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
            response = llm_adapter.chat(messages, temperature=0.5)
            if response and response.strip():
                return response.strip()
        except Exception:
            pass

    # Offline fallback
    lines = [
        "# 📑 后汉三国志·列传",
        "",
        "## 📜 平生功业纪",
    ]
    for ev in events_str:
        lines.append(f"- {ev}")
    lines.append("")
    lines.append("## ✍️ 史官曰")
    lines.append(
        "【评曰：观其生平，行兵用武，经略内政，皆有一时之风采。"
        "虽处乱世之中，能有此建树，亦足称一时之雄杰。然成败得失，"
        "存乎天命与人事之间，后之来者，可以为鉴。】"
    )
    return "\n".join(lines)
