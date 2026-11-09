const state = {
  sessionId: null,
  exportReady: false,
  automaton: null,
  lastRun: null,
  probes: null,
  testedWord: "",
  turingRun: null,
};

const exampleProbes = new Map();

const log = document.querySelector("#log");
const machine = document.querySelector("#machine");
const examples = document.querySelector("#examples");
const status = document.querySelector("#status");
const prompt = document.querySelector("#prompt");
const send = document.querySelector("#send");
const download = document.querySelector("#download");
const determinize = document.querySelector("#determinize");
const regexButton = document.querySelector("#regex");
const grammarButton = document.querySelector("#grammar");
const GRAMMAR_LINE_LIMIT = 32;
const remember = document.querySelector("#remember");
const fresh = document.querySelector("#fresh");
const memoryNote = document.querySelector("#memory");
const runner = document.querySelector("#runner");
const word = document.querySelector("#word");
const runResult = document.querySelector("#run-result");

document.querySelector("#composer").addEventListener("submit", (event) => {
  event.preventDefault();
  submitPrompt();
});

prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitPrompt();
  }
});

download.addEventListener("click", () => {
  if (!state.exportReady || !state.sessionId) return;
  window.location.href = `/api/sessions/${state.sessionId}/export`;
});

remember.addEventListener("click", saveMemory);
determinize.addEventListener("click", determinizeAutomaton);
regexButton.addEventListener("click", askRegex);
grammarButton.addEventListener("click", askGrammar);
fresh.addEventListener("click", startFresh);

document.querySelector("#runner").addEventListener("submit", async (event) => {
  event.preventDefault();
  await simulate();
});

document.getElementById("turing-file")?.addEventListener("change", () => {
  const file = document.getElementById("turing-file")?.files?.[0];
  const name = document.getElementById("turing-file-name");
  if (name) name.textContent = file ? file.name : "Ningún archivo elegido";
});

document.getElementById("turing-loader")?.addEventListener("submit", (event) => {
  event.preventDefault();
  const file = document.getElementById("turing-file")?.files?.[0];
  loadTuringFile(file).catch(() => {
    const status = document.getElementById("turing-status");
    if (status) status.textContent = "Se cortó la conexión con el servidor.";
  });
});

document.getElementById("turing-runner")?.addEventListener("submit", (event) => {
  event.preventDefault();
  simulateTuring().catch(() => {
    showTuringError("Se cortó la conexión con el servidor.");
  });
});

for (const input of document.querySelectorAll('input[name="run-mode"]')) {
  input.addEventListener("change", onRunMode);
}
document.getElementById("play-toggle")?.addEventListener("click", togglePlayback);
document.getElementById("step-prev")?.addEventListener("click", () => stepPlayback(-1));
document.getElementById("step-next")?.addEventListener("click", () => stepPlayback(1));
document.getElementById("step-reset")?.addEventListener("click", resetPlayback);
document.getElementById("play-speed")?.addEventListener("input", syncSpeedLabel);

const playbackRun = {
  model: null,
  index: 0,
  playing: false,
  timer: 0,
  raf: 0,
  motionToken: 0,
  word: "",
};
const SPEED_LABELS = ["Muy lenta", "Lenta", "Media", "Rápida", "Muy rápida"];
const SPEED_MS = [2400, 1700, 1100, 700, 420];
syncSpeedLabel();

init();

async function init() {
  try {
    const [health, session, exampleList, stored] = await Promise.all([
      fetch("/api/health").then((response) => response.json()),
      fetch("/api/sessions", { method: "POST" }).then((response) => response.json()),
      fetch("/api/examples").then((response) => response.json()),
      fetch("/api/memory").then((response) => response.json()),
    ]);
    state.sessionId = session.id;
    renderStatus(health);
    renderMemoryCount(stored.count);
    renderExamples(exampleList);
    renderEmptyLog();
  } catch (error) {
    status.textContent = "No pude abrir la aplicación";
    status.className = "status offline";
    log.replaceChildren(messageNode("assistant", "Recargá la página. El servidor no respondió.", "error"));
  }
}

function renderStatus(health) {
  status.className = "status";
  if (!health.online) {
    status.textContent = "Ollama no encontrado. Los ejemplos sí funcionan.";
    status.classList.add("offline");
    return;
  }
  if (!health.model_ready) {
    status.textContent = `Falta el modelo ${health.model}`;
    status.classList.add("missing");
    return;
  }
  status.textContent = `Ollama · ${health.model}`;
  status.classList.add("ready");
}

function renderMemoryCount(count) {
  const label = count === 1 ? "solución" : "soluciones";
  memoryNote.textContent = `Memoria compartida: ${count} ${label}`;
}

async function saveMemory() {
  if (!state.sessionId) return;
  remember.disabled = true;
  const response = await fetch(`/api/sessions/${state.sessionId}/remember`, { method: "POST" });
  const body = await readBody(response);
  if (!response.ok) {
    log.append(messageNode("assistant", body.detail || "No pude guardar la solución.", "error"));
    remember.disabled = false;
    return;
  }
  renderConversation(body);
}

function renderExamples(exampleList) {
  examples.replaceChildren();
  exampleProbes.clear();
  for (const example of exampleList) {
    if (Array.isArray(example.probes)) exampleProbes.set(example.id, example.probes);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.textContent = example.title;
    button.addEventListener("click", () => loadExample(example.id));
    examples.append(button);
  }
}

function renderEmptyLog() {
  const note = messageNode(
    "assistant",
    "Describí un lenguaje regular, o cargá un ejemplo para ver el autómata y descargar el .jff.",
  );
  note.classList.add("hint");
  log.replaceChildren(note);
}

function lockInputs(locked) {
  send.disabled = locked;
  fresh.disabled = locked;
  if (locked) {
    determinize.disabled = true;
    regexButton.disabled = true;
    grammarButton.disabled = true;
  } else {
    syncDeterminize(state.automaton);
    syncRegex(state.automaton);
    syncGrammar(state.automaton);
  }
  for (const button of examples.querySelectorAll("button")) button.disabled = locked;
}

function syncDeterminize(automaton) {
  if (!automaton) {
    determinize.disabled = true;
    determinize.title = "Primero tiene que haber un autómata";
    return;
  }
  if (automaton.deterministic) {
    determinize.disabled = true;
    determinize.title = "Ya es un AFD";
    return;
  }
  determinize.disabled = false;
  determinize.title = "Convierte este AFN en un AFD, sin épsilon";
}

function syncRegex(automaton) {
  if (!automaton) {
    regexButton.disabled = true;
    regexButton.title = "Primero tiene que haber un autómata";
    return;
  }
  regexButton.disabled = false;
  regexButton.title = automaton.deterministic
    ? "Saca la expresión regular de este AFD"
    : "Primero hay que determinizarlo";
}

function syncGrammar(automaton) {
  if (!automaton) {
    grammarButton.disabled = true;
    grammarButton.title = "Primero tiene que haber un autómata";
    return;
  }
  grammarButton.disabled = false;
  grammarButton.title = automaton.deterministic
    ? "Arma la gramática lineal a derecha de este AFD"
    : "Primero hay que determinizarlo";
}

function showLoading(text) {
  document.getElementById("loading-note")?.remove();
  const note = messageNode("assistant", text, "loading");
  note.id = "loading-note";
  log.append(note);
  log.setAttribute("aria-busy", "true");
  log.scrollTop = log.scrollHeight;
}

function hideLoading() {
  document.getElementById("loading-note")?.remove();
  log.removeAttribute("aria-busy");
}

async function startFresh() {
  if (!state.sessionId) return;
  lockInputs(true);
  try {
    const response = await fetch(`/api/sessions/${state.sessionId}/reset`, { method: "POST" });
    const body = await readBody(response);
    if (!response.ok) {
      log.append(messageNode("assistant", body.detail || "No pude empezar un autómata nuevo.", "error"));
      log.scrollTop = log.scrollHeight;
      return;
    }
    prompt.value = "";
    word.value = "";
    state.probes = null;
    state.testedWord = "";
    renderConversation(body);
    clearTuringPanel();
    prompt.focus();
  } catch (error) {
    log.append(messageNode("assistant", "Se cortó la conexión con el servidor.", "error"));
  } finally {
    lockInputs(false);
  }
}

async function submitPrompt() {
  const text = prompt.value.trim();
  if (!text || !state.sessionId) return;
  lockInputs(true);
  send.textContent = "Generando…";
  showLoading("Generando el autómata…");
  try {
    const response = await fetch(`/api/sessions/${state.sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const body = await readBody(response);
    if (!response.ok) {
      hideLoading();
      log.append(messageNode("assistant", body.detail || "No pude generar el autómata.", "error"));
      log.scrollTop = log.scrollHeight;
      return;
    }
    prompt.value = "";
    state.probes = null;
    renderConversation(body);
  } catch (error) {
    hideLoading();
    log.append(messageNode("assistant", "Se cortó la conexión con el servidor.", "error"));
  } finally {
    hideLoading();
    lockInputs(false);
    send.textContent = "Generar";
  }
}

async function determinizeAutomaton() {
  if (!state.sessionId || determinize.disabled) return;
  lockInputs(true);
  showLoading("Determinizando…");
  try {
    const response = await fetch(`/api/sessions/${state.sessionId}/determinize`, { method: "POST" });
    const body = await readBody(response);
    hideLoading();
    if (!response.ok) {
      log.append(messageNode("assistant", body.detail || "No pude determinizar el autómata.", "error"));
      log.scrollTop = log.scrollHeight;
      return;
    }
    renderConversation(body);
  } catch (error) {
    hideLoading();
    log.append(messageNode("assistant", "Se cortó la conexión con el servidor.", "error"));
  } finally {
    lockInputs(false);
  }
}

async function askGrammar() {
  if (!state.sessionId || grammarButton.disabled) return;
  lockInputs(true);
  showLoading("Armando la gramática…");
  try {
    const response = await fetch(`/api/sessions/${state.sessionId}/grammar`, { method: "POST" });
    const body = await readBody(response);
    hideLoading();
    if (!response.ok) {
      log.append(messageNode("assistant", body.detail || "No pude armar la gramática.", "error"));
      log.scrollTop = log.scrollHeight;
      return;
    }
    renderConversation(body);
  } catch (error) {
    hideLoading();
    log.append(messageNode("assistant", "Se cortó la conexión con el servidor.", "error"));
  } finally {
    lockInputs(false);
  }
}

async function askRegex() {
  if (!state.sessionId || regexButton.disabled) return;
  lockInputs(true);
  showLoading("Armando la expresión…");
  try {
    const response = await fetch(`/api/sessions/${state.sessionId}/regex`, { method: "POST" });
    const body = await readBody(response);
    hideLoading();
    if (!response.ok) {
      log.append(messageNode("assistant", body.detail || "No pude sacar la expresión.", "error"));
      log.scrollTop = log.scrollHeight;
      return;
    }
    renderConversation(body);
  } catch (error) {
    hideLoading();
    log.append(messageNode("assistant", "Se cortó la conexión con el servidor.", "error"));
  } finally {
    lockInputs(false);
  }
}

async function loadExample(exampleId) {
  if (!state.sessionId) return;
  const response = await fetch(`/api/sessions/${state.sessionId}/examples/${exampleId}`, { method: "POST" });
  const body = await readBody(response);
  if (!response.ok) {
    log.append(messageNode("assistant", body.detail || "No pude cargar el ejemplo.", "error"));
    return;
  }
  const listed = exampleProbes.get(exampleId);
  state.probes = Array.isArray(listed) ? listed : null;
  renderConversation(body);
  clearTuringPanel();
}

async function simulate() {
  const runButton = runner.querySelector('button[type="submit"]');
  const tested = word.value;
  state.testedWord = tested;
  stopPlayback();
  hidePlayback();
  runResult.hidden = false;
  runResult.className = "run-result pending";
  runResult.textContent = "Simulando…";
  hideRunSteps();
  clearRunMarks();
  state.lastRun = null;
  word.disabled = true;
  if (runButton) runButton.disabled = true;
  setProbesDisabled(true);
  let response;
  try {
    response = await fetch(`/api/sessions/${state.sessionId}/simulate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: tested }),
    });
  } catch (error) {
    showRunError("Se cortó la conexión con el servidor.");
    word.disabled = false;
    if (runButton) runButton.disabled = false;
    setProbesDisabled(false);
    return;
  }
  word.disabled = false;
  if (runButton) runButton.disabled = false;
  setProbesDisabled(false);
  const body = await readBody(response);
  if (!response.ok) {
    showRunError(body.detail || "No pude simular.");
    return;
  }
  state.lastRun = body;
  if (runMode() === "lenta") openPlayback(body, true);
  else {
    hidePlayback();
    applyTrace(ComgenTrace.simulationTrace(body, state.automaton));
  }
}

async function loadTuringFile(file) {
  const status = document.getElementById("turing-status");
  if (!state.sessionId) return;
  if (!file) {
    if (status) status.textContent = "Elegí un archivo .jff.";
    return;
  }
  if (status) status.textContent = "Cargando la máquina…";
  let bytes;
  try {
    bytes = await file.arrayBuffer();
  } catch (error) {
    if (status) status.textContent = "No pude leer el archivo.";
    return;
  }
  let response;
  try {
    response = await fetch(`/api/sessions/${state.sessionId}/turing`, {
      method: "POST",
      headers: { "Content-Type": "application/xml" },
      body: bytes,
    });
  } catch (error) {
    if (status) status.textContent = "Se cortó la conexión con el servidor.";
    return;
  }
  const body = await readBody(response);
  if (!response.ok) {
    if (status) status.textContent = body.detail || "No pude cargar la máquina.";
    return;
  }
  if (status) status.textContent = body.message || "Cargué la máquina de Turing.";
  const form = document.getElementById("turing-runner");
  if (form) form.hidden = false;
  state.turingRun = null;
  const result = document.getElementById("turing-result");
  if (result) {
    result.textContent = "";
    result.className = "run-result";
  }
  clearTuringSteps();
  document.getElementById("turing-word")?.focus();
}

async function simulateTuring() {
  const form = document.getElementById("turing-runner");
  const input = document.getElementById("turing-word");
  const button = form && form.querySelector('button[type="submit"]');
  const result = document.getElementById("turing-result");
  if (!state.sessionId || !input) return;
  if (result) {
    result.hidden = false;
    result.className = "run-result pending";
    result.textContent = "Simulando la máquina…";
  }
  clearTuringSteps();
  state.turingRun = null;
  input.disabled = true;
  if (button) button.disabled = true;
  let response;
  try {
    response = await fetch(`/api/sessions/${state.sessionId}/turing/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: input.value, trace: true }),
    });
  } catch (error) {
    showTuringError("Se cortó la conexión con el servidor.");
    input.disabled = false;
    if (button) button.disabled = false;
    return;
  }
  input.disabled = false;
  if (button) button.disabled = false;
  const body = await readBody(response);
  if (!response.ok) {
    showTuringError(body.detail || "No pude simular la máquina.");
    return;
  }
  state.turingRun = body;
  if (!window.ComgenCinta) {
    showTuringError("No pude armar la traza de la cinta.");
    return;
  }
  applyTuring(ComgenCinta.tapeTrace(body));
}

function showTuringError(message) {
  const result = document.getElementById("turing-result");
  if (result) {
    result.hidden = false;
    result.className = "run-result error";
    result.textContent = message;
  }
  clearTuringSteps();
  state.turingRun = null;
}

function applyTuring(trace) {
  const result = document.getElementById("turing-result");
  if (!result) return;
  result.hidden = false;
  if (!trace.ok) {
    showTuringError(trace.summary);
    return;
  }
  const kind = trace.verdict === "Acepta"
    ? "accept"
    : trace.verdict === "No terminó"
      ? "timeout"
      : trace.verdict === "Rechaza"
        ? "reject"
        : "error";
  result.className = `run-result ${kind}`;
  result.textContent = trace.summary;
  renderTuringSteps(trace);
}

function renderTuringSteps(trace) {
  const list = document.getElementById("turing-steps");
  const wrap = document.getElementById("turing-steps-wrap");
  if (!list || !wrap) return;
  document.getElementById("turing-more")?.remove();
  list.replaceChildren();
  if (!trace.steps.length) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  trace.steps.forEach((step, position) => {
    for (const notice of gapNotices(step, position, trace)) {
      list.append(el("li", { class: "run-gap" }, [notice]));
    }
    const item = el("li", {}, [`${step.index + 1}. ${step.text}`]);
    item.append(renderCinta(step));
    list.append(item);
  });
  wrap.scrollTop = wrap.scrollHeight;
  if (!trace.moreLabel) return;
  const button = el("button", { id: "turing-more", type: "button", class: "secondary" }, [trace.moreLabel]);
  button.addEventListener("click", () => {
    if (!state.turingRun || !window.ComgenCinta) return;
    const next = ComgenCinta.tapeTrace(state.turingRun, { expanded: trace.omitted > 0 });
    applyTuring(next);
    document.getElementById("turing-more")?.focus();
  });
  wrap.after(button);
}

function gapNotices(step, position, trace) {
  if (Array.isArray(step.gaps) && step.gaps.length) {
    return step.gaps.filter((item) => typeof item === "string" && item);
  }
  if (step.gapBefore) return [step.gapBefore];
  if (position === 1 && trace.gap) return [trace.gap];
  return [];
}

function renderCinta(step) {
  const row = document.createElement("div");
  row.className = "cinta";
  row.setAttribute("role", "group");
  row.setAttribute("aria-label", "Cinta");
  if (step.leading) {
    row.append(el("span", { class: "cinta-omit" }, [`${step.leading} antes`]));
  }
  for (const cell of step.cells) {
    const node = document.createElement("span");
    node.className = cell.head ? "cinta-cell is-head" : "cinta-cell";
    if (cell.blank) node.classList.add("is-blank");
    node.textContent = cell.text;
    node.setAttribute("aria-label", cell.spoken);
    if (cell.head) node.setAttribute("aria-current", "true");
    row.append(node);
  }
  if (step.trailing) {
    row.append(el("span", { class: "cinta-omit" }, [`${step.trailing} después`]));
  }
  return row;
}

function clearTuringSteps() {
  const list = document.getElementById("turing-steps");
  const wrap = document.getElementById("turing-steps-wrap");
  if (list) list.replaceChildren();
  if (wrap) wrap.hidden = true;
  document.getElementById("turing-more")?.remove();
}

function clearTuringPanel() {
  state.turingRun = null;
  const form = document.getElementById("turing-runner");
  if (form) form.hidden = true;
  const status = document.getElementById("turing-status");
  if (status) status.textContent = "";
  const input = document.getElementById("turing-word");
  if (input) {
    input.value = "";
    input.disabled = false;
  }
  const file = document.getElementById("turing-file");
  if (file) file.value = "";
  const fileName = document.getElementById("turing-file-name");
  if (fileName) fileName.textContent = "Ningún archivo elegido";
  const result = document.getElementById("turing-result");
  if (result) {
    result.textContent = "";
    result.className = "run-result";
  }
  clearTuringSteps();
}

function showRunError(message) {
  stopPlayback();
  hidePlayback();
  runResult.hidden = false;
  runResult.className = "run-result error";
  runResult.textContent = message;
  hideRunSteps();
  clearRunMarks();
  state.lastRun = null;
}

function applyTrace(trace) {
  clearRunMarks();
  runResult.hidden = false;
  if (!trace.ok) {
    showRunError(trace.summary);
    return;
  }
  runResult.className = trace.accepted ? "run-result accept" : "run-result reject";
  runResult.textContent = window.ComgenWord
    ? ComgenWord.resultWithWord(trace.summary, state.testedWord)
    : trace.summary;
  renderRunSteps(trace);
  const hint = document.getElementById("run-hint");
  const text = runHint(markRun(trace));
  if (hint) {
    hint.textContent = text;
    hint.hidden = !text;
  }
}

function renderRunSteps(trace) {
  const list = document.getElementById("run-steps");
  const wrap = document.getElementById("run-steps-wrap");
  if (!list || !wrap) return;
  document.getElementById("run-more")?.remove();
  list.replaceChildren();
  if (!trace.steps.length) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  trace.steps.forEach((step, position) => {
    if (position === 1 && trace.gap) {
      list.append(el("li", { class: "run-gap" }, [trace.gap]));
    }
    // El número va en el texto: Chrome reinicia el marcador de un <ol>
    // cuando un ancestro tiene scroll, y todos los pasos salían como 1.
    const item = el("li", {}, [`${step.index + 1}. ${step.text}`]);
    list.append(item);
  });
  wrap.scrollTop = wrap.scrollHeight;
  if (!trace.moreLabel) return;
  const button = el("button", { id: "run-more", type: "button", class: "secondary" }, [trace.moreLabel]);
  button.addEventListener("click", () => {
    if (!state.lastRun) return;
    const next = ComgenTrace.simulationTrace(state.lastRun, state.automaton, {
      expanded: trace.omitted > 0,
    });
    applyTrace(next);
    document.getElementById("run-more")?.focus();
  });
  wrap.after(button);
}

function hideRunSteps() {
  const list = document.getElementById("run-steps");
  const wrap = document.getElementById("run-steps-wrap");
  if (list) list.replaceChildren();
  if (wrap) wrap.hidden = true;
  const hint = document.getElementById("run-hint");
  if (hint) {
    hint.textContent = "";
    hint.hidden = true;
  }
  document.getElementById("run-more")?.remove();
}

function clearRunMarks() {
  for (const node of machine.querySelectorAll(".is-visited, .is-here, .is-used, .is-missing, .is-firing")) {
    node.classList.remove("is-visited", "is-here", "is-used", "is-missing", "is-firing");
  }
  for (const node of machine.querySelectorAll(".playback-dot")) node.remove();
  for (const node of machine.querySelectorAll("[aria-current]")) {
    node.removeAttribute("aria-current");
  }
}

function markRun(trace) {
  const flags = { here: false, visited: false, cells: 0, row: false, missing: false };
  const here = new Set(trace.here);
  for (const id of trace.visited) {
    if (here.has(id)) continue;
    for (const node of machine.querySelectorAll(`#diagram [data-state="${cssAttr(id)}"]`)) {
      node.classList.add("is-visited");
      flags.visited = true;
    }
  }
  for (const id of trace.here) {
    const drawn = machine.querySelector(`#diagram [data-state="${cssAttr(id)}"]`);
    if (drawn) {
      drawn.classList.add("is-here");
      flags.here = true;
    }
    const row = machine.querySelector(`#delta tr[data-state="${cssAttr(id)}"]`);
    if (row) {
      row.classList.add("is-here");
      row.querySelector("th")?.setAttribute("aria-current", "true");
      flags.row = true;
    } else if (machine.querySelector("#delta")) {
      flags.missing = true;
    }
  }
  for (const lookup of trace.lastLookups) {
    const cell = machine.querySelector(
      `#delta td[data-from="${cssAttr(lookup.from)}"][data-symbol="${cssAttr(lookup.symbol)}"]`,
    );
    if (!cell) continue;
    cell.classList.add("is-used");
    cell.setAttribute("aria-current", "true");
    flags.cells += 1;
    revealInTable(cell);
  }
  return flags;
}

function runHint(flags) {
  const parts = [];
  if (flags.here && flags.visited) {
    parts.push("En el dibujo, el borde grueso es donde terminó y el punteado es un estado por el que pasó.");
  } else if (flags.here) {
    parts.push("En el dibujo, el borde grueso es donde terminó.");
  } else if (flags.visited) {
    parts.push("En el dibujo, el borde punteado es un estado por el que pasó.");
  }
  if (flags.cells > 1) parts.push("En la tabla, los recuadros son las celdas de la última lectura.");
  else if (flags.cells === 1) parts.push("En la tabla, el recuadro es la última flecha.");
  else if (flags.row) parts.push("En la tabla, la fila remarcada es donde terminó.");
  if (flags.missing) parts.push("Ese estado no está entre las primeras filas de la tabla.");
  return parts.join(" ");
}

function runMode() {
  const picked = document.querySelector('input[name="run-mode"]:checked');
  return picked && picked.value === "lenta" ? "lenta" : "rapida";
}

function motionReduced() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function stepDelay() {
  const input = document.getElementById("play-speed");
  const raw = input ? Number(input.value) : 3;
  const index = Number.isFinite(raw) ? raw - 1 : 2;
  return SPEED_MS[index] || SPEED_MS[2];
}

function syncSpeedLabel() {
  const input = document.getElementById("play-speed");
  const out = document.getElementById("play-speed-value");
  if (!input) return;
  const label = SPEED_LABELS[Number(input.value) - 1] || "Media";
  if (out) out.textContent = label;
  input.setAttribute("aria-valuetext", label);
}

function onRunMode() {
  stopPlayback();
  if (!state.lastRun || !state.lastRun.ok) {
    hidePlayback();
    return;
  }
  if (runMode() === "lenta") openPlayback(state.lastRun, false);
  else {
    hidePlayback();
    applyTrace(ComgenTrace.simulationTrace(state.lastRun, state.automaton));
  }
}

function openPlayback(result, autoplay) {
  if (!window.ComgenPlayback) {
    showRunError("No pude armar la prueba lenta.");
    return;
  }
  const model = ComgenPlayback.playback(result, state.automaton);
  if (!model.ok) {
    showRunError(model.summary);
    return;
  }
  stopPlayback();
  playbackRun.model = model;
  playbackRun.index = 0;
  playbackRun.word = state.testedWord;
  hideRunSteps();
  runResult.hidden = true;
  runResult.textContent = "";
  runResult.className = "run-result";
  const panel = document.getElementById("playback");
  if (panel) panel.hidden = false;
  renderTape(model);
  showPlaybackFrame(0);
  if (autoplay) startPlayback();
}

function togglePlayback() {
  if (playbackRun.playing) pausePlayback();
  else startPlayback();
}

function startPlayback() {
  if (!playbackRun.model || !playbackRun.model.frames.length) return;
  const last = playbackRun.model.frames.length - 1;
  if (playbackRun.index >= last) showPlaybackFrame(0);
  playbackRun.playing = true;
  syncPlaybackControls();
  schedulePlayback();
}

function pausePlayback() {
  playbackRun.playing = false;
  clearTimeout(playbackRun.timer);
  playbackRun.timer = 0;
  syncPlaybackControls();
}

function stopPlayback() {
  pausePlayback();
  cancelPlaybackMotion();
}

function schedulePlayback() {
  clearTimeout(playbackRun.timer);
  playbackRun.timer = setTimeout(() => {
    if (!playbackRun.playing || !playbackRun.model) return;
    const last = playbackRun.model.frames.length - 1;
    if (playbackRun.index >= last) {
      pausePlayback();
      return;
    }
    showPlaybackFrame(playbackRun.index + 1);
    if (playbackRun.index >= last) pausePlayback();
    else schedulePlayback();
  }, stepDelay());
}

function stepPlayback(delta) {
  if (!playbackRun.model) return;
  pausePlayback();
  const next = playbackRun.index + delta;
  if (next < 0 || next >= playbackRun.model.frames.length) return;
  showPlaybackFrame(next);
}

function resetPlayback() {
  if (!playbackRun.model) return;
  pausePlayback();
  showPlaybackFrame(0);
}

function showPlaybackFrame(index) {
  const model = playbackRun.model;
  if (!model) return;
  const frame = model.frames[index];
  if (!frame) return;
  playbackRun.index = index;
  cancelPlaybackMotion();
  paintTape(model, frame);
  markPlayback(model, frame);
  const caption = playbackCaption(model, frame);
  const step = document.getElementById("playback-step");
  if (step) step.textContent = caption;
  setPlaybackLive(caption);
  paintVerdict(model, frame);
  if (!motionReduced() && frame.edges.length) pulseEdges(frame.edges);
  syncPlaybackControls();
}

function playbackCaption(model, frame) {
  const paso = `Paso ${frame.index + 1} de ${model.frames.length}.`;
  const text = frame.kind === "verdict" && window.ComgenWord
    ? ComgenWord.resultWithWord(frame.text, playbackRun.word)
    : frame.text;
  const note = frame.note ? ` ${frame.note}` : "";
  return `${paso} ${text}${note}`;
}

function setPlaybackLive(text) {
  const live = document.getElementById("playback-live");
  if (!live) return;
  live.textContent = runMode() === "lenta" ? text : "";
}

function paintVerdict(model, frame) {
  const banner = document.getElementById("playback-verdict");
  if (!banner) return;
  if (frame.kind !== "verdict") {
    banner.hidden = true;
    banner.textContent = "";
    banner.className = "playback-verdict";
    return;
  }
  banner.hidden = false;
  banner.textContent = model.accepted ? "Acepta" : "Rechaza";
  banner.className = model.accepted ? "playback-verdict is-accept" : "playback-verdict is-reject";
  banner.setAttribute("aria-hidden", "true");
  if (motionReduced()) return;
  banner.classList.remove("is-show");
  void banner.offsetWidth;
  banner.classList.add("is-show");
}

function renderTape(model) {
  const tape = document.getElementById("tape");
  if (!tape) return;
  tape.replaceChildren();
  if (!model.tape.length) {
    const cell = document.createElement("span");
    cell.className = "tape-cell is-blank";
    cell.textContent = "ε";
    cell.setAttribute("aria-label", "Cadena vacía");
    tape.append(cell);
    return;
  }
  model.tape.forEach((symbol, index) => {
    const cell = document.createElement("span");
    cell.className = "tape-cell";
    cell.dataset.index = String(index);
    const blank = symbol === "";
    cell.textContent = blank ? "ε" : symbol;
    cell.setAttribute(
      "aria-label",
      blank ? `Posición ${index + 1}, épsilon` : `Posición ${index + 1}, ${symbol}`,
    );
    tape.append(cell);
  });
}

function paintTape(model, frame) {
  const tape = document.getElementById("tape");
  if (!tape) return;
  if (!model.tape.length) {
    const blank = tape.querySelector(".is-blank");
    if (!blank) return;
    blank.classList.remove("is-accept", "is-reject");
    if (frame.kind === "verdict") blank.classList.add(model.accepted ? "is-accept" : "is-reject");
    return;
  }
  let current = null;
  for (const cell of tape.querySelectorAll(".tape-cell")) {
    const index = Number(cell.dataset.index);
    cell.classList.remove("is-current", "is-read", "is-stuck");
    cell.removeAttribute("aria-current");
    const stuck = model.stuckIndex === index && (frame.kind === "stuck" || frame.kind === "verdict");
    if (stuck) {
      cell.classList.add("is-stuck");
      cell.setAttribute("aria-current", "true");
      current = cell;
      continue;
    }
    if (frame.kind !== "verdict" && index === frame.tapeIndex) {
      cell.classList.add("is-current");
      cell.setAttribute("aria-current", "true");
      current = cell;
      continue;
    }
    if (index < frame.readCount) cell.classList.add("is-read");
  }
  if (current) revealTape(current);
}

function revealTape(cell) {
  const tape = cell.parentElement;
  if (!tape) return;
  const left = cell.offsetLeft;
  const right = left + cell.offsetWidth;
  if (left < tape.scrollLeft) tape.scrollLeft = Math.max(0, left - 8);
  else if (right > tape.scrollLeft + tape.clientWidth) {
    tape.scrollLeft = right - tape.clientWidth + 8;
  }
}

function markPlayback(model, frame) {
  clearRunMarks();
  const here = new Set(frame.states);
  const seen = new Set();
  for (let index = 0; index < frame.index; index += 1) {
    for (const id of model.frames[index].states) {
      if (seen.has(id) || here.has(id)) continue;
      seen.add(id);
      for (const node of machine.querySelectorAll(`#diagram [data-state="${cssAttr(id)}"]`)) {
        node.classList.add("is-visited");
      }
    }
  }
  for (const id of frame.states) {
    const drawn = machine.querySelector(`#diagram [data-state="${cssAttr(id)}"]`);
    if (drawn) drawn.classList.add("is-here");
    const row = machine.querySelector(`#delta tr[data-state="${cssAttr(id)}"]`);
    if (!row) continue;
    row.classList.add("is-here");
    row.querySelector("th")?.setAttribute("aria-current", "true");
  }
  const missing = frame.kind === "stuck" || (frame.kind === "verdict" && model.stuckIndex >= 0);
  for (const cell of frame.cells) {
    const node = machine.querySelector(
      `#delta td[data-from="${cssAttr(cell.from)}"][data-symbol="${cssAttr(cell.symbol)}"]`,
    );
    if (!node) continue;
    node.classList.add(missing ? "is-missing" : "is-used");
    node.setAttribute("aria-current", "true");
    revealInTable(node);
  }
  for (const edge of frame.edges) {
    const from = cssAttr(edge.from);
    const to = cssAttr(edge.to);
    for (const node of machine.querySelectorAll(`#diagram [data-from="${from}"][data-to="${to}"]`)) {
      node.classList.add("is-firing");
    }
  }
}

function pulseEdges(edges) {
  const svg = machine.querySelector("#diagram svg");
  if (!svg) return;
  const jobs = [];
  const seen = new Set();
  for (const edge of edges) {
    const key = `${edge.from}\0${edge.to}`;
    if (seen.has(key) || jobs.length >= 8) continue;
    seen.add(key);
    const path = svg.querySelector(
      `path.diagram-edge[data-from="${cssAttr(edge.from)}"][data-to="${cssAttr(edge.to)}"]`,
    );
    if (!path || typeof path.getTotalLength !== "function") continue;
    let len = 0;
    try {
      len = path.getTotalLength();
    } catch (error) {
      len = 0;
    }
    if (!len) continue;
    const dot = svgEl("circle", { r: "12", class: "playback-dot" });
    svg.append(dot);
    jobs.push({ path, dot, len });
  }
  if (!jobs.length) return;
  const duration = Math.max(280, Math.round(stepDelay() * 0.55));
  const token = playbackRun.motionToken + 1;
  playbackRun.motionToken = token;
  const started = performance.now();
  const tick = (now) => {
    if (playbackRun.motionToken !== token) return;
    const p = Math.min(1, (now - started) / duration);
    const eased = p < 0.5 ? 2 * p * p : 1 - ((-2 * p + 2) ** 2) / 2;
    for (const job of jobs) {
      const point = job.path.getPointAtLength(job.len * eased);
      job.dot.setAttribute("cx", String(point.x));
      job.dot.setAttribute("cy", String(point.y));
    }
    if (p < 1) playbackRun.raf = requestAnimationFrame(tick);
    else playbackRun.raf = 0;
  };
  playbackRun.raf = requestAnimationFrame(tick);
}

function cancelPlaybackMotion() {
  playbackRun.motionToken += 1;
  if (playbackRun.raf) cancelAnimationFrame(playbackRun.raf);
  playbackRun.raf = 0;
  for (const dot of machine.querySelectorAll(".playback-dot")) dot.remove();
}

function hidePlayback() {
  playbackRun.model = null;
  playbackRun.index = 0;
  const panel = document.getElementById("playback");
  if (panel) panel.hidden = true;
  const step = document.getElementById("playback-step");
  if (step) step.textContent = "";
  const banner = document.getElementById("playback-verdict");
  if (banner) {
    banner.hidden = true;
    banner.textContent = "";
    banner.className = "playback-verdict";
  }
  const tape = document.getElementById("tape");
  if (tape) tape.replaceChildren();
  setPlaybackLive("");
  syncPlaybackControls();
}

function syncPlaybackControls() {
  const model = playbackRun.model;
  const last = model ? model.frames.length - 1 : 0;
  const prev = document.getElementById("step-prev");
  const next = document.getElementById("step-next");
  const reset = document.getElementById("step-reset");
  const toggle = document.getElementById("play-toggle");
  if (prev) prev.disabled = !model || playbackRun.index <= 0;
  if (next) next.disabled = !model || playbackRun.index >= last;
  if (reset) reset.disabled = !model;
  if (!toggle) return;
  toggle.disabled = !model;
  toggle.textContent = playbackRun.playing ? "Pausa" : "Reproducir";
  toggle.setAttribute("aria-pressed", playbackRun.playing ? "true" : "false");
}

function revealInTable(cell) {
  const wrap = cell.closest(".delta-wrap");
  if (!wrap) return;
  const top = cell.offsetTop;
  const bottom = top + cell.offsetHeight;
  if (top < wrap.scrollTop) wrap.scrollTop = top;
  else if (bottom > wrap.scrollTop + wrap.clientHeight) {
    wrap.scrollTop = bottom - wrap.clientHeight;
  }
}

function cssAttr(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function renderDiagram(automaton) {
  const model = ComgenDiagram.automatonDiagram(automaton);
  const children = [el("h3", { id: "titulo-dibujo" }, ["Dibujo"])];
  if (!model.drawn) {
    children.push(el("p", { class: "diagram-note" }, [model.message]));
  } else {
    children.push(el("div", { class: "diagram-frame" }, [diagramSvg(model)]));
    children.push(el("p", { class: "diagram-legend" }, [model.legend]));
    children.push(el("p", { class: "sr" }, [model.summary]));
  }
  return el("section", {
    class: "block diagram",
    id: "diagram",
    "aria-labelledby": "titulo-dibujo",
  }, children);
}

function diagramSvg(model) {
  const svg = svgEl("svg", {
    viewBox: `0 0 ${model.width} ${model.height}`,
    focusable: "false",
    "aria-hidden": "true",
  });
  if (model.start) {
    svg.append(svgEl("path", { d: model.start.d, class: "diagram-start" }));
    svg.append(svgEl("polygon", { points: model.start.arrow, class: "diagram-start-head" }));
  }
  for (const edge of model.edges) {
    svg.append(svgEl("path", {
      d: edge.d,
      class: "diagram-edge",
      "data-from": edge.from,
      "data-to": edge.to,
    }));
    svg.append(svgEl("polygon", {
      points: edge.arrow,
      class: "diagram-arrow",
      "data-from": edge.from,
      "data-to": edge.to,
    }));
  }
  for (const node of model.nodes) svg.append(diagramNode(node));
  for (const edge of model.edges) {
    const text = svgEl("text", { x: String(edge.labelX), y: String(edge.labelY), class: "diagram-edge-label" }, edge.label);
    svg.append(text);
  }
  return svg;
}

function diagramNode(node) {
  const group = svgEl("g", { class: "diagram-state" });
  group.setAttribute("data-state", node.id);
  const title = svgEl("title", {}, node.accessibleName);
  group.append(title);
  if (node.shape === "circle") {
    group.append(svgEl("circle", {
      cx: node.x,
      cy: node.y,
      r: node.r,
      class: "diagram-node",
    }));
    if (node.final) {
      group.append(svgEl("circle", {
        cx: node.x,
        cy: node.y,
        r: node.r - 5,
        class: "diagram-ring",
      }));
    }
  } else {
    group.append(svgEl("rect", {
      x: node.x - node.w / 2,
      y: node.y - node.h / 2,
      width: node.w,
      height: node.h,
      rx: node.h / 2,
      class: "diagram-node",
    }));
    if (node.final) {
      const inset = 4;
      group.append(svgEl("rect", {
        x: node.x - node.w / 2 + inset,
        y: node.y - node.h / 2 + inset,
        width: node.w - inset * 2,
        height: node.h - inset * 2,
        rx: Math.max(0, (node.h - inset * 2) / 2),
        class: "diagram-ring",
      }));
    }
  }
  group.append(svgEl("text", { x: node.x, y: node.y, class: "diagram-state-label" }, node.label));
  return group;
}

function svgEl(tag, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (text) node.textContent = text;
  return node;
}

function renderDelta(automaton, expanded) {
  const model = ComgenDelta.transitionTable(automaton, { expanded });
  const head = el("tr", {}, [
    el("th", { class: "delta-corner", scope: "col" }, ["δ"]),
    ...model.columns.map((column) => columnHeader(column)),
  ]);
  const body = model.rows.map((row) => {
    const line = el("tr", { class: row.initial ? "is-initial" : "", "data-state": String(row.id) }, [
      rowHeader(row),
      ...row.cells.map((cell) => deltaCell(row, cell)),
    ]);
    return line;
  });
  const tableNode = el("table", {}, [
    el("caption", { class: "sr" }, [`${model.caption}. ${model.legend}`]),
    el("thead", {}, [head]),
    el("tbody", {}, body),
  ]);
  const children = [
    el("h3", { id: "titulo-transiciones" }, ["Transiciones"]),
    el("div", { class: "delta-wrap" }, [tableNode]),
  ];
  if (model.hidden) {
    children.push(el("p", { class: "delta-note", "aria-hidden": "true" }, [
      `Hay ${model.total} estados. Te muestro ${model.rows.length} para que la página siga liviana.`,
    ]));
  }
  if (model.moreLabel) {
    const button = el("button", { id: "delta-more", type: "button", class: "secondary" }, [model.moreLabel]);
    button.addEventListener("click", () => {
      const next = document.getElementById("delta");
      const opened = model.hidden > 0;
      const replacement = renderDelta(automaton, opened);
      next.replaceWith(replacement);
      document.getElementById("delta-more")?.focus();
    });
    children.push(button);
  }
  children.push(el("p", { class: "delta-legend" }, [model.legend]));
  return el("section", {
    class: "block delta",
    id: "delta",
    "aria-labelledby": "titulo-transiciones",
  }, children);
}

function columnHeader(column) {
  const cell = el("th", { scope: "col" }, [column.label]);
  if (column.epsilon) cell.setAttribute("aria-label", "épsilon");
  if (column.extra) cell.setAttribute("title", "Este símbolo no está en el alfabeto");
  return cell;
}

function rowHeader(row) {
  const cell = el("th", { scope: "row" }, [
    el("span", { class: "marks", "aria-hidden": "true" }, [row.marks || ""]),
    el("span", { class: "state-id" }, [row.id]),
  ]);
  cell.setAttribute("aria-label", row.accessibleName);
  return cell;
}

function deltaCell(row, cell) {
  const who = row.spoken || String(row.id);
  const attrs = { "data-from": String(row.id), "data-symbol": cell.symbol };
  if (cell.targets.length) return el("td", attrs, [cell.text]);
  const mark = el("span", {}, ["—"]);
  mark.setAttribute(
    "aria-label",
    cell.gap
      ? `En ${who} falta la transición con ${cell.label}`
      : `${who} no tiene flecha con ${cell.label}`,
  );
  attrs.class = cell.gap ? "gap" : "none";
  return el("td", attrs, [mark]);
}

function syncWordBox() {
  const hint = document.getElementById("word-hint");
  const alphabet = state.automaton && Array.isArray(state.automaton.alphabet)
    ? state.automaton.alphabet
    : [];
  if (hint && window.ComgenWord) {
    hint.textContent = state.automaton
      ? ComgenWord.alphabetHint(alphabet)
      : "Si dejás el campo vacío, se prueba la cadena vacía.";
  }
  if (word) {
    const sample = state.automaton && window.ComgenWord ? ComgenWord.placeholderFor(alphabet) : "";
    word.placeholder = sample || "0101";
  }
  renderProbes();
}

function renderProbes() {
  const probes = document.getElementById("probes");
  if (!probes) return;
  probes.replaceChildren();
  if (!state.automaton || !window.ComgenWord) {
    probes.hidden = true;
    return;
  }
  const alphabet = Array.isArray(state.automaton.alphabet) ? state.automaton.alphabet : [];
  const words = ComgenWord.probeWords(alphabet, state.probes);
  if (!words.length) {
    probes.hidden = true;
    return;
  }
  probes.hidden = false;
  const label = document.createElement("span");
  label.id = "probes-label";
  label.className = "probes-label";
  label.textContent = "Probá";
  const group = document.createElement("div");
  group.className = "probe-list";
  group.setAttribute("role", "group");
  group.setAttribute("aria-labelledby", "probes-label");
  for (const item of words) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = item ? "probe" : "probe is-empty";
    button.textContent = ComgenWord.probeLabel(item);
    button.setAttribute("aria-label", ComgenWord.probeSpoken(item));
    button.addEventListener("click", () => {
      word.value = item;
      simulate();
    });
    group.append(button);
  }
  probes.append(label, group);
}

function setProbesDisabled(disabled) {
  const probes = document.getElementById("probes");
  if (!probes) return;
  for (const button of probes.querySelectorAll("button")) button.disabled = disabled;
}

function renderConversation(body) {
  log.replaceChildren();
  if (body.recalled && body.recalled.length) {
    const note = messageNode(
      "assistant",
      "El modelo analiza este pedido con soluciones guardadas a la vista:\n" + body.recalled.join("\n"),
    );
    note.classList.add("recall");
    log.append(note);
  }
  if (!body.messages.length) renderEmptyLog();
  for (const item of body.messages) {
    log.append(messageNode(item.role, item.content, item.tone));
  }
  log.scrollTop = log.scrollHeight;
  renderAutomaton(body.automaton, body.warnings, body.pattern, body.grammar);
  state.automaton = body.automaton || null;
  state.exportReady = Boolean(body.export_ready);
  download.disabled = !state.exportReady;
  syncDeterminize(state.automaton);
  syncRegex(state.automaton);
  syncGrammar(state.automaton);
  remember.disabled = !body.can_remember;
  remember.textContent = body.remembered ? "En la memoria" : "Guardar en memoria";
  syncGuide(body.automaton);
  if (typeof body.memory_count === "number") renderMemoryCount(body.memory_count);
  runner.hidden = !body.automaton;
  syncWordBox();
  runResult.hidden = false;
  runResult.textContent = "";
  runResult.className = "run-result";
  stopPlayback();
  hidePlayback();
  hideRunSteps();
  state.lastRun = null;
}

function renderGrammar(grammar) {
  if (!grammar || !grammar.text) return null;
  const model = ComgenGrammar.grammarView(grammar, { limit: GRAMMAR_LINE_LIMIT });
  const list = el("ol", { class: "grammar-list" }, model.lines.map(renderProduction));
  list.setAttribute("aria-label", "Producciones");
  const children = [
    el("h3", { id: "titulo-gramatica", class: "kicker" }, ["Gramática lineal a derecha"]),
    el("p", { class: "grammar-note" }, [model.legend]),
    list,
  ];
  if (model.hidden) {
    const note = grammar.jflap
      ? `Hay ${model.hidden} variables más. La descarga trae la gramática completa.`
      : `Hay ${model.hidden} variables más.`;
    children.push(el("p", { class: "grammar-note" }, [note]));
  }
  if (grammar.jflap && state.sessionId) {
    children.push(el("a", {
      id: "grammar-download",
      class: "grammar-download",
      href: `/api/sessions/${state.sessionId}/grammar/export`,
    }, ["Descargar gramática .jff"]));
  } else if (grammar.jflap_note) {
    children.push(el("p", { class: "grammar-note" }, [grammar.jflap_note]));
  }
  return el("section", {
    class: "grammar-block",
    "aria-labelledby": "titulo-gramatica",
  }, children);
}

function renderProduction(line) {
  if (!line.ok) {
    const raw = el("li", { class: "grammar-line" }, [line.raw]);
    raw.setAttribute("aria-label", line.spoken);
    return raw;
  }
  const alternatives = [];
  for (const alt of line.alternatives) {
    if (alternatives.length) {
      alternatives.push(el("span", { class: "grammar-sep", "aria-hidden": "true" }, ["|"]));
    }
    const piece = el("span", { class: alt.empty ? "grammar-alt is-empty" : "grammar-alt" }, [alt.text]);
    if (alt.empty) piece.setAttribute("title", "Cadena vacía");
    alternatives.push(piece);
  }
  const variable = el("span", { class: "grammar-var" }, [line.variable]);
  if (line.start) variable.append(el("span", { class: "grammar-badge" }, ["inicial"]));
  const item = el("li", { class: line.start ? "grammar-line is-start" : "grammar-line" }, [
    variable,
    el("span", { class: "grammar-arrow", "aria-hidden": "true" }, ["→"]),
    el("span", { class: "grammar-alts" }, alternatives),
  ]);
  item.setAttribute("aria-label", line.spoken);
  return item;
}

function renderCard(automaton) {
  if (!window.ComgenCard) return null;
  const model = ComgenCard.automatonCard(automaton);
  if (!model.shown) return null;
  const rows = model.rows.map((item) => el("div", {
    class: "def-row",
    role: "group",
    "aria-label": item.spoken,
  }, [
    el("dt", { "aria-hidden": "true" }, [
      el("span", { class: "def-key" }, [item.key]),
      el("span", { class: "def-label" }, [item.label]),
    ]),
    el("dd", { "aria-hidden": "true" }, [item.value]),
  ]));
  const children = [
    el("h3", { id: "titulo-definicion" }, ["Definición"]),
    el("dl", { class: "def" }, rows),
  ];
  if (model.note) children.push(el("p", { class: "card-note" }, [model.note]));
  return el("section", {
    class: "block card",
    id: "definicion",
    "aria-labelledby": "titulo-definicion",
  }, children);
}

function renderAutomaton(automaton, warnings, pattern, grammar) {
  machine.replaceChildren();
  if (!automaton) {
    machine.append(el("div", { class: "empty-state" }, [
      el("p", { class: "empty-title" }, ["Sin autómata"]),
      el("p", { class: "empty" }, ["Todavía no hay un autómata. Escribí un enunciado o cargá un ejemplo."]),
    ]));
    return;
  }

  machine.append(el("div", { class: "machine-head" }, [
    el("p", { class: "machine-desc" }, [automaton.description || "Autómata finito"]),
    el("div", { class: "machine-meta" }, [kindBadgeNode(automaton)]),
  ]));
  const card = renderCard(automaton);
  if (card) machine.append(card);
  if (pattern) {
    const line = el("p", { class: "regex-line" }, [pattern]);
    line.setAttribute("aria-label", "Expresión regular");
    machine.append(el("div", { class: "regex-block" }, [
      el("p", { class: "kicker" }, ["Expresión regular"]),
      line,
    ]));
  }
  const grammarBlock = renderGrammar(grammar);
  if (grammarBlock) machine.append(grammarBlock);

  machine.append(renderDiagram(automaton));
  machine.append(renderDelta(automaton, false));

  if (warnings && warnings.length) {
    const list = el("ul", { class: "warnings" });
    for (const warning of warnings) list.append(el("li", {}, [warning]));
    machine.append(list);
  }
}

function syncGuide(automaton) {
  const node = document.getElementById("accion-guia");
  if (!node || !window.ComgenGuia) return;
  const model = ComgenGuia.actionGuide(automaton);
  node.textContent = model.text;
  node.className = `accion-guia is-${model.kind}`;
}

function kindBadgeNode(automaton) {
  const model = window.ComgenGuia
    ? ComgenGuia.kindBadge(automaton)
    : {
      kind: automaton.deterministic === true ? "afd" : automaton.deterministic === false ? "afn" : "duda",
      text: automaton.deterministic === true
        ? "AFD · determinista"
        : automaton.deterministic === false
          ? "AFN · no determinista"
          : "Autómata",
      spoken: "",
    };
  const node = el("span", { class: `badge is-${model.kind}` }, [model.text]);
  if (model.spoken) node.setAttribute("title", model.spoken);
  return node;
}

function messageNode(role, content, tone) {
  const className = tone === "error" || tone === "loading"
    ? `msg assistant ${tone}`
    : `msg ${role}`;
  const node = el("article", { class: className }, [content]);
  if (tone === "error") node.setAttribute("role", "alert");
  return node;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

async function readBody(response) {
  try {
    return await response.json();
  } catch (error) {
    return {};
  }
}
