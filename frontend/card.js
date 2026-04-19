// Karten-Darstellung.

const SUIT_SYMBOL = {
  red: "\u2665",
  yellow: "\u2605",
  green: "\u2663",
  blue: "\u2666",
};

const SUIT_LABEL = {
  red: "Rot", yellow: "Gelb", green: "Grün", blue: "Blau",
};

function cardElement(card, { onClick = null, disabled = false, small = false } = {}) {
  const el = document.createElement("div");
  el.className = "card";
  if (small) el.classList.add("small");

  if (card.type === "wizard") {
    el.classList.add("wizard");
    el.innerHTML = `
      <div class="corner top"><span class="num">Z</span></div>
      <div class="center">\u2728</div>
      <div class="corner bot"><span class="num">Z</span></div>
    `;
  } else if (card.type === "jester") {
    el.classList.add("jester");
    el.innerHTML = `
      <div class="corner top"><span class="num">N</span></div>
      <div class="center">\u{1F921}</div>
      <div class="corner bot"><span class="num">N</span></div>
    `;
  } else {
    el.classList.add(card.suit);
    const sym = SUIT_SYMBOL[card.suit] || "";
    el.innerHTML = `
      <div class="corner top"><span class="num">${card.value}</span><span class="sym">${sym}</span></div>
      <div class="center">${sym}</div>
      <div class="corner bot"><span class="num">${card.value}</span><span class="sym">${sym}</span></div>
    `;
  }

  if (onClick && !disabled) {
    el.classList.add("clickable");
    el.addEventListener("click", () => onClick(card));
  }
  if (disabled) el.classList.add("disabled");
  return el;
}

function suitIconElement(suit) {
  const el = document.createElement("span");
  el.className = `suit-icon ${suit || "none"}`;
  el.textContent = suit ? SUIT_SYMBOL[suit] : "Kein Trumpf";
  return el;
}

function cardsEqual(a, b) {
  return a.type === b.type && a.suit === b.suit && a.value === b.value;
}

window.Cards = { cardElement, suitIconElement, SUIT_LABEL, SUIT_SYMBOL, cardsEqual };
