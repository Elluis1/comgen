# Rendimiento

Medición del 14 de octubre de 2026, con Ollama 0.40.4, en una VM Linux de 4 CPU Intel Xeon (KVM) y sin GPU. Ollama eligió el backend de CPU. Los números de RAM son del proceso de Ollama durante la generación, con `num_ctx` 4096, no de toda la máquina.

## Modelos en la biblioteca oficial

Nombres y tamaños publicados en ollama.com, y los que bajó `ollama pull` en esta máquina:

| Modelo | Parámetros (Ollama) | Cuantización | Disco | Contexto del Modelfile |
| --- | --- | --- | --- | --- |
| `qwen2.5:0.5b` | 494.03M | Q4_K_M | 397 MB | 32K |
| `gemma3:1b` | 999.89M | Q4_K_M | 806 MB | 32K |
| `llama3.2:1b` | 1.2B | Q8_0 | 1.3 GB | 128K |
| `qwen2.5:1.5b` | 1.5B | Q4_K_M | 986 MB | 32K |

En ollama.com, el mismo día: `qwen2.5:0.5b` 398 MB, `gemma3:1b` 806 MB, `llama3.2:1b` 1.3 GB y `qwen2.5:1.5b` 986 MB. Qwen2.5 lista español entre más de 29 idiomas. Llama 3.2 declara español entre sus idiomas oficiales. Gemma 3 declara más de 140 idiomas. `qwen2.5:7b` (4.7 GB en la biblioteca) no se midió: el default tiene que quedar en alrededor de 1B o menos.

## Cómo se midió

El pipeline que queda en el programa: esquema JSON (si Ollama lo rechaza o vuelve vacío, se reintenta con `format: json`), temperatura 0, `num_ctx` 4096, `num_predict` 768 y el reintento de `repair_prompt` si la validación falla. El timeout de cada pedido en esta corrida fue 120 s. El de la aplicación sigue en 180 s.

Un acierto es un autómata exportable que acepta y rechaza estas cadenas:

| Id | Enunciado | Acepta | Rechaza |
| --- | --- | --- | --- |
| paridad | cadenas binarias con cantidad par de unos | vacío, `0`, `00`, `11`, `1010` | `1`, `10`, `111`, `01` |
| termina-01 | un AFD para cadenas binarias que terminan en 01 | `01`, `001`, `101`, `0001` | vacío, `0`, `1`, `10`, `010`, `011` |
| termina-ab | un AFD sobre {a, b} que acepte cadenas que terminan en ab | `ab`, `aab`, `bab`, `abab` | vacío, `a`, `b`, `ba`, `aa`, `abb` |
| regex-caa | quiero un afd que comience por c siga por aa* y luego termine con b* | `ca`, `caa`, `cab`, `caabb` | vacío, `c`, `a`, `cb`, `b` |
| regex-bloques | un AFD que comience por a* siga con bbb* y termine con cc* | `bbc`, `abbc`, `bbbcc`, `aaabbbccc` | vacío, `bc`, `bb`, `c`, `ac` |

La primera llamada de cada modelo solo carga el modelo y no entra en el puntaje.

## Resultados

| Modelo | Aciertos | Carga | Suma de los 5 pedidos | RAM del proceso | Tamaño en `/api/ps` |
| --- | --- | --- | --- | --- | --- |
| `gemma3:1b` | 2/5 | 6,6 s | 23,5 s | 1404 MiB | 1187 MiB |
| `qwen2.5:1.5b` | 2/5 | 7,4 s | 37,6 s | 1447 MiB | 1318 MiB |
| `qwen2.5:0.5b` | 1/5 | 3,9 s | 60,3 s | 798 MiB | 619 MiB |
| `llama3.2:1b` | 1/5 | 9,2 s | 65,1 s | 2101 MiB | 1866 MiB |

Detalle de `gemma3:1b`, el default:

| Enunciado | Resultado | Tiempo | Llamados |
| --- | --- | --- | --- |
| paridad | acierto | 4,3 s | 1 |
| termina-01 | falló el lenguaje | 2,3 s | 1 |
| termina-ab | falló el lenguaje | 1,8 s | 1 |
| regex-caa | acierto, con reparación | 9,7 s | 2 |
| regex-bloques | falló el lenguaje (aceptó `bb`) | 5,4 s | 1 |

`qwen2.5:0.5b` acertó solo `regex-caa` (1,1 s). En paridad y en `regex-bloques` no cerró el JSON: el tope de 768 tokens cortó la respuesta y el reintento tampoco sirvió (26,6 s y 27,8 s). `llama3.2:1b` acertó solo `regex-bloques` y en `termina-ab` también dejó el JSON a la mitad (46,8 s). `qwen2.5:1.5b` acertó paridad (10,3 s) y `regex-caa` (3,8 s), el mismo 2/5 que Gemma, con más latencia.

Ningún modelo de alrededor de 1B armó bien «termina en 01» ni «termina en ab». El JSON de Gemma, en esos dos, sí se pudo validar: el error fue el lenguaje, no el formato.

## Elección

El default es `gemma3:1b`. Tiene 999.89M de parámetros, cuantización Q4_K_M, 806 MB en disco y 1404 MiB de RAM del proceso con este contexto. En el grupo de alrededor de 1B fue el de más aciertos (2/5), con JSON válido en los cinco enunciados y la suma de tiempos más baja. `qwen2.5:0.5b` ocupó 798 MiB y acertó 1/5. `llama3.2:1b` acertó 1/5 y ocupó 2101 MiB: el tag oficial viene en Q8_0. `qwen2.5:1.5b` también acertó 2/5; queda fuera del default porque pasa el tope de alrededor de 1B.

## Minimización, 14 de octubre de 2026

Área de esta corrida: el tiempo de CPU de minimizar un AFD total. El default sigue en `gemma3:1b`. No se midió Ollama.

### Entorno

VM Linux 6.12, Python 3.12.3, 4 CPU Intel Xeon (KVM), sin GPU. Un solo hilo. `time.process_time` coincidió con `time.perf_counter` (el proceso no esperaba red ni disco). El antes es una corrida. El después de la tabla es la mediana de tres, sin `tracemalloc`. El pico de RAM es de `tracemalloc` durante la llamada, no de toda la máquina.

El algoritmo de antes recorría todos los estados en cada vuelta de la partición. Con miles de estados eso es del orden de n² y una intersección legal de las familias (el tope de producto es 4096) dejaba la notebook varios minutos. El de ahora parte la misma partición, pero solo vuelve a mirar el bloque que se separó.

### Antes y después

| Caso | Estados | Antes | Después | Pico de RAM |
| --- | --- | --- | --- | --- |
| AFD distinguible, solo `minimize_dfa` | 200 | 266 ms | 0,63 ms | 157 KiB → 150 KiB |
| AFD distinguible, solo `minimize_dfa` | 1000 | 7,0 s | 6,0 ms | 757 KiB → 633 KiB |
| AFD distinguible, solo `minimize_dfa` | 4000 | 113,5 s | 85 ms | 3,1 MiB → 2,7 MiB |
| «longitud múltiplo de 30 y de 29» sobre {a, b} | 870 | 1,07 s | 0,055 s | — |
| «longitud múltiplo de 48 y de 47» sobre {0, 1} | 2256 | 7,73 s | 0,26 s | — |
| «longitud múltiplo de 64 y de 63» sobre {0, 1} | 4032 | 254,6 s | 0,84 s | 13,5 MiB → 13,2 MiB |

El caso de 4032 estados es el más grande que las familias pueden armar (64 × 63, justo debajo del tope de 4096). El lenguaje no cambió: sigue habiendo 4032 estados, la cadena vacía se acepta y 48 ceros se rechazan. Repetir el después de 4000 y de 4032 con `tracemalloc` activado dio 191 ms y 1,59 s. La memoria queda igual; lo que bajó es el CPU.

### Topes

Siguen y quedaron dichos en el mensaje, en español:

- Construcción de subconjuntos de una expresión: 512. Si pasa, «demasiados estados (más de 512)».
- Simulación: más de 500 símbolos, o más de 8192 estados.
- Minimización: más de 8192 estados. El producto de las familias entra; un autómata más grande corta antes de la partición.
- JSON del modelo, cuando de verdad trae un autómata: 200 estados o 2000 transiciones. Se rechaza antes de armarlo.
- Máquina de Turing: todavía no está en el código. El tope de pasos queda para cuando exista.

### Contexto del modelo chico

`gemma3:1b`, temperatura 0, `num_ctx` 4096 y `num_predict` 768 no se tocaron. Con 10 vueltas guardadas en la sesión, el texto que se manda al modelo pasó de 8786 a 5112 caracteres si el autómata era el de paridad, y de 39919 a 18197 si tenía 25 estados. Se mandan las últimas 8 mensajes y el JSON del autómata actual va en una sola línea. Si la respuesta fallida supera 4000 caracteres, el reintento la corta: en un ejemplo de 19535 caracteres quedaron 4076. El prompt del sistema no se alargó.

## Alcanzables, 15 de octubre de 2026

Área de esta corrida: el tiempo de CPU de `validate_fa` cuando el autómata ya es válido. El default sigue en `gemma3:1b`. No se midió Ollama. La minimización de la corrida anterior no se tocó.

### Entorno

La misma VM Linux 6.12, Python 3.12.3, 4 CPU Intel Xeon (KVM), sin GPU, un solo hilo. `time.process_time` coincidió con `time.perf_counter`. El antes y el después son la mediana de cinco llamadas para la validación sola, y de tres para la familia y la descarga. El pico de RAM es de `tracemalloc` durante la llamada, no de toda la máquina.

`validate_fa` busca estados inalcanzables para avisar. Antes, cada estado volvía a mirar la lista entera de flechas. En un AFD total eso es del orden de estados × transiciones, y la función corre en cada respuesta de la sesión y otra vez al armar el `.jff`. Ahora las flechas se indexan una vez por estado de origen y el recorrido es el del grafo.

El aviso no cambió. Un estado `lejos` sin flechas sigue diciendo «Hay estados inalcanzables: lejos.».

### Antes y después

| Caso | Estados | Antes | Después | Pico de RAM |
| --- | --- | --- | --- | --- |
| AFD total, solo `validate_fa` | 200 | 1,4 ms | 0,21 ms | — |
| AFD total, solo `validate_fa` | 1000 | 28,4 ms | 1,2 ms | — |
| AFD total, solo `validate_fa` | 4000 | 488 ms | 5,5 ms | 2,0 MiB → 2,3 MiB |
| «longitud múltiplo de 64 y de 63» sobre {0, 1}, solo `validate_fa` | 4032 | 599 ms | 6,6 ms | 1,9 MiB → 2,3 MiB |
| El mismo AFD, `export_jflap` | 4032 | 655 ms | 153 ms | 17,7 MiB → 17,7 MiB |
| El mismo pedido, `recognize_family` de punta a punta | 4032 | 831 ms | 320 ms | — |

El caso de 4032 estados y 8064 transiciones es el más grande que las familias pueden armar. El lenguaje no cambió: la validación sigue en silencio si todos los estados se alcanzan. El índice de flechas suma unas décimas de mebibyte mientras corre la llamada; lo que bajó es el CPU. En la descarga, el pico sigue siendo el XML.

De los 153 ms que quedan al exportar, la búsqueda de alcanzables ya no es la parte grande: el archivo se arma igual, carácter por carácter. Un test pide que validar el AFD de 4000 estados tarde menos de 0,2 s.

## Compilación de expresiones, 16 de octubre de 2026

Área de esta corrida: el tiempo de CPU de minimizar el AFD que arma `compile_pattern`, adentro de `app/regex_lang.py`. El default sigue en `gemma3:1b`. No se midió Ollama. No se tocaron `app/minimize.py`, la eliminación de estados ni el tope de 512 subconjuntos.

### Entorno

La misma VM Linux 6.12, Python 3.12.3, 4 CPU Intel Xeon (KVM), sin GPU, un solo hilo. El antes y el después son la mediana de cinco llamadas, sin `tracemalloc`. El pico de RAM es de `tracemalloc` en una llamada aparte, no de toda la máquina.

`compile_pattern` construye el AFD por posiciones y después lo minimiza. El tope de 512 subconjuntos ya cortaba el caso exponencial (el noveno símbolo desde el final, sobre {0, 1}). Lo que seguía adentro del tope era la minimización: en cada vuelta buscaba el bloque de cada destino recorriendo la lista entera. Una cadena de símbolos iguales, todos distinguibles, es del orden de n². Ahora la partición es la misma y solo se vuelve a mirar el bloque que se separó, igual que en `app/minimize.py`.

El autómata y el texto de la explicación no cambian. Se compararon 35 expresiones, entre ellas `a*bbb*cc*`, `(a|b)*abb`, 400 aes seguidas y la del octavo símbolo desde el final. `a*` sigue en un estado. `(a|b)*abb` sigue en cuatro.

### Antes y después

| Caso | Estados | Antes | Después | Pico de RAM |
| --- | --- | --- | --- | --- |
| `a` repetida 100 veces | 102 | 10,6 ms | 1,3 ms | 305 KiB → 309 KiB |
| `a` repetida 200 veces | 202 | 52,9 ms | 3,3 ms | 597 KiB → 601 KiB |
| `a` repetida 400 veces | 402 | 316,5 ms | 7,0 ms | 1359 KiB → 1363 KiB |
| `a` repetida 500 veces | 502 | 576,6 ms | 9,2 ms | 1814 KiB → 1818 KiB |
| el 8.º símbolo desde el final es 1, sobre {0, 1} | 256 | 8,8 ms | 5,6 ms | 836 KiB → 840 KiB |
| `a*bbb*cc*` | 5 | 0,2 ms | 0,2 ms | 25 KiB → 23 KiB |

500 aes es el caso largo que todavía entra: 502 estados, justo debajo del tope de 512. El lenguaje no cambió: 500 aes se aceptan, 499 y 501 se rechazan. La memoria queda igual; lo que bajó es el CPU. En la notebook chica, medio segundo de compilación por una expresión larga ya no aparece.

El caso que pasa el tope sigue cortando antes de minimizar. `(0|1)*1` seguido de ocho `(0|1)` responde «La expresión genera demasiados estados (más de 512)» en unos 7 ms, igual que antes. Un test pide que 400 aes compilen en menos de 0,2 s y que el AFD tenga 402 estados.

## Descarga del .jff, 17 de octubre de 2026

Área de esta corrida: el tiempo de CPU y la memoria de `export_jflap` cuando el AFD ya es válido. El default sigue en `gemma3:1b`. No se midió Ollama. No se tocaron la minimización, la búsqueda de alcanzables ni la compilación de expresiones.

### Entorno

La misma VM Linux 6.12, Python 3.12.3, 4 CPU Intel Xeon (KVM), sin GPU, un solo hilo. `time.process_time` coincidió con `time.perf_counter`. El antes del ciclo es la mediana de cinco llamadas, y el de la familia es la mediana de tres. El después es la mediana de siete. Esas corridas no llevaban `tracemalloc`. El pico de RAM es de `tracemalloc` en una llamada aparte, no de toda la máquina.

`export_jflap` armaba un nodo por etiqueta y, al cerrar el archivo, lo recorría carácter por carácter para sacar los que XML 1.0 no admite. En el AFD de 4032 estados el archivo pesa 1 000 594 bytes: casi todo ese recorrido caía sobre el esqueleto, que es ASCII. Ahora los nombres, los símbolos y el comentario siguen pasando por `xml_text`, y el resto se escribe directo. El escape de los atributos es el de antes: `&`, `<`, `>`, las comillas, el retorno, el salto y la tabulación.

El archivo no cambió. El `.jff` de «longitud múltiplo de 64 y longitud múltiplo de 63» sobre {0, 1} es el mismo, byte por byte. El pozo sigue entrando solo en la descarga.

### Antes y después

| Caso | Estados | Antes | Después | Pico de RAM |
| --- | --- | --- | --- | --- |
| AFD total, ciclo sobre {0, 1} | 200 | 6,4 ms | 0,73 ms | 842 KiB → 197 KiB |
| AFD total, ciclo sobre {0, 1} | 1000 | 32,1 ms | 4,1 ms | 4,2 MiB → 992 KiB |
| AFD total, ciclo sobre {0, 1} | 4000 | 133,7 ms | 17,2 ms | 17,2 MiB → 4,0 MiB |
| AFD total, ciclo sobre {0, 1} | 4032 | 134,8 ms | 17,0 ms | 17,3 MiB → 4,1 MiB |
| «longitud múltiplo de 64 y de 63» sobre {0, 1} | 4032 | 139,9 ms | 16,1 ms | 17,2 MiB → 4,1 MiB |

El caso de 4032 estados y 8064 transiciones es el más grande que las familias pueden armar. La llamada incluye la revisión de que el AFD es total: si le faltan flechas, el pozo se agrega igual que antes. Lo que bajó es armar el texto. En la notebook chica, la descarga de ese autómata deja de armar diecisiete mebibytes de nodos para un archivo de un megabyte.

Un test pide que exportar el AFD de 4000 estados tarde menos de 0,08 s. La gramática de JFLAP no se tocó: no abre más de 26 variables, y ese archivo es chico.

## Simulación repetida, 18 de octubre de 2026

Área de esta corrida: el tiempo de CPU de simular muchas cadenas sobre el mismo autómata. El default sigue en `gemma3:1b`. No se midió Ollama. No se tocaron la minimización, la búsqueda de alcanzables, la compilación de expresiones ni la descarga del `.jff`.

### Entorno

La misma VM Linux 6.12, Python 3.12.3, sin GPU, un solo hilo. `time.process_time` coincidió con `time.perf_counter`. El antes y el después son la mediana de siete llamadas, salvo la tanda de 31 simulaciones sueltas y «divisibles por 16 y por 15», que son la mediana de cinco. Esas corridas no llevaban `tracemalloc`. El pico de RAM es de `tracemalloc` en una llamada aparte, no de toda la máquina.

Cada `simulate` armaba el índice de flechas de cero y pasaba cada nombre y cada símbolo por NFC y por el reconocimiento de épsilon. El control de una familia hace eso por cada palabra de prueba: 31 en el producto binario de 4032 estados, y unas 1500 en la divisibilidad en base 10. La cadena es corta. Lo que costaba era rearmar el índice.

Ahora el control y la revisión de las cadenas del modelo usan un solo índice. Un carácter ASCII no se normaliza: no es épsilon, y el NFC no lo cambia. Una palabra ASCII se parte en sus caracteres, sin mirar marcas ni jamo. Si hay un acento, un jamo o la palabra «epsilon», sigue el camino de antes.

El lenguaje no cambió. La vacía de «múltiplo de 64 y de 63» se acepta, 48 ceros se rechazan, y en base 10 el 32 se acepta y el 31 se rechaza. Los topes siguen en 8192 estados y 500 símbolos, con el mismo texto en español.

### Antes y después

| Caso | Antes | Después | Pico de RAM |
| --- | --- | --- | --- |
| 31 cadenas cortas sobre el AFD de 4032 estados, un solo índice | 216,6 ms | 2,2 ms | 1312 KiB → 1311 KiB |
| «números en base 10 divisibles por 32», de punta a punta | 155,6 ms | 6,2 ms | 424 KiB → 418 KiB |
| «divisibles por 16 y por 15» en base 10, de punta a punta | 141,8 ms | 7,8 ms | — |
| «longitud múltiplo de 64 y de 63» sobre {0, 1}, de punta a punta | 442,1 ms | 226,9 ms | 13,6 MiB → 13,6 MiB |
| una simulación de la cadena vacía, AFD de 4032 | 5,9 ms | 2,2 ms | — |
| una simulación de 500 ceros, el mismo AFD | 6,4 ms | 2,4 ms | — |

El pico no baja: una sola copia del índice de 8064 flechas ya ocupaba cerca de 1,3 MiB, y el AFD de 4032 estados sigue siendo los 13,6 MiB. Lo que bajó es el CPU, porque ese índice ya no se arma 31 veces, ni 1500. En la divisibilidad decimal el control era casi todo el pedido: pasó de 156 ms a 6 ms. En el producto de 4032 estados la minimización sigue adentro (cerca de 200 ms) y no se tocó; la simulación de las 31 palabras dejó de sumar otros 200 ms.

Un test pide que «divisibles por 32» en base 10 tarde menos de 0,05 s, que el producto de 64 y 63 tarde menos de 2 s, y que 400 cadenas cortas sobre un AFD de 501 estados, con el índice ya armado, tarden menos de 0,05 s. Los 2 s dejan margen en una notebook con Windows (ahí midió 0,56 s) y siguen lejos del recorrido cuadrático, que tardaba minutos.

## Paso de la máquina de Turing, 19 de octubre de 2026

Área de esta corrida: el tiempo de CPU de `step` cuando la cinta crece hasta el tope. El default sigue en `gemma3:1b`. No se midió Ollama. No se tocaron la minimización, la búsqueda de alcanzables, la compilación de expresiones, la descarga del `.jff` ni el índice de la simulación. `run` tampoco: sin traza sigue usando una sola lista.

### Entorno

La misma VM Linux 6.12, Python 3.12.3, sin GPU, un solo hilo. `time.process_time` coincidió con `time.perf_counter`. El antes es la mediana de tres llamadas. El después de ir a la derecha es la mediana de siete, y el de quedarse en el lugar es la mediana de cinco. Esas corridas no llevaban `tracemalloc`. El pico de RAM es de `tracemalloc` en una llamada aparte, no de toda la máquina. La tabla se volvió a medir el mismo día, con la firma por valor y por tipo y el sello atado a la cinta.

La máquina lee `a` o el blanco, escribe lo mismo y se mueve a la derecha. `step` se llama hasta que la cinta llega a 4096 celdas: 4095 movimientos y el paso que corta. El mensaje no cambió: «No terminó: la cinta llegó a 4096 celdas.»

Cada `step` volvía a pasar todos los símbolos de la cinta por el chequeo de controles. Ir a la derecha hasta el tope es un triángulo: alrededor de ocho millones de lecturas. Por eso tardaba 6,6 s. `run` ya revisaba la entrada una vez y no repetía ese recorrido.

Ahora `start` y `step` marcan la cinta como ya revisada para ese alfabeto y esos estados. El paso siguiente mira solo el símbolo bajo el cabezal. La marca nombra esa cinta: copiar la configuración a otra no arrastra la revisión. La máquina se vuelve a validar si cambian los campos de un estado (nombre, inicial, final), el alfabeto, el blanco o los campos de una flecha (origen, lectura, destino, escritura, movimiento). Cada campo entra en la firma con su tipo: `True == 1` y `False == 0`, pero no son el mismo valor, y un símbolo que solo iguala a «a» tampoco. No se usa la dirección del objeto: un estado o una flecha nuevos pueden ocupar la del que se liberó. Reemplazar una transición en la lista, o soltar las viejas y armar dos nuevas, se ve en el paso siguiente. Una configuración armada afuera, con la épsilon en NFD, se normaliza una vez y después no.

`step` sigue copiando la cinta para devolver una configuración independiente: la anterior no se modifica. Esa copia, y la firma que ahora también guarda el tipo, es lo que queda de los 35 ms. `run` no necesita esa copia y sigue en 1 ms. No se unificaron los dos caminos.

### Antes y después

| Caso | Antes | Después | Pico de RAM |
| --- | --- | --- | --- |
| Ir a la derecha con `step` hasta 4096 celdas | 6642 ms | 34,5 ms | 102 KiB → 102 KiB |
| La misma máquina, `run` sin traza | 1,0 ms | 1,0 ms | — |
| Quedarse en el lugar, 10000 veces `step` | 174,6 ms | 37,1 ms | — |

El pico no baja y no sube: la cinta del tope sigue siendo una tupla de 4096 símbolos, y el sello apunta a esa misma tupla. Lo que bajó es el CPU. En la notebook chica, recorrer la cinta con `step` hasta el tope deja de ser varios segundos.

Los topes siguen en 10000 pasos y 4096 celdas, con el mismo texto en español. Un test pide que esos 4096 `step` tarden menos de 0,5 s y que la cinta, el cabezal y el mensaje coincidan con `run`.

## Control de la divisibilidad, 20 de octubre de 2026

Área de esta corrida: el tiempo de CPU y la memoria de armar la muestra con la que se controla un número. El default sigue en `gemma3:1b`. No se midió Ollama. No se tocaron la minimización, la búsqueda de alcanzables, la compilación de expresiones, la descarga del `.jff`, el índice de la simulación ni el paso de la máquina de Turing.

### Entorno

La misma VM Linux 6.12, Python 3.12.3, sin GPU, un solo hilo. `time.process_time` coincidió con `time.perf_counter`. El antes y el después del pedido completo son la mediana de siete llamadas, sin `tracemalloc`. El de la muestra sola también. El pico de RAM es de `tracemalloc` en una llamada aparte, no de toda la máquina. El antes de la muestra es la misma función de antes, corrida al lado de la nueva, con la misma lista de palabras.

El control de «divisible por n» prueba hasta 1500 cadenas. Para un número, el rango llega a `base · módulo · 3`. En base 36 y módulo 128 eso son 13825 enteros, tres textos cada uno. Se formateaban todos y recién después se tiraba lo que pasaba de 1500. Cada formato volvía a armar los 36 dígitos. La muestra que de verdad se simula no cambió: siguen siendo 1500 cadenas, en el mismo orden, y la última sigue siendo `02t`.

Ahora el alfabeto de dígitos de las bases 2 a 36 se arma una vez, y el recorrido corta al llegar a 1500. Lo que no entra en la muestra no se convierte en texto.

El lenguaje no cambió. En base 36, divisible por 128, el AFD mínimo sigue en 18 estados. La vacía, `0`, `3k` (128) y `74` (256) se aceptan. `1`, `3j` (127) y `3l` (129) se rechazan.

### Antes y después

La muestra es `_control_words`. El pedido es `recognize_family` de punta a punta, con el armado del AFD y la simulación de esas 1500 cadenas.

| Caso | Antes | Después | Pico de RAM |
| --- | --- | --- | --- |
| Muestra, base 36, módulo 128 | 32,2 ms | 0,34 ms | 2420 KiB → 233 KiB |
| Muestra, base 10, módulo 128 | 5,1 ms | 0,55 ms | 783 KiB → 225 KiB |
| Muestra, base 16, módulo 64 | 5,9 ms | 0,52 ms | 662 KiB → 226 KiB |
| Muestra, base 10, módulo 32 | 1,7 ms | 0,49 ms | 327 KiB → 225 KiB |
| Pedido completo, base 36, módulo 128 | 45,4 ms | 14,5 ms | 3,1 MiB → 3,1 MiB |
| Pedido completo, base 10, módulo 128 | 12,5 ms | 7,9 ms | 995 KiB → 974 KiB |
| Pedido completo, base 16, módulo 64 | 10,5 ms | 5,9 ms | — |
| Pedido completo, base 10, módulo 32 | 6,5 ms | 5,3 ms | 412 KiB → 310 KiB |

En el pedido de base 36 el pico no baja: el AFD de 128 estados y 36 símbolos se arma igual, y eso ya ocupa los 3,1 MiB. Lo que bajó es la muestra. Antes, formatear enteros que nadie simulaba sumaba 32 ms y 2,4 MiB encima del autómata. Ahora esa muestra queda en un tercio de milisegundo.

El tope sigue en 1500 palabras. No se sube el módulo (128) ni la base (36). Un test pide que la muestra de base 36 y módulo 128 tarde menos de 0,01 s, que siga en 1500 cadenas y que el lenguaje sea el de antes.
