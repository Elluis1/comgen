// Dibujo del autómata. Puro: no toca el DOM, así el test lo corre con node.
// No se dibuja un autómata enorme: un recorte parecería otro lenguaje, y
// miles de círculos traban una notebook chica. La tabla lista el resto.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenDiagram = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const STATE_LIMIT = 16;
  const MAX_LABEL = 14;

  function automatonDiagram(automaton) {
    const seen = new Set();
    const unique = [];
    for (const item of listOf(automaton && automaton.states)) {
      const state = asState(item);
      if (!state || seen.has(state.id)) continue;
      seen.add(state.id);
      unique.push(state);
    }
    const total = unique.length;
    const empty = {
      drawn: false,
      total,
      limit: STATE_LIMIT,
      message: total
        ? `Este autómata tiene ${total} estados. El dibujo se arma hasta ${STATE_LIMIT}, para que la página no se trabe. La tabla de abajo los lista.`
        : "Este autómata no tiene estados para dibujar.",
      legend: "",
      summary: "",
      width: 0,
      height: 0,
      nodes: [],
      edges: [],
      start: null,
    };
    if (!total || total > STATE_LIMIT) return empty;

    const alphabet = listOf(automaton && automaton.alphabet).filter((symbol) => symbol);
    const deterministic = Boolean(automaton && automaton.deterministic);
    const nodes = place(unique.map(toNode));
    const grouped = groupEdges(listOf(automaton && automaton.transitions), seen);
    const edges = layoutEdges(nodes, grouped);
    relaxLabels(nodes, edges);
    const start = startArrow(nodes);
    const flags = {
      deterministic,
      hasLoop: edges.some((edge) => edge.loop),
      hasEpsilon: edges.some((edge) => edge.epsilon),
      hasGap: missingArrow(nodes, alphabet, grouped, deterministic),
    };
    const size = fit(nodes, edges, start);
    return {
      drawn: true,
      total,
      limit: STATE_LIMIT,
      message: "",
      legend: legend(flags),
      summary: summary(nodes, edges),
      width: size.width,
      height: size.height,
      nodes: nodes.map(publicNode),
      edges: edges.map(publicEdge),
      start: start ? publicStart(start) : null,
    };
  }

  function idOf(value) {
    if (typeof value === "string") return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    return "";
  }

  // El 0 numérico es el símbolo «0», no una épsilon. Un nulo sigue siendo épsilon.
  function readOf(value) {
    if (typeof value === "string") return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    if (value == null) return "";
    return null;
  }

  // El 0 numérico es el estado «0». Si se descarta, la flecha que sale de él desaparece.
  function asState(state) {
    if (!state || typeof state !== "object") return null;
    const id = idOf(state.id);
    if (!id) return null;
    return { id, initial: Boolean(state.initial), final: Boolean(state.final) };
  }

  // Una marca suelta se pega a «con» en el resumen: «con ́ va a q0».
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

  function listOf(value) {
    return Array.isArray(value) ? value : [];
  }

  function toNode(state) {
    const fullLabel = state.id;
    const label = fullLabel.length <= MAX_LABEL ? fullLabel : `${fullLabel.slice(0, MAX_LABEL - 1)}…`;
    const shape = label.length <= 4
      ? { shape: "circle", r: 26, w: 52, h: 52 }
      : { shape: "pill", r: 20, w: Math.min(188, Math.max(88, Math.round(label.length * 9 + 28))), h: 40 };
    return {
      id: state.id,
      initial: Boolean(state.initial),
      final: Boolean(state.final),
      label,
      fullLabel,
      accessibleName: stateName(state),
      x: 0,
      y: 0,
      ...shape,
    };
  }

  function stateName(state) {
    const id = quotePiece(state.id);
    if (state.initial && state.final) return `${id}, inicial y final`;
    if (state.initial) return `${id}, inicial`;
    if (state.final) return `${id}, final`;
    return id;
  }

  function place(nodes) {
    const count = nodes.length;
    const ordered = [
      ...nodes.filter((node) => node.initial),
      ...nodes.filter((node) => !node.initial),
    ];
    if (count === 1) return ordered;
    if (count === 2) {
      const gap = 156;
      ordered[0].x = 0;
      ordered[1].x = ordered[0].w / 2 + gap + ordered[1].w / 2;
      return ordered;
    }
    const half = Math.max(...ordered.map((node) => Math.max(node.w, node.h) / 2));
    const chord = half * 2 + (count <= 6 ? 78 : 44);
    const radius = Math.max(chord / (2 * Math.sin(Math.PI / count)), count <= 4 ? 118 : 96);
    for (let index = 0; index < count; index += 1) {
      const angle = Math.PI + (index * 2 * Math.PI) / count;
      ordered[index].x = radius * Math.cos(angle);
      ordered[index].y = radius * Math.sin(angle);
    }
    return ordered;
  }

  function groupEdges(transitions, known) {
    const byFrom = new Map();
    for (const item of transitions) {
      if (!item || typeof item !== "object") continue;
      const from = idOf(item.from);
      const to = idOf(item.to);
      if (!from || !to || !known.has(from) || !known.has(to)) continue;
      const read = readOf(item.read);
      if (read === null) continue;
      let inner = byFrom.get(from);
      if (!inner) {
        inner = new Map();
        byFrom.set(from, inner);
      }
      let symbols = inner.get(to);
      if (!symbols) {
        symbols = [];
        inner.set(to, symbols);
      }
      if (!symbols.includes(read)) symbols.push(read);
    }
    return byFrom;
  }

  function layoutEdges(nodes, grouped) {
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const center = {
      x: nodes.reduce((sum, node) => sum + node.x, 0) / nodes.length,
      y: nodes.reduce((sum, node) => sum + node.y, 0) / nodes.length,
    };
    const edges = [];
    for (const source of nodes) {
      const inner = grouped.get(source.id);
      if (!inner) continue;
      const targets = [...inner.keys()].sort((left, right) => {
        if (left === source.id) return 1;
        if (right === source.id) return -1;
        return 0;
      });
      for (const targetId of targets) {
        const target = byId.get(targetId);
        const symbols = inner.get(targetId);
        const epsilon = symbols.includes("");
        const label = edgeLabel(symbols);
        if (targetId === source.id) {
          edges.push(loopEdge(source, center, nodes.length, label, epsilon));
          continue;
        }
        const back = grouped.get(targetId);
        const mutual = Boolean(back && back.has(source.id));
        edges.push(curveEdge(source, target, label, epsilon, mutual));
      }
    }
    return edges;
  }

  function edgeLabel(symbols) {
    const ordered = [...symbols.filter((symbol) => symbol !== ""), ...symbols.filter((symbol) => symbol === "")];
    const text = ordered.map((symbol) => (symbol === "" ? "ε" : quotePiece(symbol))).join(", ");
    if (text.length <= 28) return text;
    return `${text.slice(0, 27)}…`;
  }

  function loopEdge(node, center, count, label, epsilon) {
    const outward = loopDirection(node, center, count);
    const tx = -outward.y;
    const ty = outward.x;
    const spread = 0.85;
    const startDir = unit(outward.x * Math.cos(spread) + tx * Math.sin(spread), outward.y * Math.cos(spread) + ty * Math.sin(spread));
    const endDir = unit(outward.x * Math.cos(spread) - tx * Math.sin(spread), outward.y * Math.cos(spread) - ty * Math.sin(spread));
    const start = borderAlong(node, startDir.x, startDir.y);
    const tip = borderAlong(node, endDir.x, endDir.y);
    const reach = Math.max(node.r, node.h / 2) + 34;
    const side = Math.max(node.r, node.h / 2) * 0.85;
    const c1 = {
      x: node.x + outward.x * reach + tx * side,
      y: node.y + outward.y * reach + ty * side,
    };
    const c2 = {
      x: node.x + outward.x * reach - tx * side,
      y: node.y + outward.y * reach - ty * side,
    };
    const lineEnd = pullBack(tip, c2, 8);
    const crest = cubic(start, c1, c2, lineEnd, 0.5);
    return {
      from: node.id,
      to: node.id,
      label,
      epsilon,
      loop: true,
      kind: "loop",
      start,
      c1,
      c2,
      lineEnd,
      tip,
      labelX: crest.x + outward.x * 14,
      labelY: crest.y + outward.y * 14,
      arrow: arrowHead(tip, c2, 9),
    };
  }

  function curveEdge(source, target, label, epsilon, mutual) {
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const len = Math.hypot(dx, dy) || 1;
    const px = -dy / len;
    const py = dx / len;
    // La perpendicular ya cambia de signo al invertir el sentido, así que las
    // dos flechas de una ida y vuelta quedan en lados opuestos sin tocar el signo.
    const bend = mutual ? 42 : 16;
    const control = {
      x: (source.x + target.x) / 2 + px * bend,
      y: (source.y + target.y) / 2 + py * bend,
    };
    const start = borderToward(source, control);
    const tip = borderToward(target, control);
    const lineEnd = pullBack(tip, control, 8);
    // Más cerca del estado que sale, para que en un ciclo las etiquetas no se apilen en el medio.
    const mid = quadratic(start, control, lineEnd, mutual ? 0.38 : 0.46);
    const nudge = bend >= 0 ? 12 : -12;
    return {
      from: source.id,
      to: target.id,
      label,
      epsilon,
      loop: false,
      kind: "curve",
      start,
      c: control,
      lineEnd,
      tip,
      labelX: mid.x + px * nudge,
      labelY: mid.y + py * nudge,
      arrow: arrowHead(tip, control, 9),
    };
  }

  function relaxLabels(nodes, edges) {
    for (let pass = 0; pass < 10; pass += 1) {
      for (const edge of edges) {
        for (const node of nodes) {
          const dx = edge.labelX - node.x;
          const dy = edge.labelY - node.y;
          const padX = node.w / 2 + 8;
          const padY = node.h / 2 + 8;
          if (Math.abs(dx) >= padX || Math.abs(dy) >= padY) continue;
          const outX = padX - Math.abs(dx);
          const outY = padY - Math.abs(dy);
          if (outX < outY) edge.labelX += (dx < 0 ? -1 : 1) * (outX + 1);
          else edge.labelY += (dy < 0 ? -1 : 1) * (outY + 1);
        }
      }
      for (let left = 0; left < edges.length; left += 1) {
        for (let right = left + 1; right < edges.length; right += 1) {
          const a = edges[left];
          const b = edges[right];
          const dx = b.labelX - a.labelX;
          const dy = b.labelY - a.labelY;
          const dist = Math.hypot(dx, dy);
          const min = 20;
          if (dist >= min) continue;
          const push = (min - dist) / 2 + 0.5;
          const ux = dist ? dx / dist : 1;
          const uy = dist ? dy / dist : 0;
          a.labelX -= ux * push;
          a.labelY -= uy * push;
          b.labelX += ux * push;
          b.labelY += uy * push;
        }
      }
    }
  }

  function loopDirection(node, center, count) {
    if (count <= 2) return { x: 0, y: -1 };
    const ux = node.x - center.x;
    const uy = node.y - center.y;
    const len = Math.hypot(ux, uy) || 1;
    if (node.initial && ux / len < -0.6) return { x: 0, y: -1 };
    return { x: ux / len, y: uy / len };
  }

  function startArrow(nodes) {
    const initial = nodes.find((node) => node.initial);
    if (!initial) return null;
    const tip = borderAlong(initial, -1, 0);
    const from = { x: tip.x - 34, y: tip.y };
    return {
      from,
      lineEnd: pullBack(tip, from, 8),
      tip,
      arrow: arrowHead(tip, from, 9),
    };
  }

  function missingArrow(nodes, alphabet, grouped, deterministic) {
    if (!deterministic) return false;
    for (const node of nodes) {
      const inner = grouped.get(node.id);
      const used = new Set();
      if (inner) {
        for (const symbols of inner.values()) {
          for (const symbol of symbols) if (symbol) used.add(symbol);
        }
      }
      for (const symbol of alphabet) {
        if (!used.has(symbol)) return true;
      }
    }
    return false;
  }

  function legend(flags) {
    const parts = [
      "El doble círculo es un estado final.",
      "La flecha suelta marca el inicial.",
    ];
    if (flags.hasLoop) parts.push("Una flecha que vuelve al mismo estado es un lazo.");
    if (flags.hasEpsilon) parts.push("ε es una transición con la cadena vacía.");
    if (flags.hasGap) parts.push("Las flechas que faltan no se dibujan: en la tabla aparecen como un guión.");
    else if (!flags.deterministic) parts.push("En un AFN puede haber más de una flecha con el mismo símbolo.");
    return parts.join(" ");
  }

  function summary(nodes, edges) {
    return nodes.map((node) => {
      const shown = quotePiece(node.fullLabel);
      let name = shown;
      if (node.initial && node.final) name += " es inicial y final.";
      else if (node.initial) name += " es inicial.";
      else if (node.final) name += " es final.";
      else name += ".";
      const own = edges.filter((edge) => edge.from === node.id);
      if (!own.length) return `${name} No salen flechas.`;
      const bits = own.map((edge) => (
        edge.to === node.id
          ? `con ${edge.label} vuelve a ${shown}`
          : `con ${edge.label} va a ${quotePiece(edge.to)}`
      ));
      const sentence = `${bits[0].charAt(0).toUpperCase()}${bits[0].slice(1)}`;
      const rest = bits.slice(1).map((bit) => `y ${bit}`).join(", ");
      return rest ? `${name} ${sentence}, ${rest}.` : `${name} ${sentence}.`;
    }).join(" ");
  }

  function borderAlong(node, ux, uy) {
    const dir = unit(ux, uy);
    if (node.shape === "circle") {
      return { x: node.x + dir.x * node.r, y: node.y + dir.y * node.r };
    }
    return capsuleBorder(node, dir.x, dir.y);
  }

  function borderToward(node, point) {
    return borderAlong(node, point.x - node.x, point.y - node.y);
  }

  function capsuleBorder(node, ux, uy) {
    const radius = node.h / 2;
    const halfFlat = Math.max(0, (node.w - node.h) / 2);
    if (Math.abs(uy) > 1e-8) {
      const t = radius / Math.abs(uy);
      if (Math.abs(ux * t) <= halfFlat + 1e-6) {
        return { x: node.x + ux * t, y: node.y + Math.sign(uy) * radius };
      }
    }
    const capX = ux >= 0 ? halfFlat : -halfFlat;
    const disc = Math.max(0, radius * radius - (capX * uy) * (capX * uy));
    const t = ux * capX + Math.sqrt(disc);
    return { x: node.x + ux * t, y: node.y + uy * t };
  }

  function pullBack(tip, from, distance) {
    const dx = tip.x - from.x;
    const dy = tip.y - from.y;
    const len = Math.hypot(dx, dy) || 1;
    return { x: tip.x - (dx / len) * distance, y: tip.y - (dy / len) * distance };
  }

  function arrowHead(tip, from, size) {
    const dx = tip.x - from.x;
    const dy = tip.y - from.y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const baseX = tip.x - ux * size;
    const baseY = tip.y - uy * size;
    const wing = size * 0.48;
    return [
      { x: tip.x, y: tip.y },
      { x: baseX + -uy * wing, y: baseY + ux * wing },
      { x: baseX - -uy * wing, y: baseY - ux * wing },
    ];
  }

  function cubic(p0, p1, p2, p3, t) {
    const u = 1 - t;
    return {
      x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
      y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
    };
  }

  function quadratic(p0, p1, p2, t) {
    const u = 1 - t;
    return {
      x: u * u * p0.x + 2 * u * t * p1.x + t * t * p2.x,
      y: u * u * p0.y + 2 * u * t * p1.y + t * t * p2.y,
    };
  }

  function unit(x, y) {
    const len = Math.hypot(x, y) || 1;
    return { x: x / len, y: y / len };
  }

  function fit(nodes, edges, start) {
    const box = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
    const add = (x, y, padX, padY) => {
      box.minX = Math.min(box.minX, x - padX);
      box.minY = Math.min(box.minY, y - padY);
      box.maxX = Math.max(box.maxX, x + padX);
      box.maxY = Math.max(box.maxY, y + padY);
    };
    for (const node of nodes) add(node.x, node.y, node.w / 2, node.h / 2);
    for (const edge of edges) {
      add(edge.labelX, edge.labelY, Math.max(14, edge.label.length * 4.2), 11);
      for (const point of edgePoints(edge)) add(point.x, point.y, 2, 2);
    }
    if (start) {
      add(start.from.x, start.from.y, 2, 2);
      for (const point of start.arrow) add(point.x, point.y, 2, 2);
    }
    const margin = 14;
    const dx = margin - box.minX;
    const dy = margin - box.minY;
    const width = box.maxX - box.minX + margin * 2;
    const height = box.maxY - box.minY + margin * 2;
    for (const node of nodes) {
      node.x += dx;
      node.y += dy;
    }
    for (const edge of edges) shiftEdge(edge, dx, dy);
    if (start) {
      start.from.x += dx;
      start.from.y += dy;
      start.lineEnd.x += dx;
      start.lineEnd.y += dy;
      start.tip.x += dx;
      start.tip.y += dy;
      start.arrow.forEach((point) => {
        point.x += dx;
        point.y += dy;
      });
    }
    return { width: Math.ceil(width), height: Math.ceil(height) };
  }

  function edgePoints(edge) {
    const points = [edge.start, edge.lineEnd, edge.tip, ...edge.arrow];
    if (edge.kind === "loop") points.push(edge.c1, edge.c2);
    else points.push(edge.c);
    return points;
  }

  function shiftEdge(edge, dx, dy) {
    for (const point of edgePoints(edge)) {
      point.x += dx;
      point.y += dy;
    }
    edge.labelX += dx;
    edge.labelY += dy;
  }

  function round(value) {
    return Math.round(value * 10) / 10;
  }

  function publicNode(node) {
    return {
      id: node.id,
      x: round(node.x),
      y: round(node.y),
      r: node.r,
      w: node.w,
      h: node.h,
      shape: node.shape,
      label: node.label,
      fullLabel: node.fullLabel,
      initial: node.initial,
      final: node.final,
      accessibleName: node.accessibleName,
    };
  }

  function publicEdge(edge) {
    return {
      from: edge.from,
      to: edge.to,
      label: edge.label,
      epsilon: edge.epsilon,
      loop: edge.loop,
      d: pathOf(edge),
      labelX: round(edge.labelX),
      labelY: round(edge.labelY),
      tip: { x: round(edge.tip.x), y: round(edge.tip.y) },
      arrow: edge.arrow.map((point) => `${round(point.x)},${round(point.y)}`).join(" "),
    };
  }

  function publicStart(start) {
    return {
      d: `M ${round(start.from.x)} ${round(start.from.y)} L ${round(start.lineEnd.x)} ${round(start.lineEnd.y)}`,
      tip: { x: round(start.tip.x), y: round(start.tip.y) },
      arrow: start.arrow.map((point) => `${round(point.x)},${round(point.y)}`).join(" "),
    };
  }

  function pathOf(edge) {
    const move = `M ${round(edge.start.x)} ${round(edge.start.y)}`;
    const end = `${round(edge.lineEnd.x)} ${round(edge.lineEnd.y)}`;
    if (edge.kind === "loop") {
      return `${move} C ${round(edge.c1.x)} ${round(edge.c1.y)} ${round(edge.c2.x)} ${round(edge.c2.y)} ${end}`;
    }
    return `${move} Q ${round(edge.c.x)} ${round(edge.c.y)} ${end}`;
  }

  return { automatonDiagram, STATE_LIMIT, MAX_LABEL };
});
