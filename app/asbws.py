"""Conexión con asbplayer por WebSocket: LinguaMiner manda, asbplayer graba.

asbplayer (la extensión) se conecta como cliente a un servidor WebSocket
local; aquí ese servidor es LinguaMiner, en /ws. El protocolo, tal como lo
implementan asbplayer y su complemento de Anki:

- asbplayer manda el texto «PING» cada 10 s y espera «PONG»; si no llega,
  reconecta.
- El servidor manda peticiones JSON-RPC 2.0 (get-bound-media, get-subtitles,
  seek-timestamp, mine-subtitle) y asbplayer contesta con el mismo id.

Las rutas de FastAPI que lo usan son síncronas (corren en hilos), así que
`call()` es bloqueante y salta al bucle de asyncio de la conexión.
"""
import asyncio
import json
import threading
import uuid


class AsbError(Exception):
    pass


class NotConnected(AsbError):
    pass


class Hub:
    def __init__(self):
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._send_lock: asyncio.Lock | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._guard = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def serve(self, ws):
        """Atiende una conexión de asbplayer hasta que se cierre. Una nueva
        sustituye a la anterior (asbplayer reconecta solo)."""
        await ws.accept()
        with self._guard:
            self._ws, self._loop = ws, asyncio.get_running_loop()
            self._send_lock = asyncio.Lock()
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "PING":
                    await self._send(ws, "PONG")
                    continue
                try:
                    data = json.loads(msg)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                rid = data.get("id")
                if "method" in data and rid is not None:
                    # asbplayer no pide nada al servidor; si lo hace, se le dice
                    await self._send(ws, json.dumps({
                        "jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32601, "message": "Method not found"}}))
                    continue
                fut = self._pending.pop(str(rid), None) if rid is not None else None
                if fut is not None and not fut.done():
                    fut.set_result(data)
        except Exception:                               # noqa: BLE001
            pass                                        # desconexión
        finally:
            with self._guard:
                if self._ws is ws:
                    self._ws = None
                    for fut in self._pending.values():
                        if not fut.done():
                            fut.set_exception(NotConnected("asbplayer se desconectó"))
                    self._pending.clear()

    async def _send(self, ws, text: str):
        lock = self._send_lock
        if lock is None:
            await ws.send_text(text)
            return
        async with lock:
            await ws.send_text(text)

    async def _call(self, method: str, params: dict, timeout: float):
        ws = self._ws
        if ws is None:
            raise NotConnected("asbplayer no está conectado")
        rid = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send(ws, json.dumps({"jsonrpc": "2.0", "id": rid,
                                             "method": method, "params": params}))
            data = await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)
        if data.get("error"):
            err = data["error"]
            raise AsbError(err.get("message") if isinstance(err, dict) else str(err))
        return data.get("result")

    def call(self, method: str, params: dict | None = None, timeout: float = 5.0):
        """Petición a asbplayer desde un hilo; devuelve su `result`.
        No llamar desde el propio bucle de asyncio (se bloquearía)."""
        with self._guard:
            loop, ws = self._loop, self._ws
        if ws is None or loop is None:
            raise NotConnected("asbplayer no está conectado")
        fut = asyncio.run_coroutine_threadsafe(
            self._call(method, params or {}, timeout), loop)
        try:
            return fut.result(timeout + 1)
        except TimeoutError as e:        # en 3.11+ también el de asyncio y concurrent
            fut.cancel()
            raise AsbError(f"asbplayer no contestó a {method}") from e


HUB = Hub()
