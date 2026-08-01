from pathlib import Path


def load_prompt(filename: str, default: str | None = None) -> str | None:
    """Load a system prompt from the prompts directory.

    If the file doesn't exist and a default is provided, returns the default.
    Otherwise, raises FileNotFoundError.
    """
    path = Path(__file__).parent / "prompts" / filename
    if not path.exists() and default is not None:
        return default
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


ADVISOR_SYSTEM = load_prompt("advisor.md")
ADVISOR_SYSTEM_EN = load_prompt("advisor_en.md")
ALIGNMENT_SYSTEM = load_prompt("alignment.md")
GAMEMASTER_INTRO_SYSTEM = load_prompt("gamemaster_intro.md")
GAMEMASTER_INTRO_SYSTEM_EN = load_prompt(
    "gamemaster_intro_en.md",
    default=GAMEMASTER_INTRO_SYSTEM,  # fallback to Chinese if English not found
)
GAMEMASTER_PLAN_SYSTEM = load_prompt("gamemaster_plan.md")
GAMEMASTER_PLAN_SYSTEM_EN = load_prompt(
    "gamemaster_plan_en.md",
    default=GAMEMASTER_PLAN_SYSTEM,
)
GAMEMASTER_COMMAND_SYSTEM = load_prompt("gamemaster_command.md")
GAMEMASTER_COMMAND_SYSTEM_EN = load_prompt(
    "gamemaster_command_en.md",
    default=GAMEMASTER_COMMAND_SYSTEM,
)
NARRATIVE_SYSTEM = load_prompt("narrative.md")
NARRATIVE_SYSTEM_EN = load_prompt("narrative_en.md")
GLOBAL_NARRATIVE_SYSTEM = load_prompt("global_narrative.md")
GLOBAL_NARRATIVE_SYSTEM_EN = load_prompt("global_narrative_en.md")
PLAN_SUGGESTIONS_SYSTEM = load_prompt("plan_suggestions.md")
NPC_INTERPRETER_SYSTEM = load_prompt("npc_interpreter.md")
NPC_DECISION_SYSTEM = load_prompt("npc_decision.md")
NPC_DECISION_SYSTEM_EN = load_prompt("npc_decision_en.md")
INTENT_PARSE_SYSTEM = load_prompt("intent_parse.md")
WORLD_SIMULATOR_SYSTEM = load_prompt("world_simulator.md")
# MACRO_SIM_SYSTEM: deleted — use scenario-specific prompts only
# (e.g. scenarios/three-kingdoms/prompts/macro_simulator_zh.md)
# The macro_policy_engine loads from scenario dirs directly.
MACRO_SIM_SYSTEM = None
MACRO_SIM_SYSTEM_EN = None

# Dictionary of system prompt contents mapping to prompt names to detect in LLMAdapter and suppress verbose logs.
KNOWN_PROMPTS = {
    "ADVISOR_SYSTEM": ADVISOR_SYSTEM,
    "ADVISOR_SYSTEM_EN": ADVISOR_SYSTEM_EN,
    "ALIGNMENT_SYSTEM": ALIGNMENT_SYSTEM,
    "GAMEMASTER_INTRO_SYSTEM": GAMEMASTER_INTRO_SYSTEM,
    "GAMEMASTER_PLAN_SYSTEM": GAMEMASTER_PLAN_SYSTEM,
    "GAMEMASTER_COMMAND_SYSTEM": GAMEMASTER_COMMAND_SYSTEM,
    "NARRATIVE_SYSTEM": NARRATIVE_SYSTEM,
    "NARRATIVE_SYSTEM_EN": NARRATIVE_SYSTEM_EN,
    "GLOBAL_NARRATIVE_SYSTEM": GLOBAL_NARRATIVE_SYSTEM,
    "GLOBAL_NARRATIVE_SYSTEM_EN": GLOBAL_NARRATIVE_SYSTEM_EN,
    "PLAN_SUGGESTIONS_SYSTEM": PLAN_SUGGESTIONS_SYSTEM,
    "NPC_INTERPRETER_SYSTEM": NPC_INTERPRETER_SYSTEM,
    "NPC_DECISION_SYSTEM": NPC_DECISION_SYSTEM,
    "NPC_DECISION_SYSTEM_EN": NPC_DECISION_SYSTEM_EN,
    "INTENT_PARSE_SYSTEM": INTENT_PARSE_SYSTEM,
    "WORLD_SIMULATOR_SYSTEM": WORLD_SIMULATOR_SYSTEM,
    "POLICY_PARSE_SYSTEM": load_prompt("policy_parse.md"),
    "MACRO_SIM_SYSTEM": MACRO_SIM_SYSTEM,
}
