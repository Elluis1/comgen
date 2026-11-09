// Gramática en la pantalla. Pura: no toca el DOM, así el test la corre con node.
// El texto ya viene armado por el servidor (comillas y todo). Acá solo se parte
// en renglones para que entre en la pantalla y se lea.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenGrammar = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // El mismo tope que GRAMMAR_LINE_LIMIT en app.js. No subirlo: una gramática
  // de mil variables no tiene que dibujarse entera en la notebook chica.
  const LINE_LIMIT = 32;

  function grammarView(grammar, options) {
    const limit = limitOf(options);
    const text = grammar && typeof grammar.text === "string" ? grammar.text : "";
    const start = startOf(grammar);
    const parsed = text.split("\n").flatMap((line) => {
      const clean = String(line).replace(/\r$/, "");
      if (!clean) return [];
      return [parseLine(clean, start)];
    });
    const lines = parsed.slice(0, limit);
    const startLine = parsed.find((line) => line.start) || null;
    const hasEmpty = parsed.some((line) => line.alternatives.some((alt) => alt.empty));
    return {
      lines,
      hidden: Math.max(0, parsed.length - lines.length),
      total: parsed.length,
      legend: legend(startLine, hasEmpty),
    };
  }

  function parseLine(line, start) {
    const marker = " → ";
    // «A → B» es un solo nombre. La flecha de adentro no parte la producción.
    const arrow = arrowAt(line, marker);
    if (arrow <= 0) {
      return { ok: false, raw: line, variable: line, start: false, alternatives: [], spoken: line };
    }
    const variable = line.slice(0, arrow);
    const alternatives = splitAlts(line.slice(arrow + marker.length)).flatMap((text) => {
      if (!text) return [];
      return [{ text, empty: text === "ε" }];
    });
    const isStart = Boolean(start) && unquote(variable).normalize("NFC") === start;
    return {
      ok: true,
      raw: line,
      variable,
      start: isStart,
      alternatives,
      spoken: spokenOf(variable, isStart, alternatives),
    };
  }

  function arrowAt(line, marker) {
    let depth = 0;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (ch === "«") depth += 1;
      else if (ch === "»" && depth > 0) depth -= 1;
      if (depth === 0 && line.startsWith(marker, i)) return i;
    }
    return -1;
  }

  // «A | B» es un solo nombre: la barra de adentro no abre otra alternativa.
  function splitAlts(rest) {
    const parts = [];
    let current = "";
    let depth = 0;
    for (let i = 0; i < rest.length; i += 1) {
      const ch = rest[i];
      if (ch === "«") depth += 1;
      else if (ch === "»" && depth > 0) depth -= 1;
      if (depth === 0 && rest.startsWith(" | ", i)) {
        parts.push(current);
        current = "";
        i += 2;
        continue;
      }
      current += ch;
    }
    parts.push(current);
    return parts;
  }

  function unquote(name) {
    if (name.length >= 2 && name.startsWith("«") && name.endsWith("»")) {
      return name.slice(1, -1).split("‹").join("«").split("›").join("»");
    }
    return name;
  }

  function spokenOf(variable, isStart, alternatives) {
    const who = isStart ? `${variable}, símbolo inicial` : variable;
    const bits = alternatives.map((alt) => (alt.empty ? "épsilon" : alt.text));
    if (!bits.length) return who;
    if (bits.length === 1) return `${who}: ${bits[0]}`;
    return `${who}: ${bits.slice(0, -1).join(", o ")}, o ${bits[bits.length - 1]}`;
  }

  function legend(startLine, hasEmpty) {
    const parts = [];
    if (startLine) parts.push(`${startLine.variable} es el símbolo inicial.`);
    if (hasEmpty) parts.push("Donde dice ε, la derivación puede terminar.");
    if (!parts.length) parts.push("Cada renglón es una producción.");
    return parts.join(" ");
  }

  function startOf(grammar) {
    if (!grammar || typeof grammar.start !== "string" || !grammar.start) return "";
    return grammar.start.normalize("NFC");
  }

  function limitOf(options) {
    const value = options && options.limit;
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) return Math.floor(value);
    return LINE_LIMIT;
  }

  return { grammarView, LINE_LIMIT };
});
