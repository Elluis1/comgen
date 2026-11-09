const wordHint = require("../static/word_hint.js");

const payload = JSON.parse(process.argv[2] || "{}");
const fn = wordHint[payload.fn];
if (typeof fn !== "function") {
  process.stderr.write(`No está ${payload.fn}\n`);
  process.exit(1);
}
process.stdout.write(JSON.stringify(fn(...(payload.args || []))));
