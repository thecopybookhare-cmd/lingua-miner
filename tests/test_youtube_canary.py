"""El canario de YouTube: que suene cuando debe, y solo entonces."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "youtube_canary", Path(__file__).resolve().parent.parent / "scripts" / "youtube_canary.py")
canary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(canary)


def _run(monkeypatch, statuses, deno="/venv/bin/deno"):
    it = iter(statuses)
    monkeypatch.setattr(canary, "check", lambda url: (next(it), "detalle"))
    monkeypatch.setattr(canary.ytdlp, "deno_path", lambda: deno)
    return canary.main()


@pytest.mark.parametrize("statuses,code", [
    (["ok", "ok", "ok"], 0),
    (["ok", "broken", "blocked"], 0),          # un vídeo concreto puede fallar
    (["broken", "broken", "blocked"], 1),      # roto de verdad: abre issue
    (["blocked", "blocked", "blocked"], 2),    # IPs de GitHub: no concluyente
])
def test_exit_codes(monkeypatch, capsys, statuses, code):
    assert _run(monkeypatch, statuses) == code


def test_missing_deno_is_broken_even_if_a_video_passes(monkeypatch, capsys):
    assert _run(monkeypatch, ["ok", "ok", "ok"], deno=None) == 1
    assert "Deno is missing" in capsys.readouterr().out
