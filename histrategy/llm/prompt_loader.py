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


ADVISOR_SYSTEM_PROMPT = load_prompt("advisor.md")
ALIGNMENT_SYSTEM_PROMPT = load_prompt("alignment.md")
GAMEMASTER_INTRO_SYSTEM = load_prompt("gamemaster_intro.md")
GAMEMASTER_PLAN_SYSTEM = load_prompt("gamemaster_plan.md")
GAMEMASTER_COMMAND_SYSTEM = load_prompt("gamemaster_command.md")
NARRATIVE_SYSTEM = load_prompt("narrative.md")
NARRATIVE_SYSTEM_EN = load_prompt("narrative_en.md")
PLAN_SUGGESTIONS_SYSTEM = load_prompt("plan_suggestions.md")
NPC_INTERPRETER_SYSTEM = load_prompt("npc_interpreter.md")
INTENT_PARSE_SYSTEM = load_prompt("intent_parse.md")
WORLD_SIMULATOR_SYSTEM = load_prompt("world_simulator.md")

# Dictionary of system prompt contents mapping to prompt names to detect in LLMAdapter and suppress verbose logs.
KNOWN_PROMPTS = {
    "ADVISOR_SYSTEM_PROMPT": ADVISOR_SYSTEM_PROMPT,
    "ALIGNMENT_SYSTEM_PROMPT": ALIGNMENT_SYSTEM_PROMPT,
    "GAMEMASTER_INTRO_SYSTEM": GAMEMASTER_INTRO_SYSTEM,
    "GAMEMASTER_PLAN_SYSTEM": GAMEMASTER_PLAN_SYSTEM,
    "GAMEMASTER_COMMAND_SYSTEM": GAMEMASTER_COMMAND_SYSTEM,
    "NARRATIVE_SYSTEM": NARRATIVE_SYSTEM,
    "PLAN_SUGGESTIONS_SYSTEM": PLAN_SUGGESTIONS_SYSTEM,
    "NPC_INTERPRETER_SYSTEM": NPC_INTERPRETER_SYSTEM,
    "INTENT_PARSE_SYSTEM": INTENT_PARSE_SYSTEM,
    "WORLD_SIMULATOR_SYSTEM": WORLD_SIMULATOR_SYSTEM,
    "POLICY_PARSE_SYSTEM": load_prompt("policy_parse.md"),
    "MACRO_SIM_SYSTEM": load_prompt("macro_simulator.md"),
}
