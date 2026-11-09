# Hoja de ruta

Cada ítem de abajo entra en **una** corrida. No mezclar dos. Al cerrarlo, la suite anterior tiene que seguir verde (`make test`, sin Ollama) y el ítem nuevo tiene que tener tests propios. Los criterios de aceptación son el cierre: si no se cumplen, el ítem no está hecho.

El orden de las próximas corridas es el de «Por dónde seguir». Un ítem **Hecho** no se reabre. Lo que no está en esa lista espera.

## Ya resuelto

Quedó cubierto con tests, no hace falta reabrirlo:

- **Modelo de bajo consumo por defecto.** `gemma3:1b`, alrededor de 1B, en la configuración, `.env.example` y el README. El prompt es corto. Ollama recibe JSON estructurado, temperatura 0, `num_ctx` 4096 y `num_predict` 768. Si el modelo configurado declara más de 3B, queda un aviso en español en el log y la generación no se corta. Los tests no necesitan Ollama.
- `E+` acepta la cadena vacía cuando `E` la acepta. Antes `(a*)+` y `(c+)(c*)+` rechazaban palabras que sí están en el lenguaje.
- `extract_regex` ya no convierte una oración en español en una expresión. `¿…unos?`, `comience por a*` y `hola?` devuelven `None`. Siguen saliendo `a?`, `(a|b)* abb`, `a* | b*` y los bloques con «comience / siga / termine».
- Un enunciado que es una pregunta (`¿Cadenas binarias con cantidad par de unos?`) no descarta un AFD válido ni obliga a un segundo llamado al modelo. `a?` y un grupo con `*` sí se tratan como expresión.
- Una expresión que arma más de 512 subconjuntos corta con un error, no cuelga el proceso. `(a|b)*a` seguido de catorce veces `(a|b)` tiene que fallar en menos de dos segundos.
- `simulate` no revienta si falta el estado inicial o si hay dos: responde que tiene que haber exactamente uno.
- Si `memory/solutions.json` está dañado, `/api/memory` responde igual y guardar no pisa el archivo.
- Los tests no leen el `memory/solutions.json` del repositorio: cada uno usa un archivo propio.
- Al exportar un AFD al que le faltan flechas, el `.jff` agrega un estado pozo no final y las transiciones que faltan (hacia el pozo, y del pozo hacia sí mismo). El lenguaje no cambia. El aviso de transición faltante puede seguir en la pantalla; el archivo descargado ya es total.
- **Familias de curso en código.** Divisibilidad, resto, cantidad, longitud, termina, empieza y contiene (y su complemento, intersección o unión) se construyen y se minimizan sin Ollama. Un AFD total que manda el modelo también se minimiza antes de mostrarlo y de exportarlo.
- **Cuantificador `?` en un literal corto.** `bb?`, `01?` y «quiero un afd para bb?» se tratan como expresión. Si el modelo responde `kind: fa`, hay un segundo intento y el AFD lo arma el código. «¿Cadenas binarias con cantidad par de unos?» y «un AFD que termine en 01?» siguen siendo preguntas: un AFD válido se acepta en el primer llamado. Los tests no abren Ollama.

## Por dónde seguir

En este orden:

1. Completar el AFD con un pozo al exportar. **Hecho.**
2. Pasar de AFN (con épsilon) a AFD. **Hecho.**
3. Minimizar un AFD cualquiera. **Hecho.**
4. Sacar la expresión regular de un autómata finito. **Hecho.**
5. Gramáticas regulares, ida y vuelta con el autómata. **Hecho.**

No hay ningún ítem en curso. Lo próximo, antes que el resto de lo abierto (bugs 3 a 10, rendimiento 11 a 14, Thompson, importar un `.jff` de autómata finito, gramáticas independientes, pila y el selector de formalismo), son los ejemplos de la máquina (ítem 30). Después siguen los enunciados en español (31). Una por día. No mezclarlas. Sin frameworks ni dependencias nuevas. El modelo por defecto sigue en `gemma3:1b`.

6. Modelo de una cinta y simulación determinista, con tope de pasos y errores en español. Ítem 27. **Hecho.**
7. Exportar e importar el `.jff` de tipo `turing` de JFLAP. Ítem 28. **Hecho.**
8. Traza de la cinta, paso a paso, en la pantalla. Ítem 29. **Hecho.**
9. Ejemplos armados en código: aⁿbⁿ, incremento binario y palíndromos. Ítem 30.
10. Enunciados en español: la máquina la arma el código; el modelo chico solo saca parámetros. Ítem 31.

## Bugs y robustez

### 1. Completar el AFD con un pozo al exportar

**Hecho.** Exportar un AFD parcial agrega un estado pozo no final y las flechas que faltan. El autómata de la sesión no se toca, así el aviso puede seguir en la pantalla.

`validate_fa` deja pasar un AFD al que le faltan flechas y solo avisa («falta la transición con 1»). La simulación rechaza por ese hueco. El enunciado que le mandamos a Ollama pide un AFD total; el `.jff` descargado ahora sale total.

**Hecho cuando:**

- Exportar un AFD parcial agrega un estado pozo no final y las transiciones que faltan, hacia el pozo o de vuelta al pozo.
- El lenguaje no cambia: las cadenas que antes aceptaba siguen aceptando, y las que caían en el hueco siguen rechazando.
- El XML abre como `<type>fa</type>` y, desde cada estado, hay exactamente una transición por símbolo.
- El aviso de transición faltante puede quedar en la pantalla, pero el archivo descargado ya es total.
- Hay un test con el autómata de un solo estado que tiene `0` y no tiene `1`.

### 2. Cuantificadores `?` que todavía no se ven

**Hecho.** `_looks_like_regex_request` trata `bb?`, `01?` y «quiero un afd para bb?» como expresión. Si el modelo responde `kind: fa`, hay un segundo intento y el AFD lo arma el código. «¿Cadenas binarias con cantidad par de unos?» y «un AFD que termine en 01?» siguen siendo preguntas: un AFD válido se acepta en el primer llamado. Esas dos, además, se arman en código y no llaman al modelo.

`_looks_like_regex_request` reconocía `a?` y `)?`, pero no `bb?` ni un mensaje que es solo `01?`: el `?` quedaba pegado a más de un carácter y no había segundo intento si el modelo dibujaba las flechas.

**Hecho cuando:**

- El texto `bb?`, el texto `01?` y «quiero un afd para bb?» se tratan como expresión. Si el modelo responde `kind: fa`, hay un segundo intento.
- «¿Cadenas binarias con cantidad par de unos?» y «un AFD que termine en 01?» no. En los dos, un AFD válido se acepta en el primer llamado: el `?` de esa pregunta no es un cuantificador.
- Hay tests de esos enunciados, con el modelo mockeado.

### 3. «y» / «o» entre expresiones

`extract_regex("a* y b*")` devuelve `None`. Antes devolvía `a*yb*`, que mete la letra y en el alfabeto. Lo seguro era no adivinar; falta la unión.

**Hecho cuando:**

- `extract_regex("a* y b*")` y `extract_regex("a* o b*")` devuelven `a*|b*`.
- `extract_regex("comience por a* y siga con b*")` sigue siendo `a*b*` (la «y» de la oración no es una unión).
- Una oración sin expresión («cadenas con cantidad par de unos») sigue en `None`.

### 4. Un segundo pedido a la misma sesión no tiene que llamar otra vez al modelo

El botón de la pantalla se deshabilita, pero dos POST seguidos a `/messages` entran en fila en el lock de la sesión y los dos llaman a Ollama.

**Hecho cuando:**

- Si ya hay una generación en curso para esa sesión, el segundo POST responde 409 con un mensaje en español y el modelo se llama una sola vez.
- Otra sesión, en paralelo, puede cargar un ejemplo.
- El test usa un `chat` falso que espera una señal, no Ollama.

### 5. Tope para el JSON del modelo

No hay límite de estados ni de transiciones en lo que devuelve Ollama. Un JSON enorme pasa por Pydantic y por `validate_fa` en el request.

**Hecho cuando:**

- Por encima de un tope explícito (por ejemplo 200 estados o 2000 transiciones) `interpret_text` tira `ModelReplyError` con un texto claro, sin armar el autómata.
- Un AFD chico, como el de paridad, sigue pasando.
- El test no abre una conexión de red.

### 6. `OLLAMA_TIMEOUT` inválido tira abajo el proceso

`Settings` hace `float(...)` del entorno. Un valor como `abc` revienta el primer request. Además `get_settings` queda cacheado: un test que cambia el entorno no ve el valor nuevo si alguien ya llamó a la función.

**Hecho cuando:**

- Un timeout que no es un número usa el default de 180 y la app arranca.
- El test limpia la caché de `get_settings` y no depende del orden de la suite.

### 7. El nombre del `.jff` se come las tildes

`_filename` solo deja ASCII. «Expresión regular» baja como algo parecido a `expresin-regular.jff`.

**Hecho cuando:**

- La tilde se reemplaza por la vocal: `expresion-regular.jff`.
- `ñ` pasa a `n`.
- Un título vacío o hecho solo de símbolos sigue cayendo en `automata.jff`.
- El encabezado `Content-Disposition` no puede inyectar comillas ni saltos de línea.

### 8. La memoria pisa un lenguaje distinto

`save` reemplaza una entrada si el Jaccard de los tokens es ≥ 0.8. Dos pedidos parecidos en español, con patrones distintos, se pisan.

**Hecho cuando:**

- Guardar `a*bbb*cc*` y después un pedido con el mismo molde pero patrón `(ab|ba)*aaa*(c|bb)*` deja las dos entradas.
- Un segundo guardado del mismo patrón sí reemplaza la entrada vieja y no duplica.
- El test usa un archivo temporal.

### 9. La simulación en el navegador no atrapa un corte de red

`simulate` en `static/app.js` no tiene `catch`. Si `fetch` falla, el error se pierde.

**Hecho cuando:**

- Un fallo de red escribe un mensaje en `#run-result` y no deja la promesa rechazada.
- Se puede cubrir con un test del script o, si no hay harness de navegador, con una revisión chica y un comentario en el ítem de cómo se probó. No hace falta levantar Ollama.

### 10. Escapes en la expresión regular

`\*` se lee como «cero o más barras invertidas», no como un asterisco literal. No hace falta implementar clases ni `{n,m}` en esta corrida.

**Hecho cuando:**

- `compile_pattern(r"\*")` acepta `*` y rechaza la cadena vacía y `a`.
- `\(` y `\)` son paréntesis literales.
- `a\*` acepta solo `a*`.
- Un `\` colgando al final es un `RegexError` en español.

## Rendimiento y calidad de código

### 11. Partir `app/regex_lang.py`

El archivo junta el parser, Glushkov, el determinizado, la minimización y el texto de los estados. Ya pasa de las quinientas líneas.

**Hecho cuando:**

- El parser, la construcción del AFD y la explicación viven en módulos separados, con los mismos resultados.
- `compile_pattern` y `extract_regex` se siguen importando desde `app.regex_lang` (aunque sea un reexport).
- `make test` queda verde sin cambiar los tests de lenguaje, salvo imports rotos.

### 12. Cachear la compilación de una expresión

Cada pedido recompila desde cero. En una sesión el usuario repite el mismo patrón al simular y al exportar.

**Hecho cuando:**

- La segunda `compile_pattern` del mismo string no vuelve a construir el autómata.
- Dos patrones distintos no comparten resultado.
- El cache tiene un tope de entradas.
- Un test cuenta las llamadas al armado del AFD, no el tiempo de pared.

### 13. Dejar la suite sin el warning de Starlette

Pytest avisa que `TestClient` con `httpx` está deprecado y pide `httpx2`.

**Hecho cuando:**

- `make test` termina sin warnings.
- No se pinnea una versión rota de FastAPI para tapar el aviso: se actualiza el cliente de test o se aísla el warning con un motivo escrito al lado, si la librería todavía no ofrece reemplazo.

### 14. Contrato del JSON, con casos rotos

Hoy un JSON mal formado cae en `ModelReplyError` o en Pydantic, pero hay pocos tests de borde: `states: null`, `from` numérico, lista en vez de objeto, alfabeto con un símbolo de dos letras.

**Hecho cuando:**

- Cada uno de esos casos devuelve un error en español y no una excepción sin atrapar.
- El test cubre al menos cuatro respuestas inválidas, todas locales.

## Hacia la materia

Los algoritmos van en código. Ollama, si entra, solo redacta o elige; no decide la pertenencia ni la forma normal.

### 15. AFN con épsilon a AFD

**Hecho.** `app/determinize.py` arma el AFD por subconjuntos, con clausura épsilon, y lo deja en la sesión. El botón **Determinizar** lo pide y después se puede exportar. El ejemplo `a* con épsilon` no usa Ollama. Un AFD que ya es determinista no se reescribe. El pozo sigue entrando solo en el `.jff`.

El determinizado de una expresión sigue adentro del compilador. Esta función es la que se aplica al autómata de la sesión.

**Hecho cuando:**

- Hay una función que, dado un AFN con épsilon, devuelve un AFD.
- Un AFN que acepta `a*` por una cadena de épsilon y un lazo en `a` produce un AFD que acepta `""`, `a` y `aa`, y rechaza `b`.
- El AFD tiene un solo estado inicial, no tiene épsilon y pasa `validate_fa` sin errores.
- La pantalla puede pedir el determinizado del autómata actual y después exportarlo.
- El test no usa Ollama.

### 16. Minimizar un AFD cualquiera

**Hecho.** `app/minimize.py` minimiza un AFD total por partición. Las familias de curso ya salen mínimas, y un AFD total del modelo se minimiza antes de mostrarlo y de exportarlo. Un AFD parcial no se reescribe: el pozo sigue entrando solo en el `.jff`.

**Hecho cuando:**

- Hay una función de minimización por partición, la de la materia, sobre un AFD total.
- El AFD de paridad, que ya es mínimo, conserva dos estados y el mismo lenguaje (`""` y `11` aceptan, `1` rechaza).
- Un AFD con dos estados finales equivalentes y el mismo comportamiento en `a` y en `b` baja a un solo estado final.
- El resultado se puede mostrar y exportar.
- No hace falta, en esta corrida, reemplazar el minimizador interno de `regex_lang`.

### 17. Del autómata finito a la expresión regular

**Hecho.** `app/regex_from_fa.py` arma la expresión por eliminación de estados. El botón **Expresión** la pide y la API la devuelve en `pattern`. Un AFN responde que primero hay que determinizarlo. El autómata de la sesión no se modifica. Si el AFD es total, se minimiza una copia para achicar la expresión; el de la pantalla queda igual. Por encima de 16 estados no se arma, para no trabar la notebook.

El camino expresión → AFD ya estaba. Esta es la vuelta.

**Hecho cuando:**

- A partir de los ejemplos `paridad` y `termina-en-01` se obtiene una expresión.
- Esa expresión, compilada con `compile_pattern`, acepta y rechaza las mismas cadenas que el ejemplo en un conjunto escrito en el test (incluidas la vacía y algunas de largo 4 o 5).
- Si el autómata no es determinista, el error dice que primero hay que determinizarlo, o la función lo hace y el test lo muestra.
- La expresión aparece en la respuesta de la API.

### 18. AFN de Thompson, además del AFD

El compilador esconde el AFN con épsilon. En la materia ese AFN se dibuja.

**Hecho cuando:**

- `thompson(pattern)` arma un AFN con épsilon para `a*bbb*cc*` y `(a|b)*abb`.
- `simulate` acepta las mismas cadenas que `compile_pattern` en los tests que ya existen para esas expresiones.
- El AFN pasa `validate_fa` con `deterministic=False`.
- Se puede exportar a `.jff` y el `<read>` de una épsilon va vacío, como en el test de épsilon actual.

### 19. Importar un `.jff` de autómata finito

Hoy solo se exporta. Cerrar el círculo con JFLAP evita traducir a mano.

**Hecho cuando:**

- Exportar paridad y volver a leer ese XML devuelve los mismos estados, el mismo inicial, los mismos finales y las mismas transiciones.
- Un archivo que no es XML, o que no tiene `<type>fa</type>`, responde 400 con un mensaje en español.
- El autómata importado se puede simular en la sesión.
- El test usa el XML que genera `export_jflap`, más un XML mínimo escrito en el test.

### 20. Gramáticas regulares

**Hecho.** `app/grammar.py` arma una gramática lineal a derecha desde un AFD (`A → aB` y `A → ε`) y, al revés, un AFN. El botón **Gramática** la muestra y el `.jff` usa `<type>grammar</type>`, con la vacía en un `<right>` vacío. JFLAP toma `S` como inicial, así que el archivo solo se exporta si el inicial es `S` y cada variable es una letra mayúscula que no está en el alfabeto. Un AFN pide determinizarlo. No se minimiza y el pozo no entra: sigue solo en el `.jff` del autómata. Por encima de 1024 estados o 8192 producciones no se arma.

Lineales a derecha, como las de la materia, enlazadas con el AF.

**Hecho cuando:**

- De un AFD se obtiene una gramática lineal a derecha, y de una gramática lineal a derecha se obtiene un AFN.
- Para paridad, la gramática genera `""`, `0`, `11` y `1010`, y no genera `1` ni `10` (mirando el lenguaje del AF armado de vuelta, en cadenas hasta largo 6).
- La gramática se valida: un solo símbolo inicial, terminales y no terminales disjuntos, producciones `A → aB`, `A → a` o `A → ε` según lo que se documente en el módulo.
- Se exporta en el formato de gramática de JFLAP y un test revisa el XML.

### 21. Gramática independiente del contexto: modelo y derivación

Sin forma normal todavía. Solo el objeto, la validación y una derivación paso a paso.

**Hecho cuando:**

- Se puede cargar `{ aⁿbⁿ | n ≥ 1 }` con producciones `S → aSb | ab`.
- Una derivación más a la izquierda de `aaabbb` devuelve la lista de formas sentenciales, de `S` hasta la cadena.
- `ab`, `aabb` derivan; `aab` y la vacía no, y el resultado lo dice sin tirar una excepción.
- Una producción mal formada (lado izquierdo con dos símbolos, o un terminal que no está en el alfabeto) es un error en español.

### 22. Limpieza de una gramática independiente

Paso previo a Chomsky y Greibach. Una corrida, tres limpiezas, en este orden: épsilon, unitarias, símbolos inútiles.

**Hecho cuando:**

- Cada limpieza tiene una función y un test con una gramática chica escrita a mano.
- Después de las tres, no quedan producciones épsilon (salvo que el lenguaje tenga la vacía y se documente el caso), no quedan unitarias y todo símbolo aparece en alguna derivación de una cadena de terminales.
- El lenguaje de un ejemplo chico no cambia en las cadenas de largo ≤ 4 que el test enumera.

### 23. Forma normal de Chomsky

Depende del ítem 22.

**Hecho cuando:**

- La función recibe una gramática ya limpia, o la limpia llamando a lo del ítem 22.
- Toda producción queda `A → BC` o `A → a`.
- Para `{ aⁿbⁿ | n ≥ 1 }`, CYK acepta `ab` y `aaabbb`, y rechaza `aab` y `ba`.
- CYK vive en código, con un test de la tabla, no delegado en el modelo.

### 24. Forma normal de Greibach

Depende del ítem 23.

**Hecho cuando:**

- Toda producción queda `A → aα`, con `α` una secuencia de no terminales (posiblemente vacía).
- El ejemplo `{ aⁿbⁿ | n ≥ 1 }` sigue aceptando `aabb` y rechazando `aab` por derivación o por un reconocedor que use esa forma.
- Si la gramática de entrada no está en Chomsky, el error lo dice o la función la convierte y el test lo fija.

### 25. Autómata de pila: modelo y simulación

**Hecho cuando:**

- Hay un modelo con estados, alfabeto de entrada, alfabeto de pila, inicio, finales y transiciones `(estado, lee, desapila) → (estado, apila)`.
- La validación rechaza un AP sin estado inicial o con un símbolo que no está en el alfabeto.
- El AP de `{ aⁿbⁿ | n ≥ 1 }` acepta `ab` y `aaabbb` por estado final, y rechaza `aab` y `ba`.
- La simulación muestra los pasos: estado, lo que falta leer y el contenido de la pila.
- Hay un tope de pasos para no entrar en un lazo de épsilon.
- El test arma el AP en código, sin Ollama.

### 26. Exportar el autómata de pila a JFLAP

Depende del ítem 25.

**Hecho cuando:**

- El XML usa el tipo que JFLAP abre para un autómata de pila y guarda lectura, desapilado y apilado.
- Exportar el AP de `{ aⁿbⁿ }` y volver a leerlo recupera las transiciones.
- Si el ítem 19 todavía no existe, el lector de este ítem alcanza con el XML de autómatas de pila; no hace falta el de autómatas finitos.

Los ítems 27 a 29 están hechos. Los ítems 30 y 31 siguen en ese orden, una corrida cada uno. Van antes que lo abierto de más arriba y antes que el ítem 32. Una sola cinta, determinista. No entran en estas corridas varias cintas, el no determinismo ni un reconocedor universal. Sin frameworks ni dependencias nuevas. El modelo por defecto sigue en `gemma3:1b` y el prompt, si alguna corrida lo usa, queda corto.

### 27. Máquina de Turing: modelo y simulación de una cinta

**Hecho.** `app/turing.py` define la máquina de una cinta y la simula. Hay un solo inicial, finales, alfabeto de cinta, blanco y transiciones (estado, lee) → (estado, escribe, L|R|S). El cabezal vive en la configuración y arranca en el primer símbolo. Si falta la transición, se detiene: acepta en un estado final y rechaza si no lo es. No hay pozo. «No terminó» es el tope de 10000 pasos o el de 4096 celdas. Con los dos topes a la vez, ir solo a la derecha corta por las celdas, porque 4096 es menor que 10000; el mensaje sigue siendo «No terminó». El tope de pasos se ve con un máximo más chico. No hay `.jff`, ni pantalla, ni ejemplos, ni llamado al modelo.

Una corrida. No incluye el `.jff`, la pantalla, los ejemplos ni el enunciado en español: eso son los ítems 28 a 31. Esta corrida no llama al modelo.

**Hecho cuando:**

- Hay un modelo con estados, exactamente un estado inicial, finales, alfabeto de cinta, blanco, posición del cabezal y transiciones `(estado, lee) → (estado, escribe, L|R)`. Quedarse (`S`) puede entrar si el test lo fija.
- Dos transiciones con el mismo estado y el mismo símbolo leído son un error en español. También lo son cero iniciales, dos iniciales, un símbolo fuera del alfabeto y un movimiento que no es L, R ni el que el módulo documente.
- Una máquina chica, escrita en el test y no en la lista de ejemplos, acepta las cadenas del test y rechaza los contraejemplos. Sirve la que decide `{ aⁿbⁿ | n ≥ 1 }`, o una más chica que copie `aⁿ` o que reconozca un lenguaje finito.
- Hay un tope de pasos (por ejemplo 10000) y un tope de celdas (por ejemplo 4096). Si se agota el de pasos, la respuesta es «no terminó», no un cuelgue ni una excepción sin atrapar. Una máquina que solo se mueve a la derecha tiene que cortar por ese tope.
- Se puede pedir la corrida entera o de a un paso. Cada paso devuelve el estado, la cinta y la posición del cabezal.
- Si falta la transición del símbolo bajo el cabezal, la simulación rechaza o responde «no terminó», y el test deja escrito cuál de las dos.
- El test arma la máquina en código. `make test` no abre Ollama.

### 28. Exportar e importar la máquina de Turing a JFLAP

**Hecho.** `app/turing_jflap.py` escribe y lee el `.jff`. El XML usa `<type>turing</type>` y guarda lectura, escritura y movimiento (`L`, `R` y `S`). El blanco sale como `<read />` y `<write />` vacíos. Un comentario dice el carácter (`El blanco de Comgen es _ .`) y, al importar, la etiqueta vacía vuelve a ser ese blanco. Si el archivo no trae el comentario, el blanco es `_` cuando ese símbolo no está escrito en otra flecha. Exportar la máquina de { aⁿbⁿ | n ≥ 1 } del test del ítem 27 y volver a leerla recupera estados, inicial, finales, blanco y transiciones. Una máquina a la que le falta una transición se exporta igual, sin pozo. `POST /api/sessions/{id}/turing` carga el XML en la sesión (400 si no es XML o el tipo no es `turing`) y `POST /api/sessions/{id}/turing/run` la simula. No hay traza en la pantalla ni ejemplos nuevos. El autómata de la materia, si estaba en la sesión, sigue en su lugar.

Depende del ítem 27. Una corrida. No incluye la traza de la pantalla ni los ejemplos.

**Hecho cuando:**

- El XML usa `<type>turing</type>` y guarda lectura, escritura y movimiento (`L`, `R` y, si el modelo lo tiene, `S`).
- El blanco sale como `<read />` y `<write />` vacíos, el blanco que abre JFLAP. Al importar, esa etiqueta vacía vuelve a ser el blanco del modelo.
- Exportar la máquina del test del ítem 27 y volver a leer ese XML recupera estados, inicial, finales, blanco y transiciones.
- Un archivo que no es XML, o que no tiene `<type>turing</type>`, responde 400 con un mensaje en español.
- La máquina importada se puede simular en la sesión.
- Una máquina a la que le falta una transición se exporta igual, sin inventar un pozo. El lenguaje no se completa en el archivo.
- El test usa el XML que genera el exportador, más un XML mínimo escrito en el test. No hace falta el lector de autómatas finitos. Alcanza la biblioteca estándar: no sumes una librería de XML.

### 29. Traza de la cinta en la pantalla

**Hecho.** `static/cinta.js` arma la traza y la pantalla la muestra al simular la máquina cargada con un `.jff`. Cada paso trae la cinta, el cabezal y el estado. Si hay más de 24 pasos, se ven el arranque y el final, y un botón abre el resto. Cada cinta muestra como mucho 24 casillas alrededor del cabezal. «No terminó» y un rechazo se leen en español. Un corte de red no deja la promesa rechazada. `POST /api/sessions/{id}/turing/run` con `{"trace": true}` pide los pasos; sin eso, `steps` sigue vacío. La traza guarda como mucho 256 cintas: si la corrida es más larga, quedan el arranque y la última, y `trace_omitted` cuenta el medio que no se copió. En la vista de 24, cada hueco dice cuántos pasos faltan en ese lugar: los que no se copiaron dicen «No se guardaron» y no se cuentan en el corte de al lado. El ␣ es el blanco de la máquina (`blank` en la corrida), no siempre `_`.

Depende del ítem 27. Una corrida. Sin frameworks, sin CDN y sin fuentes descargadas. El texto sigue en español. Esta corrida no llama al modelo.

**Hecho cuando:**

- Al simular una máquina se ve la cinta, la posición del cabezal y el estado, paso a paso.
- Si hay muchos pasos, se ven el arranque y el final, y un botón abre el resto. El tope visible queda en el orden del `STEP_LIMIT` de la traza del autómata (24). No lo subas para la cinta.
- «No terminó» y un rechazo se leen en español, en `#run-result` o en el bloque de la traza, y un fallo de red no deja la promesa rechazada.
- Siguen los id `fresh`, `download`, `remember`, `determinize`, `regex` y `grammar`, el id `grammar-download` y el texto Nuevo autómata. `ROW_LIMIT` y `COL_LIMIT` siguen en 32. `STATE_LIMIT` del dibujo sigue en 16.
- El test puede ser del script, como los de la tabla y la traza: node, y si no está, se salta. No hace falta levantar Ollama.

### 30. Ejemplos de máquinas de Turing

Depende de los ítems 27 y 29. Una corrida. Las tres máquinas se arman en código, sin Ollama, y se cargan como Paridad y Termina en 01.

**Hecho cuando:**

- `{ aⁿbⁿ | n ≥ 1 }` acepta `ab`, `aabb` y `aaabbb`, y rechaza la vacía, `aab`, `ba` y `abb`.
- Incremento binario, con el bit más significativo a la izquierda y el cabezal al empezar en el primer símbolo: `1` deja `10`, `11` deja `100`, `101` deja `110` y `0` deja `1`. La cinta, sin blancos a los costados, es ese resultado, y la máquina para en un estado final.
- Palíndromos sobre `{a, b}`: aceptan la vacía, `a`, `aa`, `aba` y `abba`, y rechazan `ab` y `aab`.
- Los tres aparecen en la pantalla, se pueden simular y se pueden exportar a `.jff`.
- El modelo por defecto sigue en `gemma3:1b`. Esta corrida no lo llama. El test no abre Ollama.

### 31. Enunciados en español que arman una máquina en código

Depende del ítem 30. Una corrida. El mismo criterio que las familias de autómatas: el algoritmo vive en código. `gemma3:1b` solo entra si hace falta, y únicamente para extraer parámetros. No dibuja la máquina.

**Hecho cuando:**

- Un enunciado de una familia conocida (aⁿbⁿ, incrementar un binario, palíndromos) arma la máquina en código y no llama a Ollama.
- Si el enunciado no entra del todo y el modelo responde, el JSON trae parámetros (alfabeto, familia y, si hace falta, n). El código construye las transiciones. Una tabla de transiciones que mande el modelo no se usa.
- El prompt sigue corto, con temperatura 0. El default sigue en `gemma3:1b`. No se cambia por un modelo más grande ni se alarga el prompt.
- Un parámetro imposible (alfabeto vacío, n negativo o una familia que no existe) es un error en español.
- El test mockea el modelo. `make test` no abre Ollama. No hay frameworks ni dependencias nuevas.

### 32. Elegir el formalismo en la pantalla

Depende de que haya al menos dos modelos implementados (por ejemplo el autómata finito y el de pila). Queda después de las cinco corridas de la máquina de Turing (ítems 27 a 31): no se arranca junto con ellas. La pantalla tiene que dejar de asumir que todo es un autómata finito.

**Hecho cuando:**

- Se puede elegir autómata finito, gramática o autómata de pila antes de pedir la construcción. Lo que todavía no esté implementado figura deshabilitado, con el mismo texto de «más adelante» que ya usa el backend.
- Cargar «Paridad de unos» sigue mostrando la tabla y la descarga del `.jff`.
- En un ancho chico el selector no se sale de la pantalla.
