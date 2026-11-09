const fs = require("fs");
const { transitionTable } = require("../static/delta.js");

// Sin argumentos, el JSON entra por stdin en UTF-8: {automaton, options}.
// Hace falta para miles de columnas: Windows corta la línea de comandos
// cerca de los 32767 caracteres. Con argumentos, sigue el camino de antes.
let automaton;
let options;
if (process.argv[2] === undefined) {
  const payload = JSON.parse(fs.readFileSync(0, "utf8"));
  automaton = payload.automaton;
  options = payload.options || {};
} else {
  automaton = JSON.parse(process.argv[2]);
  options = JSON.parse(process.argv[3] || "{}");
}

process.stdout.write(JSON.stringify(transitionTable(automaton, options)));
