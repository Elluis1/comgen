const guia = require("../static/guia.js");

const payload = JSON.parse(process.argv[2] || "{}");
const fn = guia[payload.fn];
if (typeof fn !== "function") {
  process.stderr.write(`No está ${payload.fn}\n`);
  process.exit(1);
}
process.stdout.write(JSON.stringify(fn(...(payload.args || []))));
