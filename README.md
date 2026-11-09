# Comgen

Generador de autómatas para cursar **Teoría de la Computabilidad** y **Paradigmas**. Escribís un enunciado en español («un AFD sobre {0, 1} que acepte los números binarios divisibles por 5») y Comgen arma el autómata, lo muestra, lo simula y lo exporta como archivo `.jff` para abrir en [JFLAP](https://www.jflap.org/).

Corre en tu máquina, con un modelo de lenguaje chico y local (Ollama + `gemma3:1b`, alrededor de 1B de parámetros). No usa servicios en la nube y anda en una notebook modesta.

> 📸 **[CAPTURA PENDIENTE]** Pantalla principal: enunciado, autómata dibujado y tabla δ.

## Para quién es

Para estudiantes que quieren comprobar un ejercicio, ver el autómata dibujado y bajarlo a JFLAP sin armarlo a mano, y para docentes que quieren generar ejemplos rápido.

## Qué hace

- **Del enunciado al autómata (AFD / AFN).** Muchas familias típicas de la materia se arman directamente en código, sin consultar al modelo, y salen minimizadas:
  - números en base k divisibles por n, o con resto r;
  - cantidad de un símbolo par, impar o módulo n; longitud par, impar o múltiplo de n;
  - termina en, empieza con o contiene una subcadena; el k-ésimo símbolo desde el principio o el final;
  - secuencias de bloques («infinitos 1, luego tres ceros…»);
  - complemento, intersección y unión de esas propiedades.

  Para el resto, el modelo devuelve un JSON chico que el programa valida, minimiza y contrasta antes de mostrarlo. También acepta expresiones regulares en el enunciado (`(a|b)*abb`, `bb?`).
- **Pantalla de la materia:** dibujo del autómata, tabla δ de transiciones y simulación de una cadena, con recorrido paso a paso (reproducir, anterior, siguiente).
- **Determinizar:** AFN con épsilon → AFD por subconjuntos.
- **Expresión:** AFD → expresión regular por eliminación de estados.
- **Gramática:** AFD → gramática lineal a derecha, descargable como `.jff` de gramática.
- **Exportar a JFLAP:** `.jff` de tipo `fa` (si al AFD le faltan flechas, la descarga agrega un estado pozo) y de tipo `grammar`.
- **Máquina de Turing de una cinta (determinista):** simulación con tope de pasos y de celdas, traza de la cinta en pantalla, y exportación e importación del `.jff` de tipo `turing`.
- **Memoria local:** las soluciones que marcás como buenas se guardan en `memory/solutions.json` y el modelo las ve como referencia en pedidos parecidos.
- Tres ejemplos que andan sin Ollama: *Paridad de unos*, *Termina en 01* y *a\* con épsilon*.

> 📸 **[CAPTURA PENDIENTE]** Simulación paso a paso de una cadena.
>
> 📸 **[CAPTURA PENDIENTE]** El `.jff` exportado, abierto en JFLAP.

## Requisitos

- **Python 3.10 o más.**
- **[Ollama](https://ollama.com/download)** con el modelo `gemma3:1b` (806 MB en disco; unos 1,4 GB de RAM durante la generación). Solo hace falta para generar desde texto: los ejemplos, las conversiones y los tests andan sin Ollama.
- Opcional: Node.js, para correr los tests del dibujo y de la pantalla (sin Node se saltan).

## Instalación y uso

### Windows (PowerShell)

```powershell
git clone https://github.com/Elluis1/comgen.git
cd comgen
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
ollama pull gemma3:1b
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Linux / macOS

```bash
git clone https://github.com/Elluis1/comgen.git
cd comgen
make install            # crea .venv e instala requirements.txt
ollama pull gemma3:1b
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abrí <http://127.0.0.1:8000>. `GET /api/health` dice si Ollama está en línea y si el modelo está descargado.

### Configuración (opcional)

Copiá `.env.example` a `.env` para cambiar el host de Ollama, el timeout o el modelo:

```env
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3:1b
OLLAMA_TIMEOUT=180
```

Se recomienda un modelo de alrededor de 1B. Si el nombre del modelo declara más de 3B, Comgen avisa en el log.

## API

Todo pasa por sesiones (`POST /api/sessions` devuelve el id):

| Método | Ruta | Qué hace |
| --- | --- | --- |
| `GET` | `/api/health` | Estado de Ollama y del modelo |
| `GET` | `/api/examples` | Lista de ejemplos |
| `GET` | `/api/memory` | Soluciones guardadas |
| `POST` | `/api/sessions` | Crea una sesión |
| `POST` | `/api/sessions/{id}/messages` | Envía un enunciado |
| `POST` | `/api/sessions/{id}/examples/{example_id}` | Carga un ejemplo |
| `POST` | `/api/sessions/{id}/simulate` | Simula una cadena |
| `POST` | `/api/sessions/{id}/determinize` | AFN → AFD |
| `POST` | `/api/sessions/{id}/regex` | AFD → expresión regular |
| `POST` | `/api/sessions/{id}/grammar` | AFD → gramática regular |
| `GET` | `/api/sessions/{id}/grammar/export` | `.jff` de la gramática |
| `GET` | `/api/sessions/{id}/export` | `.jff` del autómata |
| `POST` | `/api/sessions/{id}/remember` | Guarda la solución en memoria |
| `POST` | `/api/sessions/{id}/reset` | Nuevo autómata |
| `POST` | `/api/sessions/{id}/turing` | Carga una máquina de Turing (el cuerpo es el XML `.jff`) |
| `POST` | `/api/sessions/{id}/turing/run` | Simula una palabra: `{"word": "ab"}` |
| `GET` | `/api/sessions/{id}/turing/export` | `.jff` de la máquina |

Ejemplo de máquina de Turing desde Python, sin levantar el servidor:

```python
from app.turing import TuringMachine, TuringState, TuringTransition, run
from app.turing_jflap import export_turing_jflap, import_turing_jflap

machine = TuringMachine(
    states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
    tape_alphabet=["a", "_"],
    blank="_",
    transitions=[TuringTransition("q0", "a", "qf", "a", "R")],
)
print(run(machine, "a").message)                 # acepta
otra = import_turing_jflap(export_turing_jflap(machine))
```

## Tests

La suite no necesita Ollama.

```bash
make test                                   # Linux / macOS
```

```powershell
.\.venv\Scripts\python -m pytest            # Windows
```

## Estructura

```text
app/            backend FastAPI (main.py) y la lógica:
                familias.py, regex_lang.py, determinize.py, minimize.py,
                regex_from_fa.py, grammar.py, simulate.py, validate.py,
                export_jflap.py, turing.py, turing_jflap.py,
                ollama_client.py, prompts.py, memory.py, sanitize.py
static/         pantalla (HTML, CSS y JavaScript sin frameworks)
tests/          pytest (y runners de Node para la parte visual)
docs/           ROADMAP.md, PRUEBAS.md (casos adversariales), RENDIMIENTO.md (mediciones de modelos)
memory/         solutions.json, la memoria local
```

## Hoja de ruta

Lo que viene (ejemplos de Turing armados en código, enunciados en español, autómatas de pila, Chomsky y Greibach, entre otros) está en [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
