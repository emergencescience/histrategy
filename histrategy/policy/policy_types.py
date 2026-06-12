"""Policy command types for macro historical engine.

Replaces battle-level Command types with policy-level PolicyCommand types.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ─── Policy command types ──────────────────────────────────────

POLICY_COMMAND_TYPES = frozenset({
    "tax_rate",      # Set tax rate for territories
    "law",           # Enact/abolish a law or institution
    "appoint",       # Appoint/dismiss a character to/from a position
    "diplomacy",     # Send envoy, form alliance, break relations
    "declare_war",   # Declare war on another faction (battles are LLM-simulated)
    "sue_peace",     # Offer peace / become tributary
    "relocate_capital",  # Move capital to another territory
    "intelligence",  # Send spies, gather intel
    "develop",       # Invest in territory development
    "trade",         # Establish trade route
    "conscript",     # Raise troops (macro-level, no unit micromanagement)
})


@dataclass
class PolicyCommand:
    """A player policy decision, parsed from natural language.

    Unlike v2/v3 battle Commands, PolicyCommands represent
    high-level strategic decisions — tax policy, law enactment,
    diplomacy, war declaration — rather than unit-level orders.
    """

    type: str
    params: dict = field(default_factory=dict)
    notes: str = ""          # Original context from player text
    source_text: str = ""    # The raw text fragment this came from

    def __post_init__(self):
        if self.type not in POLICY_COMMAND_TYPES:
            raise ValueError(
                f"Unknown policy command type '{self.type}'. "
                f"Must be one of: {', '.join(sorted(POLICY_COMMAND_TYPES))}"
            )


# ─── Policy command validation helpers ─────────────────────────

REQUIRED_PARAMS: dict[str, set[str]] = {
    "tax_rate": {"rate"},
    "law": {"name"},
    "appoint": {"character"},
    "diplomacy": {"target", "action"},
    "declare_war": {"target"},
    "sue_peace": {"target"},
    "relocate_capital": {"to"},
    "intelligence": {"target"},
    "develop": {"territory"},
    "trade": {"target"},
    "conscript": {"amount"},
}

OPTIONAL_PARAMS: dict[str, set[str]] = {
    "tax_rate": {"territory"},
    "law": {"scope", "territory"},
    "appoint": {"position", "territory"},
    "diplomacy": {"terms", "gift"},
    "declare_war": {"reason", "casus_belli"},
    "sue_peace": {"terms", "tribute"},
    "relocate_capital": {"reason"},
    "intelligence": {"scope"},
    "develop": {"focus"},
    "trade": {"goods", "amount"},
    "conscript": {"territory"},
}


def validate_policy_params(cmd_type: str, params: dict) -> list[str]:
    """Check required params exist, warn about unknown params.
    
    Returns list of error messages (empty = valid).
    """
    errors = []
    required = REQUIRED_PARAMS.get(cmd_type, set())
    known = required | OPTIONAL_PARAMS.get(cmd_type, set())
    
    for key in required:
        if key not in params:
            errors.append(f"'{cmd_type}' requires param '{key}'")
    
    for key in params:
        if key not in known:
            errors.append(f"'{cmd_type}' has unknown param '{key}'")
    
    return errors
