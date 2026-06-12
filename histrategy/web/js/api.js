/* ─── API Client ─── */
const API = {
  base: '',
  
  async _fetch(path, opts={}) {
    const url = this.base + path;
    const res = await fetch(url, {
      headers: {'Content-Type':'application/json', ...opts.headers},
      ...opts,
    });
    if (!res.ok) {
      const err = await res.text().catch(() => res.statusText);
      throw new Error(`API ${res.status}: ${err}`);
    }
    return res.json();
  },

  async health() { return this._fetch('/api/health'); },
  
  async createGame(faction, scenario='207', opts={}) {
    return this._fetch('/api/games', {
      method:'POST',
      body: JSON.stringify({faction, scenario, new:true, ...opts}),
    });
  },

  async getGame(gameId) { return this._fetch(`/api/games/${gameId}`); },

  async planMode(gameId) {
    return this._fetch(`/api/games/${gameId}/plan`, {method:'POST'});
  },

  async executeCommand(gameId, decision) {
    return this._fetch(`/api/games/${gameId}/command`, {
      method:'POST',
      body: JSON.stringify({decision}),
    });
  },

  async listGames() { return this._fetch('/api/games'); },

  async autosave(gameId, jwt) {
    return this._fetch(`/api/games/${gameId}/autosave`, {
      method:'POST',
      headers: jwt ? {Authorization:`Bearer ${jwt}`} : {},
    });
  },

  getJwt() {
    const m = document.cookie.match(/jwt=([^;]+)/);
    return m ? m[1] : null;
  }
};
