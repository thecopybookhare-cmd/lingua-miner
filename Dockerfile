# syntax=docker/dockerfile:1
# LinguaMiner en un contenedor: el servidor web, sin la ventana de escritorio.
# Se abre en el navegador del anfitrión (http://localhost:8977). La biblioteca,
# las tarjetas en cola y los modelos descargados viven en /data.

# Solo la lista de dependencias. Copiar pyproject.toml entero invalidaría la
# caché en cada cambio de versión y reinstalaría 2 GB y once modelos.
FROM python:3.12-slim AS deps
COPY pyproject.toml /
RUN python -c "import tomllib; d = tomllib.load(open('/pyproject.toml', 'rb')); \
open('/requirements.txt', 'w').write('\\n'.join(d['project']['dependencies']) + '\\n')"

FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/thecopybookhare-cmd/lingua-miner" \
      org.opencontainers.image.description="Turn the videos you watch into Anki flashcards — offline, 12 languages" \
      org.opencontainers.image.licenses="MIT"

# ffmpeg del sistema (media.py lo prefiere al binario estático descargable) y
# espeak-ng para la transcripción fonética de las palabras
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app

# dependencias antes que el código: tocar la app no las reinstala
COPY --from=deps /requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

# Los modelos de spaCy son paquetes de Python. Descargados en tiempo de
# ejecución se perderían al recrear el contenedor, y el asistente de primer
# arranque no avisa cuando faltan: la app caería al tokenizador regex sin
# decir nada. Van dentro de la imagen. (El cantonés usa el de chino.)
RUN for m in ca_core_news_sm fr_core_news_sm en_core_web_sm de_core_news_sm \
             pt_core_news_sm it_core_news_sm ru_core_news_sm nl_core_news_sm \
             zh_core_web_sm ja_core_news_sm ko_core_news_sm; do \
      python -m spacy download "$m" || exit 1; \
    done \
 && rm -rf /root/.cache

# pyproject.toml al final: diagnostics.py lee de ahí la versión
COPY pyproject.toml ./
COPY app ./app
COPY static ./static

RUN useradd --create-home --uid 1000 linguaminer \
 && mkdir -p /data && chown linguaminer:linguaminer /data
USER linguaminer

# LINGUAMINER_ANKI_HOST: Anki corre en el anfitrión, no aquí dentro.
# LINGUAMINER_TRUST_ALL_CLIENTS: el navegador llega desde la puerta de enlace
# de Docker, no desde 127.0.0.1; el control de acceso es el puerto publicado.
ENV PYTHONUNBUFFERED=1 \
    LINGUAMINER_DIR=/data \
    LINGUAMINER_ANKI_HOST=host.docker.internal \
    LINGUAMINER_TRUST_ALL_CLIENTS=1

VOLUME /data
EXPOSE 8977

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8977/api/health', timeout=4)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8977"]
