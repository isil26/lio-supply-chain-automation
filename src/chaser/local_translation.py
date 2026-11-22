"""CPU-only Argos translation for supplier correspondence on the Manti host."""
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


def to_english(text, hint, is_english):
    code = language(text, hint)
    path = model_root() / code if code in LANGUAGES else None
    if path is None or not (path / "model/model.bin").is_file():
        return None
    with _LOAD:
        tokenizer, model = _model(path)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip() or (is_english(line) and not language(line)) or not any(c.isalpha() for c in line):
            continue
        sentences = re.split(r"(?<=[.!?])\s+|(?<=[。！？])", line.strip())
        batches = []
        for sentence in sentences:
            tokens = tokenizer.encode(sentence, out_type=str)
            batches.extend(tokens[i:i+220] for i in range(0, len(tokens), 220))
        if batches:
            output = model.translate_batch(batches, beam_size=4, max_decoding_length=420,
                                           max_input_length=0, replace_unknowns=True)
            lines[index] = " ".join("".join(x.hypotheses[0]).replace("▁", " ").strip() for x in output)
    return dict(english="\n".join(lines), language=LANGUAGES[code], summary=None, source="translated")
