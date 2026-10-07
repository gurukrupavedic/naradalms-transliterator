"""Telugu → other-script transliteration, through Aksharamukha 2.3's *string* API.

The options per target are the ones validated for the SLMTS publishing pipeline (Telugu books
converted to Kannada, Devanagari and IAST), kept identical so the output matches what those
documents already contain:

  target  Aksharamukha script  post options
  sa      Devanagari           indicDandas
  en      IAST                 AnusvaratoNasalASTISO, indicDandas
  kn      Kannada              indicDandas
  ta      Tamil                indicDandas, then visarga ꞉ → ஃ and Vedic accent marks dropped

`indicDandas` looks like a no-op (its function in PostProcess just returns the string) but the
library branches on the option's name: without it the Telugu danda `।` comes out as `.` in IAST and
Kannada. `AnusvaratoNasalASTISO` turns ṃ into ṅ/ñ/ṇ/n/m when a stop follows directly
(saṃkalpa → saṅkalpa).

Tamil script has no letters for most of Sanskrit's consonant distinctions, so Aksharamukha's
`Tamil` target writes them the way Vedic text is usually written in Tamil: Grantha letters for
ś ṣ s h kṣ jñ, and superscript digits on a base consonant for the others (க² க³ க⁴ for kh g gh).
Its other Tamil targets come out in Malayalam and Bengali letters here, so they are not used. It
writes visarga as the modifier letter colon ꞉ (U+A789), which Noto Serif Tamil has no glyph for and
which showed as a box; that is rewritten to Tamil's own ஃ (U+0B83), which the font has.

The Vedic accent marks (the Devanagari udatta and anudatta, and the Vedic Extensions block) pass
through Aksharamukha unchanged, and neither Noto Serif Tamil nor any font in its fallback stack can
attach them to a Tamil letter: they rendered as dotted circles. Tamil script has no equivalent
mark, so they are dropped from the Tamil output. In the real book they occur about sixteen times,
mostly in the Guru invocation; Telugu and Kannada keep them, as those fonts carry them.

Aksharamukha 2.3's *docx* converter swaps its pre/post option lists; the string API used here does
not, so none of that compensation applies. Operating on whole strings also avoids the docx path's
per-Word-run limitation, where an anusvara at the end of one run never sees the consonant that
starts the next.
"""

import re
import warnings
from dataclasses import dataclass

# Importing the library byte-compiles a few of its own modules, which prints SyntaxWarnings for
# code we don't control (`is` with a literal). Only first import without a cached .pyc does this.
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from aksharamukha import transliterate as _aksharamukha

SOURCE_SCRIPT = "Telugu"


@dataclass(frozen=True)
class Target:
    aksharamukha_name: str
    post_options: tuple[str, ...]
    # (regex, replacement) pairs applied to Aksharamukha's output, in order. For characters the
    # target's font cannot draw.
    replacements: tuple[tuple[str, str], ...] = ()


TARGETS: dict[str, Target] = {
    "sa": Target("Devanagari", ("indicDandas",)),
    "en": Target("IAST", ("AnusvaratoNasalASTISO", "indicDandas")),
    "kn": Target("Kannada", ("indicDandas",)),
    "ta": Target(
        "Tamil",
        ("indicDandas",),
        replacements=(
            ("\ua789", "\u0b83"),  # modifier colon -> Tamil aytham, for visarga
            ("[\u0951\u0952\u1cd0-\u1cff\ua8e0-\ua8ff]", ""),  # Vedic accent marks
        ),
    ),
}

# Vedic accent marks that can sit between an anusvara and the next consonant: the Devanagari
# anudatta/svarita, combining diacritics IAST output uses for them, and the Vedic Extensions and
# Devanagari Extended blocks.
_VEDIC_ACCENTS = "॒̱॑̀́̍̎̏᳐͞-᳿꣠-ꣿ"
_NASAL_FOR = {
    **dict.fromkeys("kg", "ṅ"),
    **dict.fromkeys("cj", "ñ"),
    **dict.fromkeys("ṭḍ", "ṇ"),
    **dict.fromkeys("td", "n"),
    **dict.fromkeys("pb", "m"),
}
_SPACED_ANUSVARA = re.compile(f"[ṃṁ](?=[{_VEDIC_ACCENTS}]*[  \t]*([kgcjṭḍtdpb]))")


def spaced_nasal(iast: str) -> str:
    """ṃ/ṁ → ṅ/ñ/ṇ/n/m before a stop, also across spaces and Vedic accents.

    "trinetraṃ bhaje" → "trinetram bhaje". Anything else in between blocks it: a danda (`|`), a
    comma, a digit, a line break. A line break matters: the ṃ that ends one verse line is not
    assimilated to the consonant that starts the next.

    Optional because it also rewrites Telugu prose and anusvara teaching examples written in IAST
    ("bhāgaṃ pai" → "bhāgam pai"), which the default rule leaves alone.
    """
    return _SPACED_ANUSVARA.sub(lambda m: _NASAL_FOR[m.group(1)], iast)


def transliterate(text: str, script: str, *, spaced_nasal_rule: bool = False) -> str:
    """One Telugu text into `script` ('sa', 'en', 'kn' or 'ta').

    `spaced_nasal_rule` only affects 'en'.
    """
    target = TARGETS[script]
    if not text.strip():
        return text

    post_options = target.post_options
    use_spaced = script == "en" and spaced_nasal_rule
    if use_spaced:
        # The spaced rule covers the adjacent case too, so it replaces the default one.
        post_options = tuple(o for o in post_options if o != "AnusvaratoNasalASTISO")

    result = _aksharamukha.process(
        SOURCE_SCRIPT,
        target.aksharamukha_name,
        text,
        nativize=True,
        post_options=list(post_options),
    )
    for pattern, replacement in target.replacements:
        result = re.sub(pattern, replacement, result)
    return spaced_nasal(result) if use_spaced else result
