/* Imperialis — interactions du plateau (phases, annotations, unités, résolveur, map, zoom). */

async function postJSON(url, data) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return r.json().catch(() => ({}));
}

function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

const Game = {
  async advance() {
    const r = await postJSON("/api/phase/advance", { gid: GID });
    if (r.finished) {
      alert("Partie terminée ! Voir le tracker VP pour le résultat.");
      window.location.href = window.location.href.replace(/\/play\/.*/, `/play/${GID}`);
      return;
    }
    window.location.reload();
  },

  async saveAnnotation(player_id) {
    const ta = document.getElementById("anno-text");
    const text = (ta.value || "").trim();
    if (!text) return;
    await postJSON("/api/annotation", { gid: GID, player_id, text });
    const list = document.getElementById("anno-list");
    const div = document.createElement("div");
    div.className = "annotation";
    div.innerHTML = `<span class="small muted">maintenant</span> · ${esc(text)}`;
    list.prepend(div);
    ta.value = "";
  },

  async adjCP(player_id, delta) {
    const r = await postJSON("/api/cp", { player_id, delta, reason: "Ajustement manuel" });
    const el = document.getElementById("cp_" + player_id);
    if (el) el.textContent = r.cp;
  },

  async adjVP(player_id, delta) {
    const r = await postJSON("/api/vp", { player_id, delta, reason: "Ajustement manuel" });
    const el = document.getElementById("vp_" + player_id);
    if (el) el.textContent = r.vp_total;
  },

  async useStratagem(player_id, name, cp) {
    if (!confirm(`Utiliser "${name}" (${cp} CP) ?`)) return;
    const r = await postJSON("/api/stratagem/use", { player_id, name, cp });
    const el = document.getElementById("cp_" + player_id);
    if (el) el.textContent = r.cp;
  },

  async adjWounds(unit_id, delta) {
    const r = await postJSON("/api/unit/wounds", { unit_id, delta });
    const el = document.getElementById("wounds_" + unit_id);
    if (el && r.wounds_current != null) {
      const total = el.textContent.split("/")[1];
      el.textContent = `${r.wounds_current}/${total}`;
    }
  },
};

const UnitModal = {
  async open(unit_id) {
    const modal = document.getElementById("unit-modal");
    const content = document.getElementById("unit-modal-content");
    content.innerHTML = "<p>Chargement…</p>";
    modal.classList.add("open");
    const html = await fetch(`/play/${GID}/unit/${unit_id}`).then(r => r.text());
    content.innerHTML = html;
  },
  close() {
    document.getElementById("unit-modal").classList.remove("open");
  },
};

/* ============================================================
   Résolveur d'attaque (encart plateau, avec dés côté client)
   ============================================================ */
const Resolver = {
  state: { weapon: null, result: null, attackerId: null, defenderId: null, woundSaves: 0 },

  init() {
    const aSel = document.getElementById("rsv_a");
    const dSel = document.getElementById("rsv_d");
    if (!aSel || !dSel) return;
    // group units by seat
    const bySeat = { 1: [], 2: [] };
    UNITS.forEach(u => { (bySeat[u.seat] = bySeat[u.seat] || []).push(u); });
    aSel.innerHTML = this._optgroups(bySeat);
    dSel.innerHTML = this._optgroups(bySeat);
    // defaults: attacker = first seat-1 unit, defender = first seat-2 unit
    if (bySeat[1] && bySeat[1][0]) aSel.value = bySeat[1][0].id;
    if (bySeat[2] && bySeat[2][0]) dSel.value = bySeat[2][0].id;
    aSel.addEventListener("change", () => { this.populateWeapons(); this.compute(); });
    dSel.addEventListener("change", () => { this.renderDefStats(); this.compute(); });
    document.getElementById("rsv_w").addEventListener("change", () => this.compute());
    this.populateWeapons();
    this.renderDefStats();
    this.compute();
  },

  _optgroups(bySeat) {
    let html = "";
    for (const s of [1, 2]) {
      const list = bySeat[s] || [];
      if (!list.length) continue;
      html += `<optgroup label="Joueur ${s}">`;
      list.forEach(u => {
        const label = `${u.name} (${u.models_current}/${u.models_total} mod.${u.wounds_total ? " · " + u.wounds_current + "/" + u.wounds_total + " PV" : ""})`;
        html += `<option value="${u.id}">${esc(label)}</option>`;
      });
      html += "</optgroup>";
    }
    if (!html) html = `<option value="">— Aucune unité —</option>`;
    return html;
  },

  _currentUnit(id) { return UNITS.find(u => String(u.id) === String(id)); },

  populateWeapons() {
    const wSel = document.getElementById("rsv_w");
    const a = this._currentUnit(document.getElementById("rsv_a").value);
    const weapons = (a && a.weapons) || [];
    wSel.innerHTML = weapons.length
      ? weapons.map((w, i) => `<option value="${i}">[${esc(w.type || "?")}] ${esc(w.name)}</option>`).join("")
      : `<option value="">— Aucune arme —</option>`;
  },

  renderDefStats() {
    const box = document.getElementById("rsv_def_stats");
    const d = this._currentUnit(document.getElementById("rsv_d").value);
    if (!d) { box.textContent = ""; return; }
    const s = d.stats || {};
    box.innerHTML = `T ${esc(s.T || "?")} · Sv ${esc(s.Sv || "?")}${s.InSv ? "/" + esc(s.InSv) : ""} · W ${esc(s.W || "?")}`
      + (d.wounds_total ? ` · PV ${d.wounds_current}/${d.wounds_total}` : "");
  },

  async compute() {
    const aId = document.getElementById("rsv_a").value;
    const dId = document.getElementById("rsv_d").value;
    const w = parseInt(document.getElementById("rsv_w").value, 10);
    const out = document.getElementById("rsv_result");
    if (!aId || !dId || isNaN(w)) { out.innerHTML = `<p class="muted small">Sélectionne attaquant, arme et défenseur.</p>`; return; }
    out.innerHTML = "<p class='small muted'>Calcul…</p>";
    const r = await postJSON("/api/resolve-attack", { a_unit_id: aId, d_unit_id: dId, w });
    if (!r.ok) { out.innerHTML = `<p class="muted small">${esc(r.error || "Calcul impossible.")}</p>`; return; }
    this.state = { weapon: r.weapon, result: r.result, attackerId: aId, defenderId: dId, woundSaves: 0 };
    this.render(r);
  },

  render(r) {
    const res = r.result, w = r.weapon, d = r.defender;
    const attacks = (res.A_val || 0) * res.num_attackers;
    const out = document.getElementById("rsv_result");
    const dice = attacks > 0
      ? `<button class="btn small" onclick="Resolver.roll('wound')">🎲 Blesser (${attacks}D6 ≥ ${res.wound_target_str})</button>
         <button class="btn small" onclick="Resolver.roll('save')">🎲 Sauvegarder (≥ ${res.save_target_str})</button>`
      : "";
    let saveCell = res.save_target_str;
    if (res.save.chosen_kind === "invuln") saveCell += ` <span class="small muted">(inv.)</span>`;
    out.innerHTML = `
      <table class="stats" style="width:100%;margin-top:6px">
        <tr><th>Attaques</th><th>Blesser</th><th>Sauvegarde</th><th>Dégâts/att.</th></tr>
        <tr>
          <td>${esc(w.A)}${res.A_val && res.num_attackers ? ` × ${res.num_attackers} = ${attacks}` : ""}</td>
          <td class="big">${res.wound_target_str}</td>
          <td class="big">${saveCell}</td>
          <td>${esc(w.D)}</td>
        </tr>
      </table>
      <ul class="small" style="margin-top:6px">
        <li><b>Blesser :</b> F${esc(w.S)} vs E${esc((d.stats||{}).T || "?")} → ${res.wound_target_str} sur 1D6.</li>
        <li><b>Sauvegarder :</b> ${res.save.armour_target ? `armure ${res.save.armour_target}+ (après AP ${esc(w.AP)})` : `pas d'armure après AP ${esc(w.AP)}`}${res.save.invuln_target ? ` · invulnérable ${res.save.invuln_target}+` : ""}.</li>
        <li><b>Dégâts :</b> ${esc(w.D)} par attaque non sauvegardée · défenseur ${d.wounds_current}/${d.wounds_total || "?"} PV.</li>
        ${res.exp_damage != null ? `<li class="muted"><em>Moyenne :</em> ~${(res.exp_attacks||0).toFixed(1)} att → ~${(res.exp_wounds||0).toFixed(1)} bless. → ~${(res.exp_unsaved||0).toFixed(1)} non sauvegardées → ~${(res.exp_damage||0).toFixed(1)} dégâts.</li>` : ""}
      </ul>
      <div class="dice-tools" style="margin-top:8px">${dice}<div id="roll-out" class="small" style="margin-top:6px"></div></div>`;
  },

  _diceFace(v, cls = "") {
    return `<span class="dice-face ${cls}">${v}</span>`;
  },

  roll(kind) {
    const res = this.state.result;
    if (!res) return;
    const out = document.getElementById("roll-out");
    const rollDice = (n) => { const a = []; for (let i = 0; i < n; i++) a.push(1 + Math.floor(Math.random() * 6)); return a; };
    // Mêmes dés animés (dice-pop) que le Battle Shock : un span .dice-face par dé.
    const faces = (dice, tgt) => dice.map(v => this._diceFace(v, v >= tgt ? "hit" : "miss")).join("");
    if (kind === "wound") {
      const tgt = res.wound_target;
      if (!tgt) { out.textContent = "Données incomplètes."; return; }
      const n = Math.max(1, (res.A_val || 1) * res.num_attackers);
      const dice = rollDice(n);
      const succ = dice.filter(v => v >= tgt).length;
      this.state.woundSaves = succ;
      out.innerHTML = `<div class="dice-result">Blessures : <span class="dice-row">${faces(dice, tgt)}</span> → <b>${succ}</b> réussite(s) sur ${n} (≥${tgt}+).</div>`
        + (succ > 0 ? ` <button class="btn small" onclick="Resolver.roll('save')">Lancer ${succ} sauvegardes →</button>` : "");
    } else {
      const tgt = res.save.chosen_target;
      if (!tgt) { out.textContent = "Données incomplètes."; return; }
      const m = Math.max(1, this.state.woundSaves || 1);
      const dice = rollDice(m);
      const svd = dice.filter(v => v >= tgt).length;
      const failed = m - svd;
      const dmg = this.state.weapon ? this.state.weapon.D : "?";
      out.innerHTML = `<div class="dice-result">Sauvegardes : <span class="dice-row">${faces(dice, tgt)}</span> → <b>${failed}</b> non sauvegardée(s) sur ${m} (≥${tgt}+). → ~${failed} × ${esc(dmg)} dégât(s) potentiel(s).</div>`;
    }
  },
};

/* ============================================================
   Battle Shock (Command phase) : jet 2D6 vs LD, marque l'unité
   ============================================================ */
const BattleShock = {
  init() {
    const sel = document.getElementById("bs_unit");
    if (!sel) return;
    const bySeat = { 1: [], 2: [] };
    UNITS.forEach(u => { (bySeat[u.seat] = bySeat[u.seat] || []).push(u); });
    let html = "";
    for (const s of [1, 2]) {
      const list = bySeat[s] || [];
      if (!list.length) continue;
      html += `<optgroup label="Joueur ${s}">`;
      list.forEach(u => {
        const ld = (u.stats && u.stats.LD) || "?";
        const half = u.models_total > 0 && (u.models_current <= u.models_total / 2);
        const tag = half ? " ⚡demi-effectif" : (u.battle_shocked ? " · déjà shock" : "");
        html += `<option value="${u.id}">${esc(u.name)} (LD ${esc(ld)}${tag})</option>`;
      });
      html += "</optgroup>";
    }
    sel.innerHTML = html || `<option value="">— Aucune unité —</option>`;
    // default: first unit of the active seat if available
    const activeSeat = (typeof ACTIVE_SEAT !== "undefined" && ACTIVE_SEAT) || 1;
    if (bySeat[activeSeat] && bySeat[activeSeat][0]) sel.value = bySeat[activeSeat][0].id;
  },

  _ldNum(u) {
    const ld = (u && u.stats && u.stats.LD) || "";
    const m = String(ld).match(/(\d+)/);
    return m ? parseInt(m[1], 10) : null;
  },

  _diceFace(v) { return `<span class="dice-face">${v}</span>`; },

  async roll() {
    const sel = document.getElementById("bs_unit");
    const out = document.getElementById("bs_result");
    if (!sel || !out) return;
    const u = UNITS.find(x => String(x.id) === String(sel.value));
    if (!u) { out.innerHTML = `<span class="muted">Sélectionne une unité.</span>`; return; }
    const ld = this._ldNum(u);
    if (ld == null) { out.innerHTML = `<span class="muted">LD inconnu pour cette unité.</span>`; return; }
    const d1 = 1 + Math.floor(Math.random() * 6);
    const d2 = 1 + Math.floor(Math.random() * 6);
    const total = d1 + d2;
    const failed = total > ld;
    const half = u.models_total > 0 && (u.models_current <= u.models_total / 2);
    let msg = `<div>${this._diceFace(d1)} ${this._diceFace(d2)} = <b>${total}</b> vs LD <b>${ld}</b> — `;
    if (failed) {
      msg += `<span class="half">ÉCHEC : l'unité est battle-shocked.</span></div>`;
      // forcer l'état shock côté serveur + UI
      await postJSON("/api/unit/toggle-shock", { unit_id: u.id, shocked: 1 });
      u.battle_shocked = true;
      const cb = document.querySelector(`.shock-toggle[data-unit="${u.id}"]`);
      if (cb) { cb.checked = true; const panel = cb.closest(".unit"); if (panel) panel.classList.add("shocked"); }
    } else {
      msg += `<span class="ok">Réussi : l'unité tient.</span></div>`;
      // en cas de réussite, retirer l'état shock s'il était actif
      if (u.battle_shocked) {
        await postJSON("/api/unit/toggle-shock", { unit_id: u.id, shocked: 0 });
        u.battle_shocked = false;
        const cb = document.querySelector(`.shock-toggle[data-unit="${u.id}"]`);
        if (cb) { cb.checked = false; const panel = cb.closest(".unit"); if (panel) panel.classList.remove("shocked"); }
      }
    }
    if (!half && u.models_total > 0) {
      msg += `<div class="muted small">Note : cette unité n'est pas sous demi-effectif (test non requis par les règles core).</div>`;
    }
    out.innerHTML = msg;
  },
};

/* ============================================================
   Plateau interactif : placement de jetons sur le layout
   Une unité peut être divisée en plusieurs jetons (multi-figurines)
   et un jeton peut être marqué détruit (reste sur le plateau, grisé).
   ============================================================ */
const Board = {
  init() {
    this.el = document.getElementById("board");
    this.palette = document.getElementById("palette-list");
    if (!this.el) return;
    this.tokens = (typeof TOKENS !== "undefined" && TOKENS) ? TOKENS.slice() : [];
    this.units = (typeof UNITS !== "undefined" && UNITS) ? UNITS.slice() : [];
    this.render();
  },

  render() {
    // jetons placés
    this.el.querySelectorAll(".token").forEach(t => t.remove());
    this.tokens.forEach(tk => {
      if (tk.pos_x == null || tk.pos_y == null) return;
      this.el.appendChild(this._token(tk));
    });
    // palette = unités sans aucun jeton
    const hasToken = new Set(this.tokens.map(t => t.unit_id));
    const unplaced = this.units.filter(u => !hasToken.has(u.id));
    this.palette.innerHTML = unplaced.length
      ? unplaced.map(u =>
          `<button class="token-chip p${u.seat}" onclick="Board.place(${u.id})"><span class="dot"></span>${esc(u.name)}</button>`
        ).join(" ")
      : `<span class="small muted">Toutes les unités sont placées.</span>`;
  },

  _initials(name) {
    if (!name) return "?";
    const clean = String(name).replace(/\(.*?\)/g, "").trim();
    const words = clean.split(/\s+/).filter(w => w.length > 2);
    if (words.length === 0) return clean.slice(0, 2).toUpperCase();
    if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
    return words.slice(0, 2).map(w => w[0]).join("").toUpperCase();
  },

  _badge(tk) {
    // Pour une unité multi-figurines : le nombre de figurines du sous-groupe.
    // Pour une unité mono-figurine multi-pv : les PV restants/total.
    if (tk.models_total > 1) return String(tk.models);
    if (tk.wounds_total) return `${tk.wounds_current}/${tk.wounds_total}`;
    return "";
  },

  _token(tk) {
    const t = document.createElement("div");
    let cls = `token p${tk.seat}`;
    if (tk.dead) cls += " dead";
    else if (tk.battle_shocked) cls += " shocked";
    t.className = cls;
    t.dataset.token = tk.id;
    t.dataset.label = tk.name || "";
    t.title = tk.name || "";
    t.style.left = (tk.pos_x * 100) + "%";
    t.style.top = (tk.pos_y * 100) + "%";
    const badge = this._badge(tk);
    const splitBtn = (tk.models > 1 && !tk.dead)
      ? `<button class="token-act token-split" title="Diviser (1 figurine)">⤴</button>` : "";
    const deadBtn = `<button class="token-act token-dead" title="${tk.dead ? 'Rétablir' : 'Marquer détruit'}">${tk.dead ? '↺' : '☠'}</button>`;
    const xBtn = `<button class="token-act token-x" title="Retirer du plateau">×</button>`;
    t.innerHTML = `<span class="token-init">${esc(this._initials(tk.name))}</span>`
      + (badge ? `<span class="token-hp">${esc(badge)}</span>` : "")
      + `<span class="token-acts">${splitBtn}${deadBtn}${xBtn}</span>`;
    t.querySelector(".token-x").addEventListener("click", (e) => { e.stopPropagation(); this.remove(tk.id); });
    t.querySelector(".token-dead").addEventListener("click", (e) => { e.stopPropagation(); this.dead(tk.id); });
    const sp = t.querySelector(".token-split");
    if (sp) sp.addEventListener("click", (e) => { e.stopPropagation(); this.split(tk.id); });
    this._makeDraggable(t, tk);
    return t;
  },

  place(unitId) {
    const u = this.units.find(x => x.id === unitId);
    if (!u) return;
    postJSON("/api/token/place", { unit_id: unitId, x: 0.5, y: 0.5 }).then(r => {
      this.tokens.push({
        id: r.token_id, unit_id: unitId, seat: u.seat, name: u.name,
        pos_x: r.x, pos_y: r.y,
        models: u.models_current || u.models_total || 1,
        dead: false, label: null,
        models_total: u.models_total, models_current: u.models_current,
        wounds_total: u.wounds_total, wounds_current: u.wounds_current,
        battle_shocked: u.battle_shocked,
      });
      this.render();
    });
  },

  split(tokenId) {
    postJSON("/api/token/split", { token_id: tokenId }).then(r => {
      if (!r.ok) { alert(r.error || "Division impossible."); return; }
      const src = this.tokens.find(t => t.id === tokenId);
      if (src) src.models -= 1;
      // recharge le nouveau jeton depuis le serveur : on connaît son id, on
      // le reconstruit à partir du jeton source.
      if (src) {
        this.tokens.push({
          id: r.new_token_id, unit_id: src.unit_id, seat: src.seat, name: src.name,
          pos_x: Math.min(1, (src.pos_x || 0.5) + 0.04),
          pos_y: Math.min(1, (src.pos_y || 0.5) + 0.04),
          models: 1, dead: false, label: src.label,
          models_total: src.models_total, models_current: src.models_current,
          wounds_total: src.wounds_total, wounds_current: src.wounds_current,
          battle_shocked: src.battle_shocked,
        });
      }
      this.render();
    });
  },

  dead(tokenId) {
    postJSON("/api/token/dead", { token_id: tokenId }).then(r => {
      const tk = this.tokens.find(t => t.id === tokenId);
      if (tk) tk.dead = !!r.dead;
      this.render();
    });
  },

  remove(tokenId) {
    postJSON("/api/token/remove", { token_id: tokenId }).then(() => {
      this.tokens = this.tokens.filter(t => t.id !== tokenId);
      this.render();
    });
  },

  _persist(tk, x, y) {
    tk.pos_x = x; tk.pos_y = y;
    postJSON("/api/token/move", { token_id: tk.id, x, y });
  },

  _makeDraggable(t, tk) {
    let dragging = false, sx, sy, startLeft, startTop, rect;
    const onDown = (e) => {
      if (e.target.closest(".token-acts")) return;
      dragging = true;
      rect = this.el.getBoundingClientRect();
      const p = e.touches ? e.touches[0] : e;
      sx = p.clientX; sy = p.clientY;
      startLeft = tk.pos_x; startTop = tk.pos_y;
      t.classList.add("dragging");
      e.preventDefault();
    };
    const onMove = (e) => {
      if (!dragging) return;
      const p = e.touches ? e.touches[0] : e;
      const dx = (p.clientX - sx) / rect.width;
      const dy = (p.clientY - sy) / rect.height;
      const nx = Math.max(0, Math.min(1, startLeft + dx));
      const ny = Math.max(0, Math.min(1, startTop + dy));
      t.style.left = (nx * 100) + "%";
      t.style.top = (ny * 100) + "%";
      tk._pending = { x: nx, y: ny };
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      t.classList.remove("dragging");
      if (tk._pending) { this._persist(tk, tk._pending.x, tk._pending.y); delete tk._pending; }
    };
    t.addEventListener("mousedown", onDown);
    t.addEventListener("touchstart", onDown, { passive: false });
    document.addEventListener("mousemove", onMove);
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("mouseup", onUp);
    document.addEventListener("touchend", onUp);
  },
};

/* ============================================================
   Zoom au clic sur les images de cartes
   ============================================================ */
const Zoom = {
  init() {
    document.addEventListener("click", (e) => {
      const img = e.target.closest("img.zoomable");
      if (img) this.open(img.src, img.alt);
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") this.close(); });
  },
  open(src, alt) {
    const lb = document.getElementById("lightbox");
    const im = document.getElementById("lightbox-img");
    im.src = src; im.alt = alt || "";
    lb.classList.add("open");
  },
  close() {
    document.getElementById("lightbox").classList.remove("open");
  },
};

// Coche la checklist (effet visuel local)
document.addEventListener("change", async (e) => {
  // Battle-shock toggle
  if (e.target.classList.contains("shock-toggle")) {
    const unit_id = e.target.dataset.unit;
    const r = await postJSON("/api/unit/toggle-shock", {
      unit_id,
      shocked: e.target.checked ? 1 : 0,
    });
    const panel = e.target.closest(".unit");
    if (panel) panel.classList.toggle("shocked", !!r.battle_shocked);
  }
  // Compteur de modèles
  if (e.target.classList.contains("models-input")) {
    const unit_id = e.target.dataset.unit;
    await postJSON("/api/unit/models", { unit_id, current: parseInt(e.target.value, 10) || 0 });
  }
  // Checklist
  if (e.target.classList.contains("chk")) {
    const li = e.target.closest("li");
    if (li) li.classList.toggle("done", e.target.checked);
  }
});

Zoom.init();