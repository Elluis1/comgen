// Guía de los botones del autómata. Pura: no toca el DOM ni recorre flechas.
// Solo mira si el resultado dice que es determinista. El 1 no es true y el 0 no es false.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ComgenGuia = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const TEXT = {
    vacio: "Elegí un ejemplo o escribí el enunciado. Ahí se habilitan Determinizar, Expresión, Gramática y la descarga.",
    afd: "Es un AFD, autómata finito determinista. Desde cada estado sale a lo sumo una flecha por símbolo. Podés sacar la expresión, armar la gramática o descargar el .jff.",
    afn: "Es un AFN, autómata finito no determinista. Puede haber más de una flecha con el mismo símbolo, o con ε. Determinizar arma el AFD. La expresión y la gramática piden ese AFD; el .jff de este AFN ya se puede bajar.",
    duda: "Este resultado no dice si es un AFD o un AFN. Si Determinizar está habilitado, conviene usarlo antes de la expresión o la gramática.",
  };

  const BADGE = {
    afd: { text: "AFD · determinista", spoken: "Autómata finito determinista" },
    afn: { text: "AFN · no determinista", spoken: "Autómata finito no determinista" },
    duda: { text: "Autómata", spoken: "No dice si es determinista" },
  };

  function actionGuide(automaton) {
    const kind = kindOf(automaton);
    return { kind, text: TEXT[kind] };
  }

  function kindBadge(automaton) {
    const kind = kindOf(automaton);
    if (kind === "vacio") return { shown: false, kind, text: "", spoken: "" };
    const badge = BADGE[kind];
    return { shown: true, kind, text: badge.text, spoken: badge.spoken };
  }

  function kindOf(automaton) {
    if (!automaton || typeof automaton !== "object" || Array.isArray(automaton)) return "vacio";
    if (automaton.deterministic === true) return "afd";
    if (automaton.deterministic === false) return "afn";
    return "duda";
  }

  return { actionGuide, kindBadge, TEXT };
});
