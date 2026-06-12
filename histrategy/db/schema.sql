-- ═══════════════════════════════════════════════════════════
-- 三國志略 — SQL Schema (SQLite / PostgreSQL compatible)
-- ═══════════════════════════════════════════════════════════
-- All UUIDs stored as TEXT for cross-DB compatibility.
-- JSON columns stored as TEXT (SQLite) / JSONB (PostgreSQL).
-- datetime('now') is SQLite-only; PostgreSQL uses NOW().
-- ═══════════════════════════════════════════════════════════

-- game_room: 一局游戏的会话（symmetry: 没有 player_faction_id）
CREATE TABLE IF NOT EXISTS game_room (
    id              TEXT PRIMARY KEY,        -- UUID
    host_user_id    TEXT,                    -- 创建者 user_id（可空）
    scenario        TEXT DEFAULT '207',
    year            INTEGER DEFAULT 207,
    season          TEXT DEFAULT '春',
    quarter_number  INTEGER DEFAULT 0,       -- 当前季度序号
    phase           TEXT DEFAULT 'lobby',    -- lobby | waiting | resolving | finished
    world_state     TEXT,                    -- JSON: 完整 WorldState 快照
    slots           TEXT,                    -- JSON: [Slot, ...]
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- faction_slot: 每个势力槽位（对称：人类/AI 同一张表）
CREATE TABLE IF NOT EXISTS faction_slot (
    id              TEXT PRIMARY KEY,        -- UUID
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    faction_id      TEXT NOT NULL,           -- "cao" | "shu" | "wu" | ...
    occupant_type   TEXT NOT NULL DEFAULT 'open',  -- "human" | "ai_npc" | "open"
    occupant_id     TEXT,                    -- user_id (human) | NULL (ai/open)

    -- AI 配置（仅 occupant_type='ai_npc' 时有效）
    ai_model        TEXT,                    -- LLM model for this NPC
    ai_personality  TEXT,                    -- JSON: aggression/caution/mercy 覆盖

    -- 当前季度决策
    pending_decision TEXT,                   -- 本季度已提交的原始决策文本
    pending_commands TEXT,                   -- JSON: 解析后的结构化命令

    -- 状态
    is_active       INTEGER DEFAULT 1,

    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,

    UNIQUE(room_id, faction_id)
);

-- quarter_turn: 每个季度的完整记录
CREATE TABLE IF NOT EXISTS quarter_turn (
    id              TEXT PRIMARY KEY,        -- UUID
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    year            INTEGER NOT NULL,
    season          TEXT NOT NULL,

    faction_decisions TEXT,                  -- JSON: {"cao": {...}, "shu": {...}, ...}
    baseline_result  TEXT,                   -- JSON: TurnResult
    macro_delta      TEXT,                   -- JSON: MacroPolicyEngine output
    narratives       TEXT,                   -- JSON: {"cao": "...", "shu": "...", ...}
    state_changes    TEXT,                   -- JSON: 所有 faction 的资源变化
    token_usage      TEXT,                   -- JSON: {"intent_parse": 0, "npc_cao": 0, ...}

    created_at       TEXT NOT NULL
);

-- llm_call_log: LLM 调用记录
CREATE TABLE IF NOT EXISTS llm_call_log (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER DEFAULT 0,

    call_type       TEXT NOT NULL,           -- "intent_parse" | "npc_decision" | "macro_simulate" | "narrative"
    faction_id      TEXT,                    -- 哪个 faction 的调用（NULL = 全局）
    provider        TEXT,
    model           TEXT,

    prompt_tokens       INTEGER DEFAULT 0,
    completion_tokens   INTEGER DEFAULT 0,
    total_tokens        INTEGER DEFAULT 0,
    reasoning_tokens    INTEGER,
    latency_ms          INTEGER DEFAULT 0,

    system_prompt   TEXT,
    user_prompt     TEXT,
    response        TEXT,
    error           TEXT,

    created_at      TEXT NOT NULL
);

-- simulation_event_log: 确定性引擎事件
CREATE TABLE IF NOT EXISTS simulation_event_log (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER DEFAULT 0,

    event_type      TEXT NOT NULL,           -- "black_swan" | "baseline" | "policy_cmd" | "state_mutation"
    event_data      TEXT,                    -- JSON

    created_at      TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_faction_slot_room ON faction_slot(room_id);
CREATE INDEX IF NOT EXISTS idx_quarter_turn_room ON quarter_turn(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_room ON llm_call_log(room_id);
CREATE INDEX IF NOT EXISTS idx_sim_event_log_room ON simulation_event_log(room_id);
