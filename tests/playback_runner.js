const { playback } = require("../static/playback.js");

const payload = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(playback(payload.result, payload.automaton)));
