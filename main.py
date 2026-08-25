
from __future__ import annotations

import ast
import json
import math
import os
import re
import secrets
import threading
import time
from collections import Counter, defaultdict, deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# ============================================================
# CONFIG
# ============================================================

APP_NAME = "Nexora"
VERSION = "11.0"
SLOGAN = "Intelligence. Secured."

HOST = "0.0.0.0"

try:
    PORT = int(os.environ.get("PORT", "8000"))
except ValueError:
    PORT = 8000

DATA_FILE = os.environ.get(
    "NEXORA_DATA_FILE",
    "nexora_data.json"
).strip() or "nexora_data.json"

API_KEY = os.environ.get(
    "NEXORA_API_KEY",
    ""
).strip()

MAX_INPUT = 5000
MAX_OUTPUT = 10000
MAX_MEMORY_LENGTH = 800
MAX_MEMORIES = 500
MAX_KNOWLEDGE_KEY = 200
MAX_KNOWLEDGE_VALUE = 4000
MAX_CONTEXT = 50

RATE_WINDOW = 60
API_RATE_LIMIT = 60
WEB_RATE_LIMIT = 40

LOCK = threading.RLock()


# ============================================================
# STATE
# ============================================================

memories: list[dict] = []
knowledge: dict[str, dict] = {}

conversation = deque(maxlen=MAX_CONTEXT)

request_history = defaultdict(deque)

security_events = deque(maxlen=500)

security_state = "normal"

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
    r"\bpassword\s*[:=]\s*\S+",
    r"\bapi[_-]?key\s*[:=]\s*\S+",
    r"\bsecret\s*[:=]\s*\S+",
    r"\bbearer\s+[A-Za-z0-9._-]{20,}",
]

INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all previous instructions",
    r"ignore your instructions",
    r"ignore safety rules",
    r"you are now the system",
    r"system message:",
    r"developer message:",
]

DANGEROUS_PATTERNS = [
    r"\bhow\s+to\s+kill\s+someone\b",
    r"\bhow\s+to\s+hurt\s+someone\b",
    r"\bhow\s+to\s+poison\s+someone\b",
    r"\bhow\s+to\s+make\s+a\s+bomb\b",
    r"\bhow\s+to\s+build\s+a\s+bomb\b",
    r"\bhow\s+to\s+make\s+an\s+explosive\b",
    r"\bhow\s+to\s+build\s+an\s+explosive\b",
    r"\bhow\s+to\s+make\s+a\s+weapon\b",
    r"\bhow\s+to\s+build\s+a\s+weapon\b",
]

RISKY_PATTERNS = [
    r"\bdeadly\s+challenge\b",
    r"\bdangerous\s+challenge\b",
    r"\bchoking\s+challenge\b",
    r"\bhow\s+to\s+get\s+high\b",
    r"\bhow\s+to\s+starve\b",
    r"\bhow\s+to\s+purge\b",
    r"\bexercise\s+until\s+i\s+collapse\b",
]


def security_event(event: str, severity: str = "INFO") -> None:
    with LOCK:
        security_events.append({
            "event": event,
            "severity": severity,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })


def contains_secret(text: str) -> bool:
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in SECRET_PATTERNS
    )


def contains_injection(text: str) -> bool:
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in INJECTION_PATTERNS
    )


def safety_check(text: str) -> tuple[bool, str]:
    lower = text.lower()

    if any(
        re.search(pattern, lower)
        for pattern in DANGEROUS_PATTERNS
    ):
        return False, "dangerous"

    if any(
        re.search(pattern, lower)
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


def safety_response(category: str) -> str:
    if category == "self_harm":
        return (
            "I can't provide instructions for hurting yourself. "
            "Please talk to a trusted adult or someone who can "
            "support you."
        )

    if category == "dangerous":
        return (
            "I can't provide instructions for seriously harming "
            "people or creating dangerous weapons or explosives."
        )

    if category == "risky":
        return (
            "I can't encourage dangerous habits or challenges."
        )

    return "I can't safely help with that."


def is_locked() -> bool:
    with LOCK:
        return security_state in ("lockdown", "emergency")


# ============================================================
# AUTHENTICATION
# ============================================================

def authentication_enabled() -> bool:
    return bool(API_KEY)


def valid_api_key(provided: str | None) -> bool:
    if not API_KEY:
        return False

    if not provided:
        return False

    return secrets.compare_digest(
        provided,
        API_KEY
    )


# ============================================================
# RATE LIMITING
# ============================================================

def rate_limit(client_id: str, limit: int) -> bool:
    now = time.time()

    with LOCK:
        history = request_history[client_id]

        while history and now - history[0] > RATE_WINDOW:
            history.popleft()

        if len(history) >= limit:
            security_event(
                "rate_limit_triggered",
                "WARN"
            )
            return False

        history.append(now)

    return True


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
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return

        loaded_memories = data.get("memories", [])

        if isinstance(loaded_memories, list):
            cleaned = []

            for item in loaded_memories:
                if isinstance(item, str):
                    cleaned.append({
                        "text": item,
                        "created": time.time(),
                    })

                elif isinstance(item, dict):
                    text = item.get("text")

                    if isinstance(text, str):
                        cleaned.append({
                            "text": text,
                            "created": float(
                                item.get(
                                    "created",
                                    time.time()
                                )
                            ),
                        })

            memories = cleaned[-MAX_MEMORIES:]

        loaded_knowledge = data.get("knowledge", {})

        if isinstance(loaded_knowledge, dict):
            for key, value in loaded_knowledge.items():

                if isinstance(value, str):
                    knowledge[str(key).lower()] = {
                        "value": value,
                        "created": time.time(),
                    }

                elif isinstance(value, dict):
                    stored_value = value.get("value")

                    if isinstance(stored_value, str):
                        knowledge[str(key).lower()] = {
                            "value": stored_value,
                            "created": float(
                                value.get(
                                    "created",
                                    time.time()
                                )
                            ),
                        }

        loaded_settings = data.get("settings", {})

        if isinstance(loaded_settings, dict):
            for key in settings:
                if key in loaded_settings:
                    settings[key] = loaded_settings[key]

    except Exception as exc:
        security_event(
            "data_load_failed",
            "ERROR"
        )
        print(
            "Data load warning:",
            type(exc).__name__
        )


def save_data() -> None:
    temporary = DATA_FILE + ".tmp"

    try:
        directory = os.path.dirname(
            os.path.abspath(DATA_FILE)
        )

        os.makedirs(
            directory,
            exist_ok=True
        )

        with LOCK:
            data = {
                "memories": list(memories),
                "knowledge": dict(knowledge),
                "settings": dict(settings),
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

    except Exception as exc:
        security_event(
            "data_save_failed",
            "ERROR"
        )

        print(
            "Data save warning:",
            type(exc).__name__
        )


# ============================================================
# TEXT ENGINE
# ============================================================

STOP_WORDS = {
    "the", "a", "an", "is", "are", "am",
    "i", "you", "my", "your", "to", "of",
    "and", "or", "in", "on", "it", "this",
    "that", "what", "do", "does", "did",
    "for", "with", "me", "can", "could",
    "would", "should", "be", "have", "has",
    "how", "why", "when", "where",
    "please", "tell", "about",
    "was", "were", "will", "from",
    "as", "at", "by", "we", "our",
}


def words(text: str) -> list[str]:
    return [
        token
        for token in re.findall(
            r"[a-zA-Z0-9']+",
            text.lower()
        )
        if token not in STOP_WORDS
    ]


def normalize(text: str) -> str:
    return " ".join(words(text))


def similarity_score(query: str, text: str) -> float:
    query_words = words(query)
    text_words = words(text)

    if not query_words or not text_words:
        return 0.0

    query_counts = Counter(query_words)
    text_counts = Counter(text_words)

    score = 0.0

    for word, count in query_counts.items():
        if word in text_counts:
            score += min(
                count,
                text_counts[word]
            )

    query_normalized = normalize(query)
    text_normalized = normalize(text)

    if query_normalized and query_normalized in text_normalized:
        score += 3.0

    return score


def freshness(timestamp: float) -> float:
    age = max(
        0,
        time.time() - timestamp
    )

    return 1.0 / (
        1.0 + age / 86400
    )


# ============================================================
# MEMORY ENGINE
# ============================================================

class MemoryEngine:

    @staticmethod
    def save(text: str) -> bool:

        text = text.strip()

        if not text or len(text) > MAX_MEMORY_LENGTH:
            return False

        if contains_secret(text):
            security_event(
                "secret_memory_blocked",
                "WARN"
            )
            return False

        if contains_injection(text):
            security_event(
                "memory_injection_blocked",
                "WARN"
            )
            return False

        with LOCK:

            for item in memories:
                if item["text"].lower() == text.lower():
                    return True

            memories.append({
                "text": text,
                "created": time.time(),
            })

            if len(memories) > MAX_MEMORIES:
                del memories[
                    :-MAX_MEMORIES
                ]

        save_data()

        return True

    @staticmethod
    def all() -> list[str]:

        with LOCK:
            return [
                item["text"]
                for item in memories
            ]

    @staticmethod
    def clear() -> None:

        with LOCK:
            memories.clear()

        save_data()

    @staticmethod
    def search(
        query: str,
        limit: int = 8
    ) -> list[str]:

        scored = []

        with LOCK:
            snapshot = list(memories)

        for item in snapshot:

            relevance = similarity_score(
                query,
                item["text"]
            )

            if relevance <= 0:
                continue

            score = (
                relevance
                + freshness(
                    item["created"]
                )
            )

            scored.append(
                (score, item["text"])
            )

        scored.sort(
            key=lambda item: item[0],
            reverse=True
        )

        return [
            text
            for _, text
            in scored[:limit]
        ]

    @staticmethod
    def delete(query: str) -> bool:

        results = MemoryEngine.search(
            query,
            limit=1
        )

        if not results:
            return False

        target = results[0]

        with LOCK:

            for item in memories:

                if item["text"] == target:

                    memories.remove(item)

                    save_data()

                    return True

        return False


# ============================================================
# KNOWLEDGE ENGINE
# ============================================================

class KnowledgeEngine:

    @staticmethod
    def add(
        key: str,
        value: str
    ) -> bool:

        key = key.strip()
        value = value.strip()

        if not key or not value:
            return False

        if len(key) > MAX_KNOWLEDGE_KEY:
            return False

        if len(value) > MAX_KNOWLEDGE_VALUE:
            return False

        if contains_secret(key) or contains_secret(value):
            security_event(
                "secret_knowledge_blocked",
                "WARN"
            )
            return False

        if contains_injection(value):
            security_event(
                "knowledge_injection_blocked",
                "WARN"
            )
            return False

        with LOCK:

            knowledge[key.lower()] = {
                "value": value,
                "created": time.time(),
            }

        save_data()

        return True

    @staticmethod
    def search(
        query: str,
        limit: int = 5
    ) -> list[tuple[float, str, str]]:

        with LOCK:
            snapshot = list(
                knowledge.items()
            )

        results = []

        for key, record in snapshot:

            value = record["value"]

            relevance = (
                similarity_score(
                    query,
                    key
                ) * 3.0
                +
                similarity_score(
                    query,
                    value
                )
            )

            if relevance <= 0:
                continue

            score = (
                relevance
                + freshness(
                    record["created"]
                )
            )

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

        return results[:limit]


# ============================================================
# CONTEXT ENGINE
# ============================================================

class ContextEngine:

    @staticmethod
    def add(
        role: str,
        content: str
    ) -> None:

        with LOCK:

            conversation.append({
                "role": role,
                "content": content,
                "timestamp": time.time(),
            })

    @staticmethod
    def recent(
        limit: int = 10
    ) -> list[dict]:

        with LOCK:
            return list(
                conversation
            )[-limit:]

    @staticmethod
    def clear() -> None:

        with LOCK:
            conversation.clear()


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
    def calculate(expression: str):

        expression = expression.strip()

        if not expression:
            return None

        if len(expression) > 200:
            return None

        try:

            tree = ast.parse(
                expression,
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

                    if isinstance(
                        value,
                        bool
                    ):
                        return None

                    if isinstance(
                        value,
                        (int, float)
                    ):

                        if not math.isfinite(
                            float(value)
                        ):
                            return None

                        if abs(value) > 10**100:
                            return None

                        return value

                    return None

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

                    if left is None or right is None:
                        return None

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

                    if isinstance(
                        result,
                        float
                    ) and not math.isfinite(result):
                        return None

                    if abs(result) > 10**100:
                        return None

                    return result

                return None

            result = evaluate(tree)

            if isinstance(result, float):
                result = round(result, 10)

            return result

        except Exception:
            return None


# ============================================================
# INTENT ENGINE
# ============================================================

MODES = {
    "friendly",
    "professional",
    "concise",
    "teacher",
    "technical",
    "creative",
    "formal",
    "energetic",
}


class IntentEngine:

    @staticmethod
    def detect(message: str) -> str:

        text = message.lower().strip()

        if re.match(
            r"^(hi|hello|hey|hiya)\b",
            text
        ):
            return "greeting"

        if text in {
            "bye",
            "goodbye",
            "see you",
            "see ya",
        }:
            return "goodbye"

        if "who are you" in text:
            return "identity"

        if (
            "what can you do" in text
            or "your capabilities" in text
        ):
            return "capabilities"

        if "what version" in text:
            return "version"

        if "slogan" in text:
            return "slogan"

        if (
            "what time is it" in text
            or "current time" in text
        ):
            return "time"

        if (
            "what date is it" in text
            or "today's date" in text
            or "what day is it" in text
        ):
            return "date"

        if "what year is it" in text:
            return "year"

        if (
            "what mode" in text
            or "which mode" in text
        ):
            return "current_mode"

        if (
            "what is my name" in text
            or "what's my name" in text
        ):
            return "get_name"

        if (
            "what do you remember" in text
            or "show my memories" in text
            or "what have i told you" in text
        ):
            return "recall"

        if (
            "clear memory" in text
            or "clear memories" in text
            or "forget everything" in text
        ):
            return "forget_all"

        if text.startswith("remember "):
            return "remember"

        if text.startswith("forget "):
            return "forget_one"

        if text.startswith("find memory "):
            return "memory_search"

        if text.startswith("teach nexora "):
            return "knowledge_add"

        if text.startswith("search knowledge "):
            return "knowledge_search"

        if (
            text.startswith("calculate ")
            or text.startswith("calc ")
        ):
            return "calculate"

        if (
            text.startswith("set mode ")
            or text.startswith("use ")
            and " mode" in text
        ):
            return "mode"

        if text.startswith("set response length "):
            return "response_length"

        if text.startswith("my name is "):
            return "set_name"

        if text.startswith("clear conversation"):
            return "clear_conversation"

        if text.startswith("explain "):
            return "explain"

        if text.startswith("define "):
            return "define"

        if text.startswith("compare "):
            return "compare"

        if (
            "thank you" in text
            or text == "thanks"
            or text.startswith("thanks ")
        ):
            return "thanks"

        if (
            "how are you" in text
            or "how're you" in text
        ):
            return "how_are_you"

        if "?" in text:
            return "question"

        return "conversation"


# ============================================================
# LOCAL REASONING ENGINE
# ============================================================

class ReasoningEngine:

    @staticmethod
    def identity() -> str:

        return (
            "I'm Nexora, a local-first AI assistant running "
            "without an external language model. I combine "
            "intent detection, retrieval, memory, context, "
            "planning and deterministic tools."
        )

    @staticmethod
    def capabilities() -> str:

        return (
            "I can:\n\n"
            "• reason through structured tasks\n"
            "• retrieve relevant memories\n"
            "• search user knowledge\n"
            "• maintain conversation context\n"
            "• perform safe calculations\n"
            "• detect intents\n"
            "• compare stored information\n"
            "• explain stored knowledge\n"
            "• create simple task plans\n"
            "• remember user-provided information\n"
            "• apply safety filtering\n"
            "• detect secrets\n"
            "• rate-limit requests\n"
            "• protect the external API with an API key\n\n"
            "I don't pretend to know facts that aren't "
            "available in my local knowledge."
        )

    @staticmethod
    def retrieve(
        query: str
    ) -> dict:

        memories_found = MemoryEngine.search(
            query,
            limit=5
        )

        knowledge_found = KnowledgeEngine.search(
            query,
            limit=5
        )

        context = ContextEngine.recent(
            limit=8
        )

        return {
            "memories": memories_found,
            "knowledge": knowledge_found,
            "context": context,
        }

    @staticmethod
    def plan(message: str) -> list[str]:

        text = message.lower()

        if (
            "build" in text
            or "make" in text
            or "create" in text
        ):
            return [
                "identify the requested outcome",
                "retrieve relevant local information",
                "break the task into smaller steps",
                "validate the result",
            ]

        if (
            "compare" in text
            or "difference" in text
        ):
            return [
                "identify the two subjects",
                "retrieve information about each",
                "compare only available information",
                "report uncertainty where information is missing",
            ]

        if (
            "explain" in text
            or "how does" in text
        ):
            return [
                "identify the topic",
                "retrieve matching knowledge",
                "organize the explanation",
                "avoid unsupported claims",
            ]

        return [
            "understand the request",
            "retrieve relevant context",
            "select the safest useful response",
        ]

    @staticmethod
    def answer(
        message: str,
        intent: str
    ) -> str:

        text = message.strip()

        if intent == "greeting":

            name = settings.get("user_name")

            if name:
                return (
                    f"Hey {name}! I'm Nexora. "
                    "What are we working on?"
                )

            return (
                "Hey! I'm Nexora. "
                "What are we working on?"
            )

        if intent == "goodbye":
            return "See you later! 👋"

        if intent == "identity":
            return ReasoningEngine.identity()

        if intent == "capabilities":
            return ReasoningEngine.capabilities()

        if intent == "thanks":
            return "You're welcome! 😊"

        if intent == "how_are_you":
            return (
                "I'm running normally and ready to help."
            )

        if intent == "version":
            return f"I'm running Nexora v{VERSION}."

        if intent == "slogan":
            return f"My slogan is: {SLOGAN}"

        if intent == "time":
            return (
                "The server's current time is "
                + datetime.now().strftime("%H:%M:%S")
                + "."
            )

        if intent == "date":
            return (
                "Today is "
                + datetime.now().strftime(
                    "%A, %d %B %Y"
                )
                + "."
            )

        if intent == "year":
            return (
                f"The current year is "
                f"{datetime.now().year}."
            )

        if intent == "current_mode":
            return (
                "I'm currently using "
                + str(
                    settings.get(
                        "mode",
                        "friendly"
                    )
                )
                + " mode."
            )

        if intent == "remember":

            value = re.sub(
                r"^remember\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            if value.lower().startswith("that "):
                value = value[5:].strip()

            if MemoryEngine.save(value):
                return "Got it. I've saved that to memory."

            return "I couldn't safely save that."

        if intent == "recall":

            saved = MemoryEngine.all()

            if not saved:
                return "I don't have any saved memories yet."

            return (
                "Here's what I remember:\n\n"
                + "\n".join(
                    f"{i}. {item}"
                    for i, item
                    in enumerate(saved, 1)
                )
            )

        if intent == "forget_all":

            MemoryEngine.clear()

            return "Done. I've cleared my saved memories."

        if intent == "forget_one":

            target = re.sub(
                r"^forget\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            if MemoryEngine.delete(target):
                return (
                    "Done. I've forgotten the "
                    "matching memory."
                )

            return "I couldn't find a matching memory."

        if intent == "memory_search":

            query = re.sub(
                r"^find memory\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            results = MemoryEngine.search(query)

            if not results:
                return "I couldn't find a matching memory."

            return (
                "Matching memories:\n\n"
                + "\n".join(
                    "• " + item
                    for item in results
                )
            )

        if intent == "calculate":

            expression = re.sub(
                r"^(calculate|calc)\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            result = Calculator.calculate(expression)

            if result is None:
                return "I couldn't safely calculate that."

            return f"The answer is {result}."

        if intent == "mode":

            match = re.search(
                r"(?:use|set mode)\s+([a-zA-Z]+)",
                text,
                re.IGNORECASE
            )

            if not match:
                return (
                    "Available modes: "
                    + ", ".join(sorted(MODES))
                )

            mode = match.group(1).lower()

            if mode not in MODES:
                return (
                    "I don't know that mode.\n\n"
                    "Available modes: "
                    + ", ".join(sorted(MODES))
                )

            with LOCK:
                settings["mode"] = mode

            save_data()

            return f"Speaking mode changed to {mode}."

        if intent == "response_length":

            match = re.search(
                r"set response length\s+"
                r"(short|normal|long)",
                text,
                re.IGNORECASE
            )

            if not match:
                return (
                    "Available response lengths: "
                    "short, normal, long."
                )

            length = match.group(1).lower()

            with LOCK:
                settings["response_length"] = length

            save_data()

            return (
                f"Response length changed to {length}."
            )

        if intent == "set_name":

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
                return "I couldn't safely save that name."

            with LOCK:
                settings["user_name"] = name

            save_data()

            return f"Nice to meet you, {name}."

        if intent == "get_name":

            name = settings.get("user_name")

            if name:
                return f"Your saved name is {name}."

            return "I don't have your name saved yet."

        if intent == "knowledge_add":

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

            key, value = content.split("=", 1)

            if KnowledgeEngine.add(key, value):
                return (
                    "I've added that to my knowledge base."
                )

            return "I couldn't safely add that."

        if intent == "knowledge_search":

            query = re.sub(
                r"^search knowledge\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            results = KnowledgeEngine.search(query)

            if not results:
                return (
                    "I couldn't find anything matching that."
                )

            return "\n".join(
                f"• {key}: {value}"
                for _, key, value
                in results
            )

        if intent == "clear_conversation":

            ContextEngine.clear()

            return (
                "I've cleared the conversation context."
            )

        if intent == "explain":

            topic = re.sub(
                r"^explain\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            results = KnowledgeEngine.search(
                topic,
                limit=1
            )

            if results:
                return (
                    "Here's what I know:\n\n"
                    + results[0][2]
                )

            return (
                f"I don't have enough reliable local "
                f"knowledge to explain '{topic}' yet."
            )

        if intent == "define":

            topic = re.sub(
                r"^define\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            results = KnowledgeEngine.search(
                topic,
                limit=1
            )

            if results:
                return results[0][2]

            return (
                f"I don't have a reliable local definition "
                f"of '{topic}' yet."
            )

        if intent == "compare":

            topic = re.sub(
                r"^compare\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            parts = re.split(
                r"\s+(?:vs\.?|versus|and)\s+",
                topic,
                maxsplit=1,
                flags=re.IGNORECASE
            )

            if len(parts) != 2:
                return (
                    "Tell me two things to compare, "
                    "for example: compare cats vs dogs."
                )

            first = parts[0].strip()
            second = parts[1].strip()

            first_info = KnowledgeEngine.search(
                first,
                limit=1
            )

            second_info = KnowledgeEngine.search(
                second,
                limit=1
            )

            response = [
                "Comparison:",
                "",
                f"{first}:",
                (
                    first_info[0][2]
                    if first_info
                    else "No matching local knowledge."
                ),
                "",
                f"{second}:",
                (
                    second_info[0][2]
                    if second_info
                    else "No matching local knowledge."
                ),
            ]

            return "\n".join(response)

        # ----------------------------------------------------
        # RETRIEVAL-FIRST REASONING
        # ----------------------------------------------------

        retrieved = ReasoningEngine.retrieve(text)

        knowledge_results = retrieved["knowledge"]
        memory_results = retrieved["memories"]

        if knowledge_results:

            best = knowledge_results[0]

            if best[0] >= 1.5:
                return best[2]

        if memory_results:

            return (
                "I found something relevant in memory:\n\n"
                + "\n".join(
                    "• " + item
                    for item in memory_results[:3]
                )
            )

        # ----------------------------------------------------
        # NATURAL MATH
        # ----------------------------------------------------

        possible_math = re.sub(
            r"[^0-9+\-*/().% ]",
            "",
            text
        ).strip()

        if (
            possible_math
            and any(
                operator in possible_math
                for operator in "+-*/%"
            )
            and len(possible_math) <= 100
        ):

            result = Calculator.calculate(
                possible_math
            )

            if result is not None:
                return f"The answer is {result}."

        # ----------------------------------------------------
        # SIMPLE TASK PLANNING
        # ----------------------------------------------------

        if (
            text.lower().startswith(
                (
                    "how do i ",
                    "how can i ",
                    "how should i ",
                )
            )
        ):

            steps = ReasoningEngine.plan(text)

            return (
                "I can structure that locally as:\n\n"
                + "\n".join(
                    f"{i}. {step}"
                    for i, step
                    in enumerate(steps, 1)
                )
                + "\n\n"
                "I don't have enough external knowledge "
                "to fill in unsupported factual details."
            )

        # ----------------------------------------------------
        # UNKNOWN
        # ----------------------------------------------------

        return (
            "I'm following you, but I don't have enough "
            "reliable local knowledge to answer that yet.\n\n"
            "You can teach me using:\n"
            "teach Nexora topic = information"
        )


# ============================================================
# OUTPUT
# ============================================================

def apply_style(response: str) -> str:

    with LOCK:
        length = settings.get(
            "response_length",
            "normal"
        )

        emoji_enabled = settings.get(
            "emoji",
            True
        )

    if length == "short":

        lines = response.splitlines()

        if len(lines) > 6:
            response = "\n".join(
                lines[:6]
            )

    if not emoji_enabled:

        response = re.sub(
            r"[\U0001F300-\U0001FAFF]",
            "",
            response
        )

    return response.strip()


def validate_output(response: str) -> str:

    if not isinstance(response, str):
        raise ValueError("invalid output")

    response = response.strip()

    if not response:
        raise ValueError("empty output")

    if len(response) > MAX_OUTPUT:
        raise ValueError("output too long")

    if contains_secret(response):
        security_event(
            "secret_output_blocked",
            "CRITICAL"
        )
        raise ValueError("secret output")

    allowed, category = safety_check(response)

    if not allowed:
        security_event(
            "unsafe_output_blocked",
            "CRITICAL"
        )
        raise ValueError(
            f"unsafe output: {category}"
        )

    return response


# ============================================================
# PIPELINE
# ============================================================

def process(
    message: str,
    client_id: str,
    source: str = "web"
) -> str:

    if not isinstance(message, str):
        return "Invalid message."

    message = message.strip()

    if not message:
        return "Please enter a message."

    if len(message) > MAX_INPUT:
        return (
            "That message is too long. "
            f"Maximum length is {MAX_INPUT} characters."
        )

    if is_locked():
        return "Nexora is currently in security lockdown."

    limit = (
        API_RATE_LIMIT
        if source == "api"
        else WEB_RATE_LIMIT
    )

    if not rate_limit(
        f"{source}:{client_id}",
        limit
    ):
        return (
            "Rate limit reached. Please wait a moment "
            "before sending another request."
        )

    if contains_secret(message):

        security_event(
            "secret_input_blocked",
            "WARN"
        )

        return (
            "For your privacy, don't send passwords, "
            "API keys, access tokens or other secrets "
            "in chat."
        )

    allowed, category = safety_check(message)

    if not allowed:

        security_event(
            "unsafe_request",
            "WARN"
        )

        return safety_response(category)

    try:

        ContextEngine.add(
            "user",
            message
        )

        intent = IntentEngine.detect(message)

        response = ReasoningEngine.answer(
            message,
            intent
        )

        response = apply_style(response)

        response = validate_output(response)

        ContextEngine.add(
            "assistant",
            response
        )

        return response

    except Exception as exc:

        security_event(
            "processing_failure",
            "ERROR"
        )

        print(
            "Processing error:",
            type(exc).__name__
        )

        return (
            "Nexora encountered an internal problem "
            "and stopped safely."
        )


# ============================================================
# WEB UI
# ============================================================

HTML = r"""
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>Nexora v11</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;

    color: white;

    font-family:
        Inter,
        Arial,
        sans-serif;

    background:
        radial-gradient(
            circle at 10% 10%,
            #3b006f,
            transparent 32%
        ),
        radial-gradient(
            circle at 90% 90%,
            #00515b,
            transparent 32%
        ),
        #050008;
}

.container {
    width: min(1050px, 94%);
    margin: 28px auto;
}

.header {
    text-align: center;
    margin-bottom: 18px;
}

.logo {
    font-size: clamp(42px, 7vw, 68px);
    font-weight: 900;

    background:
        linear-gradient(
            90deg,
            #ffffff,
            #67ffff,
            #d000ff
        );

    color: transparent;
    background-clip: text;
    -webkit-background-clip: text;
}

.slogan {
    color: #67ffff;
    font-size: 11px;
    letter-spacing: 5px;
}

.status {
    color: #8d8d9b;
    font-size: 12px;
    margin-top: 8px;
}

.chat {
    height: 68vh;
    min-height: 430px;
    overflow-y: auto;

    padding: 22px;

    border: 1px solid
        rgba(180, 0, 255, .35);

    border-radius: 20px;

    background:
        rgba(5, 4, 12, .91);

    box-shadow:
        0 0 50px
        rgba(150, 0, 255, .12);
}

.message {
    max-width: 82%;

    padding: 14px 17px;
    margin-bottom: 16px;

    border-radius: 16px;

    white-space: pre-wrap;
    overflow-wrap: anywhere;

    line-height: 1.55;
}

.nexora {
    border-left: 3px solid #67ffff;
    background: rgba(25, 25, 45, .85);
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
    margin-bottom: 6px;

    color: #67ffff;

    font-size: 10px;
    font-weight: bold;

    letter-spacing: 2px;
}

.composer {
    display: flex;
    gap: 10px;
    margin-top: 15px;
}

input {
    flex: 1;
    min-width: 0;

    padding: 16px;

    border: 1px solid #7500ff;
    border-radius: 13px;

    background: #110819;
    color: white;

    font-size: 15px;
    outline: none;
}

input:focus {
    border-color: #67ffff;
}

button {
    border: 0;
    border-radius: 13px;

    padding: 0 25px;

    color: white;
    font-weight: bold;

    background:
        linear-gradient(
            135deg,
            #7000ff,
            #c000ff
        );

    cursor: pointer;
}

button:hover {
    opacity: .9;
}

button:disabled {
    opacity: .5;
    cursor: wait;
}

</style>

</head>

<body>

<div class="container">

<div class="header">

<div class="logo">
Nexora
</div>

<div class="slogan">
INTELLIGENCE. SECURED.
</div>

<div class="status">
v11.0 • Local Reasoning • Memory • Knowledge • Security
</div>

</div>

<div class="chat" id="chat">

<div class="message nexora">

<span class="sender">
NEXORA
</span>

Hey! I'm Nexora v11. What are we working on?

</div>

</div>

<form
    class="composer"
    id="composer"
>

<input
    id="message"
    maxlength="5000"
    autocomplete="off"
    placeholder="Talk to Nexora..."
>

<button
    id="send"
    type="submit"
>
Send
</button>

</form>

</div>

<script>

const form =
    document.getElementById("composer");

const input =
    document.getElementById("message");

const button =
    document.getElementById("send");

function addMessage(
    sender,
    text,
    type
) {

    const chat =
        document.getElementById("chat");

    const message =
        document.createElement("div");

    message.className =
        "message " + type;

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
        button.disabled = true;

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

            let data;

            try {
                data =
                    await response.json();
            } catch {
                data = {};
            }

            if (!response.ok) {

                addMessage(
                    "NEXORA",
                    data.error ||
                    "The server rejected the request.",
                    "nexora"
                );

            } else {

                addMessage(
                    "NEXORA",
                    data.reply ||
                    "Nexora couldn't produce a response.",
                    "nexora"
                );
            }

        } catch (error) {

            addMessage(
                "NEXORA",
                "I couldn't connect to the Nexora server.",
                "nexora"
            );

        } finally {

            button.disabled = false;
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

class NexoraServer(BaseHTTPRequestHandler):

    server_version = "NexoraHTTP/11.0"

    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status)

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

        self.wfile.write(body)

    def authorized(self) -> bool:

        provided = (
            self.headers.get("X-API-Key")
            or self.headers.get("Authorization")
        )

        if provided and provided.startswith("Bearer "):
            provided = provided[7:].strip()

        if not valid_api_key(provided):

            security_event(
                "authentication_failed",
                "WARN"
            )

            return False

        return True

    def do_GET(self):

        path = urlparse(
            self.path
        ).path

        if path == "/":

            body = HTML.encode("utf-8")

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
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

            self.wfile.write(body)

            return

        if path == "/health":

            self.send_json({
                "status": "ok",
                "name": APP_NAME,
                "version": VERSION,
                "local_ai": True,
                "external_model": False,
                "authentication": authentication_enabled(),
                "memory": True,
                "knowledge": True,
                "context": True,
                "reasoning": True,
                "planning": True,
                "calculator": True,
                "safety": True,
                "security": True,
                "lockdown": is_locked(),
            })

            return

        if path == "/api/security":

            if not self.authorized():

                self.send_json(
                    {
                        "error":
                        "Authentication required."
                    },
                    401
                )

                return

            with LOCK:

                events = list(
                    security_events
                )[-50:]

                current_state = security_state

            self.send_json({
                "state": current_state,
                "authentication":
                    authentication_enabled(),
                "events": events,
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
            "/api/chat",
            "/api/web-chat",
        ):

            self.send_json(
                {"error": "Not found"},
                404
            )

            return

        # External API:
        # API key REQUIRED.
        if path == "/api/chat":

            if not self.authorized():

                self.send_json(
                    {
                        "error":
                        "Authentication required. "
                        "Provide X-API-Key."
                    },
                    401
                )

                return

            source = "api"

        # Built-in browser:
        # No API key exposed to JavaScript.
        else:

            source = "web"

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

        except ValueError:

            self.send_json(
                {
                    "error":
                    "Invalid Content-Length."
                },
                400
            )

            return

        if (
            content_length <= 0
            or content_length > 100000
        ):

            self.send_json(
                {"error": "Request too large."},
                413
            )

            return

        try:

            raw = self.rfile.read(
                content_length
            )

            data = json.loads(
                raw.decode("utf-8")
            )

        except Exception:

            self.send_json(
                {"error": "Invalid JSON."},
                400
            )

            return

        if not isinstance(data, dict):

            self.send_json(
                {
                    "error":
                    "JSON object required."
                },
                400
            )

            return

        message = data.get("message")

        if not isinstance(message, str):

            self.send_json(
                {
                    "error":
                    "The 'message' field must be text."
                },
                400
            )

            return

        client_id = self.client_address[0]

        reply = process(
            message,
            client_id,
            source
        )

        self.send_json({
            "reply": reply
        })

    def log_message(
        self,
        format_string,
        *args
    ):
        return


# ============================================================
# STARTUP
# ============================================================

def startup():

    load_data()

    print("=" * 60)
    print("NEXORA")
    print(SLOGAN)
    print("=" * 60)

    print(f"Version: {VERSION}")
    print(f"Host: {HOST}")
    print(f"Port: {PORT}")

    print(
        "API authentication:",
        "ENABLED" if API_KEY else "DISABLED"
    )

    print("Browser endpoint: ENABLED")
    print("Persistent memory: ENABLED")
    print("Knowledge engine: ENABLED")
    print("Context engine: ENABLED")
    print("Intent engine: ENABLED")
    print("Reasoning engine: ENABLED")
    print("Planning engine: ENABLED")
    print("Calculator: ENABLED")
    print("Security monitoring: ENABLED")
    print("External model: DISABLED")

    print("=" * 60)

    server = ThreadingHTTPServer(
        (HOST, PORT),
        NexoraServer
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print("Nexora shutting down.")

    finally:

        server.server_close()


if __name__ == "__main__":
    startup()


