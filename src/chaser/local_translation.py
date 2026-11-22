"""CPU-only Argos translation for supplier correspondence on the Manti host."""
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
import os
from pathlib import Path
import re
from threading import Lock

LANGUAGES = {"pl": "Polish", "zh": "Chinese", "ko": "Korean"}
HANGUL = re.compile(r"[\uac00-\ud7a3]")
HAN = re.compile(r"[\u3400-\u9fff]")
POLISH = re.compile(r"[ąćęłńóśźż]|\b(dostawa|sztuk|prosimy|oferta|potwierdzenie)\b", re.I)
_LOAD = Lock()


def model_root():
    return Path(os.environ.get("SOONY_TRANSLATION_MODELS", "/opt/lio/translation-models"))


def language(text, hint=None):
    if HANGUL.search(text):
        return "ko"
    if HAN.search(text):
        return "zh"
    if POLISH.search(text):
        return "pl"
    return hint


@lru_cache(maxsize=3)
def _model(path):
    import ctranslate2
    import sentencepiece
    tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(path / "sentencepiece.model"))
    model = ctranslate2.Translator(str(path / "model"), device="cpu", compute_type="int8",
                                   inter_threads=1, intra_threads=1)
    return tokenizer, model


# Item keys, PO numbers, prices, quantities and times must survive neural decoding verbatim.
REFERENCE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z0-9]+(?:-[A-Z0-9]+)+|"
                       r"(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]+|"
                       r"[0-9]+(?:[ \u00a0][0-9]{3}(?![0-9])|[.,:/-][0-9]+)*)(?![A-Za-z0-9])")


def references_preserved(source, english):
    return not (Counter(REFERENCE.findall(source)) - Counter(REFERENCE.findall(english)))


def _preserve(source, english, translate_fragments):
    expected = list(REFERENCE.finditer(source))
    if not expected or references_preserved(source, english):
        return english
    # A single nearly identical changed reference can be repaired in place,
    # retaining the model's natural English word order and sentence structure.
    got = list(REFERENCE.finditer(english))
    needed = Counter(m[0] for m in expected) - Counter(m[0] for m in got)
    extra = Counter(m[0] for m in got) - Counter(m[0] for m in expected)
    if sum(needed.values()) == sum(extra.values()) == 1:
        missing, wrong = next(iter(needed)), next(iter(extra))
        if sum(m[0] == wrong for m in got) == 1 and SequenceMatcher(None, missing, wrong).ratio() >= 0.7:
            hit = next(m for m in got if m[0] == wrong)
            return english[:hit.start()] + missing + english[hit.end():]
    # If the model omitted, split or rewrote more terms, keep the source
    # tokens outside inference and translate only the surrounding phrases.
    phrases = []
    offset = 0
    for match in expected:
        phrases.append(source[offset:match.start()].strip())
        offset = match.end()
    phrases.append(source[offset:].strip())
    positions = [i for i, phrase in enumerate(phrases) if any(c.isalpha() for c in phrase)]
    for index, result in zip(positions, translate_fragments([phrases[i] for i in positions])):
        phrases[index] = result
    pieces = [part for pair in zip(phrases, [m[0] for m in expected]) for part in pair]
    return " ".join(part for part in [*pieces,phrases[-1]] if part)


def to_english(text, hint, is_english):
    code = language(text, hint)
    path = model_root() / code if code in LANGUAGES else None
    if path is None or not (path / "model/model.bin").is_file():
        return None
    with _LOAD:
        tokenizer, model = _model(path)

    def decode(phrases):
        results = []
        for phrase in phrases:
            tokens = tokenizer.encode(phrase, out_type=str)
            chunks = [tokens[i:i+220] for i in range(0, len(tokens), 220)]
            output = model.translate_batch(chunks, beam_size=4, max_decoding_length=420,
                                           max_input_length=0, replace_unknowns=True)
            results.append(" ".join("".join(x.hypotheses[0]).replace("▁", " ").strip() for x in output))
        return results

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip() or (is_english(line) and not language(line)) or not any(c.isalpha() for c in line):
            continue
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|(?<=[。！？])", line.strip()) if s]
        lines[index] = " ".join(_preserve(s,en,decode) for s,en in zip(sentences,decode(sentences)))
    return dict(english="\n".join(lines), language=LANGUAGES[code], summary=None, source="translated")
