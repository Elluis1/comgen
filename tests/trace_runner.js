const { simulationTrace } = require("../static/trace.js");

const payload = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(
  simulationTrace(payload.result, payload.automaton, payload.options || {}),
));
