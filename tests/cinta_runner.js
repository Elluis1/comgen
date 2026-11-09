const fs = require("fs");
const { tapeTrace } = require("../static/cinta.js");

// Sin argumentos, el JSON entra por stdin en UTF-8: {result, options}.
// Una cinta de 4096 casillas no entra en la línea de comandos.
let payload;
if (process.argv[2] === undefined) {
  payload = JSON.parse(fs.readFileSync(0, "utf8"));
} else {
  payload = JSON.parse(process.argv[2]);
}
process.stdout.write(JSON.stringify(tapeTrace(payload.result, payload.options)));
