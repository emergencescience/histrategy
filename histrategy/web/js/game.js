/* ─── Game State & Event Handlers ─── */
const Game = {
  gameId: null,
  faction: null,
  engineVersion: null,

  async init() {
    // Check health
    try {
      const h = await API.health();
      this.engineVersion = h.engine_version;
      const badge = UI.el('llm-badge');
      if (badge) {
        badge.textContent = h.llm_available ? 'AI ON' : 'AI OFF';
        badge.className = 'llm-badge ' + (h.llm_available ? 'llm-on' : 'llm-off');
      }
    } catch(e) {
      console.warn('Health check failed:', e);
    }

    // ── Check for resume from URL ──
    const params = new URLSearchParams(location.search);
    const resumeId = params.get('game_id');
    if (resumeId) {
      await this.resumeGame(resumeId);
      return;
    }

    // Show faction select
    UI.showFactionSelect(async (faction) => {
      this.faction = faction;
      await this.startNewGame();
    });
  },

  async resumeGame(gameId) {
    try {
      UI.toast('正在恢复游戏...');
      const data = await API.getGame(gameId);
      this.gameId = gameId;
      this.faction = data.faction_status?.faction_id || '';

      UI.showGameView();
      this._bindEvents();

      // Render past turns
      const turns = data.turns || [];
      if (turns.length > 0) {
        for (const t of turns) {
          UI.appendNarrative(
            `<span class="turn-marker">▸ 第 ${t.turn} 回合 — ${t.year}年${t.season}</span>`,
            'turn-marker'
          );
          if (t.player_decision) {
            UI.appendNarrative(`<b>君令:</b> ${t.player_decision}`, 'diplo');
          }
          if (t.narrative) {
            UI.appendNarrative(t.narrative);
          }
          if (t.aftermath) {
            UI.appendNarrative(t.aftermath);
          }
          if (t.npc_actions && t.npc_actions.length) {
            UI.appendNarrative(`<b>天下动向:</b><br>${t.npc_actions.map(a => '· '+a).join('<br>')}`, 'diplo');
          }
        }
      }

      // Update stats
      if (data.faction_status) {
        UI.updateStats(data.faction_status);
      }

      UI.toast('游戏已恢复！当前第 ' + (data.faction_status?.turn || '?') + ' 回合');
    } catch(e) {
      UI.toast('恢复游戏失败: ' + e.message, true);
      // Fall back to new game
      UI.showFactionSelect(async (faction) => {
        this.faction = faction;
        await this.startNewGame();
      });
    }
  },

  async startNewGame() {
    try {
      UI.toast('正在创建新游戏...');
      const data = await API.createGame(this.faction);
      this.gameId = data.game_id;
      
      UI.showGameView();
      this._bindEvents();
      
      // Show intro
      if (data.intro && data.intro.narrative) {
        UI.appendNarrative(data.intro.narrative);
      }
      if (data.faction_status) {
        UI.updateStats(data.faction_status);
      }
      UI.toast('新游戏已就绪！输入策令开始你的征程。');
    } catch(e) {
      UI.toast('创建游戏失败: ' + e.message, true);
    }
  },

  async executeCommand() {
    const input = UI.el('decision-input');
    const text = input.value.trim();
    if (!text || !this.gameId) return;

    UI.showLoading();
    input.value = '';
    
    // Show player decision
    UI.appendNarrative(`\n<span class="turn-marker">▸ 第 ? 回合 — 君令</span>\n${text}`, 'diplo');
    
    try {
      const result = await API.executeCommand(this.gameId, text);
      
      // Narrative
      if (result.narrative) {
        UI.appendNarrative(result.narrative);
      }
      if (result.aftermath) {
        UI.appendNarrative(result.aftermath);
      }
      
      // State update
      if (result.world_state) {
        Game._extractAndUpdateStats(result);
      }
      
      // Knowledge cards
      if (result.knowledge_cards) {
        UI.renderKnowledgeCards(result.knowledge_cards);
      }
      
      // Black swan events
      if (result.black_swan_events) {
        UI.renderBlackSwans(result.black_swan_events);
      }
      
      // NPC data
      if (result.world_state && result.world_state.factions) {
        UI.renderNPCs(result.world_state.factions);
      }
      
      // NPC reactions
      if (result.npc_reactions && result.npc_reactions.length) {
        for (const r of result.npc_reactions) {
          const faction = r.faction || r.name || '';
          const action = r.action || r.reaction || '';
          if (action) UI.appendNarrative(`**${faction}**: ${action}`, 'diplo');
        }
      }
      
      // Game over?
      if (result.game_over) {
        UI.appendNarrative('\n🎌 **游戏结束**', 'event');
        UI.el('btn-execute').disabled = true;
      }
      
      // Token usage
      const usage = result._usage || {};
      if (usage.sim_tokens) {
        UI.toast(`本回合消耗 ${usage.sim_tokens.toLocaleString()} tokens`);
      }
    } catch(e) {
      UI.toast('策令执行失败: ' + e.message, true);
    } finally {
      UI.hideLoading();
    }
  },

  async planMode() {
    if (!this.gameId) return;
    UI.showLoading();
    try {
      const result = await API.planMode(this.gameId);
      if (result.narrative) {
        UI.appendNarrative('\n<span class="turn-marker">📋 战略规划</span>');
        UI.appendNarrative(result.narrative);
      }
      if (result.suggestions && result.suggestions.length) {
        UI.appendNarrative('\n**建议方略:**');
        for (const s of result.suggestions) {
          UI.appendNarrative(`• ${s}`);
        }
      }
      UI.toast('战略规划已更新');
    } catch(e) {
      UI.toast('规划请求失败: ' + e.message, true);
    } finally {
      UI.hideLoading();
    }
  },

  async autosave() {
    if (!this.gameId) return;
    try {
      const jwt = API.getJwt();
      await API.autosave(this.gameId, jwt);
      UI.toast('💾 已保存');
    } catch(e) {
      UI.toast('保存失败: ' + e.message, true);
    }
  },

  _extractAndUpdateStats(result) {
    const ws = result.world_state;
    if (!ws || !ws.player_faction_id) return;
    
    let seasonVal = ws.season_cn || ws.season || '?';
    if (typeof seasonVal === 'object' && seasonVal !== null) {
      seasonVal = seasonVal.cn || seasonVal.name || '?';
    }
    const seasonMap = {
      'SPRING': '春', 'SUMMER': '夏', 'AUTUMN': '秋', 'WINTER': '冬',
      'spring': '春', 'summer': '夏', 'autumn': '秋', 'winter': '冬'
    };
    if (seasonMap[seasonVal]) {
      seasonVal = seasonMap[seasonVal];
    }

    const pf = ws.factions && ws.factions[ws.player_faction_id];
    const status = {
      year: ws.year || 207,
      season: seasonVal,
      treasury: pf ? pf.treasury : 0,
      food: pf ? pf.food : 0,
      morale: pf ? (pf.morale_actual || 0) : 0,
      strength: pf ? (pf.strength_actual || 0) : 0,
      territories: pf && pf.territories ? pf.territories : [],
      turn: ws.turn_number || 0,
    };
    UI.updateStats(status);
  },

  _bindEvents() {
    const input = UI.el('decision-input');
    const btnExec = UI.el('btn-execute');
    const btnPlan = UI.el('btn-plan');
    const btnSave = UI.el('btn-autosave');
    
    if (btnExec) btnExec.addEventListener('click', () => this.executeCommand());
    if (btnPlan) btnPlan.addEventListener('click', () => this.planMode());
    if (btnSave) btnSave.addEventListener('click', () => this.autosave());
    
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.executeCommand();
        }
      });
    }
  }
};

// Boot
document.addEventListener('DOMContentLoaded', () => Game.init());
