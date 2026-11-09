const { automatonDiagram } = require("../static/diagram.js");

const automaton = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(automatonDiagram(automaton)));
