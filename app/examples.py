"""Frases de ejemplo desde el PROPIO contenido del usuario (100% local):
busca un lema en las transcripciones de todas las sesiones."""
import json


def find(con, lemma: str, limit: int = 4,
         exclude_sid: str = "", exclude_idx: int = -1,
         language: str = "") -> list[dict]:
    """`language` limita la búsqueda a las sesiones de ese idioma: «die» es
    un lema alemán y uno inglés, y los ejemplos no pueden mezclarse."""
    lemma = (lemma or "").strip().lower()
    if not lemma:
        return []
    out, seen = [], set()
    q = "SELECT id, title, transcript_json FROM sessions"
    args = ()
    if language:
        q, args = q + " WHERE language=?", (language,)
    rows = con.execute(q + " ORDER BY created_at DESC", args).fetchall()
    for row in rows:
        try:
            segs = json.loads(row["transcript_json"])
        except Exception:
            continue
        for i, seg in enumerate(segs):
            if row["id"] == exclude_sid and i == exclude_idx:
                continue
            text = (seg.get("text") or "").strip()
            if not text or text in seen:
                continue
            if any(t.get("is_word") and t.get("lemma") == lemma
                   for t in seg.get("tokens", [])):
                seen.add(text)
                out.append({"text": text,
                            "text_es": seg.get("text_es") or "",
                            "session_id": row["id"],
                            "session_title": row["title"],
                            "index": i,
                            "start": seg.get("start", 0)})
                if len(out) >= limit:
                    return out
    return out
