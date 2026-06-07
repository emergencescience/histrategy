"""
三國志略 v2 — Intent Parser + Command Validator

Parses player free-text into structured commands and validates them
against physics engine constraints.
"""

from .intent import IntentParser
from .validator import CommandValidator

__all__ = ["IntentParser", "CommandValidator"]
