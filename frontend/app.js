// Wizard-Online Client (Hausregeln).

const socket = io(window.location.origin, {
  transports: ["websocket", "polling"],
});

socket.on("connect", () => {
  console.log("[socket] connected", socket.id);
});
socket.on("disconnect", (reason) => {
  console.warn("[socket] disconnected:", reason);
});
socket.on("connect_error", (err) => {
  console.error("[socket] connect_error:", err.message);
});

const state = {
  roomId: null,
  playerId: null,
  name: null,
  gameState: null,
  prevState: null,
  hand: [],
  blindView: {},
  legalMoves: [],
  playerOrderIndex: new Map(),
  selectedCardKey: null,
  announcedTrickId: null,
  announcedRoundNumber: null,
  prevScores: new Map(),
};

const $ = (id) => document.getElementById(id);

// ---- Toast ----

function toast(msg, variant = "error", ms = 3200) {
  const el = document.createElement("div");
  el.className = `toast ${variant}`;
  el.textContent = msg;
  $("toast-container").appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity 0.3s";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 300);
  }, ms);
}

// ---- Lobby ----

$("create-btn").addEventListener("click", () => {
  const name = $("name-input").value.trim();
  if (!name) return setLobbyError("Bitte Name eingeben.");
  state.name = name;
  socket.emit("create_room", { name });
});

$("join-btn").addEventListener("click", () => {
  const name = $("name-input").value.trim();
  const room = $("room-input").value.trim().toUpperCase();
  if (!name) return setLobbyError("Bitte Name eingeben.");
  if (!room) return setLobbyError("Bitte Raum-Code eingeben.");
  state.name = name;
  socket.emit("join_room", { name, room_id: room });
});

$("name-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("create-btn").click();
});
$("room-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("join-btn").click();
});

function setLobbyError(msg) { $("lobby-error").textContent = msg; }

// ---- Room copy / chat toggle / modal ----

$("copy-room").addEventListener("click", async () => {
  if (!state.roomId) return;
  try {
    await navigator.clipboard.writeText(state.roomId);
    toast("Raum-Code kopiert!", "info");
  } catch (e) {}
});

$("chat-toggle").addEventListener("click", () => {
  $("chat-panel").classList.toggle("collapsed");
});

$("round-modal-close").addEventListener("click", closeRoundModal);

$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("chat-input").value.trim();
  if (!text) return;
  sendChat(text);
  $("chat-input").value = "";
});

function sendChat(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return;
  socket.emit("chat_message", { text: trimmed });
}

// Quick-reactions & emoji bar
document.querySelectorAll(".quick-chip").forEach((btn) => {
  btn.addEventListener("click", () => sendChat(btn.dataset.msg));
});
document.querySelectorAll(".emoji-chip").forEach((btn) => {
  btn.addEventListener("click", () => sendChat(btn.dataset.emoji));
});

// Rules modal
function openRulesModal() { $("rules-modal").classList.remove("hidden"); }
function closeRulesModal() { $("rules-modal").classList.add("hidden"); }
$("rules-btn").addEventListener("click", openRulesModal);
$("rules-btn-game").addEventListener("click", openRulesModal);
$("rules-modal-close").addEventListener("click", closeRulesModal);
$("rules-got-it").addEventListener("click", closeRulesModal);
$("rules-modal").addEventListener("click", (e) => {
  if (e.target.id === "rules-modal") closeRulesModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeRulesModal();
    closeRoundModal();
  }
});

// ---- Server-Events ----

socket.on("room_created", ({ room_id }) => {
  state.roomId = room_id;
  $("room-info").textContent = room_id;
  showGame();
});

socket.on("joined", ({ room_id, player_id, name }) => {
  state.roomId = room_id;
  state.playerId = player_id;
  state.name = name;
  $("room-info").textContent = room_id;
  showGame();
});

socket.on("error_message", ({ message }) => {
  if (state.roomId) toast(message);
  else setLobbyError(message);
});

socket.on("game_state", (gs) => {
  state.prevState = state.gameState;
  state.gameState = gs;
  gs.players.forEach((p) => {
    if (!state.playerOrderIndex.has(p.id)) {
      state.playerOrderIndex.set(p.id, state.playerOrderIndex.size);
    }
  });
  handleTransitions(state.prevState, gs);
  render();
});

socket.on("your_hand", ({ hand, blind_view, legal_moves }) => {
  state.hand = hand || [];
  state.blindView = blind_view || {};
  state.legalMoves = legal_moves || [];
  render();
});

socket.on("chat", (msg) => {
  const line = document.createElement("div");
  line.className = "chat-msg";

  const isMine = msg.from === state.name;
  if (isMine) line.classList.add("mine");

  if (isEmojiOnly(msg.text)) line.classList.add("emoji-only");

  const fromClass = isMine ? "chat-from-mine" : `chat-from-${chatColorIndex(msg.from)}`;
  line.innerHTML =
    `<span class="from ${fromClass}">${escapeHtml(msg.from)}</span>` +
    `<span class="text">${escapeHtml(msg.text)}</span>`;

  const log = $("chat-log");
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
});

function chatColorIndex(name) {
  // Stable color per player name across the session
  if (state.gameState) {
    const p = state.gameState.players.find((x) => x.name === name);
    if (p) {
      const idx = state.playerOrderIndex.get(p.id);
      if (idx !== undefined) return idx % 6;
    }
  }
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0;
  return Math.abs(h) % 6;
}

function isEmojiOnly(text) {
  if (!text) return false;
  const stripped = text.replace(/\s+/g, "");
  if (stripped.length === 0 || stripped.length > 6) return false;
  // Heuristic: no ASCII letters/digits → treat as emoji-only
  return !/[A-Za-z0-9]/.test(stripped);
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ---- Transitions (animations/toasts) ----

function handleTransitions(prev, gs) {
  // Trick just completed: announce winner
  if (gs.last_completed_trick) {
    const t = gs.last_completed_trick;
    const tKey = t.plays.map((p) => `${p.card.type}-${p.card.suit}-${p.card.value}`).join("|") + "@" + t.winner_id;
    if (tKey !== state.announcedTrickId) {
      state.announcedTrickId = tKey;
      toast(`Stich geht an ${t.winner_name}`, "gold", 2200);
    }
  }

  // Round changed
  if (prev && prev.round !== gs.round) {
    state.selectedCardKey = null;
  }

  // Score bumps
  gs.players.forEach((p) => {
    const before = state.prevScores.get(p.id);
    if (before !== undefined && before !== p.score) {
      setTimeout(() => {
        const el = document.querySelector(`[data-score-for="${p.id}"]`);
        if (el) {
          el.classList.remove("bump");
          void el.offsetWidth;
          el.classList.add("bump");
        }
      }, 50);
    }
    state.prevScores.set(p.id, p.score);
  });

  // Round modal on round_done / game_over
  if (gs.phase === "round_done" && state.announcedRoundNumber !== gs.round) {
    state.announcedRoundNumber = gs.round;
    openRoundModal(gs, false);
  }
  if (gs.phase === "game_over" && state.announcedRoundNumber !== `over:${gs.round}`) {
    state.announcedRoundNumber = `over:${gs.round}`;
    openRoundModal(gs, true);
  }
  if (gs.phase === "bidding" || gs.phase === "playing" || gs.phase === "waiting") {
    closeRoundModal();
  }
}

// ---- Render ----

function showGame() {
  $("lobby").classList.add("hidden");
  $("game").classList.remove("hidden");
}

function render() {
  const gs = state.gameState;
  if (!gs) return;
  renderStatusBar(gs);
  renderTrumpArea(gs);
  renderPlayers(gs);
  renderTable(gs);
  renderAction(gs);
  renderHand(gs);
}

const PHASE_LABELS = {
  waiting: "Warte auf Spieler",
  bidding: "Tipp-Phase",
  playing: "Stich läuft",
  round_done: "Runde zu Ende",
  game_over: "Spiel vorbei",
};

function renderStatusBar(gs) {
  // Runde
  const round = $("status-round");
  if (gs.round && gs.total_rounds) {
    round.querySelector(".status-val").textContent = `${gs.round} / ${gs.total_rounds}`;
  } else {
    round.querySelector(".status-val").textContent = "—";
  }

  // Stich (M/N)
  const trick = $("status-trick");
  if (gs.phase === "playing" || gs.phase === "round_done") {
    const m = Math.max(1, Math.min(gs.trick_of_round || 1, gs.tricks_in_round || gs.round));
    trick.querySelector(".status-val").textContent = `${m} / ${gs.tricks_in_round || gs.round}`;
  } else {
    trick.querySelector(".status-val").textContent = "—";
  }

  // Trumpf
  const trump = $("status-trump");
  const trumpVal = trump.querySelector(".status-val");
  trumpVal.innerHTML = "";
  if (gs.trump_suit) {
    trumpVal.appendChild(Cards.suitIconElement(gs.trump_suit));
    const lbl = document.createElement("span");
    lbl.textContent = Cards.SUIT_LABEL[gs.trump_suit];
    trumpVal.appendChild(lbl);
    trump.classList.add("highlight");
  } else if (gs.phase !== "waiting" && gs.round) {
    trumpVal.textContent = "—";
    trump.classList.remove("highlight");
  } else {
    trumpVal.textContent = "—";
    trump.classList.remove("highlight");
  }

  // Bedienfarbe
  const lead = $("status-lead");
  const leadVal = lead.querySelector(".status-val");
  leadVal.innerHTML = "";
  if (gs.lead_suit) {
    leadVal.appendChild(Cards.suitIconElement(gs.lead_suit));
    const lbl = document.createElement("span");
    lbl.textContent = Cards.SUIT_LABEL[gs.lead_suit];
    leadVal.appendChild(lbl);
    lead.classList.add("highlight");
  } else {
    leadVal.textContent = "—";
    lead.classList.remove("highlight");
  }

  // Am Zug
  const turn = $("status-turn");
  const turnVal = turn.querySelector(".status-val");
  if (gs.phase === "round_done" || gs.phase === "game_over" || gs.phase === "waiting") {
    turnVal.textContent = "—";
  } else {
    const cur = gs.players.find((p) => p.id === gs.current_player);
    if (cur) {
      const isMe = cur.id === state.playerId;
      turnVal.textContent = isMe ? "Du" : cur.name;
    } else {
      turnVal.textContent = "—";
    }
  }
}

function renderTrumpArea(gs) {
  const area = $("trump-card-area");
  area.innerHTML = "";

  if (gs.phase === "waiting") {
    const p = document.createElement("div");
    p.style.color = "var(--text-dim)";
    p.style.fontStyle = "italic";
    p.textContent = "Bereit? Spiel starten, sobald alle Spieler da sind.";
    area.appendChild(p);
    return;
  }

  const isLastRound = gs.round === gs.total_rounds;

  // Left: trump card or icon
  const left = document.createElement("div");
  left.className = "trump-card-wrap";
  const lbl = document.createElement("div");
  lbl.className = "trump-label-big";
  lbl.textContent = "Trumpfkarte";
  left.appendChild(lbl);
  if (gs.trump_card) {
    left.appendChild(Cards.cardElement(gs.trump_card, { small: true }));
  } else {
    const back = document.createElement("div");
    back.className = "card card-back small";
    back.innerHTML = `<div class="card-back-pattern">✦</div>`;
    left.appendChild(back);
  }
  area.appendChild(left);

  // Right: caption
  const cap = document.createElement("div");
  cap.className = "trump-caption";
  const row = document.createElement("div");
  row.className = "trump-suit-name";
  if (gs.trump_suit) {
    row.appendChild(Cards.suitIconElement(gs.trump_suit));
    row.appendChild(document.createTextNode(`Trumpf: ${Cards.SUIT_LABEL[gs.trump_suit]}`));
  } else if (isLastRound) {
    const pill = document.createElement("span");
    pill.className = "no-trump-badge";
    pill.textContent = "Kein Trumpf — letzte Runde";
    row.appendChild(pill);
  } else if (gs.trump_card) {
    // Wizard or Jester as trump card
    const pill = document.createElement("span");
    pill.className = "no-trump-badge";
    pill.textContent = gs.trump_card.type === "wizard" ? "Wizard — kein Trumpf" : "Narr — kein Trumpf";
    row.appendChild(pill);
  } else {
    const pill = document.createElement("span");
    pill.className = "no-trump-badge";
    pill.textContent = "Kein Trumpf";
    row.appendChild(pill);
  }
  cap.appendChild(row);

  if (gs.blind_round) {
    const badge = document.createElement("span");
    badge.className = "blind-round-badge";
    badge.textContent = "BLIND-RUNDE";
    badge.style.marginLeft = "0.5rem";
    row.appendChild(badge);

    const desc = document.createElement("div");
    desc.className = "trump-desc";
    desc.textContent = "Du siehst deine eigene Karte nicht — aber die deiner Mitspieler.";
    cap.appendChild(desc);
  }

  area.appendChild(cap);
}

function avatarInitials(name) {
  return (name || "?").trim().slice(0, 1).toUpperCase();
}

function renderPlayers(gs) {
  const list = $("players-list");
  list.innerHTML = "";
  const lastWinner = gs.last_trick_winner;

  for (const p of gs.players) {
    const chip = document.createElement("div");
    chip.className = "player-chip";
    if (p.id === gs.current_player && gs.phase !== "round_done" && gs.phase !== "game_over") {
      chip.classList.add("current");
    }
    if (gs.blind_round) {
      chip.classList.add("blind-mode");
      chip.classList.add(`phase-${gs.phase}`);
      if (p.id === state.playerId) chip.classList.add("is-me");
    }

    const idx = state.playerOrderIndex.get(p.id) ?? 0;
    const avatar = document.createElement("div");
    avatar.className = `player-avatar avatar-${idx % 6}`;
    avatar.textContent = avatarInitials(p.name);
    chip.appendChild(avatar);

    const info = document.createElement("div");
    info.className = "player-info";

    const isMe = p.id === state.playerId;
    const nameEl = document.createElement("div");
    nameEl.className = "pname";
    nameEl.textContent = p.name + (isMe ? " · du" : "");
    info.appendChild(nameEl);

    const stats = document.createElement("div");
    stats.className = "pstats";

    const sayStat = document.createElement("div");
    sayStat.className = "pstat";
    sayStat.innerHTML = `<span class="label">Ansage</span><span class="value">${p.bid === null || p.bid === undefined ? "—" : p.bid}</span>`;
    stats.appendChild(sayStat);

    const wonStat = document.createElement("div");
    wonStat.className = "pstat stat-won";
    let wonClass = "";
    if (p.bid !== null && p.bid !== undefined && gs.phase !== "bidding") {
      wonClass = (p.tricks === p.bid) ? " match" : "";
      if (gs.phase === "round_done" || gs.phase === "game_over") {
        wonClass = (p.tricks === p.bid) ? " match" : " miss";
      }
    }
    wonStat.innerHTML = `<span class="label">Gewonnen</span><span class="value${wonClass}">${p.tricks}</span>`;
    stats.appendChild(wonStat);

    info.appendChild(stats);
    chip.appendChild(info);

    const score = document.createElement("div");
    score.className = "score-pill";
    score.dataset.scoreFor = p.id;
    score.textContent = `${p.score > 0 ? "+" : ""}${p.score}`;
    chip.appendChild(score);

    if (p.id === gs.start_player && gs.phase !== "waiting") {
      const badge = document.createElement("div");
      badge.className = "dealer-badge";
      badge.textContent = "START";
      chip.appendChild(badge);
    }

    if (lastWinner === p.id && gs.phase === "playing" && gs.current_trick.length === 0) {
      chip.classList.add("winner-glow");
    }

    if (gs.blind_round && p.id !== state.playerId && state.blindView[p.id]) {
      const blindCards = document.createElement("div");
      blindCards.className = "blind-peek";
      for (const card of state.blindView[p.id]) {
        blindCards.appendChild(Cards.cardElement(card, { small: true }));
      }
      chip.appendChild(blindCards);
    }

    list.appendChild(chip);
  }
}

// Circular trick layout around felt table
function renderTable(gs) {
  const ring = $("trick-ring");
  const center = $("trick-center");
  ring.innerHTML = "";
  center.innerHTML = "";

  if (gs.phase === "waiting") {
    center.innerHTML = `<div class="trick-hint">Warte auf Spielstart...</div>`;
    return;
  }

  if (gs.phase === "bidding") {
    const cur = gs.players.find((p) => p.id === gs.current_player);
    const msg = cur
      ? (cur.id === state.playerId ? "Du bist dran — gib deinen Tipp ab." : `${cur.name} gibt gerade ihren Tipp ab…`)
      : "Tipp-Phase läuft...";
    center.innerHTML = `<div class="trick-hint">${escapeHtml(msg)}</div>`;
    renderSeats(ring, gs, []);
    return;
  }

  if (gs.phase === "round_done" || gs.phase === "game_over") {
    center.innerHTML = `<div class="trick-hint">${gs.phase === "game_over" ? "Spiel vorbei" : "Runde zu Ende"}</div>`;
    return;
  }

  // phase === "playing"
  const plays = gs.current_trick || [];
  renderSeats(ring, gs, plays);

  if (!plays.length) {
    if (gs.last_trick_winner) {
      const p = gs.players.find((x) => x.id === gs.last_trick_winner);
      if (p) {
        center.innerHTML = `<div class="winner-announce">✦ Stich an ${escapeHtml(p.name)}</div>`;
        return;
      }
    }
    center.innerHTML = `<div class="trick-hint">Neuer Stich — wer beginnt, spielt aus.</div>`;
    return;
  }

  if (gs.lead_suit) {
    const icon = Cards.SUIT_LABEL[gs.lead_suit];
    center.innerHTML = `<div class="trick-hint">Bedienfarbe: <strong>${icon}</strong></div>`;
  } else {
    center.innerHTML = "";
  }
}

// Position seats on the felt around the table, rotated so current player is front-bottom.
function renderSeats(ring, gs, plays) {
  const players = gs.players;
  const n = players.length;
  if (!n) return;

  // Order: start with me at bottom, others clockwise
  const myIdx = Math.max(0, players.findIndex((p) => p.id === state.playerId));
  const ordered = [];
  for (let i = 0; i < n; i++) ordered.push(players[(myIdx + i) % n]);

  // Angle: bottom = 90deg (PI/2). Distribute clockwise.
  const radiusX = 38;   // %
  const radiusY = 40;   // %
  const cardRadiusX = 22;
  const cardRadiusY = 22;

  ordered.forEach((p, i) => {
    // For i=0 (me) => angle = 90deg (bottom). Then clockwise.
    const angleDeg = 90 + (i * 360) / n;
    const rad = (angleDeg * Math.PI) / 180;
    const seatX = 50 + radiusX * Math.cos(rad);
    const seatY = 50 + radiusY * Math.sin(rad);
    const cardX = 50 + cardRadiusX * Math.cos(rad);
    const cardY = 50 + cardRadiusY * Math.sin(rad);

    const seat = document.createElement("div");
    seat.className = "trick-seat";
    if (p.id === gs.current_player && gs.phase === "playing") seat.classList.add("current-seat");

    const play = plays.find((pl) => pl.player_id === p.id);
    const winnerId = gs.last_completed_trick && gs.last_completed_trick.winner_id;
    if (play && plays.length === n && winnerId === p.id) seat.classList.add("winner");

    // Card wrapper
    if (play) {
      const cardWrap = document.createElement("div");
      cardWrap.className = "seat-card";
      cardWrap.style.position = "absolute";
      cardWrap.style.left = `${cardX}%`;
      cardWrap.style.top = `${cardY}%`;
      cardWrap.style.transform = "translate(-50%, -50%)";
      cardWrap.appendChild(Cards.cardElement(play.card, { small: true }));
      ring.appendChild(cardWrap);
    }

    // Seat avatar
    const avatar = document.createElement("div");
    const idx = state.playerOrderIndex.get(p.id) ?? 0;
    avatar.className = `seat-avatar avatar-${idx % 6}`;
    avatar.textContent = avatarInitials(p.name);
    seat.appendChild(avatar);

    const name = document.createElement("div");
    name.className = "seat-name";
    const isMe = p.id === state.playerId;
    name.textContent = isMe ? `${p.name} (du)` : p.name;
    seat.appendChild(name);

    seat.style.left = `${seatX}%`;
    seat.style.top = `${seatY}%`;
    ring.appendChild(seat);
  });
}

function renderAction(gs) {
  const area = $("action-area");
  area.innerHTML = "";
  const isMyTurn = gs.current_player === state.playerId;

  if (gs.phase === "waiting") {
    const info = document.createElement("p");
    info.innerHTML = `<strong>Spieler im Raum:</strong> ${gs.players.length} / 6`;
    area.appendChild(info);
    if (gs.players.length >= 3) {
      const btn = document.createElement("button");
      btn.className = "btn btn-gold";
      btn.textContent = "Spiel starten";
      btn.onclick = () => socket.emit("start_game", {});
      area.appendChild(btn);
    } else {
      const hint = document.createElement("p");
      hint.className = "subtle";
      hint.textContent = "Mindestens 3 Spieler werden benötigt.";
      area.appendChild(hint);
    }
    return;
  }

  if (gs.phase === "bidding") {
    if (isMyTurn) {
      const info = document.createElement("p");
      const blindHint = gs.blind_round
        ? ` <span class="subtle">(Blind — du siehst deine Karte nicht)</span>`
        : "";
      info.innerHTML = `<strong>Dein Tipp:</strong> Wie viele Stiche wirst du machen? <span class="subtle">(0–${gs.round})</span>${blindHint}`;
      area.appendChild(info);

      const wrap = document.createElement("div");
      wrap.className = "bid-grid";
      for (let i = 0; i <= gs.round; i++) {
        const b = document.createElement("button");
        b.className = "bid-btn";
        b.textContent = i;
        if (i === gs.forbidden_bid) {
          b.classList.add("forbidden");
          b.disabled = true;
          b.title = `Tipp-Zwang: Summe darf nicht ${gs.round} ergeben`;
        } else {
          b.onclick = () => socket.emit("place_bid", { bid: i });
        }
        wrap.appendChild(b);
      }
      area.appendChild(wrap);

      if (gs.forbidden_bid !== null && gs.forbidden_bid !== undefined) {
        const hint = document.createElement("p");
        hint.className = "subtle";
        hint.innerHTML = `⚠ <span class="hint-inline">Tipp-Zwang</span>: ${gs.forbidden_bid} ist gesperrt (Summe würde ${gs.round} ergeben).`;
        area.appendChild(hint);
      }
    } else {
      const cur = gs.players.find((p) => p.id === gs.current_player);
      const p = document.createElement("p");
      p.className = "subtle";
      p.textContent = cur ? `${cur.name} gibt gerade ihren Tipp ab...` : "";
      area.appendChild(p);
    }
    return;
  }

  if (gs.phase === "playing") {
    if (isMyTurn) {
      const info = document.createElement("p");
      if (gs.blind_round) {
        info.innerHTML = `<strong>Du bist dran.</strong> Klicke deine verdeckte Karte zum Spielen.`;
      } else if (gs.lead_suit) {
        info.innerHTML = `<strong>Du bist dran.</strong> <span class="subtle">Bedienfarbe: ${Cards.SUIT_LABEL[gs.lead_suit]} — du musst bedienen, wenn möglich.</span>`;
      } else {
        info.innerHTML = `<strong>Du bist dran.</strong> Spiele eine beliebige Karte aus.`;
      }
      area.appendChild(info);
    } else {
      const cur = gs.players.find((p) => p.id === gs.current_player);
      const p = document.createElement("p");
      p.className = "subtle";
      p.textContent = cur ? `${cur.name} ist dran...` : "";
      area.appendChild(p);
    }
    return;
  }

  if (gs.phase === "round_done") {
    const info = document.createElement("p");
    info.innerHTML = `<strong>Runde ${gs.round} zu Ende.</strong>`;
    area.appendChild(info);
    const btn = document.createElement("button");
    btn.className = "btn btn-primary";
    btn.textContent = "Nächste Runde";
    btn.onclick = () => socket.emit("next_round", {});
    area.appendChild(btn);
    return;
  }

  if (gs.phase === "game_over") {
    const sorted = [...gs.players].sort((a, b) => b.score - a.score);
    const h = document.createElement("p");
    h.innerHTML = `🏆 <strong>${escapeHtml(sorted[0].name)}</strong> gewinnt mit <strong>${sorted[0].score}</strong> Punkten!`;
    area.appendChild(h);
    const btn = document.createElement("button");
    btn.className = "btn btn-gold";
    btn.textContent = "Endergebnis anzeigen";
    btn.onclick = () => openRoundModal(gs, true);
    area.appendChild(btn);
    return;
  }
}

function cardKey(c) {
  return `${c.type}-${c.suit || "x"}-${c.value || "x"}`;
}

function isCardLegal(card) {
  if (!state.legalMoves || state.legalMoves.length === 0) return true;
  return state.legalMoves.some(
    (lm) => lm.type === card.type && lm.suit === card.suit && lm.value === card.value
  );
}

function renderHand(gs) {
  const handEl = $("my-hand");
  handEl.innerHTML = "";
  const isMyTurn = gs && gs.current_player === state.playerId && gs.phase === "playing";

  if (!state.hand.length) {
    const hint = document.createElement("div");
    hint.style.color = "var(--text-muted)";
    hint.style.fontStyle = "italic";
    hint.textContent = gs && gs.phase === "waiting"
      ? "Keine Karten — Spiel nicht gestartet."
      : "Keine Karten mehr.";
    handEl.appendChild(hint);
    return;
  }

  for (const card of state.hand) {
    if (card.hidden) {
      const el = renderHiddenCard(isMyTurn);
      handEl.appendChild(el);
      continue;
    }
    const canPlay = isMyTurn && isCardLegal(card);
    const key = cardKey(card);
    const el = Cards.cardElement(card, {
      onClick: canPlay ? (c) => {
        if (state.selectedCardKey === key) {
          socket.emit("play_card", { card: c });
          state.selectedCardKey = null;
        } else {
          state.selectedCardKey = key;
          renderHand(gs);
        }
      } : null,
      disabled: !canPlay,
    });
    if (canPlay) el.classList.add("legal");
    if (isMyTurn && !canPlay) el.classList.add("illegal");
    if (state.selectedCardKey === key) el.classList.add("selected");
    handEl.appendChild(el);
  }
}

function renderHiddenCard(clickable) {
  const el = document.createElement("div");
  el.className = "card card-back";
  el.innerHTML = `<div class="card-back-pattern">✦</div>`;
  if (clickable) {
    el.classList.add("clickable", "legal");
    el.addEventListener("click", () => socket.emit("play_card", { card: { hidden: true } }));
  } else {
    el.classList.add("disabled");
  }
  return el;
}

// ---- Round Modal ----

function openRoundModal(gs, isGameOver) {
  const modal = $("round-modal");
  const title = $("round-modal-title");
  const body = $("round-modal-body");
  const footer = $("round-modal-footer");

  title.textContent = isGameOver
    ? `Endergebnis — Spiel vorbei`
    : `Rundenergebnis — Runde ${gs.round} / ${gs.total_rounds}`;

  body.innerHTML = "";

  const players = [...gs.players];
  players.sort((a, b) => b.score - a.score);

  for (const p of players) {
    const tr = document.createElement("tr");

    // Spieler
    const nameTd = document.createElement("td");
    const cell = document.createElement("div");
    cell.className = "round-player-cell";
    const idx = state.playerOrderIndex.get(p.id) ?? 0;
    const av = document.createElement("div");
    av.className = `player-avatar avatar-${idx % 6}`;
    av.textContent = avatarInitials(p.name);
    cell.appendChild(av);
    const nm = document.createElement("div");
    nm.textContent = p.name + (p.id === state.playerId ? " (du)" : "");
    cell.appendChild(nm);
    nameTd.appendChild(cell);
    tr.appendChild(nameTd);

    // Ansage
    const bidTd = document.createElement("td");
    bidTd.textContent = p.bid === null || p.bid === undefined ? "—" : p.bid;
    tr.appendChild(bidTd);

    // Gemacht
    const trickTd = document.createElement("td");
    trickTd.textContent = p.tricks;
    if (p.bid !== null && p.bid !== undefined) {
      const pill = document.createElement("span");
      const hit = p.tricks === p.bid;
      pill.className = `match-pill ${hit ? "hit" : "miss"}`;
      pill.textContent = hit ? "HIT" : "MISS";
      trickTd.appendChild(pill);
    }
    tr.appendChild(trickTd);

    // Rundenpunkte (delta)
    const deltaTd = document.createElement("td");
    const delta = lastRoundDelta(p);
    if (delta === null) {
      deltaTd.innerHTML = `<span class="delta-zero">—</span>`;
    } else {
      const cls = delta > 0 ? "delta-pos" : delta < 0 ? "delta-neg" : "delta-zero";
      const sign = delta > 0 ? "+" : "";
      deltaTd.innerHTML = `<span class="${cls}">${sign}${delta}</span>`;
    }
    tr.appendChild(deltaTd);

    // Gesamt
    const totalTd = document.createElement("td");
    totalTd.innerHTML = `<span class="total-val">${p.score}</span>`;
    tr.appendChild(totalTd);

    body.appendChild(tr);
  }

  footer.innerHTML = "";
  if (!isGameOver) {
    const next = document.createElement("button");
    next.className = "btn btn-primary";
    next.textContent = "Nächste Runde starten";
    next.onclick = () => {
      socket.emit("next_round", {});
      closeRoundModal();
    };
    footer.appendChild(next);
    const close = document.createElement("button");
    close.className = "btn btn-secondary";
    close.textContent = "Schließen";
    close.onclick = closeRoundModal;
    footer.appendChild(close);
  } else {
    const close = document.createElement("button");
    close.className = "btn btn-gold";
    close.textContent = "Schließen";
    close.onclick = closeRoundModal;
    footer.appendChild(close);
  }

  modal.classList.remove("hidden");
}

function closeRoundModal() {
  $("round-modal").classList.add("hidden");
}

// Try to compute last-round delta from server scores_per_round if sent;
// fallback to stored previous total.
function lastRoundDelta(player) {
  if (Array.isArray(player.scores_per_round) && player.scores_per_round.length) {
    return player.scores_per_round[player.scores_per_round.length - 1];
  }
  // Fallback: compare to previously cached score
  const prev = state.prevScores.get(player.id);
  if (prev === undefined) return null;
  return player.score - prev;
}
