"""Una conexión sqlite compartida por los hilos del servidor, de una en una.

FastAPI atiende las rutas síncronas en varios hilos a la vez, y las
conexiones de la app (la base de datos y los diccionarios) se abren una sola
vez con check_same_thread=False. Pero una conexión de sqlite3 no aguanta dos
consultas a la vez: con el popup y la tarjeta pidiendo al mismo tiempo, una
lectura fallaba con «InterfaceError: bad parameter or other API misuse» y el
popup daba error 500 (pasó dos veces en el registro de un usuario; con 8 hilos
se reproduce miles de veces por segundo).

Locked envuelve la conexión: cada execute toma el candado, lee todas las filas
y lo suelta. Lo que devuelve se usa igual que un cursor (fetchone, fetchall,
iterar), sin tocar ya la conexión.
"""
import sqlite3
import threading


class Rows:
    """Las filas de una consulta, ya leídas."""

    def __init__(self, rows: list, cur: sqlite3.Cursor):
        self._rows = rows
        self.lastrowid = cur.lastrowid
        self.rowcount = cur.rowcount
        self.description = cur.description

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list:
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class Locked:
    def __init__(self, con: sqlite3.Connection, lock=None):
        self._con = con
        self._lock = lock or threading.RLock()

    def execute(self, sql: str, params=()) -> Rows:
        with self._lock:
            cur = self._con.execute(sql, params)
            return Rows(cur.fetchall(), cur)

    def executemany(self, sql: str, seq) -> Rows:
        with self._lock:
            cur = self._con.executemany(sql, seq)
            return Rows([], cur)

    def executescript(self, script: str) -> Rows:
        with self._lock:
            cur = self._con.executescript(script)
            return Rows([], cur)

    def commit(self):
        with self._lock:
            self._con.commit()

    def rollback(self):
        with self._lock:
            self._con.rollback()

    def backup(self, target, **kw):
        with self._lock:
            self._con.backup(target, **kw)

    def close(self):
        with self._lock:
            self._con.close()

    def __getattr__(self, name):
        # row_factory, in_transaction, total_changes…
        return getattr(self._con, name)


def connect(path, lock=None, **kw) -> Locked:
    """sqlite3.connect para una conexión que van a compartir varios hilos."""
    return Locked(sqlite3.connect(str(path), check_same_thread=False, **kw), lock)
