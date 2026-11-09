const { grammarView } = require("../static/grammar_view.js");

const grammar = JSON.parse(process.argv[2]);
const options = JSON.parse(process.argv[3] || "{}");
process.stdout.write(JSON.stringify(grammarView(grammar, options)));
