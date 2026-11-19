"""Safety net for Russian `ё` before text-to-speech.

TTS reads `е` as `е`, so a missed `ё` is an audibly wrong word
("кикбоксером" instead of "кикбоксёром"). The AI is told to write `ё`
(AI_EDITING_INSTRUCTIONS.md, "Spelling for text-to-speech"), but it misses
some. This fixes the common ones right before a text is voiced.

Only unambiguous words are listed: replacing must never turn a correct word
into a wrong one. "все" can be "все" or "всё" and "королева" can be a queen,
so they are NOT here. Stems only match at the START of a word, so "актёр*"
doesn't touch "характер".

Extra words can be added in tts_yo_words.txt at the project root (same
format as below: written with ё, `*` at the end = any ending).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

USER_WORDS_PATH = Path(__file__).resolve().parent.parent / "tts_yo_words.txt"

# Written WITH ё. `*` = stem (any ending may follow), otherwise a whole word.
_BUILTIN = """
кикбоксёр* боксёр* актёр* партнёр* режиссёр* шофёр* дирижёр* стажёр* ухажёр*
гримёр* суфлёр* контролёр* монтажёр* гувернёр* вахтёр* репортёр* призёр*
ребёнок ребёнк* ребёночк* чётк* звёзды звёзд звёздам звёздами звёздах звёздн*
ещё её неё моё твоё своё моём твоём своём
шёл пошёл нашёл ушёл пришёл зашёл прошёл перешёл дошёл подошёл обошёл вошёл
идёт идём идёте идёшь пойдёт пойдём пойдёте пойдёшь придёт придём придёте
найдёт найдём найдёте найдёшь уйдёт уйдём зайдёт зайдём дойдёт дойдём
войдёт войдём пройдёт пройдём перейдёт перейдём подойдёт подойдём
живёт живём живёте живёшь поёт поём поёшь даёт даём даёте даёшь
ведёт ведём несёт несём растёт растём зовёт зовём ждёт ждём ждёте пьёт бьёт
льёт плывёт поймёт поймём пришлёт пришлём начнёт начнём
тётя тёти тёте тётю тётей
чёрн* жёлтый жёлтая жёлтое жёлтые жёлтого жёлтой жёлтым жёлтых
лёгкий лёгкая лёгкое лёгкие лёгкого лёгкой лёгким лёгких
всерьёз зачёт зачёта зачёты времён племён знамён
Фёдор Фёдора Фёдору Фёдором Фёдоре Фёдоров Фёдорова
Артём Артёма Артёму Артёмом Артёме
Семён Семёном Семёну Пётр
Хрущёв Хрущёва Горбачёв Горбачёва Соловьёв Соловьёва Пугачёв Пугачёва
Воробьёв Воробьёва
"""
# Not "чёрн*" -> would also hit "чернила" (ink) and "черника". Kept out:
_EXCLUDED_STEMS = {"чёрн"}
_BLACK = "чёрный чёрная чёрное чёрные чёрного чёрной чёрному чёрным чёрными чёрных"


def _parse(entries: str) -> tuple[dict[str, str], dict[str, str]]:
    """{е-spelling: ё-spelling} for stems and for whole words."""
    stems: dict[str, str] = {}
    words: dict[str, str] = {}
    for raw in entries.split():
        entry = raw.strip().lower()
        if "ё" not in entry:
            continue
        if entry.endswith("*"):
            stem = entry[:-1]
            if stem not in _EXCLUDED_STEMS:
                stems[stem.replace("ё", "е")] = stem
        else:
            words[entry.replace("ё", "е")] = entry
    return stems, words


def _user_entries() -> str:
    if not USER_WORDS_PATH.exists():
        return ""
    lines = USER_WORDS_PATH.read_text(encoding="utf-8").splitlines()
    return " ".join(line.split("#", 1)[0] for line in lines)


@lru_cache(maxsize=4)
def _tables(user_mtime: float) -> tuple[dict[str, str], dict[str, str]]:
    return _parse(" ".join((_BUILTIN, _BLACK, _user_entries())))


_WORD_RE = re.compile(r"[А-Яа-яЁё]+")


def _match_case(original: str, replacement: str) -> str:
    return "".join(r.upper() if o.isupper() else r for o, r in zip(original, replacement)) + replacement[
        len(original):
    ]


def add_yo(text: str) -> str:
    """Puts `ё` back into the listed words. Leaves everything else alone."""
    mtime = USER_WORDS_PATH.stat().st_mtime if USER_WORDS_PATH.exists() else 0.0
    stems, words = _tables(mtime)

    def fix(match: re.Match) -> str:
        word = match.group(0)
        lower = word.lower()
        if "ё" in lower:
            return word
        if lower in words:
            return _match_case(word, words[lower])
        for stem, target in stems.items():
            if lower.startswith(stem):
                return _match_case(word, target + lower[len(stem):])
        return word

    return _WORD_RE.sub(fix, text)
