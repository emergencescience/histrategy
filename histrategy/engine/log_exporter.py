"""Log Exporter — formats and exports game session logs to JSON or Markdown.

Supports community sharing and DevOps agent training.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from ..state.world_state import get_data_dir, load_world


def _session_log_file() -> Path:
    return get_data_dir() / "current_session_log.json"


def clear_session_log() -> None:
    """Clear or reset the current session log on new game start."""
    path = _session_log_file()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def append_to_session_log(
    turn: int,
    year: int,
    season: str,
    player_decision: str,
    sim_result_dict: dict,
) -> None:
    """Append a turn's simulation results to the active session log."""
    path = _session_log_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "turn": turn,
        "year": year,
        "season": season,
        "player_decision": player_decision,
        "narrative": sim_result_dict.get("narrative", ""),
        "aftermath": sim_result_dict.get("aftermath", ""),
        "state_changes": sim_result_dict.get("state_changes", {}),
        "npc_reactions": sim_result_dict.get("npc_reactions", []),
        "bureaucracy": sim_result_dict.get("bureaucracy", []),
        "timestamp": datetime.now().isoformat(),
    }

    entries = []
    if path.exists():
        try:
            with open(path) as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    entries.append(log_entry)

    with open(path, "w") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def export_log(output_path: str, format_type: str = "markdown") -> bool:
    """Export the current session log to the target path in JSON or Markdown."""
    log_src = _session_log_file()
    if not log_src.exists():
        return False

    try:
        with open(log_src) as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if format_type.lower() == "json":
        try:
            with open(out_path, "w") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False

    # Default to markdown
    world = load_world()
    player_name = "主公"
    if world:
        player_fac = world.get_player_faction()
        if player_fac:
            player_name = f"{player_fac.name}（{player_fac.ruler_id}）"

    md_lines = [
        f"# 《三國志略》战纪：{player_name}之天下争霸",
        f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 总计回合：{len(entries)} 回合",
        "",
        "---",
        "",
    ]

    for entry in entries:
        season_cn = {
            "spring": "春季",
            "summer": "夏季",
            "autumn": "秋季",
            "winter": "冬季",
        }.get(entry.get("season", ""), entry.get("season", ""))
        md_lines.extend([
            f"## 第 {entry.get('turn')} 回合：{entry.get('year')}年{season_cn}",
            "",
            f"> 📜 **主公政令**：「{entry.get('player_decision')}」",
            "",
            "### 📜 局势推演",
            entry.get("narrative", "").strip(),
            "",
        ])

        # State changes
        changes = entry.get("state_changes", {})
        if changes:
            md_lines.append("### 📊 势力变动")
            for key, label in [
                ("strength", "兵力"),
                ("economy", "经济"),
                ("morale", "民心"),
                ("treasury", "资金"),
                ("food", "粮草"),
            ]:
                val = changes.get(key, 0)
                if val:
                    sign = "+" if val > 0 else ""
                    md_lines.append(f"- **{label}**：`{sign}{val}`")
            md_lines.append("")

        # Bureaucracy
        bur = entry.get("bureaucracy", [])
        if bur:
            md_lines.extend([
                "### 🏛️ 曹署执行情况",
                "| 官署 | 责任官吏 | 执行细则 |",
                "| :--- | :--- | :--- |",
            ])
            for b in bur:
                dept = b.get("department", "")
                off = b.get("official", "")
                act = b.get("action", "")
                md_lines.append(f"| {dept} | {off} | {act} |")
            md_lines.append("")

        # NPC Reactions
        reactions = entry.get("npc_reactions", [])
        if reactions:
            md_lines.append("### ⚔️ 天下八方动向")
            for r in reactions:
                md_lines.append(f"- {r}")
            md_lines.append("")

        md_lines.append("---")
        md_lines.append("")

    try:
        with open(out_path, "w") as f:
            f.write("\n".join(md_lines))
        return True
    except OSError:
        return False
