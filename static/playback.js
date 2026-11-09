// Prueba lenta: un cuadro por momento de la lectura. Puro, sin DOM, así el
// test lo corre con node. No recorta la lista (eso es de la prueba rápida):
// la cinta tiene un casillero por símbolo y el servidor ya corta en 500.
// Si un paso se queda sin estados, la cadena se corta ahí: lo que sigue no se lee.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenPlayback = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function playback(result, automaton) {
    const { finals, initial } = readStates(automaton);
    if (!result || typeof result !== "object" || !result.ok) {
      const message = result && typeof result.message === "string" && result.message
        ? result.message
        : "No pude simular.";
      return emptyPlayback(message);
    }

    const steps = listOf(result.steps)
      .filter((step) => step && typeof step === "object")
      .map((step) => ({ symbol: readOf(step.symbol), states: idsOf(step.states) }));
    const indexed = indexTransitions(automaton);
    const tape = steps.slice(1).map((step) => step.symbol);
    const end = cutAt(steps);
    const frames = [];

    if (steps.length) {
      const first = steps[0];
      const seeds = initial.filter((id) => first.states.includes(id));
      const edges = epsilonEdges(seeds, first.states, indexed.epsilon);
      frames.push(frame({
        kind: "start",
        symbol: "",
        tapeIndex: -1,
        readCount: 0,
        states: first.states,
        edges,
        cells: cellsOf(edges),
        text: stepText({
          states: first.states,
          symbol: "",
          previous: null,
          initial,
          finals,
          last: steps.length === 1,
          start: true,
        }),
        note: "",
      }));
    }

    let stuckIndex = -1;
    for (let index = 1; index < end; index += 1) {
      const step = steps[index];
      const previous = steps[index - 1].states;
      const stuck = step.states.length === 0;
      const tapeIndex = index - 1;
      let edges = [];
      let cells = [];
      let note = "";
      if (stuck) {
        stuckIndex = tapeIndex;
        cells = stuckCells(previous, step.symbol);
        note = stuckNote(step.symbol, previous, tape.length - tapeIndex - 1 > 0);
      } else {
        const moved = symbolEdges(previous, step.symbol, step.states, indexed.edges, indexed.epsilon);
        const landed = [];
        const seen = new Set();
        for (const edge of moved) {
          if (seen.has(edge.to)) continue;
          seen.add(edge.to);
          landed.push(edge.to);
        }
        edges = dedupeEdges(moved.concat(epsilonEdges(landed, step.states, indexed.epsilon)));
        cells = cellsOf(edges);
      }
      frames.push(frame({
        kind: stuck ? "stuck" : "read",
        symbol: step.symbol,
        tapeIndex,
        readCount: tapeIndex,
        states: step.states,
        edges,
        cells,
        text: stepText({
          states: step.states,
          symbol: step.symbol,
          previous,
          initial,
          finals,
          last: index === steps.length - 1,
          start: false,
        }),
        note,
      }));
    }

    const last = steps.length ? steps[Math.max(0, end - 1)] : null;
    const here = last ? last.states : [];
    const stopped = end < steps.length;
    const accepted = stopped ? false : Boolean(result.accepted);
    const summary = summaryText(accepted, here, finals, last ? last.symbol : "");
    const stuckFrame = frames.find((item) => item.kind === "stuck");
    frames.push(frame({
      kind: "verdict",
      symbol: "",
      tapeIndex: -1,
      readCount: stuckIndex >= 0 ? stuckIndex : tape.length,
      states: here,
      edges: [],
      cells: stuckFrame ? stuckFrame.cells : [],
      text: summary,
      note: stuckFrame ? stuckFrame.note : "",
    }));
    frames.forEach((item, index) => {
      item.index = index;
    });

    return {
      ok: true,
      accepted,
      verdict: accepted ? "Acepta" : "Rechaza",
      summary,
      tape,
      empty: tape.length === 0,
      stuckIndex,
      stopped,
      frames,
    };
  }

  function frame(fields) {
    return {
      index: 0,
      kind: fields.kind,
      symbol: fields.symbol,
      tapeIndex: fields.tapeIndex,
      readCount: fields.readCount,
      states: fields.states,
      edges: fields.edges,
      cells: fields.cells,
      text: fields.text,
      note: fields.note,
    };
  }

  function emptyPlayback(message) {
    return {
      ok: false,
      accepted: false,
      verdict: "",
      summary: message,
      tape: [],
      empty: true,
      stuckIndex: -1,
      stopped: false,
      frames: [],
    };
  }

  // El primer paso vacío y los que le siguen, si ya no hay estados, no se muestran.
  function cutAt(steps) {
    const stuckAt = steps.findIndex((step, index) => index > 0 && step.states.length === 0);
    if (stuckAt > 0 && steps.slice(stuckAt).every((step) => step.states.length === 0)) {
      return stuckAt + 1;
    }
    return steps.length;
  }

  function readStates(automaton) {
    const finals = new Set();
    const initial = [];
    for (const state of listOf(automaton && automaton.states)) {
      if (!state || typeof state !== "object") continue;
      const id = idOf(state.id);
      if (!id) continue;
      if (state.final) finals.add(id);
      if (state.initial) initial.push(id);
    }
    return { finals, initial };
  }

  function indexTransitions(automaton) {
    const edges = [];
    const epsilon = new Map();
    const seen = new Set();
    for (const item of listOf(automaton && automaton.transitions)) {
      if (!item || typeof item !== "object") continue;
      const from = idOf(item.from);
      const to = idOf(item.to);
      const symbol = readOf(item.read);
      if (!from || !to || symbol === null) continue;
      const key = `${from}\0${to}\0${symbol}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push({ from, to, symbol });
      if (symbol !== "") continue;
      let next = epsilon.get(from);
      if (!next) {
        next = [];
        epsilon.set(from, next);
      }
      next.push(to);
    }
    return { edges, epsilon };
  }

  function epsilonEdges(seeds, allowed, epsilon) {
    const allow = new Set(allowed);
    const out = [];
    const seenEdge = new Set();
    const seen = new Set();
    const queue = [];
    for (const seed of seeds) {
      if (seen.has(seed)) continue;
      seen.add(seed);
      queue.push(seed);
    }
    while (queue.length) {
      const state = queue.shift();
      for (const to of epsilon.get(state) || []) {
        if (!allow.has(to)) continue;
        const key = `${state}\0${to}`;
        if (!seenEdge.has(key)) {
          seenEdge.add(key);
          out.push({ from: state, to, symbol: "" });
        }
        if (seen.has(to)) continue;
        seen.add(to);
        queue.push(to);
      }
    }
    return out;
  }

  function symbolEdges(previous, symbol, next, edges, epsilon) {
    const fromSet = new Set(previous);
    const allow = new Set(next);
    const out = [];
    const seen = new Set();
    for (const edge of edges) {
      if (edge.symbol !== symbol || !fromSet.has(edge.from)) continue;
      if (!reaches(edge.to, allow, epsilon)) continue;
      const key = `${edge.from}\0${edge.to}\0${edge.symbol}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ from: edge.from, to: edge.to, symbol });
    }
    return out;
  }

  function reaches(state, allow, epsilon) {
    if (allow.has(state)) return true;
    const seen = new Set();
    const queue = [state];
    while (queue.length) {
      const current = queue.shift();
      if (seen.has(current)) continue;
      seen.add(current);
      if (allow.has(current)) return true;
      for (const to of epsilon.get(current) || []) queue.push(to);
    }
    return false;
  }

  function dedupeEdges(edges) {
    const out = [];
    const seen = new Set();
    for (const edge of edges) {
      const key = `${edge.from}\0${edge.to}\0${edge.symbol}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(edge);
    }
    return out;
  }

  function cellsOf(edges) {
    const out = [];
    const seen = new Set();
    for (const edge of edges) {
      const key = `${edge.from}\0${edge.symbol}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ from: edge.from, symbol: edge.symbol });
    }
    return out;
  }

  function stuckCells(previous, symbol) {
    const out = [];
    const seen = new Set();
    for (const from of previous) {
      if (seen.has(from)) continue;
      seen.add(from);
      out.push({ from, symbol });
    }
    return out;
  }

  function stuckNote(symbol, previous, unread) {
    const read = symbolLabel(symbol);
    const where = previous.length
      ? `desde ${joinStates(previous)} no hay una flecha con ${read}`
      : `no hay una flecha con ${read}`;
    const tail = unread ? " Lo que sigue no se lee." : "";
    return `La cadena se corta: ${where}, así que se rechaza.${tail}`;
  }

  function stepText(ctx) {
    const body = ctx.start
      ? startText(ctx.states, ctx.initial)
      : moveText(ctx.states, ctx.symbol, ctx.previous);
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
    return null;
  }

  return { playback };
});
