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


@lru_cache(maxsize=6)
def _decoder(path):
    import ctranslate2
    if (path / "bpe.model").is_file():
        from sacremoses import MosesDetokenizer, MosesTokenizer
        from subword_nmt.apply_bpe import BPE
        with (path / "bpe.model").open(encoding="utf-8") as stream:
            bpe = BPE(stream)
        source, target = MosesTokenizer(lang="en"), MosesDetokenizer(lang="pl")
        def encode(phrase):
            return bpe.segment_tokens(source.tokenize(phrase))
        def decode(tokens):
            return target.detokenize(" ".join(tokens).replace("@@ ", "").split())
    else:
        import sentencepiece
        tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(path / "sentencepiece.model"))
        def encode(phrase):
            return tokenizer.encode(phrase, out_type=str)
        def decode(tokens):
            return "".join(tokens).replace("▁", " ").strip()
    model = ctranslate2.Translator(str(path / "model"), device="cpu", compute_type="int8",
                                   inter_threads=1, intra_threads=1)

    def translate(phrases):
        results = []
        for phrase in phrases:
            tokens = encode(phrase)
            chunks = [tokens[i:i+220] for i in range(0, len(tokens), 220)]
            output = model.translate_batch(chunks, beam_size=4, max_decoding_length=420,
                                           max_input_length=0, replace_unknowns=True)
            results.append(" ".join(decode(x.hypotheses[0]) for x in output))
        return results
    return translate


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
        decode = _decoder(path)

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip() or (is_english(line) and not language(line)) or not any(c.isalpha() for c in line):
            continue
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|(?<=[。！？])", line.strip()) if s]
        lines[index] = " ".join(_preserve(s,en,decode) for s,en in zip(sentences,decode(sentences)))
    return dict(english="\n".join(lines), language=LANGUAGES[code], summary=None, source="translated")


@lru_cache(maxsize=1)
def _language_detector():
    from lingua import Language, LanguageDetectorBuilder
    return LanguageDetectorBuilder.from_languages(
        Language.ENGLISH, Language.POLISH, Language.CHINESE, Language.KOREAN).build()


def _is_english_prose(text):
    if not re.search(r"[a-zA-Z]", text):
        return False
    detected = _language_detector().detect_language_of(text)
    return detected is not None and detected.name == "ENGLISH"


# Names and company details following a conventional closing belong to the signature.
SIGNATURE = re.compile(r"^(?:best regards|kind regards|regards|thank you|sincerely|pozdrawiam(?: serdecznie)?|"
                       r"z poważaniem|감사합니다|此致敬礼|此致)[,，.。!！]?[ \t]*\r?$", re.I | re.M)

# A dropped negative can turn a supplier's refusal into an apparent commitment.
NEGATIVE = re.compile(r"\b(?:cannot|can't|will not|won't|do not|does not|no(?!\.))\b", re.I)
NEGATION = {"pl": re.compile(r"\b(?:nie|bez|brak\w*|żad\w*|niemoż\w*|niedostępn\w*)\b", re.I),
            "ko": re.compile(r"없|않|아니|아닙|불가|못|금지|안\s"),
            "zh": re.compile(r"[不无無未没沒非勿零免]|禁止")}


def to_supplier(text, code):
    """Translate English prose in place. Preserve paragraph breaks and native-language text."""
    path = model_root() / f"en-{code}"
    if not (path / "model/model.bin").is_file():
        return None
    signature = ""
    for closing in reversed(list(SIGNATURE.finditer(text))):
        rest = text[closing.end():].strip().splitlines()
        # A short sentence under "Thank you" can still be part of the request.
        if len(rest) <= 4 and all(
            "@" in line or all(not word[:1].islower() or word in {"de", "van", "von", "z", "o.o."}
                               for word in line.split()) for line in rest
        ):
            text, signature = text[:closing.end()], text[closing.end():]
            break
    parts = re.split(r"(\r?\n+|(?<=[.!?])[\t ]+|(?<=[。！？]))", text)
    positions = [i for i in range(0, len(parts), 2) if _is_english_prose(parts[i])]
    if positions:
        with _LOAD:
            translate = _decoder(path)
        phrases = [parts[i] for i in positions]
        for i, phrase, result in zip(positions, phrases, translate(phrases), strict=True):
            result = _preserve(phrase, result, translate)
            if not result.strip() or (len(phrase.split()) >= 4 and _is_english_prose(result)):
                return None
            if NEGATIVE.search(phrase) and not NEGATION[code].search(result):
                return None
            parts[i] = result
    return "".join(parts) + signature
