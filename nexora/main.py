from __future__ import annotations

import ast
import json
import math
import os
import re
import threading
import time
from collections import Counter, deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# ============================================================
# CONFIG
# ============================================================

APP_NAME = "Nexora"
VERSION = "12.0"
SLOGAN = "Intelligence. Secured."

HOST = "0.0.0.0"

try:
    PORT = int(os.environ.get("PORT", "8000"))
except ValueError:
    PORT = 8000

DATA_FILE = (
    os.environ.get(
        "NEXORA_DATA_FILE",
        "nexora_data.json"
    ).strip()
    or "nexora_data.json"
)

API_KEY = os.environ.get(
    "NEXORA_API_KEY",
    ""
).strip()

MAX_INPUT = 5000
MAX_OUTPUT = 12000
MAX_MEMORIES = 500
MAX_CONTEXT = 30
MAX_WEB_RESULTS = 8

LOCK = threading.RLock()


# ============================================================
# WEB SEARCH
# ============================================================

try:
    from web_search import search, format_results

    WEB_SEARCH_AVAILABLE = True
    WEB_SEARCH_ERROR = None

except Exception as exc:

    WEB_SEARCH_AVAILABLE = False
    WEB_SEARCH_ERROR = type(exc).__name__


# ============================================================
# STATE
# ============================================================

memories: list[dict] = []

knowledge: dict[str, dict] = {}

conversation = deque(
    maxlen=MAX_CONTEXT
)

settings = {
    "mode": "friendly",
    "response_length": "normal",
    "emoji": True,
    "user_name": None,
}


# ============================================================
# SECURITY
# ============================================================

SECRET_PATTERNS = [
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
    r"\bAIza[A-Za-z0-9_-]{20,}\b",
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
    r"\b(password|api[_-]?key|secret)\s*[:=]\s*\S+",
    r"\bbearer\s+[A-Za-z0-9._-]{20,}",
]


DANGEROUS_PATTERNS = [
    r"\bhow\s+to\s+(kill|hurt|poison)\s+someone\b",
    r"\bhow\s+to\s+(make|build)\s+(a\s+)?(bomb|explosive|weapon)\b",
]


RISKY_PATTERNS = [
    r"\bdeadly\s+challenge\b",
    r"\bdangerous\s+challenge\b",
    r"\bchoking\s+challenge\b",
    r"\bhow\s+to\s+get\s+high\b",
    r"\bhow\s+to\s+starve\b",
    r"\bhow\s+to\s+purge\b",
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


def safety_check(
    text: str
) -> tuple[bool, str]:

    lower = text.lower()

    if any(
        re.search(
            pattern,
            lower
        )
        for pattern in DANGEROUS_PATTERNS
    ):
        return False, "dangerous"

    if any(
        re.search(
            pattern,
            lower
        )
        for pattern in RISKY_PATTERNS
    ):
        return False, "risky"

    if any(
        phrase in lower
        for phrase in (
            "kill myself",
            "end my life",
            "hurt myself",
            "self harm",
            "self-harm",
            "suicide",
        )
    ):
        return False, "self_harm"

    return True, "safe"


def safety_response(
    category: str
) -> str:

    if category == "self_harm":

        return (
            "I can't provide instructions for hurting "
            "yourself. Please talk to a trusted adult or "
            "someone who can support you."
        )

    if category == "dangerous":

        return (
            "I can't provide instructions for seriously "
            "harming people or creating dangerous weapons "
            "or explosives."
        )

    return (
        "I can't encourage dangerous habits or challenges."
    )


# ============================================================
# PERSISTENCE
# ============================================================

def load_data() -> None:

    global memories
    global knowledge
    global settings

    if not os.path.exists(DATA_FILE):
        return

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            return

        raw_memories = data.get(
            "memories",
            []
        )

        if isinstance(
            raw_memories,
            list
        ):

            memories = []

            for item in raw_memories[
                -MAX_MEMORIES:
            ]:

                if isinstance(
                    item,
                    str
                ):

                    memories.append({
                        "text": item,
                        "created": time.time(),
                    })

                elif (
                    isinstance(item, dict)
                    and isinstance(
                        item.get("text"),
                        str
                    )
                ):

                    memories.append({
                        "text": item["text"],
                        "created": float(
                            item.get(
                                "created",
                                time.time()
                            )
                        ),
                    })

        raw_knowledge = data.get(
            "knowledge",
            {}
        )

        if isinstance(
            raw_knowledge,
            dict
        ):

            for key, value in raw_knowledge.items():

                if isinstance(
                    value,
                    str
                ):

                    knowledge[
                        str(key).lower()
                    ] = {
                        "value": value,
                        "created": time.time(),
                    }

                elif (
                    isinstance(value, dict)
                    and isinstance(
                        value.get("value"),
                        str
                    )
                ):

                    knowledge[
                        str(key).lower()
                    ] = {
                        "value": value["value"],
                        "created": float(
                            value.get(
                                "created",
                                time.time()
                            )
                        ),
                    }

        raw_settings = data.get(
            "settings",
            {}
        )

        if isinstance(
            raw_settings,
            dict
        ):

            settings.update({
                key: value
                for key, value
                in raw_settings.items()
                if key in settings
            })

    except Exception:

        pass


def save_data() -> None:

    temporary = DATA_FILE + ".tmp"

    try:

        with LOCK:

            data = {
                "memories": memories,
                "knowledge": knowledge,
                "settings": settings,
            }

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

    except Exception:

        try:

            if os.path.exists(
                temporary
            ):
                os.remove(
                    temporary
                )

        except OSError:

            pass


# ============================================================
# TEXT RETRIEVAL
# ============================================================

STOP_WORDS = set(
    """
    the a an is are am i you my your to of and or in on
    it this that what do does did for with me can could
    would should be have has how why when where please
    tell about was were will from as at by we our latest
    current today who
    """.split()
)


def words(
    text: str
) -> list[str]:

    return [
        word
        for word in re.findall(
            r"[a-zA-Z0-9']+",
            text.lower()
        )
        if word not in STOP_WORDS
    ]


def score(
    query: str,
    text: str
) -> float:

    query_words = words(query)
    text_words = words(text)

    if (
        not query_words
        or not text_words
    ):
        return 0.0

    query_counts = Counter(
        query_words
    )

    text_counts = Counter(
        text_words
    )

    value = sum(
        min(
            count,
            text_counts.get(
                word,
                0
            )
        )
        for word, count
        in query_counts.items()
    )

    query_normalized = " ".join(
        query_words
    )

    text_normalized = " ".join(
        text_words
    )

    if (
        query_normalized
        and query_normalized
        in text_normalized
    ):
        value += 3

    return float(value)


def memory_search(
    query: str,
    limit: int = 5
) -> list[str]:

    with LOCK:

        snapshot = list(
            memories
        )

    ranked = [
        (
            score(
                query,
                item["text"]
            ),
            item["text"]
        )
        for item in snapshot
    ]

    ranked = [
        item
        for item in ranked
        if item[0] > 0
    ]

    ranked.sort(
        reverse=True
    )

    return [
        item[1]
        for item
        in ranked[:limit]
    ]


def knowledge_search(
    query: str,
    limit: int = 5
) -> list[
    tuple[float, str, str]
]:

    with LOCK:

        snapshot = list(
            knowledge.items()
        )

    ranked = []

    for key, record in snapshot:

        relevance = (
            score(
                query,
                key
            )
            * 3
            +
            score(
                query,
                record["value"]
            )
        )

        if relevance <= 0:
            continue

        ranked.append(
            (
                relevance,
                key,
                record["value"]
            )
        )

    ranked.sort(
        reverse=True
    )

    return ranked[:limit]


def add_memory(
    text: str
) -> bool:

    text = text.strip()

    if (
        not text
        or len(text) > 800
        or contains_secret(text)
    ):
        return False

    with LOCK:

        if any(
            item["text"].lower()
            == text.lower()
            for item in memories
        ):
            return True

        memories.append({
            "text": text,
            "created": time.time(),
        })

        del memories[
            :-MAX_MEMORIES
        ]

    save_data()

    return True


# ============================================================
# SAFE CALCULATOR
# ============================================================

class Calculator:

    ALLOWED = (
        ast.Expression,
        ast.Constant,
        ast.UnaryOp,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.FloorDiv,
    )

    @staticmethod
    def calculate(
        expression: str
    ):

        if (
            not expression
            or len(expression) > 200
        ):
            return None

        try:

            tree = ast.parse(
                expression.strip(),
                mode="eval"
            )

            for node in ast.walk(tree):

                if not isinstance(
                    node,
                    Calculator.ALLOWED
                ):
                    return None

            def evaluate(node):

                if isinstance(
                    node,
                    ast.Expression
                ):

                    return evaluate(
                        node.body
                    )

                if isinstance(
                    node,
                    ast.Constant
                ):

                    value = node.value

                    if (
                        isinstance(
                            value,
                            bool
                        )
                        or not isinstance(
                            value,
                            (int, float)
                        )
                    ):
                        return None

                    if not math.isfinite(
                        float(value)
                    ):
                        return None

                    return value

                if isinstance(
                    node,
                    ast.UnaryOp
                ):

                    value = evaluate(
                        node.operand
                    )

                    if value is None:
                        return None

                    if isinstance(
                        node.op,
                        ast.USub
                    ):
                        return -value

                    if isinstance(
                        node.op,
                        ast.UAdd
                    ):
                        return value

                    return None

                if isinstance(
                    node,
                    ast.BinOp
                ):

                    left = evaluate(
                        node.left
                    )

                    right = evaluate(
                        node.right
                    )

                    if (
                        left is None
                        or right is None
                    ):
                        return None

                    try:

                        if isinstance(
                            node.op,
                            ast.Add
                        ):
                            result = left + right

                        elif isinstance(
                            node.op,
                            ast.Sub
                        ):
                            result = left - right

                        elif isinstance(
                            node.op,
                            ast.Mult
                        ):
                            result = left * right

                        elif isinstance(
                            node.op,
                            ast.Div
                        ):

                            if right == 0:
                                return None

                            result = left / right

                        elif isinstance(
                            node.op,
                            ast.FloorDiv
                        ):

                            if right == 0:
                                return None

                            result = left // right

                        elif isinstance(
                            node.op,
                            ast.Mod
                        ):

                            if right == 0:
                                return None

                            result = left % right

                        elif isinstance(
                            node.op,
                            ast.Pow
                        ):

                            if abs(right) > 100:
                                return None

                            result = left ** right

                        else:

                            return None

                    except Exception:

                        return None

                    if (
                        abs(result)
                        > 10**100
                    ):
                        return None

                    if (
                        isinstance(
                            result,
                            float
                        )
                        and not math.isfinite(
                            result
                        )
                    ):
                        return None

                    return result

                return None

            result = evaluate(
                tree
            )

            if isinstance(
                result,
                float
            ):

                return round(
                    result,
                    10
                )

            return result

        except Exception:

            return None


# ============================================================
# WEB SEARCH INTELLIGENCE
# ============================================================

WEB_TERMS = (
    "latest",
    "today",
    "current",
    "recent",
    "news",
    "score",
    "scores",
    "fixture",
    "fixtures",
    "standings",
    "table",
    "weather",
    "price",
    "prices",
    "release",
    "released",
    "update",
    "updates",
    "who won",
    "when is",
    "where is",
    "premier league",
    "champions league",
    "football",
    "match",
    "matches",
)


def needs_web_search(
    text: str
) -> bool:

    lower = text.lower()

    explicit = lower.startswith(
        (
            "search the web",
            "web search",
            "search for",
            "look up",
            "google ",
        )
    )

    current = any(
        term in lower
        for term in WEB_TERMS
    )

    question = lower.startswith(
        (
            "who ",
            "what ",
            "when ",
            "where ",
            "which ",
            "how many ",
        )
    )

    return (
        explicit
        or (
            current
            and question
        )
        or "latest" in lower
        or (
            "today" in lower
            and len(lower.split()) > 2
        )
    )


def extract_search_query(
    text: str
) -> str:

    query = re.sub(
        r"^(search the web|web search|search for|look up|google)\s*",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()

    return query or text.strip()


def smart_web_search(
    query: str
) -> str:

    if not WEB_SEARCH_AVAILABLE:

        return (
            "Web search is currently unavailable "
            "because web_search.py could not be loaded."
        )

    results = search(
        query,
        limit=MAX_WEB_RESULTS
    )

    if not results:

        return (
            "I couldn't find useful web results "
            "for that search."
        )

    return format_results(
        results
    )


# ============================================================
# NEXORA BRAIN
# ============================================================

class NexoraBrain:

    @staticmethod
    def answer(
        message: str
    ) -> str:

        text = message.strip()
        lower = text.lower()

        # ----------------------------------------------------
        # CURRENT INFORMATION
        # ----------------------------------------------------

        if needs_web_search(text):

            return smart_web_search(
                extract_search_query(
                    text
                )
            )

        # ----------------------------------------------------
        # BASIC CONVERSATION
        # ----------------------------------------------------

        if (
            lower in {
                "hi",
                "hello",
                "hey",
                "hiya",
            }
            or re.match(
                r"^(hi|hello|hey|hiya)\b",
                lower
            )
        ):

            name = settings.get(
                "user_name"
            )

            if name:

                return (
                    f"Hey {name}! "
                    "I'm Nexora. "
                    "What are we working on?"
                )

            return (
                "Hey! I'm Nexora. "
                "What are we working on?"
            )

        if lower in {
            "bye",
            "goodbye",
            "see you",
            "see ya",
        }:

            return "See you later! 👋"

        # ----------------------------------------------------
        # IDENTITY
        # ----------------------------------------------------

        if "who are you" in lower:

            return (
                f"I'm Nexora v{VERSION}, "
                "a local-first assistant with "
                "memory, knowledge retrieval, "
                "reasoning tools, safety controls, "
                "and live web search."
            )

        if (
            "what can you do" in lower
            or "capabilities" in lower
        ):

            return (
                "I can:\n\n"
                "• search the live web\n"
                "• retrieve stored knowledge\n"
                "• remember information you ask me to remember\n"
                "• use conversation context\n"
                "• perform calculations\n"
                "• compare stored information\n"
                "• explain stored knowledge\n"
                "• detect when current information is needed\n"
                "• apply safety and secret filtering"
            )

        if "what version" in lower:

            return (
                f"I'm running Nexora v{VERSION}."
            )

        if "slogan" in lower:

            return (
                f"My slogan is: {SLOGAN}"
            )

        # ----------------------------------------------------
        # TIME / DATE
        # ----------------------------------------------------

        if (
            "what time is it" in lower
            or "current time" in lower
        ):

            return datetime.now().strftime(
                "It's %H:%M:%S right now."
            )

        if (
            "what date is it" in lower
            or "today's date" in lower
            or "what day is it" in lower
        ):

            return datetime.now().strftime(
                "Today is %A, %d %B %Y."
            )

        # ----------------------------------------------------
        # MEMORY
        # ----------------------------------------------------

        if lower.startswith(
            "remember "
        ):

            value = re.sub(
                r"^remember\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            value = re.sub(
                r"^that\s+",
                "",
                value,
                flags=re.IGNORECASE
            ).strip()

            if add_memory(value):

                return (
                    "Got it. "
                    "I've saved that to memory."
                )

            return (
                "I couldn't safely save that."
            )

        if lower in {
            "what do you remember",
            "show my memories",
            "what have i told you",
        }:

            items = [
                item["text"]
                for item in memories
            ]

            if not items:

                return (
                    "I don't have any saved "
                    "memories yet."
                )

            return (
                "Here's what I remember:\n\n"
                + "\n".join(
                    f"{i}. {item}"
                    for i, item
                    in enumerate(
                        items,
                        1
                    )
                )
            )

        if lower.startswith(
            "forget "
        ):

            target = re.sub(
                r"^forget\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip().lower()

            with LOCK:

                before = len(
                    memories
                )

                memories[:] = [
                    item
                    for item in memories
                    if item["text"].lower()
                    != target
                ]

            save_data()

            if len(memories) < before:

                return (
                    "Done. "
                    "I've forgotten that memory."
                )

            return (
                "I couldn't find that exact memory."
            )

        # ----------------------------------------------------
        # KNOWLEDGE
        # ----------------------------------------------------

        if lower.startswith(
            "teach nexora "
        ):

            content = re.sub(
                r"^teach nexora\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            if "=" not in content:

                return (
                    "Use:\n"
                    "teach Nexora topic = information"
                )

            key, value = [
                part.strip()
                for part
                in content.split(
                    "=",
                    1
                )
            ]

            if (
                not key
                or not value
                or len(key) > 200
                or len(value) > 4000
                or contains_secret(value)
            ):

                return (
                    "I couldn't safely add "
                    "that knowledge."
                )

            with LOCK:

                knowledge[
                    key.lower()
                ] = {
                    "value": value,
                    "created": time.time(),
                }

            save_data()

            return (
                "I've added that to "
                "my knowledge base."
            )

        if lower.startswith(
            "search knowledge "
        ):

            query = re.sub(
                r"^search knowledge\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            found = knowledge_search(
                query
            )

            if not found:

                return (
                    "I couldn't find matching "
                    "knowledge."
                )

            return "\n".join(
                f"• {key}: {value}"
                for _, key, value
                in found
            )

        # ----------------------------------------------------
        # CALCULATOR
        # ----------------------------------------------------

        if lower.startswith(
            (
                "calculate ",
                "calc ",
            )
        ):

            expression = re.sub(
                r"^(calculate|calc)\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            result = Calculator.calculate(
                expression
            )

            if result is None:

                return (
                    "I couldn't safely "
                    "calculate that."
                )

            return (
                f"The answer is {result}."
            )

        # ----------------------------------------------------
        # NAME
        # ----------------------------------------------------

        if lower.startswith(
            "my name is "
        ):

            name = re.sub(
                r"^my name is\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            if (
                not name
                or len(name) > 100
                or contains_secret(name)
            ):

                return (
                    "I couldn't safely "
                    "save that name."
                )

            settings[
                "user_name"
            ] = name

            save_data()

            return (
                f"Nice to meet you, {name}."
            )

        if lower in {
            "what is my name",
            "what's my name",
        }:

            name = settings.get(
                "user_name"
            )

            if name:

                return (
                    f"Your saved name is {name}."
                )

            return (
                "I don't have your name "
                "saved yet."
            )

        # ----------------------------------------------------
        # MODE
        # ----------------------------------------------------

        if lower.startswith(
            "set mode "
        ):

            mode = lower[
                len("set mode "):
            ].strip()

            allowed = {
                "friendly",
                "professional",
                "concise",
                "teacher",
                "technical",
                "creative",
                "formal",
                "energetic",
            }

            if mode not in allowed:

                return (
                    "Available modes: "
                    + ", ".join(
                        sorted(allowed)
                    )
                )

            settings[
                "mode"
            ] = mode

            save_data()

            return (
                f"Speaking mode changed "
                f"to {mode}."
            )

        # ----------------------------------------------------
        # CLEAR CONTEXT
        # ----------------------------------------------------

        if lower.startswith(
            "clear conversation"
        ):

            conversation.clear()

            return (
                "I've cleared the "
                "conversation context."
            )

        # ----------------------------------------------------
        # LOCAL KNOWLEDGE RETRIEVAL
        # ----------------------------------------------------

        found = knowledge_search(
            text,
            limit=3
        )

        if (
            found
            and found[0][0] >= 2
        ):

            return found[0][2]

        # ----------------------------------------------------
        # MEMORY RETRIEVAL
        # ----------------------------------------------------

        remembered = memory_search(
            text,
            limit=3
        )

        if remembered and any(
            phrase in lower
            for phrase in (
                "remember",
                "told",
                "my ",
            )
        ):

            return (
                "I found this in memory:\n\n"
                + "\n".join(
                    "• " + item
                    for item in remembered
                )
            )

        # ----------------------------------------------------
        # NATURAL MATH
        # ----------------------------------------------------

        candidate = re.sub(
            r"[^0-9+\-*/().% ]",
            "",
            text
        ).strip()

        if (
            candidate
            and any(
                operator in candidate
                for operator in (
                    "+",
                    "-",
                    "*",
                    "/",
                    "%",
                )
            )
            and len(candidate) <= 100
        ):

            result = Calculator.calculate(
                candidate
            )

            if result is not None:

                return (
                    f"The answer is {result}."
                )

        # ----------------------------------------------------
        # FALLBACK WEB SEARCH
        # ----------------------------------------------------

        if (
            "?" in text
            and WEB_SEARCH_AVAILABLE
        ):

            return smart_web_search(
                text
            )

        # ----------------------------------------------------
        # UNKNOWN
        # ----------------------------------------------------

        return (
            "I don't have enough reliable "
            "local information to answer "
            "that confidently.\n\n"
            "If it needs current information, "
            "ask me to search the web, for example:\n\n"
            "search the web Premier League standings"
        )


# ============================================================
# PIPELINE
# ============================================================

def process(
    message: str,
    client_id: str = "local"
) -> str:

    if (
        not isinstance(
            message,
            str
        )
        or not message.strip()
    ):

        return (
            "Please enter a message."
        )

    message = message.strip()

    if len(message) > MAX_INPUT:

        return (
            "That message is too long. "
            f"Maximum length is {MAX_INPUT} characters."
        )

    if contains_secret(message):

        return (
            "For your privacy, don't send "
            "passwords, API keys, access tokens "
            "or other secrets in chat."
        )

    allowed, category = safety_check(
        message
    )

    if not allowed:

        return safety_response(
            category
        )

    try:

        conversation.append({
            "role": "user",
            "content": message,
            "timestamp": time.time(),
        })

        reply = NexoraBrain.answer(
            message
        )

        if len(reply) > MAX_OUTPUT:

            reply = (
                reply[
                    :MAX_OUTPUT
                ].rstrip()
                + "…"
            )

        conversation.append({
            "role": "assistant",
            "content": reply,
            "timestamp": time.time(),
        })

        return reply

    except Exception:

        return (
            "Nexora encountered an internal "
            "problem and stopped safely."
        )


# ============================================================
# WEB UI
# ============================================================

HTML = r"""
<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Nexora</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;
    background: #050008;
    color: #fff;
    font-family: Arial, sans-serif;
}

.wrap {
    width: min(1050px, 94%);
    margin: 28px auto;
}

.head {
    text-align: center;
}

.logo {
    font-size: 64px;
    font-weight: 900;

    background:
        linear-gradient(
            90deg,
            #fff,
            #67ffff,
            #d000ff
        );

    color: transparent;
    background-clip: text;
    -webkit-background-clip: text;
}

.slogan {
    color: #67ffff;
    letter-spacing: 5px;
    font-size: 11px;
}

.status {
    color: #888;
    margin: 8px;
}

.chat {
    height: 68vh;
    min-height: 430px;
    overflow: auto;

    padding: 22px;

    border: 1px solid #5d1475;
    border-radius: 20px;

    background: #09060f;
}

.msg {
    max-width: 82%;

    padding: 14px 17px;
    margin: 0 0 16px;

    border-radius: 16px;

    white-space: pre-wrap;
    overflow-wrap: anywhere;

    line-height: 1.55;
}

.bot {
    border-left: 3px solid #67ffff;
    background: #18152a;
}

.user {
    margin-left: auto;

    background:
        linear-gradient(
            135deg,
            #6500ff,
            #c000ff
        );
}

.sender {
    display: block;

    color: #67ffff;

    font-size: 10px;
    font-weight: bold;

    letter-spacing: 2px;

    margin-bottom: 6px;
}

.composer {
    display: flex;
    gap: 10px;
    margin-top: 15px;
}

input {
    flex: 1;

    padding: 16px;

    border: 1px solid #7500ff;
    border-radius: 13px;

    background: #110819;
    color: #fff;

    font-size: 15px;

    outline: none;
}

button {
    border: 0;
    border-radius: 13px;

    padding: 0 25px;

    color: #fff;

    font-weight: bold;

    background:
        linear-gradient(
            135deg,
            #7000ff,
            #c000ff
        );

    cursor: pointer;
}

button:disabled {
    opacity: .5;
}

</style>

</head>

<body>

<div class="wrap">

<div class="head">

<div class="logo">
Nexora
</div>

<div class="slogan">
INTELLIGENCE. SECURED.
</div>

<div class="status">
v12.0 • Local Reasoning • Memory • Web Search
</div>

</div>

<div
    class="chat"
    id="chat"
>

<div class="msg bot">

<span class="sender">
NEXORA
</span>

Hey! I'm Nexora v12. What are we working on?

</div>

</div>

<form
    class="composer"
    id="form"
>

<input
    id="input"
    maxlength="5000"
    autocomplete="off"
    placeholder="Talk to Nexora..."
>

<button
    id="send"
>

Send

</button>

</form>

</div>

<script>

const form =
    document.getElementById("form");

const input =
    document.getElementById("input");

const send =
    document.getElementById("send");

const chat =
    document.getElementById("chat");


function addMessage(
    sender,
    text,
    type
) {

    const message =
        document.createElement("div");

    message.className =
        "msg " + type;

    const senderElement =
        document.createElement("span");

    senderElement.className =
        "sender";

    senderElement.textContent =
        sender;

    message.appendChild(
        senderElement
    );

    message.appendChild(
        document.createTextNode(text)
    );

    chat.appendChild(
        message
    );

    chat.scrollTop =
        chat.scrollHeight;
}


form.addEventListener(
    "submit",
    async function(event) {

        event.preventDefault();

        const text =
            input.value.trim();

        if (!text) {
            return;
        }

        addMessage(
            "YOU",
            text,
            "user"
        );

        input.value = "";

        send.disabled = true;

        try {

            const response =
                await fetch(
                    "/api/web-chat",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body: JSON.stringify({
                            message: text
                        })
                    }
                );

            const data =
                await response.json();

            addMessage(
                "NEXORA",
                data.reply ||
                data.error ||
                "No response.",
                "bot"
            );

        } catch (error) {

            addMessage(
                "NEXORA",
                "I could not connect to the server.",
                "bot"
            );

        } finally {

            send.disabled = false;

            input.focus();
        }
    }
);

input.focus();

</script>

</body>

</html>
"""


# ============================================================
# HTTP SERVER
# ============================================================

class Server(
    BaseHTTPRequestHandler
):

    server_version = (
        "NexoraHTTP/12.0"
    )

    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "X-Content-Type-Options",
            "nosniff"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    def do_GET(self):

        path = urlparse(
            self.path
        ).path

        if path == "/":

            body = HTML.encode(
                "utf-8"
            )

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(body))
            )

            self.end_headers()

            self.wfile.write(
                body
            )

            return

        if path == "/health":

            self.send_json({
                "status": "ok",
                "name": APP_NAME,
                "version": VERSION,
                "web_search":
                    WEB_SEARCH_AVAILABLE,
                "web_search_error":
                    WEB_SEARCH_ERROR,
            })

            return

        self.send_json(
            {"error": "Not found"},
            404
        )

    def do_POST(self):

        path = urlparse(
            self.path
        ).path

        if path not in (
            "/api/web-chat",
            "/api/chat",
        ):

            self.send_json(
                {"error": "Not found"},
                404
            )

            return

        if (
            path == "/api/chat"
            and API_KEY
        ):

            provided = self.headers.get(
                "X-API-Key",
                ""
            )

            if provided != API_KEY:

                self.send_json(
                    {
                        "error":
                        "Authentication required."
                    },
                    401
                )

                return

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            if (
                content_length <= 0
                or content_length > 100000
            ):

                self.send_json(
                    {
                        "error":
                        "Request too large."
                    },
                    413
                )

                return

            data = json.loads(
                self.rfile.read(
                    content_length
                ).decode("utf-8")
            )

            if not isinstance(
                data,
                dict
            ):

                self.send_json(
                    {
                        "error":
                        "JSON object required."
                    },
                    400
                )

                return

            message = data.get(
                "message"
            )

            if not isinstance(
                message,
                str
            ):

                self.send_json(
                    {
                        "error":
                        "The 'message' field "
                        "must be text."
                    },
                    400
                )

                return

            reply = process(
                message,
                self.client_address[0]
            )

            self.send_json({
                "reply": reply
            })

        except Exception:

            self.send_json(
                {
                    "error":
                    "Invalid request."
                },
                400
            )

    def log_message(
        self,
        format_string,
        *args
    ):

        return


# ============================================================
# STARTUP
# ============================================================

def main():

    load_data()

    print("=" * 60)

    print(
        f"{APP_NAME} {VERSION} - {SLOGAN}"
    )

    print(
        f"Port: {PORT}"
    )

    print(
        "Web search:",
        "ENABLED"
        if WEB_SEARCH_AVAILABLE
        else "DISABLED"
    )

    if not WEB_SEARCH_AVAILABLE:

        print(
            "Web search error:",
            WEB_SEARCH_ERROR
        )

    print("=" * 60)

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Server
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "Nexora shutting down."
        )

    finally:

        server.server_close()


if __name__ == "__main__":

    ()from __future__ import annotations

import ast
import json
import math
import os
import re
import threading
import time
from collections import Counter, deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# ============================================================
# CONFIG
# ============================================================

APP_NAME = "Nexora"
VERSION = "12.0"
SLOGAN = "Intelligence. Secured."

HOST = "0.0.0.0"

try:
    PORT = int(os.environ.get("PORT", "8000"))
except ValueError:
    PORT = 8000

DATA_FILE = (
    os.environ.get(
        "NEXORA_DATA_FILE",
        "nexora_data.json"
    ).strip()
    or "nexora_data.json"
)

API_KEY = os.environ.get(
    "NEXORA_API_KEY",
    ""
).strip()

MAX_INPUT = 5000
MAX_OUTPUT = 12000
MAX_MEMORIES = 500
MAX_CONTEXT = 30
MAX_WEB_RESULTS = 8

LOCK = threading.RLock()


# ============================================================
# WEB SEARCH
# ============================================================

try:
    from web_search import search, format_results

    WEB_SEARCH_AVAILABLE = True
    WEB_SEARCH_ERROR = None

except Exception as exc:

    WEB_SEARCH_AVAILABLE = False
    WEB_SEARCH_ERROR = type(exc).__name__


# ============================================================
# STATE
# ============================================================

memories: list[dict] = []

knowledge: dict[str, dict] = {}

conversation = deque(
    maxlen=MAX_CONTEXT
)

settings = {
    "mode": "friendly",
    "response_length": "normal",
    "emoji": True,
    "user_name": None,
}


# ============================================================
# SECURITY
# ============================================================

SECRET_PATTERNS = [
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
    r"\bAIza[A-Za-z0-9_-]{20,}\b",
    r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
    r"\b(password|api[_-]?key|secret)\s*[:=]\s*\S+",
    r"\bbearer\s+[A-Za-z0-9._-]{20,}",
]


DANGEROUS_PATTERNS = [
    r"\bhow\s+to\s+(kill|hurt|poison)\s+someone\b",
    r"\bhow\s+to\s+(make|build)\s+(a\s+)?(bomb|explosive|weapon)\b",
]


RISKY_PATTERNS = [
    r"\bdeadly\s+challenge\b",
    r"\bdangerous\s+challenge\b",
    r"\bchoking\s+challenge\b",
    r"\bhow\s+to\s+get\s+high\b",
    r"\bhow\s+to\s+starve\b",
    r"\bhow\s+to\s+purge\b",
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


def safety_check(
    text: str
) -> tuple[bool, str]:

    lower = text.lower()

    if any(
        re.search(
            pattern,
            lower
        )
        for pattern in DANGEROUS_PATTERNS
    ):
        return False, "dangerous"

    if any(
        re.search(
            pattern,
            lower
        )
        for pattern in RISKY_PATTERNS
    ):
        return False, "risky"

    if any(
        phrase in lower
        for phrase in (
            "kill myself",
            "end my life",
            "hurt myself",
            "self harm",
            "self-harm",
            "suicide",
        )
    ):
        return False, "self_harm"

    return True, "safe"


def safety_response(
    category: str
) -> str:

    if category == "self_harm":

        return (
            "I can't provide instructions for hurting "
            "yourself. Please talk to a trusted adult or "
            "someone who can support you."
        )

    if category == "dangerous":

        return (
            "I can't provide instructions for seriously "
            "harming people or creating dangerous weapons "
            "or explosives."
        )

    return (
        "I can't encourage dangerous habits or challenges."
    )


# ============================================================
# PERSISTENCE
# ============================================================

def load_data() -> None:

    global memories
    global knowledge
    global settings

    if not os.path.exists(DATA_FILE):
        return

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            return

        raw_memories = data.get(
            "memories",
            []
        )

        if isinstance(
            raw_memories,
            list
        ):

            memories = []

            for item in raw_memories[
                -MAX_MEMORIES:
            ]:

                if isinstance(
                    item,
                    str
                ):

                    memories.append({
                        "text": item,
                        "created": time.time(),
                    })

                elif (
                    isinstance(item, dict)
                    and isinstance(
                        item.get("text"),
                        str
                    )
                ):

                    memories.append({
                        "text": item["text"],
                        "created": float(
                            item.get(
                                "created",
                                time.time()
                            )
                        ),
                    })

        raw_knowledge = data.get(
            "knowledge",
            {}
        )

        if isinstance(
            raw_knowledge,
            dict
        ):

            for key, value in raw_knowledge.items():

                if isinstance(
                    value,
                    str
                ):

                    knowledge[
                        str(key).lower()
                    ] = {
                        "value": value,
                        "created": time.time(),
                    }

                elif (
                    isinstance(value, dict)
                    and isinstance(
                        value.get("value"),
                        str
                    )
                ):

                    knowledge[
                        str(key).lower()
                    ] = {
                        "value": value["value"],
                        "created": float(
                            value.get(
                                "created",
                                time.time()
                            )
                        ),
                    }

        raw_settings = data.get(
            "settings",
            {}
        )

        if isinstance(
            raw_settings,
            dict
        ):

            settings.update({
                key: value
                for key, value
                in raw_settings.items()
                if key in settings
            })

    except Exception:

        pass


def save_data() -> None:

    temporary = DATA_FILE + ".tmp"

    try:

        with LOCK:

            data = {
                "memories": memories,
                "knowledge": knowledge,
                "settings": settings,
            }

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

    except Exception:

        try:

            if os.path.exists(
                temporary
            ):
                os.remove(
                    temporary
                )

        except OSError:

            pass


# ============================================================
# TEXT RETRIEVAL
# ============================================================

STOP_WORDS = set(
    """
    the a an is are am i you my your to of and or in on
    it this that what do does did for with me can could
    would should be have has how why when where please
    tell about was were will from as at by we our latest
    current today who
    """.split()
)


def words(
    text: str
) -> list[str]:

    return [
        word
        for word in re.findall(
            r"[a-zA-Z0-9']+",
            text.lower()
        )
        if word not in STOP_WORDS
    ]


def score(
    query: str,
    text: str
) -> float:

    query_words = words(query)
    text_words = words(text)

    if (
        not query_words
        or not text_words
    ):
        return 0.0

    query_counts = Counter(
        query_words
    )

    text_counts = Counter(
        text_words
    )

    value = sum(
        min(
            count,
            text_counts.get(
                word,
                0
            )
        )
        for word, count
        in query_counts.items()
    )

    query_normalized = " ".join(
        query_words
    )

    text_normalized = " ".join(
        text_words
    )

    if (
        query_normalized
        and query_normalized
        in text_normalized
    ):
        value += 3

    return float(value)


def memory_search(
    query: str,
    limit: int = 5
) -> list[str]:

    with LOCK:

        snapshot = list(
            memories
        )

    ranked = [
        (
            score(
                query,
                item["text"]
            ),
            item["text"]
        )
        for item in snapshot
    ]

    ranked = [
        item
        for item in ranked
        if item[0] > 0
    ]

    ranked.sort(
        reverse=True
    )

    return [
        item[1]
        for item
        in ranked[:limit]
    ]


def knowledge_search(
    query: str,
    limit: int = 5
) -> list[
    tuple[float, str, str]
]:

    with LOCK:

        snapshot = list(
            knowledge.items()
        )

    ranked = []

    for key, record in snapshot:

        relevance = (
            score(
                query,
                key
            )
            * 3
            +
            score(
                query,
                record["value"]
            )
        )

        if relevance <= 0:
            continue

        ranked.append(
            (
                relevance,
                key,
                record["value"]
            )
        )

    ranked.sort(
        reverse=True
    )

    return ranked[:limit]


def add_memory(
    text: str
) -> bool:

    text = text.strip()

    if (
        not text
        or len(text) > 800
        or contains_secret(text)
    ):
        return False

    with LOCK:

        if any(
            item["text"].lower()
            == text.lower()
            for item in memories
        ):
            return True

        memories.append({
            "text": text,
            "created": time.time(),
        })

        del memories[
            :-MAX_MEMORIES
        ]

    save_data()

    return True


# ============================================================
# SAFE CALCULATOR
# ============================================================

class Calculator:

    ALLOWED = (
        ast.Expression,
        ast.Constant,
        ast.UnaryOp,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.FloorDiv,
    )

    @staticmethod
    def calculate(
        expression: str
    ):

        if (
            not expression
            or len(expression) > 200
        ):
            return None

        try:

            tree = ast.parse(
                expression.strip(),
                mode="eval"
            )

            for node in ast.walk(tree):

                if not isinstance(
                    node,
                    Calculator.ALLOWED
                ):
                    return None

            def evaluate(node):

                if isinstance(
                    node,
                    ast.Expression
                ):

                    return evaluate(
                        node.body
                    )

                if isinstance(
                    node,
                    ast.Constant
                ):

                    value = node.value

                    if (
                        isinstance(
                            value,
                            bool
                        )
                        or not isinstance(
                            value,
                            (int, float)
                        )
                    ):
                        return None

                    if not math.isfinite(
                        float(value)
                    ):
                        return None

                    return value

                if isinstance(
                    node,
                    ast.UnaryOp
                ):

                    value = evaluate(
                        node.operand
                    )

                    if value is None:
                        return None

                    if isinstance(
                        node.op,
                        ast.USub
                    ):
                        return -value

                    if isinstance(
                        node.op,
                        ast.UAdd
                    ):
                        return value

                    return None

                if isinstance(
                    node,
                    ast.BinOp
                ):

                    left = evaluate(
                        node.left
                    )

                    right = evaluate(
                        node.right
                    )

                    if (
                        left is None
                        or right is None
                    ):
                        return None

                    try:

                        if isinstance(
                            node.op,
                            ast.Add
                        ):
                            result = left + right

                        elif isinstance(
                            node.op,
                            ast.Sub
                        ):
                            result = left - right

                        elif isinstance(
                            node.op,
                            ast.Mult
                        ):
                            result = left * right

                        elif isinstance(
                            node.op,
                            ast.Div
                        ):

                            if right == 0:
                                return None

                            result = left / right

                        elif isinstance(
                            node.op,
                            ast.FloorDiv
                        ):

                            if right == 0:
                                return None

                            result = left // right

                        elif isinstance(
                            node.op,
                            ast.Mod
                        ):

                            if right == 0:
                                return None

                            result = left % right

                        elif isinstance(
                            node.op,
                            ast.Pow
                        ):

                            if abs(right) > 100:
                                return None

                            result = left ** right

                        else:

                            return None

                    except Exception:

                        return None

                    if (
                        abs(result)
                        > 10**100
                    ):
                        return None

                    if (
                        isinstance(
                            result,
                            float
                        )
                        and not math.isfinite(
                            result
                        )
                    ):
                        return None

                    return result

                return None

            result = evaluate(
                tree
            )

            if isinstance(
                result,
                float
            ):

                return round(
                    result,
                    10
                )

            return result

        except Exception:

            return None


# ============================================================
# WEB SEARCH INTELLIGENCE
# ============================================================

WEB_TERMS = (
    "latest",
    "today",
    "current",
    "recent",
    "news",
    "score",
    "scores",
    "fixture",
    "fixtures",
    "standings",
    "table",
    "weather",
    "price",
    "prices",
    "release",
    "released",
    "update",
    "updates",
    "who won",
    "when is",
    "where is",
    "premier league",
    "champions league",
    "football",
    "match",
    "matches",
)


def needs_web_search(
    text: str
) -> bool:

    lower = text.lower()

    explicit = lower.startswith(
        (
            "search the web",
            "web search",
            "search for",
            "look up",
            "google ",
        )
    )

    current = any(
        term in lower
        for term in WEB_TERMS
    )

    question = lower.startswith(
        (
            "who ",
            "what ",
            "when ",
            "where ",
            "which ",
            "how many ",
        )
    )

    return (
        explicit
        or (
            current
            and question
        )
        or "latest" in lower
        or (
            "today" in lower
            and len(lower.split()) > 2
        )
    )


def extract_search_query(
    text: str
) -> str:

    query = re.sub(
        r"^(search the web|web search|search for|look up|google)\s*",
        "",
        text,
        flags=re.IGNORECASE
    ).strip()

    return query or text.strip()


def smart_web_search(
    query: str
) -> str:

    if not WEB_SEARCH_AVAILABLE:

        return (
            "Web search is currently unavailable "
            "because web_search.py could not be loaded."
        )

    results = search(
        query,
        limit=MAX_WEB_RESULTS
    )

    if not results:

        return (
            "I couldn't find useful web results "
            "for that search."
        )

    return format_results(
        results
    )


# ============================================================
# NEXORA BRAIN
# ============================================================

class NexoraBrain:

    @staticmethod
    def answer(
        message: str
    ) -> str:

        text = message.strip()
        lower = text.lower()

        # ----------------------------------------------------
        # CURRENT INFORMATION
        # ----------------------------------------------------

        if needs_web_search(text):

            return smart_web_search(
                extract_search_query(
                    text
                )
            )

        # ----------------------------------------------------
        # BASIC CONVERSATION
        # ----------------------------------------------------

        if (
            lower in {
                "hi",
                "hello",
                "hey",
                "hiya",
            }
            or re.match(
                r"^(hi|hello|hey|hiya)\b",
                lower
            )
        ):

            name = settings.get(
                "user_name"
            )

            if name:

                return (
                    f"Hey {name}! "
                    "I'm Nexora. "
                    "What are we working on?"
                )

            return (
                "Hey! I'm Nexora. "
                "What are we working on?"
            )

        if lower in {
            "bye",
            "goodbye",
            "see you",
            "see ya",
        }:

            return "See you later! 👋"

        # ----------------------------------------------------
        # IDENTITY
        # ----------------------------------------------------

        if "who are you" in lower:

            return (
                f"I'm Nexora v{VERSION}, "
                "a local-first assistant with "
                "memory, knowledge retrieval, "
                "reasoning tools, safety controls, "
                "and live web search."
            )

        if (
            "what can you do" in lower
            or "capabilities" in lower
        ):

            return (
                "I can:\n\n"
                "• search the live web\n"
                "• retrieve stored knowledge\n"
                "• remember information you ask me to remember\n"
                "• use conversation context\n"
                "• perform calculations\n"
                "• compare stored information\n"
                "• explain stored knowledge\n"
                "• detect when current information is needed\n"
                "• apply safety and secret filtering"
            )

        if "what version" in lower:

            return (
                f"I'm running Nexora v{VERSION}."
            )

        if "slogan" in lower:

            return (
                f"My slogan is: {SLOGAN}"
            )

        # ----------------------------------------------------
        # TIME / DATE
        # ----------------------------------------------------

        if (
            "what time is it" in lower
            or "current time" in lower
        ):

            return datetime.now().strftime(
                "It's %H:%M:%S right now."
            )

        if (
            "what date is it" in lower
            or "today's date" in lower
            or "what day is it" in lower
        ):

            return datetime.now().strftime(
                "Today is %A, %d %B %Y."
            )

        # ----------------------------------------------------
        # MEMORY
        # ----------------------------------------------------

        if lower.startswith(
            "remember "
        ):

            value = re.sub(
                r"^remember\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            value = re.sub(
                r"^that\s+",
                "",
                value,
                flags=re.IGNORECASE
            ).strip()

            if add_memory(value):

                return (
                    "Got it. "
                    "I've saved that to memory."
                )

            return (
                "I couldn't safely save that."
            )

        if lower in {
            "what do you remember",
            "show my memories",
            "what have i told you",
        }:

            items = [
                item["text"]
                for item in memories
            ]

            if not items:

                return (
                    "I don't have any saved "
                    "memories yet."
                )

            return (
                "Here's what I remember:\n\n"
                + "\n".join(
                    f"{i}. {item}"
                    for i, item
                    in enumerate(
                        items,
                        1
                    )
                )
            )

        if lower.startswith(
            "forget "
        ):

            target = re.sub(
                r"^forget\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip().lower()

            with LOCK:

                before = len(
                    memories
                )

                memories[:] = [
                    item
                    for item in memories
                    if item["text"].lower()
                    != target
                ]

            save_data()

            if len(memories) < before:

                return (
                    "Done. "
                    "I've forgotten that memory."
                )

            return (
                "I couldn't find that exact memory."
            )

        # ----------------------------------------------------
        # KNOWLEDGE
        # ----------------------------------------------------

        if lower.startswith(
            "teach nexora "
        ):

            content = re.sub(
                r"^teach nexora\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            if "=" not in content:

                return (
                    "Use:\n"
                    "teach Nexora topic = information"
                )

            key, value = [
                part.strip()
                for part
                in content.split(
                    "=",
                    1
                )
            ]

            if (
                not key
                or not value
                or len(key) > 200
                or len(value) > 4000
                or contains_secret(value)
            ):

                return (
                    "I couldn't safely add "
                    "that knowledge."
                )

            with LOCK:

                knowledge[
                    key.lower()
                ] = {
                    "value": value,
                    "created": time.time(),
                }

            save_data()

            return (
                "I've added that to "
                "my knowledge base."
            )

        if lower.startswith(
            "search knowledge "
        ):

            query = re.sub(
                r"^search knowledge\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            found = knowledge_search(
                query
            )

            if not found:

                return (
                    "I couldn't find matching "
                    "knowledge."
                )

            return "\n".join(
                f"• {key}: {value}"
                for _, key, value
                in found
            )

        # ----------------------------------------------------
        # CALCULATOR
        # ----------------------------------------------------

        if lower.startswith(
            (
                "calculate ",
                "calc ",
            )
        ):

            expression = re.sub(
                r"^(calculate|calc)\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            result = Calculator.calculate(
                expression
            )

            if result is None:

                return (
                    "I couldn't safely "
                    "calculate that."
                )

            return (
                f"The answer is {result}."
            )

        # ----------------------------------------------------
        # NAME
        # ----------------------------------------------------

        if lower.startswith(
            "my name is "
        ):

            name = re.sub(
                r"^my name is\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            if (
                not name
                or len(name) > 100
                or contains_secret(name)
            ):

                return (
                    "I couldn't safely "
                    "save that name."
                )

            settings[
                "user_name"
            ] = name

            save_data()

            return (
                f"Nice to meet you, {name}."
            )

        if lower in {
            "what is my name",
            "what's my name",
        }:

            name = settings.get(
                "user_name"
            )

            if name:

                return (
                    f"Your saved name is {name}."
                )

            return (
                "I don't have your name "
                "saved yet."
            )

        # ----------------------------------------------------
        # MODE
        # ----------------------------------------------------

        if lower.startswith(
            "set mode "
        ):

            mode = lower[
                len("set mode "):
            ].strip()

            allowed = {
                "friendly",
                "professional",
                "concise",
                "teacher",
                "technical",
                "creative",
                "formal",
                "energetic",
            }

            if mode not in allowed:

                return (
                    "Available modes: "
                    + ", ".join(
                        sorted(allowed)
                    )
                )

            settings[
                "mode"
            ] = mode

            save_data()

            return (
                f"Speaking mode changed "
                f"to {mode}."
            )

        # ----------------------------------------------------
        # CLEAR CONTEXT
        # ----------------------------------------------------

        if lower.startswith(
            "clear conversation"
        ):

            conversation.clear()

            return (
                "I've cleared the "
                "conversation context."
            )

        # ----------------------------------------------------
        # LOCAL KNOWLEDGE RETRIEVAL
        # ----------------------------------------------------

        found = knowledge_search(
            text,
            limit=3
        )

        if (
            found
            and found[0][0] >= 2
        ):

            return found[0][2]

        # ----------------------------------------------------
        # MEMORY RETRIEVAL
        # ----------------------------------------------------

        remembered = memory_search(
            text,
            limit=3
        )

        if remembered and any(
            phrase in lower
            for phrase in (
                "remember",
                "told",
                "my ",
            )
        ):

            return (
                "I found this in memory:\n\n"
                + "\n".join(
                    "• " + item
                    for item in remembered
                )
            )

        # ----------------------------------------------------
        # NATURAL MATH
        # ----------------------------------------------------

        candidate = re.sub(
            r"[^0-9+\-*/().% ]",
            "",
            text
        ).strip()

        if (
            candidate
            and any(
                operator in candidate
                for operator in (
                    "+",
                    "-",
                    "*",
                    "/",
                    "%",
                )
            )
            and len(candidate) <= 100
        ):

            result = Calculator.calculate(
                candidate
            )

            if result is not None:

                return (
                    f"The answer is {result}."
                )

        # ----------------------------------------------------
        # FALLBACK WEB SEARCH
        # ----------------------------------------------------

        if (
            "?" in text
            and WEB_SEARCH_AVAILABLE
        ):

            return smart_web_search(
                text
            )

        # ----------------------------------------------------
        # UNKNOWN
        # ----------------------------------------------------

        return (
            "I don't have enough reliable "
            "local information to answer "
            "that confidently.\n\n"
            "If it needs current information, "
            "ask me to search the web, for example:\n\n"
            "search the web Premier League standings"
        )


# ============================================================
# PIPELINE
# ============================================================

def process(
    message: str,
    client_id: str = "local"
) -> str:

    if (
        not isinstance(
            message,
            str
        )
        or not message.strip()
    ):

        return (
            "Please enter a message."
        )

    message = message.strip()

    if len(message) > MAX_INPUT:

        return (
            "That message is too long. "
            f"Maximum length is {MAX_INPUT} characters."
        )

    if contains_secret(message):

        return (
            "For your privacy, don't send "
            "passwords, API keys, access tokens "
            "or other secrets in chat."
        )

    allowed, category = safety_check(
        message
    )

    if not allowed:

        return safety_response(
            category
        )

    try:

        conversation.append({
            "role": "user",
            "content": message,
            "timestamp": time.time(),
        })

        reply = NexoraBrain.answer(
            message
        )

        if len(reply) > MAX_OUTPUT:

            reply = (
                reply[
                    :MAX_OUTPUT
                ].rstrip()
                + "…"
            )

        conversation.append({
            "role": "assistant",
            "content": reply,
            "timestamp": time.time(),
        })

        return reply

    except Exception:

        return (
            "Nexora encountered an internal "
            "problem and stopped safely."
        )


# ============================================================
# WEB UI
# ============================================================

HTML = r"""
<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Nexora</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;
    background: #050008;
    color: #fff;
    font-family: Arial, sans-serif;
}

.wrap {
    width: min(1050px, 94%);
    margin: 28px auto;
}

.head {
    text-align: center;
}

.logo {
    font-size: 64px;
    font-weight: 900;

    background:
        linear-gradient(
            90deg,
            #fff,
            #67ffff,
            #d000ff
        );

    color: transparent;
    background-clip: text;
    -webkit-background-clip: text;
}

.slogan {
    color: #67ffff;
    letter-spacing: 5px;
    font-size: 11px;
}

.status {
    color: #888;
    margin: 8px;
}

.chat {
    height: 68vh;
    min-height: 430px;
    overflow: auto;

    padding: 22px;

    border: 1px solid #5d1475;
    border-radius: 20px;

    background: #09060f;
}

.msg {
    max-width: 82%;

    padding: 14px 17px;
    margin: 0 0 16px;

    border-radius: 16px;

    white-space: pre-wrap;
    overflow-wrap: anywhere;

    line-height: 1.55;
}

.bot {
    border-left: 3px solid #67ffff;
    background: #18152a;
}

.user {
    margin-left: auto;

    background:
        linear-gradient(
            135deg,
            #6500ff,
            #c000ff
        );
}

.sender {
    display: block;

    color: #67ffff;

    font-size: 10px;
    font-weight: bold;

    letter-spacing: 2px;

    margin-bottom: 6px;
}

.composer {
    display: flex;
    gap: 10px;
    margin-top: 15px;
}

input {
    flex: 1;

    padding: 16px;

    border: 1px solid #7500ff;
    border-radius: 13px;

    background: #110819;
    color: #fff;

    font-size: 15px;

    outline: none;
}

button {
    border: 0;
    border-radius: 13px;

    padding: 0 25px;

    color: #fff;

    font-weight: bold;

    background:
        linear-gradient(
            135deg,
            #7000ff,
            #c000ff
        );

    cursor: pointer;
}

button:disabled {
    opacity: .5;
}

</style>

</head>

<body>

<div class="wrap">

<div class="head">

<div class="logo">
Nexora
</div>

<div class="slogan">
INTELLIGENCE. SECURED.
</div>

<div class="status">
v12.0 • Local Reasoning • Memory • Web Search
</div>

</div>

<div
    class="chat"
    id="chat"
>

<div class="msg bot">

<span class="sender">
NEXORA
</span>

Hey! I'm Nexora v12. What are we working on?

</div>

</div>

<form
    class="composer"
    id="form"
>

<input
    id="input"
    maxlength="5000"
    autocomplete="off"
    placeholder="Talk to Nexora..."
>

<button
    id="send"
>

Send

</button>

</form>

</div>

<script>

const form =
    document.getElementById("form");

const input =
    document.getElementById("input");

const send =
    document.getElementById("send");

const chat =
    document.getElementById("chat");


function addMessage(
    sender,
    text,
    type
) {

    const message =
        document.createElement("div");

    message.className =
        "msg " + type;

    const senderElement =
        document.createElement("span");

    senderElement.className =
        "sender";

    senderElement.textContent =
        sender;

    message.appendChild(
        senderElement
    );

    message.appendChild(
        document.createTextNode(text)
    );

    chat.appendChild(
        message
    );

    chat.scrollTop =
        chat.scrollHeight;
}


form.addEventListener(
    "submit",
    async function(event) {

        event.preventDefault();

        const text =
            input.value.trim();

        if (!text) {
            return;
        }

        addMessage(
            "YOU",
            text,
            "user"
        );

        input.value = "";

        send.disabled = true;

        try {

            const response =
                await fetch(
                    "/api/web-chat",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body: JSON.stringify({
                            message: text
                        })
                    }
                );

            const data =
                await response.json();

            addMessage(
                "NEXORA",
                data.reply ||
                data.error ||
                "No response.",
                "bot"
            );

        } catch (error) {

            addMessage(
                "NEXORA",
                "I could not connect to the server.",
                "bot"
            );

        } finally {

            send.disabled = false;

            input.focus();
        }
    }
);

input.focus();

</script>

</body>

</html>
"""


# ============================================================
# HTTP SERVER
# ============================================================

class Server(
    BaseHTTPRequestHandler
):

    server_version = (
        "NexoraHTTP/12.0"
    )

    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "X-Content-Type-Options",
            "nosniff"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    def do_GET(self):

        path = urlparse(
            self.path
        ).path

        if path == "/":

            body = HTML.encode(
                "utf-8"
            )

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(body))
            )

            self.end_headers()

            self.wfile.write(
                body
            )

            return

        if path == "/health":

            self.send_json({
                "status": "ok",
                "name": APP_NAME,
                "version": VERSION,
                "web_search":
                    WEB_SEARCH_AVAILABLE,
                "web_search_error":
                    WEB_SEARCH_ERROR,
            })

            return

        self.send_json(
            {"error": "Not found"},
            404
        )

    def do_POST(self):

        path = urlparse(
            self.path
        ).path

        if path not in (
            "/api/web-chat",
            "/api/chat",
        ):

            self.send_json(
                {"error": "Not found"},
                404
            )

            return

        if (
            path == "/api/chat"
            and API_KEY
        ):

            provided = self.headers.get(
                "X-API-Key",
                ""
            )

            if provided != API_KEY:

                self.send_json(
                    {
                        "error":
                        "Authentication required."
                    },
                    401
                )

                return

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            if (
                content_length <= 0
                or content_length > 100000
            ):

                self.send_json(
                    {
                        "error":
                        "Request too large."
                    },
                    413
                )

                return

            data = json.loads(
                self.rfile.read(
                    content_length
                ).decode("utf-8")
            )

            if not isinstance(
                data,
                dict
            ):

                self.send_json(
                    {
                        "error":
                        "JSON object required."
                    },
                    400
                )

                return

            message = data.get(
                "message"
            )

            if not isinstance(
                message,
                str
            ):

                self.send_json(
                    {
                        "error":
                        "The 'message' field "
                        "must be text."
                    },
                    400
                )

                return

            reply = process(
                message,
                self.client_address[0]
            )

            self.send_json({
                "reply": reply
            })

        except Exception:

            self.send_json(
                {
                    "error":
                    "Invalid request."
                },
                400
            )

    def log_message(
        self,
        format_string,
        *args
    ):

        return


# ============================================================
# STARTUP
# ============================================================

def main():

    load_data()

    print("=" * 60)

    print(
        f"{APP_NAME} {VERSION} - {SLOGAN}"
    )

    print(
        f"Port: {PORT}"
    )

    print(
        "Web search:",
        "ENABLED"
        if WEB_SEARCH_AVAILABLE
        else "DISABLED"
    )

    if not WEB_SEARCH_AVAILABLE:

        print(
            "Web search error:",
            WEB_SEARCH_ERROR
        )

    print("=" * 60)

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Server
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "Nexora shutting down."
        )

    finally:

        server.server_close()


if __name__ == "__main__":
startup()
