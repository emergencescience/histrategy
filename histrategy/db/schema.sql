-- histrategy Database Schema
-- Compatible with SQLite 3.x and PostgreSQL 14+
-- All IDs use TEXT (UUIDs as strings) for cross-DB compatibility.

-- ═══════════════════════════════════════════════════════════
-- game_room: 一局游戏会话
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS game_room (
    id              TEXT PRIMARY KEY,
    host_user_id    TEXT,
    scenario        TEXT DEFAULT '207',
    year            INTEGER DEFAULT 207,
    season          TEXT DEFAULT '春',
    quarter_number  INTEGER DEFAULT 0,
    phase           TEXT DEFAULT 'lobby',
    world_state     TEXT,                      -- JSON: 完整 WorldState
    slots           TEXT,                      -- JSON: [FactionSlot, ...]
    decision_timeout INTEGER DEFAULT 300,
    turn_summaries  TEXT DEFAULT '[]',         -- JSON: 回合摘要数组
    metadata        TEXT DEFAULT '{}',         -- JSON: 房间元数据 (lang, etc.)
    engine_version  TEXT DEFAULT '',            -- 'v1' | 'v2' | 'v3' — 哪套引擎产生此房间
    created_at      TEXT DEFAULT '',
    updated_at      TEXT DEFAULT ''
);

-- ═══════════════════════════════════════════════════════════
-- faction_slot: 每个势力槽位（对称：人类/AI 同一张表）
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS faction_slot (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    faction_id      TEXT NOT NULL,
    occupant_type   TEXT NOT NULL DEFAULT 'open',  -- human | ai_npc | open
    occupant_id     TEXT,                          -- user_id (human) | NULL
    display_name    TEXT DEFAULT '',               -- human-readable name (e.g. "张三")
    ai_model        TEXT,                          -- LLM model for NPC
    ai_temperature  REAL DEFAULT 0.7,
    pending_decision TEXT,                         -- 本季度已提交决策
    pending_commands TEXT,                         -- JSON: 结构化命令
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT '',
    updated_at      TEXT DEFAULT '',
    UNIQUE(room_id, faction_id)
);

-- ═══════════════════════════════════════════════════════════
-- quarter_turn: 每季度的完整记录
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS quarter_turn (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    year            INTEGER NOT NULL,
    season          TEXT NOT NULL,
    faction_decisions TEXT,                    -- JSON: {faction_id: {decision, commands}}
    baseline_result  TEXT,                     -- JSON: TurnResult
    macro_delta      TEXT,                     -- JSON: MacroPolicyEngine output
    narratives       TEXT,                     -- JSON: {faction_id: narrative_text}
    state_changes    TEXT,                     -- JSON: {faction_id: {strength, treasury, ...}}
    token_usage      TEXT,                     -- JSON: {call_type: tokens}
    created_at       TEXT DEFAULT ''
);

-- ═══════════════════════════════════════════════════════════
-- llm_call_log: LLM 调用记录（仅存 system_prompt_type，不存全文）
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS llm_call_log (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER DEFAULT 0,
    call_type       TEXT NOT NULL,              -- intent_parse | npc_decision | macro_simulate | narrative
    faction_id      TEXT,                      -- 哪个势力的调用（NULL = 全局）
    provider        TEXT,
    model           TEXT,
    prompt_tokens       INTEGER DEFAULT 0,
    completion_tokens   INTEGER DEFAULT 0,
    total_tokens        INTEGER DEFAULT 0,
    reasoning_tokens    INTEGER,
    latency_ms          INTEGER DEFAULT 0,
    system_prompt_type  TEXT,                  -- 仅存类型: npc_decision | macro_simulator | intent_parse | narrative | ...
    user_prompt     TEXT,                      -- 用户 prompt（不含 system prompt 全文）
    response        TEXT,                      -- LLM 响应
    error           TEXT,
    created_at      TEXT DEFAULT ''
);

-- ═══════════════════════════════════════════════════════════
-- simulation_event_log: 确定性引擎事件
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS simulation_event_log (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER DEFAULT 0,
    event_type      TEXT NOT NULL,              -- black_swan | baseline | policy_cmd | state_mutation
    event_data      TEXT,                      -- JSON
    created_at      TEXT DEFAULT ''
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_faction_slot_room ON faction_slot(room_id);
CREATE INDEX IF NOT EXISTS idx_quarter_turn_room ON quarter_turn(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_room ON llm_call_log(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_sim_event_room ON simulation_event_log(room_id, quarter_number);

-- ═══════════════════════════════════════════════════════════
-- game_state: 每季度各势力完整状态快照（数值+城池+政策）
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS game_state (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    faction_id      TEXT NOT NULL,
    -- 数值状态
    population      INTEGER DEFAULT 0,
    troops          INTEGER DEFAULT 0,
    food            REAL DEFAULT 0,
    treasury        REAL DEFAULT 0,
    morale          INTEGER DEFAULT 50,
    -- 城池控制（JSON: [{"territory_id": "xuchang", "population": 50000, ...}]）
    territories     TEXT DEFAULT '[]',
    -- 非数值状态（政策/科技树 — JSON blob）
    policies        TEXT DEFAULT '{}',
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT '',
    UNIQUE(room_id, quarter_number, faction_id)
);

-- ═══════════════════════════════════════════════════════════
-- turn_delta: 每轮数值增量（人口/兵力/粮草/库金/民心变化）
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS turn_delta (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    faction_id      TEXT NOT NULL,
    delta_type      TEXT NOT NULL,  -- 'population' | 'troops' | 'food' | 'treasury' | 'morale'
    old_value       REAL,
    new_value       REAL,
    delta           REAL,
    reason          TEXT,           -- 变化原因（如 "屯田制+5%", "战争伤亡-2000"）
    source          TEXT DEFAULT 'deterministic',  -- 'deterministic' | 'llm' | 'black_swan'
    created_at      TEXT DEFAULT ''
);

-- ═══════════════════════════════════════════════════════════
-- policy_state: 政策法令和科技树状态
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS policy_state (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES game_room(id),
    quarter_number  INTEGER NOT NULL,
    faction_id      TEXT NOT NULL,
    policy_type     TEXT NOT NULL,    -- 'law' | 'diplomacy' | 'economic' | 'military' | 'tech'
    policy_name     TEXT NOT NULL,    -- '科举制' | '盐铁专营' | '屯田制' | '九品中正制'
    policy_level    INTEGER DEFAULT 1,
    params          TEXT DEFAULT '{}',
    status          TEXT DEFAULT 'active',
    activated_at    TEXT DEFAULT '',
    revoked_at      TEXT,
    UNIQUE(room_id, faction_id, policy_name, status)
);

CREATE INDEX IF NOT EXISTS idx_game_state_room ON game_state(room_id, quarter_number);
CREATE INDEX IF NOT EXISTS idx_turn_delta_room ON turn_delta(room_id, quarter_number, faction_id);
CREATE INDEX IF NOT EXISTS idx_policy_state_room ON policy_state(room_id, faction_id);
