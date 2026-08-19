# The reader: what to take from LingQ, and what not to

Research notes and design decisions for reading books and articles in
LinguaMiner, the way you already watch video. Written before the code so the
choices are on the record.

## Why LingQ is the model

Video mining and reading are the same loop: meet a word in context, decide if
you know it, save the ones worth saving. LingQ has run that loop over text for
fifteen years, so its ergonomics are worth studying — including the parts
people complain about.

Everything below is about *mechanics*. "LingQ" is their name for a saved word
and it stays theirs; the concepts (word states, page-based reading, known-word
counts) are the common vocabulary of the whole field.

## How LingQ actually works

Word states, from [their docs](https://lingq-support.groovehq.com/help/how-do-i-create-lingqs):

| Colour | Meaning |
|---|---|
| **Blue** | new — never seen in any content |
| **Yellow** | a saved word, with a meaning attached; shades track levels 1–4 |
| **White** | known, or ignored (names, places) |

The loop: click a blue word → pick from up to 3 suggested meanings → it turns
yellow. `K` marks known, `X` ignores. Reading happens in **pages**, and
**turning the page silently marks every remaining blue word as Known.**

That last rule is the engine of the whole product. It is also the thing people
argue about, because it inflates the known-word count — the number LingQ uses
as its main progress metric.

## What we already have

More than expected. The app's word states map almost one to one:

| LingQ | LinguaMiner | 
|---|---|
| blue (new) | `unknown` — red underline |
| yellow (saved) | `learning` — orange |
| white (known) | `known` — no mark |
| ignored | `ignored` — grey |
| — | `tracking` — no LingQ equivalent |

Shortcuts `1`–`5` already set these, the states are stored per lemma and shared
across all content, and the popup already shows definitions, frequency, part of
speech and pronunciation. **The reader does not need a new vocabulary system.
It needs a new way to display text.**

## Decisions

### Copy

**Pages, not infinite scroll.** A finite page is a unit you can finish. Endless
scroll through a novel gives you nowhere to stop.

**Sentence mode.** One sentence at a time, with TTS. LingQ users reach for it
constantly, and we already have Piper for the audio.

**Import from real formats.** LingQ takes EPUB, PDF, DOCX, TXT and MOBI. EPUB
and TXT cover most of it; EPUB is a zip of XHTML, so no heavy dependency.

**Remember the position.** Sounds obvious. It's one of the
[loudest complaints](https://forum.lingq.com/t/some-issues-with-the-web-reader/2621677)
about their reader: it drops you back on page one.

### Adapt

**Turning the page marks the rest known — but ask first, and make it undoable.**
The mechanic is genuinely good: it clears the noise so the next page shows only
what's new. Doing it silently is what makes people distrust their own numbers.
So: a visible count ("mark the remaining 14 words as known?"), off by default,
and one-click undo.

**The known-word count is a metric, not a score.** LingQ makes it the headline
number and users optimise for it. We already show "% of this content you know",
which is the more useful framing: it answers *is this readable for me* rather
than *how big is my number*.

### Don't copy

**Their SRS.** LingQ's own users describe the review queue
[spiralling out of control](https://lingtuitive.com/blog/lingq-review). We send
cards to Anki, which is better at this than either of us and already holds the
user's schedule.

**Suggested meanings from other users.** LingQ shows up to three community
definitions. We have Wiktionary, Apertium, user dictionaries and neural
translation of the actual sentence — offline, and no account.

**Their word segmentation.** Chinese is
[a known weak spot](https://lingtuitive.com/blog/lingq-review) for them. We
already run spaCy plus jieba/MeCab per language, and there are tests pinning
that down.

### Where we should be better

**LingQ shows you every unknown word. It never tells you which ones are worth
your time.** That is exactly the problem the i+1 recommendation solves: a word
is highlighted only when it is unknown *and* frequent enough *and* not a proper
noun. In a novel, where a page can hold forty new words, that filter matters
more than it does in a subtitle.

If the reader ships with the recommendation already working, it isn't a LingQ
clone with a lower price — it does something LingQ doesn't.

## Plan

1. **Import.** `.txt` and `.epub` → sentences, reusing `subs.parse_subtitles`'s
   downstream path. Sessions get `source_type="text"` and segments without
   timestamps.
2. **Reading view.** Paginated text with the same clickable tokens and the same
   popup. Position saved per session, as video position already is.
3. **Cards without video.** `_build_preview` skips the frame and the clip;
   audio comes from Piper. Cards already tolerate an empty `audio_file`, so
   this path partly exists.
4. **Sentence mode and page turn.** Once the basics read well.

Steps 1 and 2 are the ones that decide whether this is worth having.

## What shipped

All four steps. Import is `.txt`/`.epub` (v1.27.0), the reading view reuses the
player's tokens, popup and word colours unchanged (v1.27.0), cards come out
with Piper audio and no video frame (v1.28.0), and sentence mode plus the page
turn landed in v1.29.0.

Two things came out of building step 4 that the research didn't predict.

**The reader had no keyboard at all.** Its buttons had advertised `A`/`←` and
`D`/`→` since the day it shipped, but the global `keydown` handler returned
early unless the *player* was visible, so none of them did anything. It now
shares the same remappable map: page turn, word states `1`–`5`, `Q` to mine,
`S` to hear the sentence. Keys that mean nothing here — pause, subtitles,
fullscreen — simply do nothing.

**No toast was visible while reading.** `#toast` lived inside
`<main id="player">`, which the reader hides, so every notice inherited a
hidden ancestor: word-state changes, errors, and the undo button this feature
depends on. It is now a child of `<body>`, with a test that fails if anything
nests it again.

Both were invisible from the player, which is where the reader was tested.
