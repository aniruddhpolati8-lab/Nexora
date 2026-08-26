
from __future__ import annotations

import ast
import json
import math
import os
import re
import threading
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable


# ============================================================
# CONFIGURATION
# ============================================================

DATA_FILE = os.environ.get(
    "NEXORA_DATA_FILE",
    "nexora_data.json",
)

MAX_KEY_LENGTH = 200
MAX_VALUE_LENGTH = 4000
MAX_RESULTS = 10

LOCK = threading.RLock()


# ============================================================
# DATA MODELS
# ============================================================

@dataclass(frozen=True)
class KnowledgeEntry:
    topic: str
    answer: str
    keywords: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    category: str = "general"


@dataclass(frozen=True)
class KnowledgeResult:
    found: bool
    answer: str = ""
    topic: str = ""
    category: str = ""
    confidence: float = 0.0
    source: str = ""


# ============================================================
# BUILT-IN KNOWLEDGE
# ============================================================

KNOWLEDGE: tuple[KnowledgeEntry, ...] = (

    # ---------------- SCIENCE ----------------

    KnowledgeEntry(
        "photosynthesis",
        (
            "Photosynthesis is the process plants use to make food. "
            "Plants use light energy, water, and carbon dioxide to produce "
            "glucose and oxygen. It mainly takes place in chloroplasts, "
            "which contain the pigment chlorophyll."
        ),
        (
            "photosynthesis",
            "plants",
            "light",
            "glucose",
            "chlorophyll",
            "carbon dioxide",
        ),
        (
            "what is photosynthesis",
            "how does photosynthesis work",
            "explain photosynthesis",
        ),
        "science",
    ),

    KnowledgeEntry(
        "gravity",
        (
            "Gravity is an attractive force between objects that have mass. "
            "Near Earth's surface, gravity causes objects to accelerate "
            "towards Earth at about 9.81 metres per second squared."
        ),
        (
            "gravity",
            "gravitational",
            "force",
            "earth",
            "mass",
            "weight",
        ),
        (
            "what is gravity",
            "how does gravity work",
            "explain gravity",
        ),
        "science",
    ),

    KnowledgeEntry(
        "atoms",
        (
            "An atom is the basic unit of an element. It contains a nucleus "
            "made of protons and neutrons, with electrons occupying regions "
            "around the nucleus. Protons are positive, electrons are "
            "negative, and neutrons have no electric charge."
        ),
        (
            "atom",
            "atoms",
            "proton",
            "neutron",
            "electron",
            "element",
        ),
        (
            "what is an atom",
            "what are atoms",
            "explain atoms",
        ),
        "science",
    ),

    KnowledgeEntry(
        "energy",
        (
            "Energy is the capacity to cause change or do work. Common "
            "forms include kinetic, gravitational potential, chemical, "
            "thermal, electrical, and light energy. Energy can be "
            "transferred or transformed, but it is conserved."
        ),
        (
            "energy",
            "kinetic",
            "potential",
            "thermal",
            "chemical",
            "electrical",
            "light",
        ),
        (
            "what is energy",
            "forms of energy",
            "types of energy",
        ),
        "physics",
    ),

    KnowledgeEntry(
        "speed",
        (
            "Speed describes how quickly distance is travelled. The basic "
            "formula is speed = distance ÷ time. For example, travelling "
            "100 metres in 20 seconds gives an average speed of 5 metres "
            "per second."
        ),
        (
            "speed",
            "distance",
            "time",
            "velocity",
        ),
        (
            "what is speed",
            "speed formula",
            "how do you calculate speed",
        ),
        "physics",
    ),

    KnowledgeEntry(
        "water cycle",
        (
            "The water cycle describes the continuous movement of water "
            "around Earth. Major processes include evaporation, "
            "condensation, precipitation, and collection."
        ),
        (
            "water",
            "cycle",
            "evaporation",
            "condensation",
            "precipitation",
        ),
        (
            "what is the water cycle",
            "explain the water cycle",
        ),
        "science",
    ),

    # ---------------- BIOLOGY ----------------

    KnowledgeEntry(
        "cell",
        (
            "A cell is the basic structural and functional unit of living "
            "organisms. Animal and plant cells contain structures such as "
            "a cell membrane, cytoplasm, and nucleus. Plant cells also "
            "contain a cell wall, chloroplasts, and a large permanent "
            "vacuole."
        ),
        (
            "cell",
            "cells",
            "biology",
            "plant cell",
            "animal cell",
            "nucleus",
            "cytoplasm",
        ),
        (
            "what is a cell",
            "what are cells",
            "explain cells",
        ),
        "biology",
    ),

    KnowledgeEntry(
        "dna",
        (
            "DNA stands for deoxyribonucleic acid. It is a molecule that "
            "stores genetic information and contains instructions used "
            "by living organisms for development and normal biological "
            "functions."
        ),
        (
            "dna",
            "genetics",
            "gene",
            "genetic",
        ),
        (
            "what is dna",
            "what does dna do",
            "explain dna",
        ),
        "biology",
    ),

    # ---------------- ASTRONOMY ----------------

    KnowledgeEntry(
        "solar system",
        (
            "The Solar System consists of the Sun and the objects that "
            "orbit it, including eight recognised planets, dwarf planets, "
            "moons, asteroids, and comets. The planets in order from the "
            "Sun are Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, "
            "and Neptune."
        ),
        (
            "solar",
            "system",
            "planets",
            "sun",
            "earth",
            "astronomy",
        ),
        (
            "what is the solar system",
            "what are the planets",
            "planets in order",
        ),
        "astronomy",
    ),

    # ---------------- MATHEMATICS ----------------

    KnowledgeEntry(
        "fraction",
        (
            "A fraction represents part of a whole. The top number is "
            "called the numerator and the bottom number is called the "
            "denominator. For example, 3/4 represents three parts out "
            "of four equal parts."
        ),
        (
            "fraction",
            "fractions",
            "numerator",
            "denominator",
        ),
        (
            "what is a fraction",
            "what are fractions",
            "explain fractions",
        ),
        "mathematics",
    ),

    KnowledgeEntry(
        "prime number",
        (
            "A prime number is a whole number greater than 1 with exactly "
            "two positive factors: 1 and itself. Examples include 2, 3, "
            "5, 7, 11, and 13. The number 2 is the only even prime."
        ),
        (
            "prime",
            "number",
            "primes",
            "factors",
        ),
        (
            "what is a prime number",
            "what are prime numbers",
            "explain prime numbers",
        ),
        "mathematics",
    ),

    KnowledgeEntry(
        "pythagorean theorem",
        (
            "The Pythagorean theorem applies to right-angled triangles. "
            "It states that a² + b² = c², where a and b are the shorter "
            "sides and c is the hypotenuse."
        ),
        (
            "pythagorean",
            "pythagoras",
            "triangle",
            "hypotenuse",
        ),
        (
            "what is pythagoras",
            "pythagorean theorem",
            "explain pythagoras",
        ),
        "mathematics",
    ),

    # ---------------- GEOGRAPHY ----------------

    KnowledgeEntry(
        "capital of france",
        "The capital of France is Paris.",
        (
            "france",
            "capital",
            "paris",
        ),
        (
            "what is the capital of france",
            "capital city of france",
        ),
        "geography",
    ),

    KnowledgeEntry(
        "capital of united kingdom",
        "The capital of the United Kingdom is London.",
        (
            "uk",
            "united",
            "kingdom",
            "britain",
            "capital",
            "london",
        ),
        (
            "what is the capital of the uk",
            "capital of britain",
            "capital of united kingdom",
        ),
        "geography",
    ),

    KnowledgeEntry(
        "continents",
        (
            "The commonly taught seven-continent model consists of "
            "Africa, Antarctica, Asia, Europe, North America, South "
            "America, and Australia or Oceania."
        ),
        (
            "continents",
            "continent",
            "africa",
            "asia",
            "europe",
        ),
        (
            "what are the continents",
            "name the continents",
            "seven continents",
        ),
        "geography",
    ),

    # ---------------- HISTORY ----------------

    KnowledgeEntry(
        "ancient egypt",
        (
            "Ancient Egypt was a civilisation centred along the Nile River. "
            "It is known for its pharaohs, pyramids, hieroglyphic writing, "
            "religious traditions, engineering, and long history."
        ),
        (
            "egypt",
            "ancient",
            "pharaoh",
            "pyramids",
            "nile",
            "hieroglyphs",
        ),
        (
            "what was ancient egypt",
            "tell me about ancient egypt",
        ),
        "history",
    ),

    KnowledgeEntry(
        "roman empire",
        (
            "The Roman Empire was a large state centred on Rome that "
            "controlled extensive territories around the Mediterranean "
            "and beyond. Roman influence can still be seen in law, "
            "language, engineering, architecture, and government."
        ),
        (
            "rome",
            "roman",
            "romans",
            "empire",
        ),
        (
            "what was the roman empire",
            "tell me about rome",
            "explain the roman empire",
        ),
        "history",
    ),

    # ---------------- COMPUTING ----------------

    KnowledgeEntry(
        "algorithm",
        (
            "An algorithm is a defined sequence of steps for solving a "
            "problem or completing a task. Algorithms are used throughout "
            "computer science, including searching, sorting, and data "
            "processing."
        ),
        (
            "algorithm",
            "algorithms",
            "computer",
            "programming",
            "steps",
        ),
        (
            "what is an algorithm",
            "what are algorithms",
            "explain algorithms",
        ),
        "computing",
    ),

    KnowledgeEntry(
        "python",
        (
            "Python is a general-purpose programming language known for "
            "its relatively clear syntax. It is used for software "
            "development, automation, education, data analysis, science, "
            "and many other tasks."
        ),
        (
            "python",
            "programming",
            "language",
            "code",
        ),
        (
            "what is python",
            "what is the python programming language",
        ),
        "computing",
    ),

    KnowledgeEntry(
        "api",
        (
            "API stands for Application Programming Interface. An API "
            "defines a way for software systems to communicate and "
            "exchange information or request operations."
        ),
        (
            "api",
            "application",
            "programming",
            "interface",
            "software",
        ),
        (
            "what is an api",
            "what does api mean",
        ),
        "computing",
    ),
)


# ============================================================
# SECRET PROTECTION
# ============================================================

SECRET_PATTERNS = (
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
    r"\bAIza[A-Za-z0-9_-]{20,}\b",
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
    r"\bpassword\s*[:=]\s*\S+",
    r"\bapi[_-]?key\s*[:=]\s*\S+",
    r"\bsecret\s*[:=]\s*\S+",
    r"\bbearer\s+[A-Za-z0-9._-]{20,}",
)


def contains_secret(text: str) -> bool:
    if not isinstance(text, str):
        return False

    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE,
        )
        for pattern in SECRET_PATTERNS
    )


# ============================================================
# DATA STORAGE
# ============================================================

def _default_data() -> dict:
    return {
        "memories": [],
        "knowledge": {},
        "settings": {},
    }


def _load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return _default_data()

    try:
        with open(
            DATA_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return _default_data()

        data.setdefault("memories", [])
        data.setdefault("knowledge", {})
        data.setdefault("settings", {})

        return data

    except (
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        return _default_data()


def _save_data(data: dict) -> bool:
    temporary = DATA_FILE + ".tmp"

    try:
        directory = os.path.dirname(
            os.path.abspath(DATA_FILE)
        )

        os.makedirs(
            directory,
            exist_ok=True,
        )

        with open(
            temporary,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False,
            )

        os.replace(
            temporary,
            DATA_FILE,
        )

        return True

    except OSError:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass

        return False


# ============================================================
# TEXT PROCESSING
# ============================================================

STOP_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "am",
    "was",
    "were",
    "what",
    "who",
    "why",
    "how",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "please",
    "tell",
    "me",
    "about",
    "explain",
    "define",
    "meaning",
    "of",
    "to",
    "for",
    "in",
    "on",
    "and",
    "or",
    "with",
    "it",
    "this",
    "that",
}


def normalise(text: str) -> str:
    if not isinstance(text, str):
        return ""

    text = text.lower().strip()

    replacements = {
        "what's": "what is",
        "whats": "what is",
        "who's": "who is",
        "whos": "who is",
        "how's": "how is",
        "hows": "how is",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def tokens(text: str) -> set[str]:
    return {
        word
        for word in normalise(text).split()
        if word not in STOP_WORDS
    }


def similarity(a: str, b: str) -> float:
    na = normalise(a)
    nb = normalise(b)

    if not na or not nb:
        return 0.0

    direct = SequenceMatcher(
        None,
        na,
        nb,
    ).ratio()

    ta = tokens(na)
    tb = tokens(nb)

    if not ta or not tb:
        return direct

    intersection = len(ta & tb)
    union = len(ta | tb)

    token_score = (
        intersection / union
        if union
        else 0.0
    )

    return (
        direct * 0.45
        + token_score * 0.55
    )


def keyword_score(
    text: str,
    entry: KnowledgeEntry,
) -> float:

    input_tokens = tokens(text)

    if not input_tokens:
        return 0.0

    keyword_tokens: set[str] = set()

    for keyword in entry.keywords:
        keyword_tokens.update(
            tokens(keyword)
        )

    if not keyword_tokens:
        return 0.0

    matches = input_tokens & keyword_tokens

    return min(
        1.0,
        len(matches)
        / max(
            1,
            len(keyword_tokens) * 0.45,
        ),
    )


# ============================================================
# KNOWLEDGE ENGINE
# ============================================================

class KnowledgeEngine:

    def __init__(
        self,
        entries: Iterable[KnowledgeEntry] = KNOWLEDGE,
    ) -> None:

        self.entries = tuple(entries)

        self._aliases: dict[
            str,
            KnowledgeEntry,
        ] = {}

        for entry in self.entries:
            self._aliases[
                normalise(entry.topic)
            ] = entry

            for alias in entry.aliases:
                self._aliases[
                    normalise(alias)
                ] = entry

    # --------------------------------------------------------
    # PERSISTENT KNOWLEDGE
    # --------------------------------------------------------

    def add(
        self,
        key: str,
        value: str,
    ) -> bool:

        if not isinstance(key, str):
            return False

        if not isinstance(value, str):
            return False

        key = key.strip()
        value = value.strip()

        if not key or not value:
            return False

        if len(key) > MAX_KEY_LENGTH:
            return False

        if len(value) > MAX_VALUE_LENGTH:
            return False

        if contains_secret(key):
            return False

        if contains_secret(value):
            return False

        with LOCK:
            data = _load_data()

            knowledge = data.get(
                "knowledge",
                {},
            )

            if not isinstance(
                knowledge,
                dict,
            ):
                knowledge = {}

            knowledge[
                normalise(key)
            ] = value

            data["knowledge"] = knowledge

            return _save_data(data)

    def get(
        self,
        key: str,
    ) -> str | None:

        if not isinstance(key, str):
            return None

        clean_key = normalise(key)

        if not clean_key:
            return None

        with LOCK:
            data = _load_data()

            knowledge = data.get(
                "knowledge",
                {},
            )

            if not isinstance(
                knowledge,
                dict,
            ):
                return None

            value = knowledge.get(
                clean_key
            )

            return (
                str(value)
                if isinstance(value, str)
                else None
            )

    def all(self) -> dict[str, str]:

        with LOCK:
            data = _load_data()

            knowledge = data.get(
                "knowledge",
                {},
            )

            if not isinstance(
                knowledge,
                dict,
            ):
                return {}

            return {
                str(key): str(value)
                for key, value
                in knowledge.items()
                if isinstance(
                    key,
                    str,
                )
            }

    def delete(
        self,
        key: str,
    ) -> bool:

        if not isinstance(key, str):
            return False

        clean_key = normalise(key)

        if not clean_key:
            return False

        with LOCK:
            data = _load_data()

            knowledge = data.get(
                "knowledge",
                {},
            )

            if not isinstance(
                knowledge,
                dict,
            ):
                return False

            if clean_key not in knowledge:
                return False

            del knowledge[clean_key]

            data["knowledge"] = knowledge

            return _save_data(data)

    def clear(self) -> bool:

        with LOCK:
            data = _load_data()

            data["knowledge"] = {}

            return _save_data(data)

    # --------------------------------------------------------
    # LOOKUP
    # --------------------------------------------------------

    def lookup(
        self,
        query: str,
    ) -> KnowledgeResult:

        if not isinstance(query, str):
            return KnowledgeResult(False)

        query = normalise(query)

        if not query:
            return KnowledgeResult(False)

        # Exact built-in topic/alias.
        exact = self._aliases.get(query)

        if exact is not None:
            return KnowledgeResult(
                found=True,
                answer=exact.answer,
                topic=exact.topic,
                category=exact.category,
                confidence=1.0,
                source="built-in",
            )

        # Exact persistent knowledge.
        persistent = self.get(query)

        if persistent is not None:
            return KnowledgeResult(
                found=True,
                answer=persistent,
                topic=query,
                category="learned",
                confidence=1.0,
                source="learned",
            )

        best_entry: KnowledgeEntry | None = None
        best_score = 0.0

        # Built-in knowledge scoring.
        for entry in self.entries:

            topic_score = similarity(
                query,
                entry.topic,
            )

            alias_score = max(
                (
                    similarity(
                        query,
                        alias,
                    )
                    for alias in entry.aliases
                ),
                default=0.0,
            )

            key_score = keyword_score(
                query,
                entry,
            )

            score = (
                topic_score * 0.35
                + alias_score * 0.40
                + key_score * 0.25
            )

            if score > best_score:
                best_score = score
                best_entry = entry

        # Persistent knowledge scoring.
        for key, value in self.all().items():

            key_score = similarity(
                query,
                key,
            )

            value_score = similarity(
                query,
                value,
            )

            score = (
                key_score * 0.75
                + value_score * 0.25
            )

            if score > best_score:
                best_score = score
                best_entry = KnowledgeEntry(
                    topic=key,
                    answer=value,
                    category="learned",
                )

        if best_entry is None:
            return KnowledgeResult(False)

        # Conservative confidence threshold.
        if best_score >= 0.82:
            confidence = 0.95

        elif best_score >= 0.68:
            confidence = 0.82

        elif best_score >= 0.55:
            confidence = 0.65

        else:
            return KnowledgeResult(False)

        return KnowledgeResult(
            found=True,
            answer=best_entry.answer,
            topic=best_entry.topic,
            category=best_entry.category,
            confidence=confidence,
            source=(
                "learned"
                if best_entry.category == "learned"
                else "built-in"
            ),
        )

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[KnowledgeResult]:

        if not isinstance(query, str):
            return []

        query = query.strip()

        if not query:
            return []

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5

        limit = max(
            1,
            min(
                limit,
                MAX_RESULTS,
            ),
        )

        results: list[KnowledgeResult] = []

        # Built-in results.
        for entry in self.entries:

            score = max(
                similarity(
                    query,
                    entry.topic,
                ),
                max(
                    (
                        similarity(
                            query,
                            alias,
                        )
                        for alias in entry.aliases
                    ),
                    default=0.0,
                ),
            )

            if score >= 0.30:
                results.append(
                    KnowledgeResult(
                        found=True,
                        answer=entry.answer,
                        topic=entry.topic,
                        category=entry.category,
                        confidence=min(
                            1.0,
                            score,
                        ),
                        source="built-in",
                    )
                )

        # Persistent results.
        for key, value in self.all().items():

            score = max(
                similarity(
                    query,
                    key,
                ),
                similarity(
                    query,
                    value,
                ) * 0.75,
            )

            if score >= 0.30:
                results.append(
                    KnowledgeResult(
                        found=True,
                        answer=value,
                        topic=key,
                        category="learned",
                        confidence=min(
                            1.0,
                            score,
                        ),
                        source="learned",
                    )
                )

        results.sort(
            key=lambda item: item.confidence,
            reverse=True,
        )

        return results[:limit]

    # --------------------------------------------------------
    # INFORMATION
    # --------------------------------------------------------

    def categories(self) -> list[str]:
        categories = {
            entry.category
            for entry in self.entries
        }

        if self.all():
            categories.add("learned")

        return sorted(categories)

    def topics(self) -> list[str]:
        topics = {
            entry.topic
            for entry in self.entries
        }

        topics.update(
            self.all().keys()
        )

        return sorted(topics)


# ============================================================
# SAFE ARITHMETIC ENGINE
# ============================================================

_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
    ast.FloorDiv: lambda a, b: a // b,
}

_ALLOWED_UNARYOPS = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


def _evaluate_math(node: ast.AST) -> float:

    if isinstance(
        node,
        ast.Expression,
    ):
        return _evaluate_math(
            node.body
        )

    if isinstance(
        node,
        ast.Constant,
    ):
        if isinstance(
            node.value,
            bool,
        ):
            raise ValueError

        if isinstance(
            node.value,
            (int, float),
        ):
            return float(node.value)

        raise ValueError

    if isinstance(
        node,
        ast.BinOp,
    ):
        operator = type(node.op)

        function = _ALLOWED_BINOPS.get(
            operator
        )

        if function is None:
            raise ValueError

        left = _evaluate_math(
            node.left
        )

        right = _evaluate_math(
            node.right
        )

        if operator in {
            ast.Div,
            ast.Mod,
            ast.FloorDiv,
        } and right == 0:
            raise ZeroDivisionError

        # Prevent absurd exponent calculations.
        if operator is ast.Pow:
            if abs(right) > 100:
                raise ValueError

            if abs(left) > 1_000_000:
                raise ValueError

        result = function(
            left,
            right,
        )

        if not math.isfinite(result):
            raise ValueError

        return result

    if isinstance(
        node,
        ast.UnaryOp,
    ):
        function = _ALLOWED_UNARYOPS.get(
            type(node.op)
        )

        if function is None:
            raise ValueError

        return function(
            _evaluate_math(node.operand)
        )

    raise ValueError


def calculate_basic(
    expression: str,
) -> float | None:

    if not isinstance(
        expression,
        str,
    ):
        return None

    expression = expression.strip()

    if not expression:
        return None

    if len(expression) > 100:
        return None

    # Only arithmetic characters.
    if not re.fullmatch(
        r"[0-9\s+\-*/%().^]+",
        expression,
    ):
        return None

    expression = expression.replace(
        "^",
        "**",
    )

    try:
        tree = ast.parse(
            expression,
            mode="eval",
        )

        result = _evaluate_math(tree)

        if not math.isfinite(result):
            return None

        return result

    except (
        SyntaxError,
        ValueError,
        TypeError,
        ZeroDivisionError,
        OverflowError,
    ):
        return None


# ============================================================
# CONVENIENCE API
# ============================================================

_DEFAULT_ENGINE = KnowledgeEngine()


def teach(
    topic: str,
    information: str,
) -> bool:
    return _DEFAULT_ENGINE.add(
        topic,
        information,
    )


def get_knowledge(
    topic: str,
) -> str | None:
    return _DEFAULT_ENGINE.get(
        topic,
    )


def search_knowledge(
    query: str,
    limit: int = 5,
) -> list[KnowledgeResult]:
    return _DEFAULT_ENGINE.search(
        query,
        limit,
    )


def lookup_knowledge(
    query: str,
) -> KnowledgeResult:
    return _DEFAULT_ENGINE.lookup(
        query,
    )


# ============================================================
# TEST SUITE
# ============================================================

def _run_tests() -> None:

    engine = KnowledgeEngine()

    print("Nexora Knowledge Engine")
    print("=" * 40)

    # Built-in knowledge.
    result = engine.lookup(
        "What is photosynthesis?"
    )

    assert result.found
    assert result.source == "built-in"

    print("✓ Built-in knowledge")

    # Fuzzy matching.
    result = engine.lookup(
        "explain gravity"
    )

    assert result.found

    print("✓ Natural-language matching")

    # Calculator.
    assert calculate_basic(
        "25 * 48"
    ) == 1200.0

    assert calculate_basic(
        "2 ^ 8"
    ) == 256.0

    assert calculate_basic(
        "10 / 2"
    ) == 5.0

    print("✓ Safe calculator")

    # Division by zero.
    assert calculate_basic(
        "10 / 0"
    ) is None

    print("✓ Calculator safety")

    # Secret protection.
    assert contains_secret(
        "password: secret123"
    )

    print("✓ Secret detection")

    # Persistent knowledge.
    test_key = "__nexora_test_topic__"

    assert engine.add(
        test_key,
        "This is test information.",
    )

    result = engine.lookup(
        test_key
    )

    assert result.found
    assert result.source == "learned"

    engine.delete(test_key)

    print("✓ Persistent knowledge")

    print("=" * 40)
    print("All knowledge engine tests passed.")


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":
    _run_tests()

    print()
    print("Example search:")
    print()

    results = search_knowledge(
        "What is an algorithm?"
    )

    for result in results:
        print(
            f"[{result.confidence:.2f}] "
            f"{result.topic} "
            f"({result.source})"
        )
        print(
            f"  {result.answer}"
        )
One important change to your Nexora

Don't use:

result = KnowledgeEngine.search(...)

because search() is an instance method now.

Use:

from knowledge import lookup_knowledge

result = lookup_knowledge(user_input)

if result.found and result.confidence >= 0.65:
    return result.answer

Or use the shared engine:

from knowledge import _DEFAULT_ENGINE

result = _DEFAULT_ENGINE.lookup(user_input)
