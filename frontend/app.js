// Wizard-Online Client (Hausregeln).

const socket = io();

const state = {
  roomId: null,
  playerId: null,
  name: null,
  gameState: null,
  hand: [],
  blindView: {},
  legalMoves: [],
  playerOrderIndex: new Map(),
};

const $ = (id) => document.getElementById(id);

// ---- Toast ----

function toast(msg, variant = "error") {
  const el = document.createElement("div");
  el.className = `toast ${variant}`;
  el.textContent = msg;
  $("toast-container").appendChild(el);
  setTimeout(() => el.remove(), 3500);
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

// ---- Room copy ----

$("copy-room").addEventListener("click", async () => {
  if (!state.roomId) return;
  try {
    await navigator.clipboard.writeText(state.roomId);
    toast("Raum-Code kopiert!", "info");
  } catch (e) {}
});

// ---- Chat ----

$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("chat-input").value.trim();
  if (!text) return;
  socket.emit("chat_message", { text });
  $("chat-input").value = "";
});

// ---- Server-Events ----

socket.on("room_created", ({ room_id }) => {
  state.roomId = room_id;
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
  state.gameState = gs;
  gs.players.forEach((p) => {
    if (!state.playerOrderIndex.has(p.id)) {
      state.playerOrderIndex.set(p.id, state.playerOrderIndex.size);
    }
  });
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
  line.innerHTML = `<span class="from">${escapeHtml(msg.from)}</span><span class="text">${escapeHtml(msg.text)}</span>`;
  const log = $("chat-log");
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
});

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ---- Rendering ----

function showGame() {
  $("lobby").classList.add("hidden");
  $("game").classList.remove("hidden");
}

function render() {
  const gs = state.gameState;
  if (!gs) return;
  renderPhase(gs);
  renderPlayers(gs);
  renderTrick(gs);
  renderAction(gs);
  renderHand(gs);
}

const PHASE_LABELS = {
  waiting: "Warte auf Spieler",
  bidding: "Tipps werden abgegeben",
  playing: "Stich läuft",
  round_done: "Runde zu Ende",
  game_over: "Spiel vorbei",
};

function renderPhase(gs) {
  const label = PHASE_LABELS[gs.phase] || gs.phase;
  const roundTxt = gs.total_rounds
    ? ` <span class="round-label">Runde ${gs.round} / ${gs.total_rounds}</span>`
    : "";
  const blindTxt = gs.blind_round ? ' <span class="blind-badge">BLIND</span>' : "";
  $("phase-info").innerHTML = `<span class="phase-label">${label}</span>${roundTxt}${blindTxt}`;

  const trumpInfo = $("trump-info");
  trumpInfo.innerHTML = "";
  if (gs.phase === "waiting") return;

  const wrap = document.createElement("div");
  wrap.className = "trump-display";
  wrap.innerHTML = `<span class="trump-label">Trumpf</span>`;
  wrap.appendChild(Cards.suitIconElement(gs.trump_suit));
  trumpInfo.appendChild(wrap);
}

function avatarInitials(name) {
  return name.trim().slice(0, 1).toUpperCase();
}

function renderPlayers(gs) {
  const list = $("players-list");
  list.innerHTML = "";
  for (const p of gs.players) {
    const chip = document.createElement("div");
    chip.className = "player-chip";
    if (p.id === gs.current_player) chip.classList.add("current");

    const idx = state.playerOrderIndex.get(p.id) ?? 0;
    const avatar = document.createElement("div");
    avatar.className = `player-avatar avatar-${idx % 6}`;
    avatar.textContent = avatarInitials(p.name);

    const info = document.createElement("div");
    info.className = "player-info";
    const bid = p.bid === null ? "—" : p.bid;
    const tricks = p.tricks;
    const isMe = p.id === state.playerId;
    info.innerHTML = `
      <div class="pname">${escapeHtml(p.name)}${isMe ? " · du" : ""}</div>
      <div class="prow">
        <span>Tipp ${bid}</span>
        <span>Stiche ${tricks}</span>
      </div>
    `;

    const score = document.createElement("div");
    score.className = "score-pill";
    score.textContent = `${p.score >= 0 ? "+" : ""}${p.score}`;

    chip.appendChild(avatar);
    chip.appendChild(info);
    chip.appendChild(score);

    if (p.id === gs.start_player && gs.phase !== "waiting") {
      const badge = document.createElement("div");
      badge.className = "dealer-badge";
      badge.textContent = "START";
      chip.appendChild(badge);
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

function renderTrick(gs) {
  const area = $("current-trick");
  area.innerHTML = "";

  if (gs.phase === "waiting") {
    const hint = document.createElement("div");
    hint.className = "subtle";
    hint.style.color = "var(--text-muted)";
    hint.style.textAlign = "center";
    hint.textContent = "Warte auf Spielstart...";
    area.appendChild(hint);
    return;
  }

  if (!gs.current_trick.length && gs.phase === "playing") {
    const hint = document.createElement("div");
    hint.style.color = "var(--text-muted)";
    hint.style.fontStyle = "italic";
    hint.textContent = "Warte auf erste Karte...";
    area.appendChild(hint);
    return;
  }

  for (const play of gs.current_trick) {
    const wrap = document.createElement("div");
    wrap.className = "trick-play";
    wrap.appendChild(Cards.cardElement(play.card));
    const who = document.createElement("div");
    who.className = "who";
    const player = gs.players.find((p) => p.id === play.player_id);
    who.textContent = player ? player.name : "?";
    wrap.appendChild(who);
    area.appendChild(wrap);
  }
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
      btn.className = "btn btn-primary";
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
        ? ` <span class="subtle">(Blind-Runde — du siehst deine Karte nicht, aber die der anderen)</span>`
        : "";
      info.innerHTML = `Wie viele Stiche wirst du machen? <span class="subtle">(0 bis ${gs.round})</span>${blindHint}`;
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
        hint.innerHTML = `⚠ <strong>Tipp-Zwang</strong>: ${gs.forbidden_bid} ist gesperrt (Summe würde ${gs.round} ergeben).`;
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
        info.innerHTML = `<strong>Du bist dran.</strong> <span class="subtle">Bedienfarbe: ${Cards.SUIT_LABEL[gs.lead_suit]}</span>`;
      } else {
        info.innerHTML = `<strong>Du bist dran.</strong> Spiele eine beliebige Karte.`;
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
    const list = document.createElement("ol");
    list.className = "scoreboard";
    sorted.forEach((p, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<span><span class="rank">#${i + 1}</span>${escapeHtml(p.name)}</span><span>${p.score}</span>`;
      list.appendChild(li);
    });
    area.appendChild(list);
    return;
  }
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
    hint.textContent = gs && gs.phase === "waiting" ? "Keine Karten — Spiel nicht gestartet." : "Keine Karten mehr.";
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
    const el = Cards.cardElement(card, {
      onClick: canPlay ? (c) => socket.emit("play_card", { card: c }) : null,
      disabled: !canPlay,
    });
    if (isMyTurn && !canPlay) el.classList.add("illegal");
    handEl.appendChild(el);
  }
}

function renderHiddenCard(clickable) {
  const el = document.createElement("div");
  el.className = "card card-back";
  el.innerHTML = `<div class="card-back-pattern">✦</div>`;
  if (clickable) {
    el.classList.add("clickable");
    el.addEventListener("click", () => socket.emit("play_card", { card: { hidden: true } }));
  } else {
    el.classList.add("disabled");
  }
  return el;
}
