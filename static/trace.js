// Recorrido de una simulación. Puro: no toca el DOM, así el test lo corre con node.
// Una cadena larga no arma cientos de ítems de entrada: se ven el arranque y
// el final, y el resto se abre con un botón.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenTrace = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const STEP_LIMIT = 24;

  function simulationTrace(result, automaton, options) {
    const expanded = Boolean(options && options.expanded);
    const finals = new Set();
    const initial = [];
    for (const state of listOf(automaton && automaton.states)) {
      if (!state || typeof state !== "object") continue;
      const id = idOf(state.id);
      if (!id) continue;
      if (state.final) finals.add(id);
      if (state.initial) initial.push(id);
    }

    if (!result || typeof result !== "object" || !result.ok) {
      const message = result && typeof result.message === "string" && result.message
        ? result.message
        : "No pude simular.";
      return emptyTrace(message);
    }

    const raw = listOf(result.steps).filter((step) => step && typeof step === "object");
    const all = raw.map((step, index) => {
      const states = idsOf(step.states);
      const symbol = readOf(step.symbol);
      const previous = index === 0 ? null : idsOf(raw[index - 1].states);
      const last = index === raw.length - 1;
      return {
        index,
        symbol,
        states,
        text: stepText({ states, symbol, previous, initial, finals, last, start: index === 0 }),
      };
    });

    const visited = [];
    const seen = new Set();
    for (const step of all) {
      for (const id of step.states) {
        if (seen.has(id)) continue;
        seen.add(id);
        visited.push(id);
      }
    }
    const here = all.length ? all[all.length - 1].states.slice() : [];
    const lastLookups = lookupsOf(all);
    const window = visibleSteps(all, expanded);
    const accepted = Boolean(result.accepted);
    const lastSymbol = all.length ? all[all.length - 1].symbol : "";

    return {
      ok: true,
      accepted,
      verdict: accepted ? "Acepta" : "Rechaza",
      summary: summaryText(accepted, here, finals, lastSymbol),
      steps: window.steps,
      total: all.length,
      omitted: window.omitted,
      gap: gapText(window.omitted),
      moreLabel: moreLabel(all.length, window.omitted, expanded),
      visited,
      here,
      lastLookups,
      limit: STEP_LIMIT,
    };
  }

  function emptyTrace(message) {
    return {
      ok: false,
      accepted: false,
      verdict: "",
      summary: message,
      steps: [],
      total: 0,
      omitted: 0,
      gap: "",
      moreLabel: "",
      visited: [],
      here: [],
      lastLookups: [],
      limit: STEP_LIMIT,
    };
  }

  function visibleSteps(steps, expanded) {
    if (expanded || steps.length <= STEP_LIMIT) return { steps, omitted: 0 };
    const tailCount = STEP_LIMIT - 1;
    const tail = steps.slice(steps.length - tailCount);
    return { steps: [steps[0], ...tail], omitted: steps.length - STEP_LIMIT };
  }

  function moreLabel(total, omitted, expanded) {
    if (omitted) return `Ver los ${total} pasos`;
    if (expanded && total > STEP_LIMIT) return "Ver menos";
    return "";
  }

  function gapText(omitted) {
    if (!omitted) return "";
    if (omitted === 1) return "Se omite 1 paso.";
    return `Se omiten ${omitted} pasos.`;
  }

  function lookupsOf(steps) {
    if (steps.length < 2) return [];
    const previous = steps[steps.length - 2];
    const last = steps[steps.length - 1];
    return previous.states.map((from) => ({ from, symbol: last.symbol }));
  }

  function stepText(ctx) {
    const body = ctx.start ? startText(ctx.states, ctx.initial) : moveText(ctx.states, ctx.symbol, ctx.previous);
    return finish(body, ctx.states, ctx.finals, ctx.last);
  }

  function startText(states, initial) {
    if (!states.length) return "No queda en ningún estado";
    const extras = states.filter((id) => !initial.includes(id));
    if (extras.length && initial.length) {
      return `Empieza en ${joinStates(initial)} y, por épsilon, también llega a ${joinStates(extras)}`;
    }
    return `Empieza en ${joinStates(states)}`;
  }

  function moveText(states, symbol, previous) {
    const read = `Lee ${symbolLabel(symbol)}`;
    if (!states.length) return `${read} y no queda en ningún estado`;
    if (sameSet(states, previous)) return `${read} y se queda en ${joinStates(states)}`;
    if (states.length === 1) return `${read} y pasa a ${joinStates(states)}`;
    return `${read} y queda en ${joinStates(states)}`;
  }

  function finish(body, states, finals, mentionFinal) {
    const clean = body.replace(/\.$/, "");
    if (!mentionFinal || !states.length) return `${clean}.`;
    const finalHere = states.filter((id) => finals.has(id));
    if (!finalHere.length) return `${clean}.`;
    if (finalHere.length === states.length) {
      return states.length > 1 ? `${clean}, que son finales.` : `${clean}, que es final.`;
    }
    const verb = finalHere.length > 1 ? "son finales" : "es final";
    return `${clean}. ${joinStates(finalHere)} ${verb}.`;
  }

  function summaryText(accepted, here, finals, lastSymbol) {
    const verdict = accepted ? "Acepta" : "Rechaza";
    if (!here.length) {
      if (lastSymbol) return `${verdict}. Lee ${symbolLabel(lastSymbol)} y no queda en ningún estado.`;
      return `${verdict}. No queda en ningún estado.`;
    }
    const names = joinStates(here);
    const finalHere = here.filter((id) => finals.has(id));
    if (!accepted || finalHere.length === here.length) {
      const clause = !accepted
        ? (here.length > 1 ? "no son finales" : "no es final")
        : (here.length > 1 ? "son finales" : "es final");
      return `${verdict}. Termina en ${names}, que ${clause}.`;
    }
    const verb = finalHere.length > 1 ? "son finales" : "es final";
    return `${verdict}. Termina en ${names}. ${joinStates(finalHere)} ${verb}.`;
  }

  function symbolLabel(symbol) {
    if (!symbol) return "épsilon";
    if (symbol.length === 1 && symbol !== "«" && symbol !== "»" && !sticks(symbol)) return symbol;
    return `«${symbol.split("«").join("‹").split("»").join("›")}»`;
  }

  function joinStates(ids) {
    const names = ids.map(displayName);
    if (names.length <= 1) return names[0] || "";
    if (names.length === 2) return `${names[0]} y ${names[1]}`;
    return `${names.slice(0, -1).join(", ")} y ${names[names.length - 1]}`;
  }

  // «q0, q1» como un solo nombre no puede partirse en dos estados.
  // {q0,q1} queda así: la coma va pegada y no se confunde con la lista.
  function displayName(name) {
    const text = String(name);
    if (text.includes(", ") || text.includes(" y ") || text.includes("«") || text.includes("»") || sticks(text)) {
      return `«${text.split("«").join("‹").split("»").join("›")}»`;
    }
    return text;
  }

  function sameSet(left, right) {
    if (!right || left.length !== right.length) return false;
    const a = left.slice().sort();
    const b = right.slice().sort();
    return a.every((id, index) => id === b[index]);
  }

  function idsOf(list) {
    const out = [];
    const seen = new Set();
    for (const value of listOf(list)) {
      const id = idOf(value);
      if (!id || seen.has(id)) continue;
      seen.add(id);
      out.push(id);
    }
    return out;
  }

  function listOf(value) {
    return Array.isArray(value) ? value : [];
  }

  // Una marca suelta se pega a la letra de atrás («Lee ́» se lee «Leé»).
  function sticks(text) {
    return typeof text === "string" && /\p{M}/u.test(text);
  }

  // El 0 numérico es el estado «0», no la cadena vacía ni una épsilon.
  function idOf(value) {
    if (typeof value === "string") return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    return "";
  }

  function readOf(value) {
    if (typeof value === "string") return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    if (value == null) return "";
    return "";
  }

  return { simulationTrace, STEP_LIMIT };
});
