---
title: Learn languages from the videos you love
---

# Learn languages from the videos you love

**Turn the videos you already watch into Anki flashcards.** Everything runs on
your own machine — no accounts, no subscriptions, no API keys, and nothing you
watch is ever uploaded anywhere.

![Click a word, read the dictionary, get the card](screenshots/demo.gif)

You open a video — a local file, a YouTube link or an HLS stream — and it plays
with word-by-word clickable subtitles. Click a word you don't know and you get
its lemma, part of speech, dictionary senses and how common it is. Keep it, and
an Anki card is built for you: the sentence audio trimmed with ffmpeg, a short
animated clip of that exact moment, and the sentence with a translation.

**▶ [Watch the 3-minute walkthrough](https://youtu.be/_Iu7WcnNXAo)**

## Start here

- **[Installing LinguaMiner, step by step](install-guide.html)** — written for
  people who have never opened a terminal.
- **[How to use it](tutorial.html)** — every feature, in the order you meet them.
- **[Adding a language](adding-a-language.html)** — what has to exist for a
  language to work, and where each candidate currently stands.

## Or run it with Docker

No installer, no Python — one command, then open <http://localhost:8977>:

```bash
docker run -d --name linguaminer -p 127.0.0.1:8977:8977 \
  -v linguaminer-data:/data --add-host=host.docker.internal:host-gateway \
  ghcr.io/thecopybookhare-cmd/lingua-miner:latest
```

Details — Anki from inside the container, your own videos, updating — are in
[the README](https://github.com/thecopybookhare-cmd/lingua-miner#docker).

## What else it does

- **Word states synced from Anki.** Red is new, orange is learning, unmarked is
  known — read back from your actual review intervals. A chip tells you what
  percentage of the video you already understand.
- **i+1 recommendations.** A word lights up only when it's unknown, frequent
  enough to be worth your time, and not a proper noun.
- **Bring the vocabulary you already have** from Migaku, jpdb, LingQ or an Anki
  deck, so those words don't start out red.
- **Read books too.** Import a `.txt` or `.epub` and you get the same clickable
  words, the same popup, and cards read aloud by Piper.
- **Condensed audio.** Export an MP3 with only the dialogue of an episode — a
  50-minute show becomes about 20 — for passive listening.
- **Your own dictionaries**, including Yomitan format.

## Twelve languages

Catalan, French, English, German, European Portuguese, Italian, Dutch, Russian,
Mandarin Chinese, Cantonese, Japanese and Korean — translating into Spanish or
English.

Transcription is Whisper, translation is CTranslate2 (OPUS-MT, or NLLB-200 for
pairs OPUS doesn't cover), speech is Piper. Each language downloads its own
models the first time you use it.

## Free and open source

MIT licensed, for Windows, macOS and Linux.
[Source code on GitHub](https://github.com/thecopybookhare-cmd/lingua-miner) ·
[Report a problem](https://github.com/thecopybookhare-cmd/lingua-miner/issues) ·
[Discussions](https://github.com/thecopybookhare-cmd/lingua-miner/discussions)
