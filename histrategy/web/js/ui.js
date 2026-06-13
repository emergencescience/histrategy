/* ─── UI Rendering ─── */
const UI = {
  el(id) { return document.getElementById(id); },

  /* ── Stats header ── */
  updateStats(status) {
    const s = status || {};
    this.el('stat-year').textContent = s.year || '?';
    this.el('stat-season').textContent = s.season || '?';
    this.el('stat-gold').textContent = (s.treasury || 0).toLocaleString();
    this.el('stat-food').textContent = (s.food || 0).toLocaleString();
    this.el('stat-morale').textContent = s.morale || 0;
    this.el('stat-strength').textContent = (s.strength || 0).toLocaleString();
    this.el('stat-lands').textContent = (s.territories || []).join('、') || '无';
    this.el('stat-turn').textContent = s.turn || 1;
  },

  /* ── Narrative ── */
  appendNarrative(text, className='') {
    const div = this.el('narrative');
    const p = document.createElement('div');
    if (className) p.className = className;
    p.innerHTML = text.replace(/\n/g, '<br>');
    div.appendChild(p);
    div.scrollTop = div.scrollHeight;
  },

  clearNarrative() { this.el('narrative').innerHTML = ''; },

  /* ── Knowledge cards ── */
  renderKnowledgeCards(cards) {
    const container = this.el('knowledge-cards');
    if (!cards || !cards.length) { container.innerHTML = ''; return; }
    container.innerHTML = cards.map(k => {
      const topic = typeof k === 'string' ? k.split(':')[0] : (k.topic || '');
      const logic = typeof k === 'string' ? k.split(':').slice(1).join(':') : (k.engine_logic || '');
      return `<div class="knowledge-card">
        <div class="topic">${this._esc(topic)}</div>
        <div class="logic">${this._esc(logic)}</div>
      </div>`;
    }).join('');
  },

  /* ── Black swan events ── */
  renderBlackSwans(events) {
    const container = this.el('blackswan-cards');
    if (!events || !events.length) { container.innerHTML = ''; return; }
    container.innerHTML = events.map(e => 
      `<div class="blackswan-card">
        <div class="swan-name">⚡ ${this._esc(e.event_id || e.name || '')}</div>
        <p>${this._esc(e.description || e.effect || '')}</p>
      </div>`
    ).join('');
  },

  /* ── NPC status ── */
  renderNPCs(npcData) {
    const container = this.el('npc-cards');
    if (!npcData) { container.innerHTML = ''; return; }
    let entries = [];
    if (Array.isArray(npcData)) {
      entries = npcData;
    } else if (npcData.factions) {
      entries = Object.entries(npcData.factions).map(([id, f]) => ({
        faction_id: id, name: f.name, territories: f.territories, 
        strength: f.strength_actual, morale: f.morale_actual, is_active: f.is_active
      }));
    }
    container.innerHTML = entries.map(e => {
      if (!e.is_active && e.is_active !== undefined) {
        return `<div class="npc-card" style="opacity:0.5">
          <div class="faction-name">${this._esc(e.name||e.faction_id)} ☠ 已灭亡</div>
          <p>${this._esc(e.faction_id)}势力已被消灭</p>
        </div>`;
      }
      const terrs = Array.isArray(e.territories) ? e.territories.join('、') : (e.territories || '');
      return `<div class="npc-card">
        <div class="faction-name">🏰 ${this._esc(e.name||e.faction_id)}</div>
        <p>兵:${(e.strength||0).toLocaleString()} 地:${this._esc(terrs)} 民:${e.morale||'?'}</p>
      </div>`;
    }).join('');
  },

  /* ── Faction select ── */
  showFactionSelect(callback) {
    const main = this.el('main-content');
    main.innerHTML = `
      <div id="faction-select">
        <h2>🏯 选择势力</h2>
        <div class="faction-grid">
          <div class="faction-btn" data-faction="cao">
            <img src="/images/avatar_cao.png" alt="曹操" class="faction-avatar">
            <div class="name">曹操</div><div class="desc">魏 · 魏武大帝</div></div>
          <div class="faction-btn" data-faction="shu">
            <img src="/images/avatar_shu.png" alt="刘备" class="faction-avatar">
            <div class="name">刘备</div><div class="desc">蜀 · 汉昭烈帝</div></div>
          <div class="faction-btn" data-faction="wu">
            <img src="/images/avatar_wu.png" alt="孙权" class="faction-avatar">
            <div class="name">孙权</div><div class="desc">吴 · 东吴大帝</div></div>
        </div>
        <button class="btn" id="start-game-btn" disabled>开始新游戏</button>
      </div>`;
    
    let selected = null;
    main.querySelectorAll('.faction-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        main.querySelectorAll('.faction-btn').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
        selected = btn.dataset.faction;
        this.el('start-game-btn').disabled = false;
      });
    });
    this.el('start-game-btn').addEventListener('click', () => {
      if (selected) callback(selected);
    });
  },

  /* ── Game view ── */
  showGameView() {
    this.el('main-content').innerHTML = `
      <div class="narrative-panel">
        <div id="narrative"><div class="empty">📜 太史令曰：天下大势，分久必合，合久必分……</div></div>
        <div class="input-area">
          <textarea id="decision-input" placeholder="输入你的策令……（例：推行屯田制，降低税率至20%，联吴抗曹）" rows="2"></textarea>
          <div class="btn-group">
            <button class="btn" id="btn-execute" title="执行策令 (Enter)">⚔ 执行</button>
            <button class="btn btn-sm" id="btn-plan" title="战略规划">📋 规划</button>
            <button class="btn btn-sm" id="btn-autosave" title="保存进度">💾</button>
          </div>
        </div>
      </div>
      <div class="side-panel">
        <div class="card"><h4>📚 知识卡片</h4><div id="knowledge-cards"></div></div>
        <div class="card"><h4>⚡ 黑天鹅</h4><div id="blackswan-cards"></div></div>
        <div class="card"><h4>🏰 天下势力</h4><div id="npc-cards"></div></div>
      </div>`;
  },

  showLoading() {
    const btn = this.el('btn-execute');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 处理中...'; }
    const input = this.el('decision-input');
    if (input) input.disabled = true;
    const plan = this.el('btn-plan');
    if (plan) plan.disabled = true;
  },

  hideLoading() {
    const btn = this.el('btn-execute');
    if (btn) { btn.disabled = false; btn.textContent = '⚔ 执行'; }
    const input = this.el('decision-input');
    if (input) { input.disabled = false; input.focus(); }
    const plan = this.el('btn-plan');
    if (plan) plan.disabled = false;
  },

  toast(msg, isError=false) {
    const t = this.el('toast');
    t.textContent = msg;
    t.className = isError ? 'error show' : 'show';
    clearTimeout(t._timeout);
    t._timeout = setTimeout(() => t.classList.remove('show'), 3000);
  },

  _esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
};
