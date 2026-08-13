"""
Narrative context formatter — converts TurnResult baseline into
structured, LLM-readable Chinese text for narrative generation.

Replaces str(baseline) which produces raw Python object strings
that LLMs struggle to parse.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from histrategy_engine.world import WorldState


def format_baseline_for_narrative(baseline, ws: WorldState | None = None) -> str:
    """Format a TurnResult baseline into structured Chinese text.

    Produces a readable narrative context suitable for LLM prompt injection.
    Each section is clearly labeled. Missing/empty sections are omitted.
    """
    lines: list[str] = []

    # ── Battles (with territory changes) ──
    battles = _safe_attr(baseline, "battles", [])
    if battles:
        lines.append("### 本季战事 (Actual Battles — authoritative)")
        for b in battles:
            # Normalize attributes (CombatResult or dict)
            atk = _safe_attr(b, "attacker_id", _safe_dict(b, "attacker_id", "?"))
            dfd = _safe_attr(b, "defender_id", _safe_dict(b, "defender_id", "?"))
            loc = _safe_attr(b, "location", _safe_dict(b, "location", "?"))
            result = _safe_attr(b, "result", _safe_dict(b, "result", "?"))
            captured = _safe_attr(b, "territory_captured", _safe_dict(b, "territory_captured", False))
            atk_loss = _format_casualties(_safe_attr(b, "attacker_casualties", _safe_dict(b, "attacker_casualties", {})))
            def_loss = _format_casualties(_safe_attr(b, "defender_casualties", _safe_dict(b, "defender_casualties", {})))

            result_cn = _battle_result_cn(str(result))
            captured_str = f" ✅ 领土易手: {atk} 夺取 {loc}" if captured else ""

            lines.append(
                f"- {atk} ⚔ {dfd} @ {loc}: {result_cn}"
                f" | 攻方损{atk_loss} 守方损{def_loss}{captured_str}"
            )

        # Territory ownership AFTER battles (authoritative)
        if ws and hasattr(ws, "factions"):
            # H35y: Build territory ownership from ws.territories[].owner_id FIRST,
            # then fall back to faction.territories — matching _extract_state_changes.
            # faction.territories can be stale after deserialization / combat.
            faction_territories: dict[str, list[str]] = {}
            if hasattr(ws, "territories") and ws.territories:
                for tid, territory in ws.territories.items():
                    owner = getattr(territory, "owner_id", "") or ""
                    if owner and owner in ws.factions:
                        faction_territories.setdefault(owner, []).append(tid)

            lines.append("")
            lines.append("### 战后领土归属 (Post-Battle Territory — authoritative)")
            for fid, faction in ws.factions.items():
                if not getattr(faction, "is_active", True):
                    continue
                tids = faction_territories.get(fid, [])
                if not tids:
                    tids = list(getattr(faction, "territories", []))
                names = []
                for tid in tids:
                    t = ws.territories.get(tid) if hasattr(ws, "territories") else None
                    names.append(t.name if t and hasattr(t, "name") else str(tid))
                warning = " ⚠️ 流亡中无领地" if not tids else ""
                lines.append(f"- {faction.name} ({fid}): {', '.join(names) if names else '无领地 (流亡中)'}{warning}")
        lines.append("")
    else:
        lines.append("### 本季战事: 无")
        lines.append("")

    # ── Resource changes ──
    rc = _safe_attr(baseline, "resource_changes", {})
    if rc:
        lines.append("### 资源变化")
        for fid, changes in (rc.items() if isinstance(rc, dict) else []):
            if isinstance(changes, dict):
                food_d = changes.get("food_delta", 0)
                tax = changes.get("tax_revenue", 0)
                spent = changes.get("treasury_spent", 0)
                famine = changes.get("famine_occurred", False)
                parts = []
                if food_d:
                    parts.append(f"粮{'+' if food_d>0 else ''}{food_d:,.0f}")
                if tax:
                    parts.append(f"税{tax:,.0f}")
                if spent:
                    parts.append(f"支出{spent:,.0f}")
                if famine:
                    parts.append("⚠️饥荒")
                if parts:
                    lines.append(f"- {fid}: {', '.join(parts)}")
        lines.append("")

    # ── Climate events ──
    climate = _safe_attr(baseline, "climate_events", [])
    if climate:
        lines.append("### 天时气候")
        for ce in climate:
            if isinstance(ce, dict):
                loc = ce.get("territory", ce.get("location", "?"))
                etype = ce.get("type", ce.get("event", "?"))
                effect = ce.get("effect", ce.get("description", ""))
                lines.append(f"- {loc}: {etype} ({effect})" if effect else f"- {loc}: {etype}")
        lines.append("")

    # ── Character events ──
    char_events = _safe_attr(baseline, "character_events", [])
    if char_events:
        lines.append("### 人物变易")
        for ce in char_events:
            if isinstance(ce, dict):
                cid = ce.get("character_id", ce.get("character_name", "?"))
                etype = ce.get("type", "?")
                delta = ce.get("delta", "")
                reason = ce.get("reason", "")
                name = ce.get("character_name", cid)
                if etype == "natural_death":
                    lines.append(f"- {name} 病故")
                elif etype == "loyalty_change" or etype == "loyalty_impact":
                    lines.append(f"- {name} 忠诚{'↑' if delta and delta > 0 else '↓'}{abs(delta) if delta else ''}: {reason}")
                elif etype == "defection":
                    lines.append(f"- {name} 叛逃至 {ce.get('new_faction', '?')}")
                else:
                    lines.append(f"- {name}: {etype}")
        lines.append("")

    return "\n".join(lines)


def _safe_attr(obj, attr: str, default=None):
    """Safely get attribute from object, returning default on any failure."""
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _safe_dict(obj, key: str, default=None):
    """Safely get key from dict (if obj is a dict)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _format_casualties(casualties) -> str:
    """Format casualties dict into a compact string."""
    if not casualties:
        return "0"
    if isinstance(casualties, dict):
        total = sum(casualties.values())
        return f"{total:,}"
    return str(casualties)


def _battle_result_cn(result_str: str) -> str:
    """Translate battle result enum values to Chinese."""
    mapping = {
        "BattleResult.DECISIVE_VICTORY": "大胜",
        "BattleResult.VICTORY": "胜",
        "BattleResult.STALEMATE": "相持",
        "BattleResult.DEFEAT": "败",
        "BattleResult.DECISIVE_DEFEAT": "大败",
        "1": "大胜",
        "2": "胜",
        "3": "相持",
        "4": "败",
        "5": "大败",
    }
    return mapping.get(result_str, result_str)
