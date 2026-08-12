# Installing LinguaMiner, step by step

This guide assumes you have **never opened a terminal**. There is exactly one
line to copy and paste. Everything else is clicking.

Total time: about 10 minutes, most of it waiting for downloads.

---

## What you are installing

LinguaMiner runs **on your own computer**. There is no account, no server and
no subscription — which is also why there is no `.dmg` to double-click: the
installer has to fetch the pieces (the translator, the dictionaries, the
speech-to-text model) and wire them up for your machine.

You will also want **Anki**, the flashcard app the cards are sent to. That one
*is* a normal installer.

---

## macOS

### 1. Open Terminal

Press `⌘ Space`, type `terminal`, press `Enter`. A window with white or black
text appears. That is it — it's just a place to paste one line.

### 2. Paste this line and press Enter

```bash
curl -LsSf https://raw.githubusercontent.com/thecopybookhare-cmd/lingua-miner/main/bootstrap.sh | bash
```

Copy it whole, click into the Terminal window, paste (`⌘V`), press `Enter`.

### 3. Wait

Text scrolls for several minutes. That is normal — it is downloading. If macOS
asks you to install "command line developer tools", say **yes** and, once that
finishes, paste the same line again.

When it is done you will see a line telling you the app was created.

### 4. Open the app

Press `⌘ Space`, type `LinguaMiner`, press `Enter`. From now on this is how you
open it — you never need the Terminal again.

---

## Windows

### 1. Open PowerShell

Press the `Windows` key, type `powershell`, press `Enter`.

### 2. Paste this line and press Enter

```powershell
irm https://raw.githubusercontent.com/thecopybookhare-cmd/lingua-miner/main/bootstrap.ps1 | iex
```

Right-click pastes in PowerShell. Then press `Enter`.

### 3. Wait, then open it

Same as above: several minutes of scrolling text. When it finishes you get a
LinguaMiner shortcut — use that from now on.

---

## First launch

The app opens on **Your library**, with a *Getting started* card that walks you
through the three steps and shows what is still downloading. Two things worth
knowing:

- **The interface picks your system language** (English, Spanish or Catalan).
  You can change it any time under ⚙️ → *Interface language*.
- **The first transcription is slow.** The speech-to-text model is ~3 GB and
  downloads the first time you press *Transcribe*. After that it is local and
  much faster. Pick the `small` model for a quick first test.

---

## Anki (needed for the flashcards)

1. Install [Anki](https://apps.ankiweb.net) — normal installer, click through it.
2. Open Anki → *Tools* → *Add-ons* → *Get Add-ons…*
3. Paste the code `2055492159` and press OK. That is **AnkiConnect**, the bridge
   LinguaMiner talks to.
4. **Restart Anki.**

Keep Anki open while you mine. If it is closed, cards queue up inside
LinguaMiner and send themselves the next time it sees Anki running — nothing
is lost.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `command not found: git` (macOS) | Run `xcode-select --install`, wait for it to finish, then paste the install line again |
| The Anki badge is red or says "Anki…" | Open Anki, check AnkiConnect is installed, then click the badge to re-check |
| Translations are empty | Open ⚙️ and use *Download translator and dictionaries*, or run `./install.sh` again |
| Transcription seems stuck | It isn't — analysing a 50-minute episode takes a few minutes before the percentage moves. Press *Transcribe* **once** and let it work |
| A video won't play | `.mkv` files get converted automatically when you import them; give it a moment |

Still stuck? [Open an issue](https://github.com/thecopybookhare-cmd/lingua-miner/issues)
and paste what the terminal printed.

---

## Updating later

Open ⚙️ → *Updates* → *Check for updates*. It updates itself; no terminal
needed.
