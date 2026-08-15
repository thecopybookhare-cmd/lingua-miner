"""Softcatalà cat->spa neural translation via CTranslate2 + SentencePiece."""
import re
from pathlib import Path

from . import config

_LEAD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detok(pieces: list[str]) -> str:
    out = "".join(pieces).replace("▁", " ")
    return out.replace("<unk>", "").strip()


def _find_sp(model_dir: Path) -> Path:
    """SentencePiece del modelo. OPUS-MT trae source.spm/target.spm por
    separado (codificamos con el de origen); Softcatalà trae un único
    sp_m.model compartido."""
    src = next(iter(model_dir.glob("**/source.spm")), None)
    if src:
        return src
    for pat in ("**/*.model", "**/*.spm"):
        hits = sorted(model_dir.glob(pat))
        if hits:
            return hits[0]
    raise FileNotFoundError("no SentencePiece model in " + str(model_dir))


class _Engine:
    def __init__(self, model_dir: Path, eos: bool = False,
                 target_token: str | None = None, nllb: dict | None = None):
        import ctranslate2
        import sentencepiece as spm
        self.sp = spm.SentencePieceProcessor(model_file=str(_find_sp(model_dir)))
        self.eos = eos                        # OPUS-MT necesita </s> en la fuente
        # modelos multilingües (romance): token de idioma destino al inicio
        self.target_token = target_token
        # NLLB: para pares que OPUS-MT no cubre (el cantonés no tiene modelo
        # bilingüe). Marca el idioma de ORIGEN al inicio y fuerza el de destino
        # como prefijo del decodificador, en vez de un solo token de destino.
        self.nllb = nllb
        ct2_dir = model_dir
        if not (model_dir / "model.bin").exists():
            cands = list(model_dir.glob("**/model.bin"))
            if not cands:
                raise FileNotFoundError("no CT2 model.bin under " + str(model_dir))
            ct2_dir = cands[0].parent
        self.tr = ctranslate2.Translator(str(ct2_dir), device="cpu")

    def translate(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        toks = self.sp.encode(text, out_type=str)
        if self.nllb:
            src, tgt = self.nllb["src"], self.nllb["tgt"]
            res = self.tr.translate_batch([[src] + toks + ["</s>"]],
                                          target_prefix=[[tgt]],
                                          beam_size=4, max_batch_size=1)
            out = res[0].hypotheses[0]
            if out and out[0] == tgt:        # el prefijo forzado no es traducción
                out = out[1:]
            return detok(out)
        if self.target_token:
            toks = [self.target_token] + toks
        if self.eos:
            toks = toks + ["</s>"]
        res = self.tr.translate_batch([toks], beam_size=2, max_batch_size=1)
        return detok(res[0].hypotheses[0])


def model_dir() -> Path:
    from . import languages
    return config.MODELS_DIR / languages.translate_spec()["dir"]


def is_downloaded() -> bool:
    return model_dir().exists() and any(model_dir().glob("**/model.bin"))


def download():
    from . import languages
    spec = languages.translate_spec()
    if spec.get("zip"):
        _download_and_convert(spec["zip"], model_dir())
    elif spec.get("repo"):
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=spec["repo"], local_dir=str(model_dir()))


def _download_and_convert(zip_url: str, dest: Path) -> None:
    """Descarga un modelo Marian de OPUS-MT (.zip) y lo convierte a CT2 sin
    torch. Para pares sin CT2 pre-hecho: p. ej. pt→es vía el modelo
    multilingüe romance itc-itc (no existe un opus-mt-pt-es bilingüe)."""
    import shutil
    import tempfile
    import zipfile

    import requests
    from ctranslate2.converters import OpusMTConverter
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        zpath = tdp / "model.zip"
        with requests.get(zip_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(zpath, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        srcdir = tdp / "src"
        with zipfile.ZipFile(zpath) as z:
            z.extractall(srcdir)
        OpusMTConverter(str(srcdir)).convert(str(dest), quantization="int8",
                                             force=True)
        # el convertidor no copia el SentencePiece de origen que usa el motor
        shutil.copy(srcdir / "source.spm", dest / "source.spm")


_ENGINES: dict = {}       # motor por par (estudio, base)
_FAILED_AT: dict = {}     # par -> timestamp del último intento fallido
_RETRY_SECS = 60.0        # un corte de red no debe matar el traductor para siempre


def translate(text: str) -> str:
    """Traduce al idioma base activo. Returns '' on any failure (never raises)."""
    import time

    from . import languages
    key = (languages.active_code(), languages.base_code())
    if _ENGINES.get(key) is None:
        last = _FAILED_AT.get(key, 0.0)
        if key in _ENGINES and time.time() - last < _RETRY_SECS:
            return ""                     # fallo reciente: esperar al reintento
        try:
            if not is_downloaded():
                download()
            spec = languages.translate_spec()
            _ENGINES[key] = _Engine(model_dir(), eos=bool(spec.get("eos")),
                                    target_token=spec.get("token"),
                                    nllb=spec.get("nllb"))
            _FAILED_AT.pop(key, None)
        except Exception:
            _ENGINES[key] = None
            _FAILED_AT[key] = time.time()
            return ""
    try:
        return _ENGINES[key].translate(text)
    except Exception:
        return ""


def sentence(text: str) -> str:
    """translate() + reintento decapitalizado cuando el modelo deja la
    primera palabra sin traducir por ir en mayúscula ('Ets molt...' ->
    'Ets muy...'): se decapitaliza, retraduce y recapitaliza."""
    out = translate(text)
    if not out:
        return out
    m = _LEAD.search(text)
    if not m:
        return out
    w = m.group(0)
    if not w[0].isupper() or w.lower() == w or w not in out:
        return out
    from . import forms
    if forms.known_exact(w) or not forms.knows_lower(w):
        return out
    decap = text[:m.start()] + w[0].lower() + w[1:] + text[m.end():]
    out2 = translate(decap)
    if not out2 or w in out2:
        return out
    return out2[:1].upper() + out2[1:]
