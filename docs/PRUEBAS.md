# Pruebas

Ataques que tienen que seguir cerrados. `make test` los corre sin Ollama. El detalle está en `tests/test_sanitize.py`, `tests/test_adversarial.py`, `tests/test_romper.py`, `tests/test_romper_extra.py`, `tests/test_romper_ida.py`, `tests/test_romper_corte.py` y `tests/test_romper_cinta.py`.

## XML de JFLAP

JFLAP rechazó un `.jff` con este cartel: `Could not parse XML! An invalid XML character (Unicode: 0x8) was found in the comment.`

El U+0008 (backspace) había quedado en el comentario y también en un `<read>`. XML 1.0 no admite ese carácter, ni el nulo, ni el resto de los controles C0 (salvo tab, salto de línea y retorno). El exportador los saca de todos los campos, comentario incluido, y también un `--` dentro del comentario. El test abre el archivo con Expat, que es un parser estricto.

## Salida del modelo

Enunciado de Luigi, con `gemma3:1b`, antes del arreglo de familias:

`un AFD sobre {0, 1} que acepte los números binarios divisibles por 5`

Ese enunciado ahora se arma en código: el AFD de 5 restos, sin llamar al modelo. La expresión que gemma había devuelto fue `(0|1)\` con un U+0008 adelante. Si esa salida llega igual, para este u otro pedido, no se acepta. En pantalla el alfabeto se veía `{, 0, 1, \}` (el backspace no se ve, y después está la barra) y un estado decía `Lee la .` con el mismo carácter invisible. El carácter de control se rechaza en la expresión, en un símbolo y en el nombre de un estado. En la descripción y en la explicación se borra, para que no llegue al comentario del `.jff`.

## Alfabeto del enunciado

Si el enunciado dice `sobre {0, 1}` (o `alfabeto {a, b}`), el autómata no puede usar un símbolo de más. Una barra `\`, un símbolo vacío o un invisible son respuesta inválida. El mensaje dice qué sobra y recuerda el alfabeto pedido. Un subconjunto no es un error: si la respuesta solo usa `1` y el enunciado dice `{0, 1}`, el `0` se agrega y rechaza. No se contesta que «0» no está en el alfabeto, porque el enunciado sí lo declaró. Si además sobra un símbolo, como «a», el error nombra ese sobrante y no mezcla la otra frase. Un `{5}` suelto no se toma como alfabeto.

## Expresión mal formada

Una barra invertida suelta, al final (`(0|1)\`) o en el medio (`a\b`), no se compila: este lenguaje no tiene escapes. Un paréntesis sin cerrar tampoco. El pedido se rechaza con un mensaje en español y, si el modelo contesta de nuevo, la segunda respuesta pasa por los mismos controles.

## Expresión anidada, llaves y corchetes

Más de 64 paréntesis anidados (`(` repetido y una `a` al fondo) no se compila: antes reventaba la pila de Python. Una anidación chica, de 8, sigue siendo la misma `a`. Las llaves (`a{2}`, `a{2,5}`) y los corchetes (`a[0-9]`) no son sintaxis de este lenguaje: si se aceptaran como símbolos, el autómata reconocería el texto `a{2}` y no dos aes. El detalle está en `tests/test_adversarial.py`.

## Unicode y alfabeto con acento

`e` + acento combinante (NFD) es el mismo símbolo que `é`. Entra así en la expresión, en el alfabeto que declara el enunciado y en el símbolo que manda el modelo. «Cantidad par de á» sobre `{á, é}` se arma en código con ese alfabeto: no se pliega a `{a, e}`. Una palabra de tres letras o más de la prosa («múltiplo», «número») sigue perdiendo el acento para poder leerse. Lo que está entre llaves no se pliega.

## Épsilon, ciclo y no determinismo

Un ciclo `q0 -ε→ q1 -λ→ q0` con `q1` final acepta la cadena vacía y no se cuelga. Otra rama con `a` hacia un estado que no es final no tapa a la rama que sí acepta: «a» entra y «aa» no, si la segunda flecha cae fuera. El `.jff` de ese AFN abre con Expat.

## JSON del modelo y de Ollama

Un entero de miles de dígitos en el JSON no es un `JSONDecodeError`: `json.loads` tira `ValueError` y antes eso era un 500. Ahora es un error en español. Un módulo legal pero enorme (80 nueves) se rechaza con el tope 128 y el número se muestra cortado, para no llenar el contexto de `gemma3:1b`. Si Ollama contesta HTML, una lista o un mensaje que no es un objeto, el cliente lo dice en español y `/api/health` sigue en 200 con `online: false`. No hace falta tener Ollama para eso.

## Memoria compartida

`solutions.json` puede ser JSON válido y estar igual de dañado: `tokens` en null, un `explanation` que es un número, `solutions` que no es una lista, UTF-16, un directorio con ese nombre o un archivo de más de 2 MB. Buscar devuelve vacío. Guardar responde que está dañada, o que es demasiado grande, y no pisa el archivo. Un BOM de UTF-8 (Bloc de notas) sí se lee. Doce guardados a la vez dejan un JSON válido.

## API y sesiones a la vez

Un `text` que es una lista, un enunciado en blanco y una sesión que no existe no tiran 500. El nombre del `.jff` no mete un salto de línea ni una comilla en `Content-Disposition`. Simular, exportar, guardar y cambiar de ejemplo mientras llega otro enunciado no revienta la sesión: si en ese instante no hay autómata, la respuesta es el error de siempre, no una excepción. El JSON que ve el cliente es una copia del historial, no la lista viva.

## Épsilon con otro glifo

La épsilon lunada (`ϵ`) ya se plegaba: su casefold es `ε`. No pasaba lo mismo con la épsilon matemática en negrita (U+1D6C6) ni con la épsilon acentuada (`έ`, o `ε` + acento combinante). El modelo las mandaba como símbolo y la validación decía que no estaban en el alfabeto, así que el cierre por épsilon no corría. Ahora cuentan como épsilon. La cadena vacía se acepta si el ciclo llega a un final, y el `.jff` no se queda con ese glifo.

No se pliegan letras que solo se parecen: la e abierta latina `ɛ` y la ucraniana `є` siguen siendo símbolos. Si el modelo las usa queriendo decir épsilon, hoy no cierran.

## La misma letra en dos formas

`e` + acento combinante es `é` también al simular. Antes la palabra se miraba code point por code point y «éé» escrito en NFD se rechazaba con «e» no está en el alfabeto. El nombre de un estado pasa por el mismo pliegue: una flecha desde `é` llega al estado guardado como `e` + acento. Si los dos nombres quedan iguales, el error es el de siempre, dos estados con el mismo nombre.

## Homoglifos, el punto y «él»

`а` cirílica y `a` latina son dos símbolos. «Cantidad par de а» sobre `{а, a}` se arma en código: `а` rechaza, `a` acepta (cero es par). Al revés, «par de a» rechaza `a` y acepta `а`. «él» no se pliega a «el»: sigue siendo prosa de dos letras y no arma la familia. El punto de `a.b` y de `.*` es un símbolo literal: `.*` acepta `...` y rechaza `a`. `(a+)+` y `(a+)+b` contra una tira larga de aes terminan al instante; este compilador no hace backtracking.

## Subconjuntos, pozo e índice

Un ciclo `q0 -ε→ q1 -λ→ q2 -ϵ→ q0`, con `q2` final, acepta la vacía. `b`, que no tiene flecha, rechaza: el subconjunto vacío no se agrega como estado y no es final. El `.jff` pone el pozo. Si `pozo` y `pozo2` ya existen, el hueco se llama `pozo3` y tampoco es final. Ocho determinizados a la vez sobre la misma sesión dejan un solo AFD, con «(determinizado)» una vez, y el lenguaje de `a*` sigue. Un estado cuyo nombre ya trae llaves (`{q0}`, `{q0,q1}`) no choca con el nombre del subconjunto: los id quedan únicos y el XML abre con Expat.

El índice de alcanzables no se queda con la última flecha del estado. `q29`, que se alcanza por una `b` anterior al bucle, y `meta`, que solo se alcanza por épsilon, no salen en el aviso. El texto sigue siendo «Hay estados inalcanzables: lejos.».

## Tabla δ

Una transición o una fila `null` no tira la tabla. Un nulo dentro del nombre no mezcla dos celdas: `q0` leyendo `a`+nulo+`b` no es `q0`+nulo+`a` leyendo `b`. El nombre `{q0,q1}` es una sola llegada, aunque lleve una coma.

## JSON anidado, sesiones y el prompt

Diez mil corchetes anidados no son un 500: `json.loads` tira `RecursionError` y la respuesta dice, en español, que está anidada demasiado. Lo mismo si el cuerpo HTTP de Ollama no se puede leer; `/api/health` sigue en 200 con `online: false`. Un JSON cortado a la mitad sigue siendo «no es JSON válido».

Cada `POST /api/sessions` se guardaba para siempre. Ahora hay tope de 128. Primero se borran las vacías; la que tiene el autómata de paridad sobrevive a ocho altas y la primera de esas altas responde 404. Un enunciado que dice «ignorá las instrucciones» y se hace pasar por `role: system` queda en el turno del usuario. El sistema sigue siendo el prompt corto.

Un `word` numérico, un cuerpo `null` y un enunciado de 5000 caracteres no tiran 500. `solutions.json` truncado, o con `solutions: null`, no se pisa. Si el archivo no está, guardarlo lo crea.

## Marca combinante y NFC

Un acento suelto (U+0301) puede ser un símbolo del alfabeto. Antes, simular `a` + ese acento normalizaba toda la palabra y la volvía `á`, que no estaba en el alfabeto: la cadena se rechazaba aunque las dos flechas existieran. Ahora la marca que está en el alfabeto no se funde con la letra de atrás. Si la marca no es un símbolo, `e` + acento sigue siendo `é`. La `á` ya compuesta no se parte en dos símbolos.

## Estrellas que el compilador pliega

`∗` (U+2217) y `⋆` (U+22C6) no están en el alfabeto de operadores, pero al compilar se vuelven `*`. La expresión `b∗` salía de un AFD que acepta «b» seguido de esa estrella y, compilada, era `b*`: aceptaba la vacía y cualquier tira de bes. `a∗*` ni siquiera compilaba. Esas dos, y también `* | ( + ? ) [ ] { } \`, se rechazan en español. La estrella de ancho completo `＊` no se pliega y la expresión es ese símbolo. `ɛ` y `є` siguen siendo letras: la vacía se rechaza y la expresión es el carácter.

Un espacio en la transición se iba en el `strip` y volvía como épsilon. Ahora se dice que hay un espacio, y un símbolo que es un solo blanco no se convierte en épsilon. Un control (U+0008, ancho cero) sigue sin entrar en la expresión.

## Expresión, pozo y ciclo de épsilon

Un AFD de 16 estados se convierte: una cadena de `a` da quince aes, y dieciséis copias de `a*` dan `a*`. Con 17 estados se niega al tope, enseguida. El pozo no entra en la sesión. Un AFD parcial (tiene `0` y no tiene `1`) sigue rechazando el `1`; el `.jff` agrega el pozo y la pantalla no. Ocho `POST /regex` a la vez dejan el mismo autómata y la misma expresión, sin Ollama.

Un ciclo `q0 -ε→ q1 -λ→ q2 -ϵ→ q0`, distinto del ejemplo `a*`, pide determinizar. Después, `c*` acepta la vacía y las ces, y `b` rechaza. El subconjunto vacío no es un estado. Solo la cadena vacía, aunque haya un camino muerto con `a`, no tiene expresión en este dialecto.

Justo 512 subconjuntos (el noveno símbolo desde el final es 1) entran y reconocen el lenguaje. El que sigue se niega. El tope no se subió. 399 aes seguidas quedan en 401 estados: 398 y 400 rechazan, 399 acepta. No se fusionaron de más.

## Tabla, dibujo, sesiones y memoria

Una llegada que se llama `q0, q1` no se ve como dos destinos. `{q0,q1}` sigue siendo una sola celda, porque la coma va pegada. Un `0` numérico no es épsilon: ni en la tabla ni en el dibujo se mezcla con la flecha vacía. `COL_LIMIT` en `static/delta.js` es 32. Cuatro mil columnas muestran 32, y la de épsilon se queda. `ROW_LIMIT` sigue en 32 y `STATE_LIMIT` del dibujo sigue en 16.

Si las sesiones del tope tienen autómata, se cae la más vieja. El 404 dice que hay que recargar. La más nueva se queda. El tope sigue en 128.

`solutions.json` con diez mil corchetes anidados era un 500: `json.loads` tira `RecursionError`. Ahora está dañada, no se pisa, y `/api/memory` sigue en 200. Un JSON de Ollama con `NaN` y tipos cruzados no es un 500: dice, en español, que no pudo armar el autómata.

## Ida y vuelta del .jff

Un AFD con emoji, comillas, `&`, `<` y un nombre `{q0,q1}` se exporta, Expat lo abre y el lenguaje de la vuelta coincide. El comentario aguanta `-->`, un RTL y un emoji. `Content-Disposition` no mete un salto de línea ni una comilla de más. Un carácter que XML 1.0 no admite se sigue sacando del archivo, como ya pedía el test del backspace: si el símbolo era solo ese control, el `<read>` queda vacío.

## Jamo

ᄀ + ᅡ (U+1100 y U+1161) es 가 si se normaliza la palabra entera. Si esas piezas están en el alfabeto, la simulación se las comía y decía que 가 no está. Ahora cada pieza que el alfabeto nombra queda sola: la cadena de las dos acepta y la sílaba ya armada sigue siendo otro símbolo, igual que la á compuesta no se parte. Si las piezas no están y la sílaba sí, ᄀ + ᅡ sigue siendo 가, como «e» + acento es «é». ᄀ + ᅡ + ᆨ es 각 cuando el alfabeto tiene la sílaba, y son tres símbolos cuando tiene las tres piezas. Una palabra puede mezclar las dos reglas: «e» + acento se vuelve «é» y, en la misma cadena, los jamo del alfabeto no se juntan.

El jamo de compatibilidad (ㄱ + ㅏ) no se compone. No hay que plegarlo.

## Expresión que junta símbolos

El compilador normaliza la expresión entera. Un AFD con «e» y el acento por separado, o con ᄀ y ᅡ, armaba una expresión que al compilarse era otro lenguaje. Ahora se niega, en español, y el autómata de la sesión no cambia. Si los dos jamo solo están en una unión, la expresión sale y el lenguaje coincide: 가 no aparece en el patrón. El dialecto sigue sin escapes. `MAX_STATES` sigue en 16.

## Gramática que se lee mal

Un terminal `|` se pegaba a la variable: `S → |S | aS | ε` parece una alternativa vacía. Un espacio desaparecía, una flecha `→` se confundía con la de la producción y un acento se pegaba a la letra de atrás. Ahora van entre comillas latinas (`«|»`, `« »`, `«→»`) y el texto de paridad sigue siendo `S → 0S | 1A | ε`. El AFN y el `.jff` guardan el símbolo de verdad: el `<right>` sigue teniendo `|S`. El pozo no entra en la gramática ni en la sesión.

`A → a`, `A → aB` y `A → ε` juntas arman un AFN: acepta la vacía, `a` y `ab`, y rechaza `b` y `aa`. No es determinista. El estado nuevo se llama `qf` y es final.

«é» y «e» + acento son el mismo no terminal. Si los dos están en la lista, el error es el de siempre, dos con el mismo nombre, y no se arma el AFN: antes la simulación los fundía y un final se contagiaba. Si la variable está en NFC y el lado derecho en NFD, es la misma. Un terminal escrito en NFD sale como «é» en el AFN y en el `.jff`, un solo carácter. JFLAP sigue sin abrir una variable que no sea una mayúscula ASCII: un no terminal jamo se niega en el archivo y el AFN igual existe. ᄀ pegado a ᅡ no se muestra como 가.

## Dibujo, tabla y el cero

El resumen del dibujo decía «va a q0, q1» cuando ese era el nombre de un solo estado. Ahora el nombre va entre comillas latinas, y lo mismo con «q0 y q1». `{q0,q1}` no las lleva: la coma va pegada. El nombre para el lector de pantalla usa las mismas comillas. En la tabla, `spoken` es el nombre entre comillas y `accessibleName` también; la celda ya no partía ese nombre. El 0 numérico es el estado «0», en el dibujo y en la tabla. No se suma al «0» escrito como texto y la épsilon sigue en otra flecha.

## Secuencia de bloques

«infinitos 1, 3 0, infinitos 1 y un 0» sobre {0, 1} es el lenguaje 1*0001*0. El 3 no está en el alfabeto: es la cantidad, no un símbolo. Lo mismo con «tres 0», «tres ceros», «dos unos», «un 0» y «una a» cuando el enunciado es esa secuencia. «infinitos», «cualquier cantidad» y «cero o más» son la estrella. «uno o más» es XX*. El AFD lo arma el código, sin Ollama.

«termina con un 0» acepta 10, 00 y 0: es (0|1)*0, no la cadena «0». «empieza con un 0» es 0(0|1)*. «empiezan con un 0 o terminan con un 1» es la unión. «contiene un 0» y «empieza con un 0 y longitud par» siguen como antes. Ahí «un 0» se vuelve «0» y «tres ceros» se vuelve «000» antes de esas familias. La secuencia solo entra si hay «continúa», «sigue» o «luego», o una lista de bloques con estrella. Si no cierra, sigue el camino viejo.

Sobre {0, 1, 2, 3} el «3 0» es ambiguo, porque el 3 sí es un símbolo. La respuesta lo dice y pide «tres ceros». «tres ceros» y «3 ceros», en ese alfabeto, siguen siendo tres ceros. «par de 3» sigue contando el símbolo 3.

## Secuencia, ordinal y el signo de pregunta

Veinte «uno o más» del mismo símbolo no vuelven. Antes el control probaba cada reparto y un enunciado corto no terminaba. Ahora cada bloque mira el tramo una vez. Dieciséis «uno o más 0» sobre {0, 1} aceptan dieciséis ceros y cuarenta, y rechazan quince, la vacía y un 1 en cualquier punta. El tope de bloques sigue en 24.

«el 2° símbolo es 1» y «el 2 ° símbolo desde el final» se arman en código. También «2º» y «2ª», aunque el alfabeto esté declarado: el signo ordinal no es un símbolo repetido. «el 0° símbolo» dice que la posición tiene que ser mayor que 0. «el 13° símbolo desde el final» nombra el tope 12. Ninguno llama al modelo.

Un acento pegado al `?`, o el `？` de ancho completo, no convierte la pregunta en expresión. «termine en 01?» con esa marca sigue terminando en 01. «cantidad par de unos» con el acento antes del `?` sigue siendo la paridad. `０１?` y `01？` sí son la expresión `01?`: si el modelo dibuja flechas, hay un segundo llamado. La estrella `＊` no se pliega.

Un ancho cero o un RTL entre `0` y `1` no acorta la palabra: «termina con 01» sigue aceptando `101` y rechazando `10`. «-3 ceros» no es tres ceros. Un módulo de miles de dígitos, o un `repeat` que es el texto de cinco mil nueves, responde en español y no tira el `ValueError` de `int()`. Un `true` en `repeat` no es el número 1. Un sustituto suelto en el enunciado no revienta la sesión.

En la gramática de la pantalla, `«A → B» → aS | ε` es una sola variable. La flecha de adentro de las comillas no parte la producción. El `0` sigue sin ser ε.

## Cinta, sesión que desaparece, dígitos y la marca

La entrada de la máquina de Turing se parte como la cadena del autómata. «e» + acento al lado de ᄀ y ᅡ, con «é» y esos jamo en el alfabeto, acepta y la cinta empieza en «é», ᄀ, ᅡ. Antes decía que «e» no estaba. ᄀ + ᅡ + ᆨ con la sílaba y el ᆨ en el alfabeto queda en la sílaba y el ᆨ. La sílaba ya compuesta no se parte aunque el alfabeto tenga las piezas. Una cinta de afuera con «e» y el acento en dos celdas no se junta en «é». Si el blanco es «é», «e» + acento en la entrada se niega: es el blanco. Ir a la izquierda con la cinta ya en el tope de celdas dice «No terminó» y no agranda la cinta. Un final sin flecha, en esa misma cinta, acepta.

Si la sesión se borra entre el alta y el candado, simular, la expresión, la gramática, determinizar, reiniciar, guardar, el mensaje, la descarga del autómata y la de la gramática responden 404 y piden recargar. No es un 500. El tope sigue en 128.

`٢` (arábigo-índico) no es el módulo 2, ni la posición 2, ni «dos ceros». «infinitos 1, ٢ 0 y un 0» no arma 1*00: dice, en español, que no entiende ese número. `３` de ancho completo sigue siendo 3. Dentro de `{٢, 0}` el `٢` queda como símbolo. Un `repeat` que es `٢` no es el número 2.

En el recorrido, en la prueba lenta, en el alfabeto de la prueba y en la tabla, una marca combinante va entre comillas latinas. «Lee ́» ya no se lee como «Leé». El `0` sigue siendo el símbolo 0, en el texto, en la columna y en el dibujo. El nombre del estado que es la marca también va entre comillas en el resumen del dibujo.

## Para la próxima

Esta corrida no las probó, o las dejó a propósito. La que sigue arranca por acá.

- No hay botón para abrir el resto de las columnas. Con más de 32 símbolos, la tabla muestra el corte y la épsilon, y no dibuja las otras. `COL_LIMIT` no se sube.
- Un símbolo que es solo un control sigue saliendo como `<read>` vacío en el `.jff`, para que JFLAP abra el archivo. El lenguaje del archivo cambia. El test de Expat lo pide así.
- La sílaba ya compuesta no se parte en jamo aunque el alfabeto tenga las piezas. Es la misma regla que la á. No partirla. Hoy se volvió a mirar en la cinta y sigue así.
- Dos `POST /messages` a la vez sobre la misma sesión siguen llamando los dos al modelo. El 409 es el ítem 4 de la hoja: no adelantarlo. El 404 de una sesión que ya no está es otra cosa: esa ya responde en español.
- La máquina de Turing no está en la pantalla ni se baja como `.jff`. El tope de pasos sigue en 10000 y el de celdas en 4096. No correr `trace=True` hasta las 4096 celdas: copia la cinta en cada paso.
- El casillero de la cinta en la prueba lenta sigue mostrando la marca sola. La frase («Lee …») ya la entrecomilla. No hace falta un control nuevo.
- Medir 512 subconjuntos en una notebook chica de verdad. Acá el tope se respetó y no se subió.
