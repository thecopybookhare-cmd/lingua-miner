"""Lecturas a la vez sobre una conexión compartida.

En el registro de un usuario, el popup dio error 500 dos veces con
«InterfaceError: bad parameter or other API misuse»: dos hilos del servidor
consultaban a la vez la misma conexión del diccionario de formas.
"""
import sqlite3
import threading

from app import db, sqlshare


def _hammer(con, n_threads=8, n=400):
    errors = []

    def work(k):
        for i in range(n):
            try:
                rows = con.execute("SELECT lemma FROM forms WHERE form=?",
                                   (f"w{(i * k) % 2000}",)).fetchall()
                assert len(rows) == 1
            except Exception as e:                      # noqa: BLE001
                errors.append(e)
    ts = [threading.Thread(target=work, args=(k,)) for k in range(1, n_threads + 1)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return errors


def _forms_db(tmp_path):
    p = tmp_path / "forms.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE forms (form TEXT, lemma TEXT)")
    c.executemany("INSERT INTO forms VALUES (?,?)", [(f"w{i}", f"l{i}") for i in range(2000)])
    c.execute("CREATE INDEX ix ON forms(form)")
    c.commit()
    c.close()
    return p


def test_concurrent_reads_do_not_trip_over_each_other(tmp_path):
    assert _hammer(sqlshare.connect(_forms_db(tmp_path))) == []


def test_rows_behave_like_a_cursor(tmp_path):
    con = sqlshare.connect(_forms_db(tmp_path))
    r = con.execute("SELECT form FROM forms WHERE form IN ('w1','w2') ORDER BY form")
    assert r.fetchone() == ("w1",) and r.fetchall() == [("w2",)] and r.fetchone() is None
    assert [x for x in con.execute("SELECT 1")] == [(1,)]
    cur = con.execute("INSERT INTO forms VALUES ('nuevo', 'n')")
    assert cur.lastrowid and cur.rowcount == 1


def test_app_database_is_shared_safely(tmp_path):
    con = db.connect(tmp_path / "app.db")
    assert isinstance(con, sqlshare.Locked)
    sid = db.create_session(con, language="de", title="t", source_type="text",
                            media_path="x", srt_source="-", model_size="-",
                            duration_secs=0, transcript_json="[]")
    errors = []

    def work():
        for _ in range(200):
            try:
                assert db.get_session(con, sid)["title"] == "t"
            except Exception as e:                      # noqa: BLE001
                errors.append(e)
    ts = [threading.Thread(target=work) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
