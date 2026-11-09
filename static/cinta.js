// Traza de la cinta de una máquina de Turing. Puro: no toca el DOM, así el
// test lo corre con node. Muchos pasos muestran el arranque y el final; el
// resto se abre con un botón. Cada cinta muestra como mucho CELL_LIMIT
// casillas alrededor del cabezal: no se dibujan 4096.
//
// Un salto en los índices guardados es un tramo que no se copió: el aviso
// «No se guardaron» queda delante del paso que sigue, con esa cantidad.
// Si la vista de 24 esconde pasos que sí están guardados, «Se omiten»
// queda en ese corte y no se le suma el tramo que no se guardó.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenCinta = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const STEP_LIMIT = 24;
  const CELL_LIMIT = 24;

  function tapeTrace(result, options) {
    const expanded = Boolean(options && options.expanded);
    const blank = blankOf(result, options);
    if (!result || typeof result !== "object") return emptyTrace("No pude simular.");

    const verdict = verdictOf(result);
    const known = verdict === "Acepta" || verdict === "Rechaza" || verdict === "No terminó";
    let raw = listOf(result.steps).filter((step) => step && typeof step === "object");
    if (!raw.length && known && Array.isArray(result.tape)) {
      raw = [{ state: result.state, tape: result.tape, head: result.head }];
    }
    if (!known && !raw.length) {
      const message = textOf(result.message);
      return emptyTrace(message || "No pude simular.");
    }

    const all = raw.map((step, position) => stepView(step, position, blank));
    const hole = holeCount(all);
    const window = visibleSteps(all, expanded);
    const steps = markGaps(window.steps, all);
    const summary = summaryOf(result, verdict);

    return {
      ok: true,
      accepted: result.accepted === true ? true : result.accepted === false ? false : null,
      status: typeof result.status === "string" ? result.status : "",
      verdict,
      summary,
      steps,
      total: all.length,
      omitted: window.omitted,
      hole,
      gap: collapsedNotice(steps),
      moreLabel: moreLabel(all.length, window.omitted, expanded, hole),
      limit: STEP_LIMIT,
      cellLimit: CELL_LIMIT,
    };
  }

  function emptyTrace(message) {
    return {
      ok: false,
      accepted: null,
      status: "",
      verdict: "",
      summary: message,
      steps: [],
      total: 0,
      omitted: 0,
      hole: 0,
      gap: "",
      moreLabel: "",
      limit: STEP_LIMIT,
      cellLimit: CELL_LIMIT,
    };
  }

  function stepView(step, position, blank) {
    const tape = listOf(step.tape);
    const head = headAt(step.head, tape.length);
    const window = windowCells(tape, head, blank);
    const name = stateName(step.state);
    return {
      index: indexOf(step, position),
      state: name,
      head,
      cells: window.cells,
      leading: window.leading,
      trailing: window.trailing,
      text: stepText(name, position, head, symbolUnder(tape, head, blank)),
      gapBefore: "",
      gaps: [],
    };
  }

  function stepText(name, position, head, symbol) {
    const where = head === null
      ? "El cabezal no tiene una posición."
      : `Cabezal en la posición ${head + 1}, sobre ${symbol}.`;
    if (!name) {
      return position === 0 ? `Empieza sin estado. ${where}` : `Sin estado. ${where}`;
    }
    if (position === 0) return `Empieza en ${name}. ${where}`;
    return `Estado ${name}. ${where}`;
  }

  function symbolUnder(tape, head, blank) {
    if (head === null) return "un casillero que no está";
    return spokenSymbol(tape[head], blank);
  }

  function windowCells(tape, head, blank) {
    const len = tape.length;
    if (!len) return { cells: [], leading: 0, trailing: 0 };
    let start = 0;
    let end = len;
    if (len > CELL_LIMIT) {
      if (head === null) {
        end = CELL_LIMIT;
      } else {
        const half = Math.floor(CELL_LIMIT / 2);
        start = Math.max(0, Math.min(head - half, len - CELL_LIMIT));
        end = start + CELL_LIMIT;
      }
    }
    const cells = [];
    for (let index = start; index < end; index += 1) {
      cells.push(cellView(tape[index], index === head, blank));
    }
    return { cells, leading: start, trailing: len - end };
  }

  function cellView(symbol, isHead, blank) {
    const raw = readOf(symbol);
    if (raw === blank) {
      return { text: "␣", spoken: "blanco", head: isHead, blank: true };
    }
    if (raw === "") {
      return { text: "vacío", spoken: "vacío", head: isHead, blank: false };
    }
    if (needsQuotes(raw)) {
      const quoted = quote(raw);
      return { text: quoted, spoken: quoted, head: isHead, blank: false };
    }
    return { text: raw, spoken: raw, head: isHead, blank: false };
  }

  function visibleSteps(steps, expanded) {
    if (expanded || steps.length <= STEP_LIMIT) return { steps: steps.slice(), omitted: 0 };
    const tailCount = STEP_LIMIT - 1;
    const tail = steps.slice(steps.length - tailCount);
    return { steps: [steps[0], ...tail], omitted: steps.length - STEP_LIMIT };
  }

  // Cada hueco queda en el paso que lo sigue. Los índices que están en la
  // lista guardada pero no en la vista son «Se omiten». Los que no están
  // en la lista son «No se guardaron». Si los dos se tocan, van en orden.
  function markGaps(shown, stored) {
    const indexes = stored.map((step) => step.index).slice().sort((left, right) => left - right);
    return shown.map((step, position) => {
      const copy = { ...step, cells: step.cells.slice(), gapBefore: "", gaps: [] };
      if (position === 0) return copy;
      const notices = noticesBetween(shown[position - 1].index, step.index, indexes);
      copy.gaps = notices;
      copy.gapBefore = notices.join(" ");
      return copy;
    });
  }

  function noticesBetween(prev, next, indexes) {
    const notices = [];
    let cursor = prev + 1;
    let omitted = 0;
    const flushOmitted = () => {
      if (!omitted) return;
      notices.push(gapText(omitted));
      omitted = 0;
    };
    for (let place = 0; place < indexes.length; place += 1) {
      const index = indexes[place];
      if (index <= prev) continue;
      if (index >= next) break;
      const hole = index - cursor;
      if (hole > 0) {
        flushOmitted();
        notices.push(holeText(hole));
      }
      omitted += 1;
      cursor = index + 1;
    }
    const tail = next - cursor;
    if (tail > 0) {
      flushOmitted();
      notices.push(holeText(tail));
    } else {
      flushOmitted();
    }
    return notices;
  }

  // El aviso único de la vista cerrada solo dice la verdad si el único
  // corte es de pasos guardados, entre el primero y el segundo. Un hueco
  // que no se guardó va en gaps, no sumado a ese corte.
  function collapsedNotice(steps) {
    if (steps.length < 2) return "";
    for (let index = 2; index < steps.length; index += 1) {
      if (steps[index].gapBefore) return "";
    }
    const notice = steps[1].gapBefore;
    if (!notice || notice.includes("guard")) return "";
    return notice;
  }

  function holeCount(steps) {
    let missing = 0;
    for (let index = 1; index < steps.length; index += 1) {
      const jump = steps[index].index - steps[index - 1].index - 1;
      if (jump > 0) missing += jump;
    }
    return missing;
  }

  function moreLabel(total, omitted, expanded, hole) {
    if (omitted) {
      return hole ? `Ver los ${total} pasos guardados` : `Ver los ${total} pasos`;
    }
    if (expanded && total > STEP_LIMIT) return "Ver menos";
    return "";
  }

  function gapText(omitted) {
    if (!omitted || omitted < 0) return "";
    if (omitted === 1) return "Se omite 1 paso.";
    return `Se omiten ${omitted} pasos.`;
  }

  function holeText(count) {
    if (count === 1) return "No se guardó 1 paso.";
    return `No se guardaron ${count} pasos.`;
  }

  function verdictOf(result) {
    if (result.status === "timeout") return "No terminó";
    if (result.status === "reject") return "Rechaza";
    if (result.status === "accept") return "Acepta";
    const message = textOf(result.message);
    if (message.startsWith("No terminó")) return "No terminó";
    if (result.accepted === false) return "Rechaza";
    if (result.accepted === true) return "Acepta";
    return "";
  }

  function summaryOf(result, verdict) {
    const message = textOf(result.message);
    if (message) return message;
    if (verdict === "No terminó") return "No terminó.";
    if (verdict === "Rechaza") return "Rechaza.";
    if (verdict === "Acepta") return "Acepta.";
    return "No pude simular.";
  }

  function headAt(head, length) {
    if (!Number.isInteger(head) || head < 0 || head >= length) return null;
    return head;
  }

  function indexOf(step, position) {
    if (Number.isInteger(step.index) && step.index >= 0) return step.index;
    return position;
  }

  function stateName(value) {
    const id = idOf(value);
    if (!id) return "";
    return displayName(id);
  }

  function spokenSymbol(symbol, blank) {
    const raw = readOf(symbol);
    if (raw === blank) return "el blanco";
    if (raw === "") return "vacío";
    if (needsQuotes(raw)) return quote(raw);
    return raw;
  }

  function needsQuotes(text) {
    if (text.length !== 1) return true;
    if (text === "«" || text === "»" || text === " ") return true;
    return sticks(text);
  }

  function quote(text) {
    return `«${String(text).split("«").join("‹").split("»").join("›")}»`;
  }

  function displayName(name) {
    const text = String(name);
    if (text.includes(", ") || text.includes(" y ") || text.includes("«") || text.includes("»") || sticks(text)) {
      return quote(text);
    }
    return text;
  }

  function sticks(text) {
    return typeof text === "string" && /\p{M}/u.test(text);
  }

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

  function textOf(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  function listOf(value) {
    return Array.isArray(value) ? value : [];
  }

  // Sin dato, el blanco de la materia es «_». Si la máquina usa otro,
  // ese carácter es el ␣ y un «_» escrito no lo es.
  function blankOf(result, options) {
    if (options && typeof options.blank === "string") return options.blank;
    if (result && typeof result.blank === "string") return result.blank;
    return "_";
  }

  return { tapeTrace, STEP_LIMIT, CELL_LIMIT };
});
