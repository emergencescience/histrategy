"""
引擎模式调度器 — 选择服务端使用的仿真引擎。

Usage:
    HISTRATEGY_ENGINE=v2   → V2 确定性引擎（零 LLM，公式驱动）
    HISTRATEGY_ENGINE=v3   → V3 混合引擎（V2 确定性基线 + Macro LLM 非线性层）

**默认 V3，环境变量不再是必需的**（不设置时即为生产在用的 V3）。

V1（纯 LLM 全量推演：一次调用让 LLM 产出全部势力的精确数值）已于 2026-10-03
下线 —— 它的失效模式是幻觉而非性能，且与确定性基线互相冲突。
设计文档：emergence-meta/internal/design/2026-10-03-remove-v1-engine.md
"""

from __future__ import annotations

import logging
import os
from enum import Enum

logger = logging.getLogger("histrategy.engine_switch")


class EngineMode(Enum):
    V2 = "v2"  # 纯确定性引擎 — 零 LLM，公式驱动（V3 的基线层）
    V3 = "v3"  # 混合引擎 — V2 确定性基线 + Macro LLM 非线性层 + GuardrailValidator（默认）


def detect_engine_mode() -> EngineMode:
    """检测当前引擎模式。

    优先级: HISTRATEGY_ENGINE > 默认 V3
    """
    engine = os.environ.get("HISTRATEGY_ENGINE", "").strip().lower()

    mode_map = {
        "v2": EngineMode.V2,
        "v3": EngineMode.V3,
    }
    if engine in mode_map:
        return mode_map[engine]

    if engine == "v1":
        logger.warning(
            "HISTRATEGY_ENGINE=v1 已下线（2026-10-03），本次按 V3 运行。"
            " 请在环境变量 / Railway 变量里删掉这一项。"
        )

    return EngineMode.V3
