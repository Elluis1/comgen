// Ficha de la definición. Pura: no toca el DOM, así el test la corre con node.
// Q, el alfabeto, el inicial y los finales. No dibuja ni la tabla ni el autómata.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenCard = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // Por encima de esto no se listan todos los nombres: la ficha tiene que
  // entrar de un vistazo. El resto está en la tabla.
  const NAME_LIMIT = 8;
  const SYMBOL_LIMIT = 12;
  const NAME_CHARS = 24;
  // Contar celdas de más no ayuda y recorre de más en una notebook chica.
  const GAP_SCAN = 4096;

  function automatonCard(automaton) {
    if (!automaton || typeof automaton !== "object" || Array.isArray(automaton)) {
      return { shown: false, rows: [], note: "" };
    }
    const states = uniqueStates(automaton.states);
    const alphabet = uniqueSymbols(automaton.alphabet);
    const deterministic = automaton.deterministic === true;
    const initials = states.filter((state) => state.initial);
    const finals = states.filter((state) => state.final);
    const gaps = deterministic ? countGaps(states, alphabet, automaton.transitions) : 0;
    return {
      shown: true,
      rows: [
        statesRow(states),
        alphabetRow(alphabet),
        pickRow("q₀", "Inicial", initials, "estado inicial", "estados iniciales"),
        pickRow("F", "Finales", finals, "estado final", "estados finales"),
      ],
      note: noteFor(states, initials, deterministic, gaps),
    };
  }

  function statesRow(states) {
    const named = nameList(states);
    if (!states.length) return row("Q", "Estados", "ninguno", "No hay estados.");
    if (states.length === 1) return row("Q", "Estados", named.value, `1 estado: ${named.value}.`);
    if (states.length <= NAME_LIMIT) {
      return row("Q", "Estados", named.value, `${states.length} estados: ${named.value}.`);
    }
    return row(
      "Q",
      "Estados",
      `${states.length} estados`,
      `${states.length} estados. Los primeros son ${named.value}.`,
    );
  }

  function alphabetRow(symbols) {
    if (!symbols.length) return row("Σ", "Alfabeto", "vacío", "Alfabeto vacío.");
    const shown = symbols.slice(0, SYMBOL_LIMIT).map((item) => showSymbol(item.id));
    const body = shown.join(", ");
    if (symbols.length <= SYMBOL_LIMIT) {
      return row("Σ", "Alfabeto", `{${body}}`, `Alfabeto: ${body}.`);
    }
    return row("Σ", "Alfabeto", `{${body}…}`, `Alfabeto de ${symbols.length} símbolos.`);
  }

  function pickRow(key, label, items, one, many) {
    const named = nameList(items);
    if (!items.length) return row(key, label, "ninguno", `No hay ${one}.`);
    if (items.length === 1) return row(key, label, named.value, `${capitalize(one)}: ${named.value}.`);
    if (items.length <= NAME_LIMIT) {
      return row(key, label, named.value, `${items.length} ${many}: ${named.value}.`);
    }
    return row(key, label, `${items.length} ${many}`, `${items.length} ${many}.`);
  }

  function noteFor(states, initials, deterministic, gaps) {
    const parts = [];
    if (!states.length) parts.push("No hay estados.");
    else if (!initials.length) parts.push("No hay estado inicial.");
    else if (initials.length > 1) parts.push("Hay más de un estado inicial.");
    if (deterministic && gaps > 0) {
      const flecha = gaps === 1 ? "Falta 1 flecha." : `Faltan ${gaps} flechas.`;
      parts.push(`${flecha} En la tabla, el guión es un rechazo.`);
    }
    return parts.join(" ");
  }

  function nameList(items) {
    const shown = items.slice(0, NAME_LIMIT).map((item) => shortName(item.id));
    return { value: shown.join(", ") };
  }

  function row(key, label, value, spoken) {
    return { key, label, value, spoken };
  }

  function countGaps(states, alphabet, transitions) {
    const cells = states.length * alphabet.length;
    if (!cells || cells > GAP_SCAN) return 0;
    const symbols = new Set(alphabet.map((item) => item.id));
    const byFrom = new Map();
    for (const item of listOf(transitions)) {
      if (!item || typeof item !== "object") continue;
      const from = textOf(item.from);
      const read = readOf(item.read);
      if (!from || !read || !symbols.has(read)) continue;
      let inner = byFrom.get(from);
      if (!inner) {
        inner = new Set();
        byFrom.set(from, inner);
      }
      inner.add(read);
    }
    let gaps = 0;
    for (const state of states) {
      const inner = byFrom.get(state.id);
      for (const symbol of alphabet) {
        if (!inner || !inner.has(symbol.id)) gaps += 1;
      }
    }
    return gaps;
  }

  function uniqueStates(list) {
    const byId = new Map();
    for (const state of listOf(list)) {
      if (!state || typeof state !== "object") continue;
      const id = textOf(state.id);
      if (!id) continue;
      const prev = byId.get(id);
      if (!prev) {
        byId.set(id, { id, initial: state.initial === true, final: state.final === true });
        continue;
      }
      prev.initial = prev.initial || state.initial === true;
      prev.final = prev.final || state.final === true;
    }
    return [...byId.values()];
  }

  function uniqueSymbols(list) {
    const out = [];
    const seen = new Set();
    for (const symbol of listOf(list)) {
      const id = textOf(symbol);
      if (!id || seen.has(id)) continue;
      seen.add(id);
      out.push({ id });
    }
    return out;
  }

  function listOf(value) {
    return Array.isArray(value) ? value : [];
  }

  // El 0 numérico no es la cadena vacía: si se pierde, se mezcla con épsilon.
  function textOf(value) {
    if (typeof value === "string") return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    return "";
  }

  function readOf(value) {
    if (typeof value === "string") return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    if (value == null) return "";
    return null;
  }

  function shortName(id) {
    return quotePiece(cutName(id));
  }

  // En el alfabeto, una llave se confunde con el conjunto. En un estado, no:
  // {q0,q1} sigue siendo un solo nombre, igual que en la tabla.
  function showSymbol(id) {
    const cut = cutName(id);
    const quoted = quotePiece(cut);
    if (quoted !== cut) return quoted;
    if (cut.includes("{") || cut.includes("}")) {
      return `«${cut.split("«").join("‹").split("»").join("›")}»`;
    }
    return cut;
  }

  function cutName(id) {
    const raw = String(id);
    if (raw.length <= NAME_CHARS) return raw;
    return `${raw.slice(0, NAME_CHARS - 1)}…`;
  }

  // «q0, q1» como un solo nombre no puede verse igual que dos estados.
  // Una marca suelta se pega a la palabra de atrás.
  function sticks(text) {
    return typeof text === "string" && /\p{M}/u.test(text);
  }

  function quotePiece(text) {
    const value = String(text);
    if (sticks(value) || value.includes(", ") || value.includes(" y ") || value.includes("«") || value.includes("»")) {
      return `«${value.split("«").join("‹").split("»").join("›")}»`;
    }
    return value;
  }

  function capitalize(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  return { automatonCard, NAME_LIMIT, SYMBOL_LIMIT, NAME_CHARS, GAP_SCAN };
});
