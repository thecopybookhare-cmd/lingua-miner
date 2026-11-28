# Netflix (and other sites) with asbplayer

LinguaMiner can't open Netflix. The video is encrypted (DRM), and breaking
that is off the table. Language Reactor and Migaku don't download it either.
They are browser extensions that work on top of the Netflix page while you
watch: they read the subtitle track (subtitles aren't encrypted), drive the
player, and record the line's audio from the tab.

[asbplayer](https://github.com/asbplayer/asbplayer) does the same, it's free
and open source, and it can be driven from outside. So the video stays in
Chrome, asbplayer acts as the recorder, and you mine in LinguaMiner as
usual:

- **The episode opens in LinguaMiner.** It shows the subtitles line by line,
  with the word colours, the popup and the card editor you already use.
  Click a line's time and Netflix jumps there.
- **`Ctrl+Shift+Z` in Netflix captures the line that's playing.** asbplayer
  records its audio and image, and LinguaMiner jumps to that line (marked
  🎬) so you can pick the word. The card carries the actor's voice and the
  scene.
- **Any other line works too.** When the card reaches Anki, LinguaMiner asks
  asbplayer to replay that line in Netflix, record it, and add the audio and
  image to the note.

LinguaMiner and Netflix work best side by side: LinguaMiner in its own
window, Netflix visible in Chrome. asbplayer can only grab the image from a
tab you can see.

## Setup (once)

1. **Chrome** (or another Chromium browser). In Firefox asbplayer can't record
   audio from DRM video.
2. Install [asbplayer](https://chromewebstore.google.com/detail/asbplayer-language-learni/hkledmpjpaehamkiehglnbelcpdflcab)
   (v1.23 or later) and keep LinguaMiner and Anki open.
3. In LinguaMiner, open ⚙️ *Settings → Netflix and other sites*. It shows two
   addresses and the note type to use.
4. In asbplayer's settings:
   - **Misc → Enable WebSocket client**: on. **WebSocket Server URL**:
     `ws://127.0.0.1:8977/ws`. LinguaMiner's settings then say *● asbplayer
     connected*.
   - **Anki → AnkiConnect URL**: `http://127.0.0.1:8977/ankiconnect`.
   - **Anki → Note type**: the one LinguaMiner shows, usually `LinguaMiner`.
     If you installed before the rename it's `CatalaMiner`, with the same
     fields.
   - **Anki → Card fields**:

     | asbplayer | LinguaMiner note field |
     |---|---|
     | Sentence | `Frase` |
     | Word | `Paraula` |
     | Definition | `Definicio` |
     | Audio | `Audio` |
     | Image | `Imatge` |
     | Source | `Font` |

5. Optional: in asbplayer, set the image capture to an **animated WebP clip**
   so the card moves like a GIF.
6. In LinguaMiner, the study language must be the show's language. If the
   subtitles are in another one, LinguaMiner warns you.

## Mining

1. Open an episode on netflix.com with subtitles in the language you study
   (`Ctrl+Shift+F` in asbplayer chooses the track).
2. In LinguaMiner, click **🍿 Netflix** in the library. The episode opens as a
   session. The ↻ button in the reader fetches it again, for example after
   switching subtitle tracks.
3. Watch. When you hear something worth keeping, press **`Ctrl+Shift+Z`** in
   Netflix. LinguaMiner jumps to that line; click the word, then ➕ (straight
   to Anki) or ✏️ (open the editor first).
4. Or read along in LinguaMiner and mine any line. Its audio and image arrive
   a few seconds after the card, once asbplayer has recorded them.

You don't have to open the episode first. If you press `Ctrl+Shift+Z` with
nothing open, LinguaMiner creates the session from that line, and fetches
the whole episode if asbplayer is connected.

The old way still works: **`Ctrl+Shift+X`** opens asbplayer's own card
dialog, and if you type the word there, the card goes straight to Anki.
LinguaMiner still fills in the translations, definition and examples.

## What to expect

- It depends on asbplayer and on Netflix's player. When Netflix changes its
  page, asbplayer usually needs an update; check its releases if subtitles
  stop showing up.
- asbplayer can't tell LinguaMiner where the video is, so LinguaMiner doesn't
  scroll along while you watch. `Ctrl+Shift+Z` is the way to say "this line".
- If Anki is closed when you mine a line you didn't capture, the card waits
  in the queue as usual, but it won't get the Netflix audio. Capture the
  line first if you mine with Anki closed.
- Only the machine running LinguaMiner can use any of this. Other devices
  in share mode can't, and neither can web pages you open. AnkiConnect
  normally asks before a new site touches your collection, and LinguaMiner
  keeps that rule: only browser extensions, asbplayer's own site and
  localhost get through.
- Notes of any other type (yours, from other decks) go through to Anki
  untouched.
