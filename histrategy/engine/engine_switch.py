"""
引擎模式调度器 — 根据 HISTRATEGY_ENGINE 环境变量选择引擎。

Usage:
    HISTRATEGY_ENGINE=v1   → V1 纯 LLM 仿真
    HISTRATEGY_ENGINE=v2   → V2 确定性引擎 (默认)
    HISTRATEGY_ENGINE=v3   → V3 混合引擎 (QuarterlyEngine + LLM 调整)
    HISTRATEGY_MACRO=1     → V3 宏观政策引擎 (等同于 HISTRATEGY_ENGINE=v3)
"""

from __future__ import annotations

import logging
import os
from enum import Enum

logger = logging.getLogger("histrategy.engine_switch")


class EngineMode(Enum):
    V1 = "v1"  # 纯 LLM
    V2 = "v2"  # 确定性 (默认)
    V3 = "v3"  # 混合引擎
    MACRO = "macro"  # 宏观政策引擎（等同于 v3）


def detect_engine_mode() -> EngineMode:
    """检测当前引擎模式。

    优先级: HISTRATEGY_ENGINE > HISTRATEGY_MACRO > 默认 V2
    """
    engine = os.environ.get("HISTRATEGY_ENGINE", "").lower()

    if engine == "v1":
        return EngineMode.V1
    elif engine == "v3":
        return EngineMode.V3
    elif engine == "v2":
        return EngineMode.V2
    elif engine == "macro":
        return EngineMode.MACRO

    # 兼容旧环境变量
    if os.environ.get("HISTRATEGY_MACRO") == "1":
        return EngineMode.V3
    if os.environ.get("HISTRATEGY_V3") == "1":
        return EngineMode.V3

    return EngineMode.V2
