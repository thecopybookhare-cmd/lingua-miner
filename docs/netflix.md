# Netflix (and other sites) with asbplayer

LinguaMiner can't open Netflix. The video is encrypted (DRM), and breaking
that is off the table. Language Reactor and Migaku don't download it either.
They are browser extensions that work on top of the Netflix page while you
watch: they read the subtitle track (subtitles aren't encrypted), drive the
player, and record the line's audio from the tab.

[asbplayer](https://github.com/killergerbah/asbplayer) does the same, it's
free and open source, and it sends cards through AnkiConnect, so LinguaMiner
can sit in between. asbplayer handles Netflix: subtitles, audio and an image
or animated clip of the scene. LinguaMiner fills in the rest before the card
reaches Anki:

| Field | Who fills it |
|---|---|
| Sentence, audio, image or clip, source | asbplayer |
| Word in dictionary form + translation (*Handschuhe* → *der Handschuh (pl. Handschuhe) — el guante*) | LinguaMiner |
| Sentence translation | LinguaMiner |
| Wiktionary definition | LinguaMiner |
| Other sentences with the word, from your own videos and books | LinguaMiner |
| Frequency | LinguaMiner |

Anything you type in asbplayer's card dialog wins: LinguaMiner only fills
fields that arrive empty. The card also counts in LinguaMiner. The word turns
*learning*, and later *known* when it matures in Anki, the same as a card you
mine in the app.

## Setup (once)

1. **Chrome** (or another Chromium browser). In Firefox asbplayer can't record
   audio from DRM video.
2. Install [asbplayer](https://chromewebstore.google.com/detail/asbplayer-language-learni/hkledmpjpaehamkiehglnbelcpdflcab)
   and keep LinguaMiner and Anki open.
3. In LinguaMiner, ⚙️ *Settings → Netflix and other sites*: copy the address
   (`http://127.0.0.1:8977/ankiconnect`).
4. In asbplayer's settings, under **Anki**:
   - **AnkiConnect URL**: paste that address.
   - **Deck**: whichever you like.
   - **Note type**: `LinguaMiner`. It appears in the list even if you've never
     sent a card from the app.
   - **Card fields**:

     | asbplayer | LinguaMiner note field |
     |---|---|
     | Sentence | `Frase` |
     | Word | `Paraula` |
     | Definition | `Definicio` |
     | Audio | `Audio` |
     | Image | `Imatge` |
     | Source | `Font` |

5. Optional: in asbplayer, set the image capture to an **animated WebP clip**
   (v1.23+) so the card moves like a GIF.
6. In LinguaMiner, the study language must be the show's language: that's
   the language it uses to find the word and translate.

## Mining

Open an episode on netflix.com, turn on subtitles in the language you study
(asbplayer picks them up; `Ctrl+Shift+F` chooses the track), and when a line
is worth keeping:

- **`Ctrl+Shift+X`** opens asbplayer's card dialog. Type the word in *Word*
  (any form: *fängt* becomes *anfangen*) and export. A word wrapped in
  `<b>…</b>` in the sentence counts too, which is handy if another tool marks
  it for you.
- **`Ctrl+Shift+Z`** exports straight away, without choosing a word. LinguaMiner
  then picks it for you if the line has exactly one word you don't know yet
  (i+1, not counting names). If it has more, you get a sentence card: the
  whole line on the front, the translation on the back.

The first card after starting LinguaMiner takes a few seconds longer while
the language models load.

## What to expect

- It depends on asbplayer and on Netflix's player. When Netflix changes its
  page, asbplayer usually needs an update; check its releases if subtitles
  stop showing up.
- Only the machine running LinguaMiner can use the bridge. Other devices
  in share mode can't, and neither can web pages you open. AnkiConnect
  normally asks before a new site touches your collection, and the bridge
  keeps that rule: only browser extensions, asbplayer's own site and
  localhost get through.
- Notes of any other type (yours, from other decks) go through to Anki
  untouched.
