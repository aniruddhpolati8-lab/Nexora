
from __future__ import annotations

import json
import os
import re
import threading


DATA_FILE = os.environ.get(
    "NEXORA_DATA_FILE",
    "nexora_data.json"
)

MAX_KEY_LENGTH = 200
MAX_VALUE_LENGTH = 4000
MAX_RESULTS = 10

LOCK = threading.RLock()


# ============================================================
# HELPERS
# ============================================================

def _load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return {
            "memories": [],
            "knowledge": {},
            "settings": {}
        }

    try:
        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def _save_data(data: dict) -> bool:
    temporary = DATA_FILE + ".tmp"

    try:
        directory = os.path.dirname(
            os.path.abspath(DATA_FILE)
        )

        os.makedirs(
            directory,
            exist_ok=True
        )

        with open(
            temporary,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                data,
                file,
                indent=2,
                ensure_ascii=False
            )

        os.replace(
            temporary,
            DATA_FILE
        )

        return True

    except Exception:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass

        return False


# ============================================================
# SECRET PROTECTION
# ============================================================

SECRET_PATTERNS = [
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
    r"\bAIza[A-Za-z0-9_-]{20,}\b",
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
    r"\bpassword\s*[:=]\s*\S+",
    r"\bapi[_-]?key\s*[:=]\s*\S+",
    r"\bsecret\s*[:=]\s*\S+",
    r"\bbearer\s+[A-Za-z0-9._-]{20,}",
]


def contains_secret(text: str) -> bool:
    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in SECRET_PATTERNS
    )


# ============================================================
# TEXT SEARCH
# ============================================================

STOP_WORDS = {
    "the", "a", "an", "is", "are",
    "am", "i", "you", "my", "your",
    "to", "of", "and", "or", "in",
    "on", "it", "this", "that",
    "what", "do", "does", "did",
    "for", "with", "me", "can",
    "could", "would", "should",
    "be", "have", "has", "how",
    "why", "when", "where",
    "please", "tell", "about"
}


def words(text: str) -> list[str]:
    return [
        word
        for word in re.findall(
            r"[a-zA-Z0-9']+",
            text.lower()
        )
        if word not in STOP_WORDS
    ]


def similarity_score(
    query: str,
    text: str
) -> float:

    query_words = words(query)
    text_words = words(text)

    if not query_words or not text_words:
        return 0.0

    query_set = set(query_words)
    text_set = set(text_words)

    score = len(
        query_set & text_set
    )

    if query.lower().strip() in text.lower():
        score += 3

    return float(score)


# ============================================================
# KNOWLEDGE ENGINE
# ============================================================

class KnowledgeEngine:

    @staticmethod
    def add(
        key: str,
        value: str
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
                {}
            )

            if not isinstance(
                knowledge,
                dict
            ):
                knowledge = {}

            knowledge[key.lower()] = value

            data["knowledge"] = knowledge

            if "memories" not in data:
                data["memories"] = []

            if "settings" not in data:
                data["settings"] = {}

            return _save_data(data)

    @staticmethod
    def get(
        key: str
    ) -> str | None:

        if not isinstance(key, str):
            return None

        with LOCK:

            data = _load_data()

            knowledge = data.get(
                "knowledge",
                {}
            )

            if not isinstance(
                knowledge,
                dict
            ):
                return None

            return knowledge.get(
                key.strip().lower()
            )

    @staticmethod
    def all() -> dict:

        with LOCK:

            data = _load_data()

            knowledge = data.get(
                "knowledge",
                {}
            )

            if not isinstance(
                knowledge,
                dict
            ):
                return {}

            return {
                str(key): str(value)
                for key, value
                in knowledge.items()
            }

    @staticmethod
    def search(
        query: str,
        limit: int = 5
    ) -> list[tuple[float, str, str]]:

        if not isinstance(
            query,
            str
        ):
            return []

        query = query.strip()

        if not query:
            return []

        knowledge = KnowledgeEngine.all()

        results = []

        for key, value in knowledge.items():

            key_score = similarity_score(
                query,
                key
            )

            value_score = similarity_score(
                query,
                value
            )

            score = (
                key_score * 3
                + value_score
            )

            if score > 0:
                results.append(
                    (
                        score,
                        key,
                        value
                    )
                )

        results.sort(
            key=lambda item: item[0],
            reverse=True
        )

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5

        limit = max(
            1,
            min(
                limit,
                MAX_RESULTS
            )
        )

        return results[:limit]

    @staticmethod
    def delete(
        key: str
    ) -> bool:

        if not isinstance(
            key,
            str
        ):
            return False

        key = key.strip().lower()

        with LOCK:

            data = _load_data()

            knowledge = data.get(
                "knowledge",
                {}
            )

            if not isinstance(
                knowledge,
                dict
            ):
                return False

            if key not in knowledge:
                return False

            del knowledge[key]

            data["knowledge"] = knowledge

            return _save_data(data)

    @staticmethod
    def clear() -> bool:

        with LOCK:

            data = _load_data()

            data["knowledge"] = {}

            return _save_data(data)


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def teach(
    topic: str,
    information: str
) -> bool:

    return KnowledgeEngine.add(
        topic,
        information
    )


def search_knowledge(
    query: str
) -> list[tuple[float, str, str]]:

    return KnowledgeEngine.search(
        query
    )


def get_knowledge(
    topic: str
) -> str | None:

    return KnowledgeEngine.get(
        topic
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("Nexora Knowledge Engine")
    print("-" * 30)

    teach(
        "Nexora",
        "Nexora is a local-first AI assistant."
    )

    result = search_knowledge(
        "What is Nexora?"
    )

    for score, key, value in result:
        print(
            f"[{score:.1f}] {key}: {value}"
        )
