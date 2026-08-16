# ⛏️ LinguaMiner

[![CI](https://github.com/thecopybookhare-cmd/lingua-miner/actions/workflows/ci.yml/badge.svg)](https://github.com/thecopybookhare-cmd/lingua-miner/actions)
![license](https://img.shields.io/badge/license-MIT-blue)
![version](https://img.shields.io/badge/version-1.21.2-8b7cf8)
![python](https://img.shields.io/badge/python-3.12-3776ab)

**Local, Migaku-style flashcard miner — learn languages from the videos you love.**

Watch anything with word-by-word interactive subtitles, click a word, and get an
Anki card with the audio of the sentence, a video frame, the sentence + neural
translation, and the word's lemma, part of speech, dictionary senses and
frequency. Everything runs **100% locally** — no accounts, no paid APIs.

![Mining a word: click it, read the dictionary, get the card](docs/screenshots/demo.gif)

*One click on an unknown word → dictionary → a card with the sentence audio, the
video frame and the translation, ready for Anki.*

**▶️ [Watch the 3-minute walkthrough](https://youtu.be/_Iu7WcnNXAo)** — every
feature, narrated.

### And this is the card you get

![The Anki card: word, sentence, animated clip, audio, then the translations](docs/screenshots/anki-card.gif)

Front carries the sentence, a short **animated clip** of the moment (not a
frozen frame) and the sentence audio. Back adds the word and sentence in your
language, plus where it came from and how common the word is.

## Features

- 🎙️ **Transcription** with Whisper (fine-tuned Catalan model, or generic
  large-v3 / small) — or use the video's own `.srt` / YouTube subtitles.
- 🖱️ **One-click mining**: click any subtitle word (or drag to select an
  expression) → editable Anki card with segment audio (ffmpeg-trimmed), video
  frame, sentence + translation.
- 🌍 **Twelve languages**: Catalan, French, English, German, European
  Portuguese, Italian, Dutch, Russian, Mandarin Chinese, Cantonese,
  **Japanese** and **Korean**. Neural
  translation runs offline via CTranslate2 (OPUS-MT, or NLLB-200 for pairs
  OPUS doesn't cover) into **Spanish or English** — pick the base under ⚙️
  *Settings → Translate to*. Catalan, French, German, Portuguese, Italian and
  English translate into either; the rest are English-base only, since no →es
  model exists for them. Each language downloads its own translator, spaCy model, Wiktionary
  glosses and Piper voice on first use.
  [Requesting a language?](docs/adding-a-language.md) — that page lists what
  has to exist and where each candidate currently stands.
- 🎨 **Migaku-style word states**: red = new · orange = learning ·
  no mark = known · grey = ignored — synced back from your Anki review
  intervals. A header chip shows the % of the video you already know.
- ⭐ **Smart recommendations (i+1)**: a word is highlighted only when it is
  unknown *and* frequent enough to be worth your time *and* not a proper noun —
  the frequency floor follows your vocabulary level, so you get the words that
  pay off, not every name you happen not to recognise.
- 🌱 **Seed from your Anki decks**: already studying this language? Point
  LinguaMiner at one of your decks and it marks those words as known — it never
  overwrites a status you set yourself.
- 📺 **Watch online**: paste a YouTube / direct / HLS link and it streams
  instantly (yt-dlp resolves the best format); cards cut audio + image
  straight from the stream. Quality selector included.
- 🎧 **Condensed audio**: export an MP3 with *only* the dialogue of an
  episode (a 50-min show becomes ~20 min) for passive listening on your
  phone — the immersion-method staple.
- 🎙️ **Podcasts & radio too**: audio-only sources work as sessions, not just
  video.
- 📋 **Words panel**: every lemma in the video grouped by frequency band;
  bulk-mark the N most frequent words of the language as known.
- 📖 **Dictionaries, four layers deep**: Wiktionary glosses in your base
  language (Spanish *or* English), Apertium bilingual senses, the neural
  translation of the word in context, and **your own dictionaries** — import
  any StarDict (`.ifo`) or Yomitan (`.zip`) file and its definitions show up in
  the same popup, Migaku-style.
- 🔊 Neural TTS pronunciation (Piper), IPA, conjugation tables, remappable
  shortcuts, daily DB backups.
- 📱 **Installable PWA + share mode**: serve the app on your LAN or
  [Tailscale](https://tailscale.com) so a friend or your phone can use it in
  a browser (off by default, full access — share only with people you trust).

| Your library | Words panel |
|---|---|
| ![Library](docs/screenshots/library.png) | ![Words panel](docs/screenshots/words-panel.png) |

## Install

Everyone installs **their own copy** — nothing to host. You don't need Python
or ffmpeg beforehand: the installer brings `uv` (which provides Python) and
`static-ffmpeg` covers ffmpeg if it's missing.

> **Heads up:** installing means pasting one line into a terminal. That's the
> only technical step — after it, LinguaMiner is a normal app you open from
> Launchpad or the Start menu. Never used a terminal? See
> [the step-by-step guide](docs/install-guide.md).

### One command (clones + installs)

**macOS / Linux**:
```bash
curl -LsSf https://raw.githubusercontent.com/thecopybookhare-cmd/lingua-miner/main/bootstrap.sh | bash
```
**Windows** (PowerShell):
```powershell
irm https://raw.githubusercontent.com/thecopybookhare-cmd/lingua-miner/main/bootstrap.ps1 | iex
```
Clones the repo into `~/LinguaMiner` and installs everything. *(Prefer to
clone yourself? Use the manual steps below.)*

### Manual (from the project folder)

**macOS / Linux**
```bash
./install.sh        # installs everything; on macOS also creates LinguaMiner.app
./run.sh            # or open LinguaMiner.app (Mac)
```

**Windows** (PowerShell, inside the project folder)
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
.\run.bat
```

The installer creates the venv (Python 3.12) and downloads the translator,
dictionary and spaCy model. The Whisper model (~3 GB) downloads itself the
first time you transcribe. App data lives in your OS's standard folder
(`Application Support` on Mac, `AppData\Roaming` on Windows,
`~/.local/share` on Linux).

### Anki (for the cards)

1. Install [Anki](https://apps.ankiweb.net)
2. In Anki: Tools → Add-ons → Get Add-ons → code `2055492159` (AnkiConnect)
3. Restart Anki and keep it open while you mine

If Anki is closed, cards queue up and send themselves when it opens.

## Usage

**→ [Full walkthrough with clips of every feature](docs/tutorial.md)**

On first launch a **Getting started** card walks you through these same three
steps and shows what is still downloading. The interface follows your system
language (English, Spanish or Catalan) — change it under ⚙️ any time.

1. Open a local file (mp4/mkv/mp3…), or paste a **YouTube / direct / HLS**
   URL and hit **Watch online**. For offline HD, **Import** downloads
   with a real progress bar.
2. Hit **Transcribe** (use `small` for a quick test) — or use the video's
   own subtitles if available.
3. Click any word in the subtitle (or drag-select an expression).
4. Review/edit the card in the popup and press **⏎**.

**Shortcuts (Migaku map):** `A`/`←` previous sentence · `D`/`→` next ·
`S`/`↓` replay · `Q` mine word under cursor · `⇧Q` open card editor ·
`1-4` word status · `W` hide subs · `E` dual subtitles · `K` condensed
playback · `G` subtitle browser · `P` auto-pause · `F` fullscreen ·
`space` play/pause · `⏎` send card · `Esc` close. All remappable in ⚙️.

## Troubleshooting

| Problem | Fix |
|---|---|
| Blank white window on launch | The app now tells you what failed instead of showing an empty window. If you still get one, you are on an old version — update, and check `desktop.log` in your app data folder |
| "Anki closed" badge | Open Anki with AnkiConnect installed; the queue sends itself |
| Video won't play | `.mkv` files are remuxed to mp4 automatically on import |
| Empty translations | Run `./install.sh` again (downloads the translator) |
| Slow transcription | Pick the `small` model in the selector. A 50-min episode takes a few minutes before the progress bar moves — press *Transcribe* once and let it run |

New to all this? The [step-by-step install guide](docs/install-guide.md) covers
the same ground with no assumed terminal experience.

## Architecture

FastAPI + SQLite + vanilla JS (no build step). Pieces:
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) with
[projecte-aina/faster-whisper-large-v3-ca-3catparla](https://huggingface.co/projecte-aina/faster-whisper-large-v3-ca-3catparla),
[softcatala/translate-cat-spa](https://huggingface.co/softcatala/translate-cat-spa)
and OPUS-MT CTranslate2 models per language, Apertium bilingual dictionaries,
spaCy, wordfreq, yt-dlp, Piper TTS, AnkiConnect.

Language profiles live in [`app/languages.py`](app/languages.py) — adding a
language is mostly adding one entry there.

## Development

```bash
uv pip install -p .venv/bin/python -e . --group dev
.venv/bin/ruff check app/ tests/     # lint
.venv/bin/python -m pytest tests/    # 190 tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md). CI runs lint + tests on
Linux/macOS/Windows on every push.

## License & fair use

Code under the [MIT](LICENSE) license © 2026 thecopybookhare.

⚠️ **Personal and educational use only.** The tool plays third-party content
for language study; respect copyright and each platform's terms. Don't
redistribute downloaded content.
