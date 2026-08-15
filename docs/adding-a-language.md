# Adding a language

Short version: adding a language is mostly one entry in
[`app/languages.py`](../app/languages.py). Whether that entry can exist at all
depends on whether five open datasets cover your language, and I can't will
them into being.

Check yours in one command:

```bash
.venv/bin/python scripts/check-language.py ru zh bn
```

## What a language needs

| Piece | What it does | Without it |
|---|---|---|
| **Whisper** | transcribes the audio | nothing works, hard stop |
| **OPUS-MT** translator (→es or →en) | translates the sentence on the card | nothing works, hard stop |
| **wordfreq** | word frequency | the i+1 recommendation can't tell a word worth learning from a rare one |
| **spaCy** model | lemma + part of speech | word forms don't group together, and proper nouns get recommended |
| **Piper** voice | neural pronunciation | no TTS button; everything else fine |

The first two decide whether a language is possible. The next two decide
whether it arrives complete or crippled.

**Why spaCy matters more than it looks.** The whole point of the
recommendation is that a word must be unknown, *frequent enough*, and *not a
proper noun*. Frequency comes from wordfreq, "not a proper noun" comes from
spaCy's POS tagger. Drop spaCy and you're back to the naive version that
recommends every name in the show. There's a regex fallback tokenizer, but it
only splits on spaces and gives no lemma.

**One language where the fallback is fatal.** Chinese doesn't put spaces
between words. Run the regex tokenizer on 我昨天晚上看了一部很好的电影。 and you
get a single token, the entire sentence. Chinese only works because
`zh_core_web_sm` exists and does the segmentation, which is why its profile
carries `spacy_required`. Bulgarian, by contrast, degrades gracefully: the
regex splits it fine, you just lose the lemmas.

**And one where frequency needs an extra.** wordfreq can't tokenize Chinese
without `jieba`, and it doesn't complain — it just returns 0 for every word,
which silently switches off the whole i+1 recommendation. That's why the
project depends on `wordfreq[jieba]` rather than plain `wordfreq`. If you add a
CJK language, check `zipf_frequency` returns something non-zero before you
believe it works.

## Where the requested languages stand

Measured August 2026 with the script above.

| Language | Whisper | →es | →en | wordfreq | spaCy | Verdict |
|---|---|---|---|---|---|---|
| Italian | yes | yes | yes | yes | yes | **shipped** |
| Dutch | yes | no | yes | yes | yes | **shipped**, English base only |
| Russian | yes | no | yes | yes | yes | **shipped**, English base only |
| Chinese | yes | no | yes | yes | yes | **shipped**, English base only |
| Cantonese | yes | **no** | **no** | borrows `zh` | borrows `zh` | **shipped** via NLLB, see below |
| Bulgarian | yes | yes | yes | yes | **no** | possible but no lemmas |
| Bengali | yes | no | yes | yes | **no** | possible but no lemmas, English base |
| Telugu | yes | **no** | **no** | **no** | **no** | blocked, no translator |
| Kazakh | yes | **no** | **no** | **no** | **no** | blocked, no translator |

### Cantonese, and the third way to get a translator

Cantonese has no OPUS-MT model in any direction, which by the rules above
should have made it impossible. It isn't, because **NLLB-200 covers 200
languages** including `yue_Hant`, and someone has already converted it to
CTranslate2. So a profile can declare an NLLB pair instead of an OPUS one:

```python
"translate_bases": {
    "en": {"repo": "JustFrederik/nllb-200-distilled-600M-ct2-int8",
           "dir": "translate-nllb-600m",
           "nllb": {"src": "yue_Hant", "tgt": "eng_Latn"}},
},
```

NLLB is invoked differently from OPUS-MT: the *source* language token goes at
the start of the input, and the target language is forced as a decoder prefix
rather than being a single token. `_Engine` handles both.

It's worth being blunt about what Cantonese does and doesn't get:

- **Transcription: good.** There are Whisper models fine-tuned on Cantonese and
  already converted to CTranslate2. Generic Whisper transcribes Cantonese as if
  it were Mandarin, so this matters.
- **Translation: good.** 我尋日睇咗一齣好好睇嘅電影。 comes out as "I saw a really
  good movie yesterday" — that's real Cantonese vocabulary (尋日, 睇咗, 嘅), not
  Mandarin.
- **Segmentation: approximate.** There is no Cantonese spaCy model, so
  `zh_core_web_sm` does the work and it was trained on Mandarin. It splits 睇咗
  as one unit instead of verb + perfective particle, and mislabels some parts
  of speech.
- **Frequencies: approximate.** wordfreq has no `yue` list. The `zh` one covers
  traditional characters and even some Cantonese-only words (睇 3.38, 唔 4.10),
  but those are Chinese-wide numbers, so words that are everyday in spoken
  Cantonese score lower than they should. Recommendations work; they're just
  biased.
- **No TTS.** rhasspy/piper-voices has no Cantonese voice, so `piper_voice` is
  `None` and the pronunciation button stays quiet.

If a Cantonese spaCy model or a `yue` frequency list ever appears, both are a
one-line change in the profile.

Telugu and Kazakh aren't a matter of effort. There is no OPUS-MT model for
either, so there is nothing to translate the sentence with. If one appears, or
if you know of another offline-capable model, open an issue and I'll look.

For Bulgarian and Bengali the missing piece is a lemmatizer. spaCy has no model
for either. [Stanza](https://stanfordnlp.github.io/stanza/) covers both and
would slot in behind the same interface, but it's a second NLP stack to install
and I haven't done that work.

## Actually adding one

Copy an existing profile in `app/languages.py`. Italian is the good template
for a Romance language, Russian for one that only has an English base.

```python
"it": {
    "name": "Italiano",
    "wordfreq": "it",
    "espeak": "it",
    "spacy": "it_core_news_sm",
    "whisper_models": {"large-v3": "large-v3", "small": "small"},
    "default_whisper": "large-v3",
    "translate_repo": None,
    "translate_zip": "https://…/itc-itc/opus-2020-07-07.zip",
    "translate_token": ">>spa<<",
    "translate_eos": True,
    "translate_dir": "translate-ita-spa",
    "piper_voice": "it/it_IT/paola/medium/it_IT-paola-medium.onnx",
    "translate_bases": {
        "en": {"repo": "gaudi/opus-mt-it-en-ctranslate2",
               "dir": "translate-ita-eng", "eos": True},
    },
},
```

Three ways to get a translator, in order of preference:

1. **A prebuilt CTranslate2 model** on Hugging Face → `translate_repo`.
2. **A Marian zip** from Tatoeba-MT-models → `translate_zip`. It gets converted
   locally without torch. Multilingual models also need `translate_token`
   (`>>spa<<`) to pick the target.
3. Nothing exists → the language can't be added yet.

Italian uses the same multilingual Romance model as Portuguese and just changes
the target token, so if you already study Portuguese the download is reused.

If a language has no →es translator, leave `translate_repo` and
`translate_zip` as `None` and declare only `translate_bases`. `bases()` works
that out on its own and the Spanish option stops being offered.

Finally, add the display name to `static/i18n.js` under `lang.<code>` in all
three UI languages. `tests/test_i18n.py` fails if you forget one.
