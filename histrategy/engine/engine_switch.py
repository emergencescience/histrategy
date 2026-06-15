"""
引擎模式调度器 — 根据 HISTRATEGY_ENGINE 环境变量选择引擎。

Usage:
    HISTRATEGY_ENGINE=v1   → V1 纯 LLM 仿真
    HISTRATEGY_ENGINE=v2   → V2 确定性引擎 (默认)
    HISTRATEGY_ENGINE=v3   → V3 混合引擎 (确定性基线 + LLM 非线性层，合并了旧 v3+macro)

旧环境变量 HISTRATEGY_MACRO 和 HISTRATEGY_V3 仍然兼容，均映射到 V3。
"""

from __future__ import annotations

import logging
import os
from enum import Enum

logger = logging.getLogger("histrategy.engine_switch")


class EngineMode(Enum):
    V1 = "v1"  # 纯 LLM 仿真 — 单次 LLM 调用推演全部世界状态
    V2 = "v2"  # 纯确定性引擎 — 零 LLM，公式驱动 (默认)
    V3 = "v3"  # 混合引擎 — V2 确定性基线 + Macro LLM 非线性层 + GuardrailValidator


def detect_engine_mode() -> EngineMode:
    """检测当前引擎模式。

    优先级: HISTRATEGY_ENGINE > 旧环境变量兼容 > 默认 V2
    """
    engine = os.environ.get("HISTRATEGY_ENGINE", "").lower()

    mode_map = {
        "v1": EngineMode.V1,
        "v2": EngineMode.V2,
        "v3": EngineMode.V3,
    }
    if engine in mode_map:
        return mode_map[engine]

    # 兼容旧环境变量 (HISTRATEGY_MACRO / HISTRATEGY_V3 → V3)
    if os.environ.get("HISTRATEGY_MACRO") == "1":
        logger.info("HISTRATEGY_MACRO=1 detected → V3 (merged V3+Macro)")
        return EngineMode.V3
    if os.environ.get("HISTRATEGY_V3") == "1":
        logger.info("HISTRATEGY_V3=1 detected → V3 (merged V3+Macro)")
        return EngineMode.V3

    return EngineMode.V2
