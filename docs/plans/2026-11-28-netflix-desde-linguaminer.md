# Netflix desde LinguaMiner (asbplayer como grabadora) — plan

**Estado:** APROBADO (opción 2, 2026-11-28). Sigue al puente AnkiConnect de v1.42.0.

## Por qué

La primera prueba real del puente (Génesis, en catalán) funcionó, pero minar
desde la interfaz de asbplayer no gustó: atajos y diálogo propios, y sin
palabra elegida la elección automática falló («Guérard», un nombre; «Va»,
una interjección). Se quiere minar con la interfaz de LinguaMiner: popup,
colores, editor.

## Límite de la API de asbplayer

`get-bound-media`, `get-subtitles`, `seek-timestamp`, `mine-subtitle`… pero
**no hay posición de reproducción**. LinguaMiner no puede seguir el vídeo, así
que no sabe qué línea acabas de oír.

## Diseño

1. **WebSocket `/ws`.** asbplayer se conecta como cliente («Enable WebSocket
   client», URL `ws://127.0.0.1:8977/ws`). PING/PONG cada 10 s; órdenes en
   JSON-RPC 2.0 (asbplayer ≥ 1.23). `app/asbws.py`: un hub con llamadas
   síncronas desde los hilos de FastAPI.
2. **El episodio como sesión** (`source_type="asbplayer"`, clave = nombre del
   archivo de subtítulos, p. ej. «Génesis S01E01 … - ca - Catalán [CC].nfimsc»).
   Se abre en el lector, una línea por párrafo, con su hora: tocarla hace
   `seek-timestamp` en Netflix.
3. **Sincronía con una tecla.** `Ctrl+Shift+Z` en Netflix (asbplayer exporta
   sin diálogo) → el puente recibe `addNote` sin palabra → no va a Anki: se
   guardan audio e imagen en `MEDIA_DIR` (`asb-*`), se marca la línea en la
   sesión (🎬) y LinguaMiner salta a ella (`/api/asbplayer/events`, sondeo).
   Eliges la palabra con el popup; la tarjeta lleva ese audio y esa imagen.
   Sustituye a la elección automática de palabra.
4. **Cualquier otra línea**: al enviarse la tarjeta (nota creada por
   LinguaMiner, con su id), `seek-timestamp` + `mine-subtitle`
   (`postMineAction: 2`, `noteId`): asbplayer graba esa línea y añade audio e
   imagen a la nota.
5. Si se escribe la palabra en el diálogo de asbplayer, sigue el camino de
   v1.42.0 (nota completada y a Anki).

## Archivos

`app/asbws.py` (nuevo), `app/main.py` (endpoints `/ws`,
`/api/asbplayer/{status,open,seek,events}`, captura en el puente, preview y
envío de sesiones asbplayer), `app/db.py` (buscar sesión por media),
`static/app.js`/`index.html`/`i18n.js`/`style.css` (lector de subtítulos,
botón 🍿 Netflix, estado de conexión en Ajustes), `docs/netflix.md`, tests.

## Verificación

Tests con un cliente WebSocket falso (TestClient) y AnkiConnect falso;
prueba de punta a punta con datos aislados; prueba real con Netflix por el
usuario.
