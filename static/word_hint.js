// Textos de la prueba de una cadena. Puro: no toca el DOM, así el test lo corre con node.
// El campo vacío es la cadena vacía de la materia. No se adivina si acepta.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenWord = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const PROBE_LIMIT = 8;
  const WORD_LIMIT = 32;

  function alphabetHint(alphabet) {
    const symbols = cleanAlphabet(alphabet);
    const tail = "Si dejás el campo vacío, se prueba la cadena vacía.";
    if (!symbols.length) return tail;
    return `Alfabeto {${symbols.map(showSymbol).join(", ")}}. ${tail}`;
  }

  function placeholderFor(alphabet) {
    const symbols = cleanAlphabet(alphabet);
    if (!symbols.length) return "";
    if (symbols.length === 2 && symbols[0] === "0" && symbols[1] === "1") return "0101";
    let word = "";
    for (let index = 0; index < 8 && word.length < 4; index += 1) {
      const symbol = symbols[index % symbols.length];
      if (symbol.length > 4) return symbol.slice(0, 4);
      if (word.length + symbol.length > 4) break;
      word += symbol;
    }
    return word;
  }

  // extras es la lista del ejemplo. Si no hay ejemplo, extras no es un array
  // y se ofrecen la vacía y los símbolos, cuando el alfabeto es chico.
  function probeWords(alphabet, extras) {
    const words = [];
    const push = (word) => {
      if (typeof word !== "string" || word.length > WORD_LIMIT) return;
      if (words.includes(word) || words.length >= PROBE_LIMIT) return;
      words.push(word);
    };
    push("");
    if (Array.isArray(extras)) {
      for (const word of extras) push(word);
      return words;
    }
    const symbols = cleanAlphabet(alphabet);
    if (symbols.length > 0 && symbols.length <= 4 && symbols.every((symbol) => symbol.length === 1)) {
      for (const symbol of symbols) push(symbol);
    }
    return words;
  }

  function probeLabel(word) {
    const text = typeof word === "string" ? word : "";
    if (!text) return "vacía";
    const shown = text.length > 12 ? `${text.slice(0, 11)}…` : text;
    if (sticks(shown)) return `«${shown.split("«").join("‹").split("»").join("›")}»`;
    return shown;
  }

  function probeSpoken(word) {
    const text = typeof word === "string" ? word : word == null ? "" : String(word);
    if (!text) return "Probar la cadena vacía";
    return `Probar la cadena ${nameWord(text)}`;
  }

  // El resumen de la traza no se reescribe. Acá se nombra la cadena adelante.
  function resultWithWord(summary, word) {
    if (typeof summary !== "string") return "";
    const named = nameWord(word);
    if (summary.startsWith("Acepta.")) return `Acepta ${named}.${summary.slice("Acepta.".length)}`;
    if (summary.startsWith("Rechaza.")) return `Rechaza ${named}.${summary.slice("Rechaza.".length)}`;
    return summary;
  }

  function nameWord(word) {
    const text = typeof word === "string" ? word : word == null ? "" : String(word);
    if (!text) return "la cadena vacía";
    const shown = text.length > WORD_LIMIT ? `${text.slice(0, WORD_LIMIT - 1)}…` : text;
    return `«${shown.split("«").join("‹").split("»").join("›")}»`;
  }

  function showSymbol(symbol) {
    const text = String(symbol);
    if (
      sticks(text)
      || text.includes(", ")
      || text.includes("{")
      || text.includes("}")
      || text.includes("«")
      || text.includes("»")
    ) {
      return `«${text.split("«").join("‹").split("»").join("›")}»`;
    }
    return text;
  }

  // Una marca suelta se pega a la llave: «{́, a}» se lee mal.
  function sticks(text) {
    return typeof text === "string" && /\p{M}/u.test(text);
  }

  function cleanAlphabet(alphabet) {
    if (!Array.isArray(alphabet)) return [];
    const out = [];
    const seen = new Set();
    for (const symbol of alphabet) {
      if (typeof symbol !== "string" || !symbol || seen.has(symbol)) continue;
      seen.add(symbol);
      out.push(symbol);
    }
    return out;
  }

  return {
    alphabetHint,
    placeholderFor,
    probeWords,
    probeLabel,
    probeSpoken,
    resultWithWord,
    PROBE_LIMIT,
    WORD_LIMIT,
  };
});
