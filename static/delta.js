// Tabla δ de la materia. Pura: no toca el DOM, así el test la corre con node.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenDelta = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // Por encima de esto no se dibujan todas las filas: miles de celdas
  // traban una notebook chica. El resto se abre con un botón.
  const ROW_LIMIT = 32;
  // Miles de columnas traban la notebook igual que miles de filas.
  const COL_LIMIT = 32;

  function transitionTable(automaton, options) {
    const expanded = Boolean(options && options.expanded);
    const alphabet = listOf(automaton && automaton.alphabet);
    const states = listOf(automaton && automaton.states);
    const transitions = listOf(automaton && automaton.transitions);
    const deterministic = Boolean(automaton && automaton.deterministic);

    const columns = [];
    const seen = new Set();
    for (const symbol of alphabet) {
      const id = readOf(symbol);
      if (!id || seen.has(id)) continue;
      seen.add(id);
      columns.push({ id, label: quotePiece(id), epsilon: false, extra: false });
    }

    let hasEpsilon = false;
    for (const item of transitions) {
      if (!item || typeof item !== "object") continue;
      const read = readOf(item.read);
      if (read === null) continue;
      if (!read) {
        hasEpsilon = true;
        continue;
      }
      if (seen.has(read)) continue;
      seen.add(read);
      columns.push({ id: read, label: quotePiece(read), epsilon: false, extra: true });
    }
    if (hasEpsilon) columns.push({ id: "", label: "ε", epsilon: true, extra: false });
    const columnTotal = columns.length;
    const capped = capColumns(columns);
    const shownColumns = capped.columns;
    const hiddenColumns = capped.hidden;

    // Mapa anidado: un nulo dentro del nombre no junta dos celdas distintas.
    const byFrom = new Map();
    for (const item of transitions) {
      if (!item || typeof item !== "object") continue;
      const from = idOf(item.from);
      const to = idOf(item.to);
      const read = readOf(item.read);
      if (!from || !to || read === null) continue;
      let inner = byFrom.get(from);
      if (!inner) {
        inner = new Map();
        byFrom.set(from, inner);
      }
      let list = inner.get(read);
      if (!list) {
        list = [];
        inner.set(read, list);
      }
      if (!list.includes(to)) list.push(to);
    }

    const alphabetSet = new Set();
    for (const symbol of alphabet) {
      const id = readOf(symbol);
      if (id) alphabetSet.add(id);
    }
    const seenRows = new Set();
    const allRows = states.filter((state) => state && typeof state === "object").flatMap((state) => {
      const id = rowId(state.id);
      if (!id || seenRows.has(id)) return [];
      seenRows.add(id);
      const rowState = { id, initial: Boolean(state.initial), final: Boolean(state.final) };
      return [{
      id,
      spoken: quotePiece(id),
      initial: rowState.initial,
      final: rowState.final,
      accessibleName: stateName(rowState),
      marks: marksOf(rowState),
      cells: shownColumns.map((column) => {
        const inner = byFrom.get(id);
        const list = (inner && inner.get(column.id)) || [];
        const gap = deterministic && !column.epsilon && alphabetSet.has(column.id) && list.length === 0;
        return {
          symbol: column.id,
          label: column.label,
          targets: list,
          text: targetText(list),
          gap,
        };
      }),
    }];
    });

    const total = allRows.length;
    const hidden = !expanded && total > ROW_LIMIT ? total - ROW_LIMIT : 0;
    const rows = hidden ? allRows.slice(0, ROW_LIMIT) : allRows;
    const hasGap = allRows.some((row) => row.cells.some((cell) => cell.gap));
    const hasBranch = allRows.some((row) => row.cells.some((cell) => cell.targets.length > 1));
    const hasExtra = shownColumns.some((column) => column.extra);

    let moreLabel = "";
    if (hidden) moreLabel = `Ver los ${total} estados`;
    else if (expanded && total > ROW_LIMIT) moreLabel = "Ver menos";

    return {
      deterministic,
      columns: shownColumns,
      columnTotal,
      hiddenColumns,
      rows,
      total,
      hidden,
      hasGap,
      hasBranch,
      caption: hidden ? `Transiciones, primeros ${rows.length} de ${total} estados` : "Transiciones",
      legend: legend({
        deterministic,
        hasGap,
        hasBranch,
        hasExtra,
        hiddenColumns,
        columnTotal,
        shown: shownColumns.length,
      }),
      moreLabel,
    };
  }

  function listOf(value) {
    return Array.isArray(value) ? value : [];
  }

  // El 0 numérico no es la cadena vacía: si se pierde, se mezcla con épsilon.
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

  function capColumns(columns) {
    if (columns.length <= COL_LIMIT) return { columns, hidden: 0 };
    const epsilon = columns.filter((column) => column.epsilon);
    const rest = columns.filter((column) => !column.epsilon);
    const room = Math.max(0, COL_LIMIT - epsilon.length);
    const kept = rest.slice(0, room);
    return { columns: kept.concat(epsilon), hidden: rest.length - kept.length };
  }

  // «q0, q1» como un solo nombre no puede verse igual que dos llegadas.
  function targetText(list) {
    if (!list.length) return "—";
    const raw = list.map((name) => String(name));
    const ambiguous = raw.some((text) => sticks(text) || text.includes(", ") || text.includes("«") || text.includes("»"));
    if (!ambiguous) return raw.join(", ");
    return raw.map((text) => `«${text.split("«").join("‹").split("»").join("›")}»`).join(", ");
  }

  function marksOf(state) {
    if (state.initial && state.final) return "→*";
    if (state.initial) return "→";
    if (state.final) return "*";
    return "";
  }

  function rowId(value) {
    return idOf(value);
  }

  // «q0, q1» en la frase del lector no puede sonar a dos estados.
  // Una marca suelta se pega a la palabra de atrás en la frase del lector.
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

  function stateName(state) {
    const id = quotePiece(state.id);
    if (state.initial && state.final) return `${id}, inicial y final`;
    if (state.initial) return `${id}, inicial`;
    if (state.final) return `${id}, final`;
    return id;
  }

  function legend(flags) {
    const parts = [
      "La flecha (→) es el estado inicial.",
      "El asterisco (*) es un estado final.",
    ];
    if (!flags.deterministic || flags.hasBranch) {
      parts.push("Si hay varias llegadas, van separadas por coma.");
    }
    if (flags.hasGap) parts.push("El guión es una flecha que falta.");
    else if (!flags.deterministic) parts.push("El guión quiere decir que por ese símbolo no hay flecha.");
    if (flags.hasExtra) parts.push("Hay un símbolo que no está en el alfabeto.");
    if (flags.hiddenColumns) {
      parts.push(
        `Hay ${flags.columnTotal} columnas. Te muestro ${flags.shown} para que la página siga liviana.`,
      );
    }
    return parts.join(" ");
  }

  return { transitionTable, ROW_LIMIT, COL_LIMIT };
});
