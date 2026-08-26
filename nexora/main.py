from __future__ import annotations

import ast
import hashlib
import html
from html.parser import HTMLParser
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ============================================================
# NEXORA 5.0
# Single-file • API-key-free • Render-friendly
#
# This is a robust local assistant shell. It does NOT contain
# a language model. It provides:
#   - session-aware conversations
#   - safe calculator
#   - web search with parsing/fallbacks
#   - current UTC/server time
#   - request validation and rate limiting
#   - CSRF protection for browser POSTs
#   - responsive UI with history restore
#
# No external Python packages are required.
# ============================================================


# ----------------------------- configuration -----------------

HOST = "0.0.0.0"
try:
    PORT = int(os.environ.get("PORT", "10000"))
except ValueError:
    PORT = 10000

if not 1 <= PORT <= 65535:
    PORT = 10000

SERVER_NAME = "Nexora"
SERVER_VERSION = "5.0"

MAX_MESSAGE_LENGTH = 4000
MAX_HISTORY_ITEMS = 100
MAX_SEARCH_RESULTS = 8
MAX_SEARCH_QUERY_LENGTH = 500
MAX_REQUEST_SIZE = 100_000
MAX_SEARCH_RESPONSE_BYTES = 2_000_000
SEARCH_TIMEOUT = 8
MAX_CONNECTIONS = 80

RATE_WINDOW_SECONDS = 60
RATE_MAX_REQUESTS = 30
SEARCH_RATE_MAX = 10

SESSION_COOKIE = "nexora_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7
MAX_SESSIONS = 5000

USER_AGENT = (
    "Nexora/5.0 (+local-assistant) "
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)

ALLOWED_METHODS = "GET, POST, OPTIONS"


# ----------------------------- logging -----------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("nexora")


# ----------------------------- state --------------------------

@dataclass
class SessionState:
    csrf_token: str
    history: deque[dict] = field(
        default_factory=lambda: deque(maxlen=MAX_HISTORY_ITEMS)
    )
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionState] = {}

    def create(self) -> tuple[str, SessionState]:
        with self._lock:
            self._prune_locked()
            session_id = secrets.token_urlsafe(32)
            state = SessionState(csrf_token=secrets.token_urlsafe(32))
            self._sessions[session_id] = state
            return session_id, state

    def get(self, session_id: str) -> SessionState | None:
        with self._lock:
            state = self._sessions.get(session_id)
            if state:
                state.last_seen = time.time()
            return state

    def get_or_create(self, session_id: str | None) -> tuple[str, SessionState]:
        if session_id:
            state = self.get(session_id)
            if state:
                return session_id, state
        return self.create()

    def clear(self, session_id: str) -> None:
        state = self.get(session_id)
        if state:
            with self._lock:
                state.history.clear()

    def _prune_locked(self) -> None:
        now = time.time()
        expired = [
            sid for sid, state in self._sessions.items()
            if now - state.last_seen > SESSION_MAX_AGE
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

        if len(self._sessions) >= MAX_SESSIONS:
            oldest = sorted(
                self._sessions.items(),
                key=lambda item: item[1].last_seen,
            )
            for sid, _ in oldest[: max(1, len(oldest) - MAX_SESSIONS + 1)]:
                self._sessions.pop(sid, None)


sessions = SessionStore()


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        cutoff = now - RATE_WINDOW_SECONDS
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            if len(self._hits) > 10000:
                stale = [
                    k for k, v in self._hits.items()
                    if not v or v[-1] < cutoff
                ]
                for k in stale[:2000]:
                    self._hits.pop(k, None)
            return True


rate_limiter = RateLimiter()


class SearchCache:
    def __init__(self, ttl: int = 90, max_items: int = 256) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._lock = threading.RLock()
        self._items: dict[str, tuple[float, list[dict]]] = {}

    def get(self, key: str) -> list[dict] | None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires, results = item
            if expires <= now:
                self._items.pop(key, None)
                return None
            return [dict(result) for result in results]

    def put(self, key: str, results: list[dict]) -> None:
        with self._lock:
            self._items[key] = (
                time.monotonic() + self.ttl,
                [dict(result) for result in results],
            )
            if len(self._items) > self.max_items:
                oldest = sorted(
                    self._items.items(),
                    key=lambda item: item[1][0],
                )
                for key_to_remove, _ in oldest[
                    : len(self._items) - self.max_items
                ]:
                    self._items.pop(key_to_remove, None)


search_cache = SearchCache()


# ----------------------------- helpers -----------------------

def now_timestamp() -> float:
    return time.time()


def utc_iso(ts: float | None = None) -> str:
    value = datetime.fromtimestamp(
        ts if ts is not None else time.time(),
        tz=timezone.utc,
    )
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clamp_text(value: str, maximum: int) -> str:
    value = value or ""
    if len(value) <= maximum:
        return value
    return value[:maximum].rstrip() + "…"


def clean_html(value: str) -> str:
    if not value:
        return ""
    value = re.sub(
        r"<(script|style|noscript)\b[^>]*>.*?</\1>",
        " ",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"<[^>]*>", " ", value)
    return normalize_text(html.unescape(value))


def json_bytes(data: object) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def valid_http_url(raw_url: str) -> bool:
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc or parsed.username or parsed.password:
        return False
    if len(raw_url) > 4096:
        return False
    return True


def extract_search_url(raw_url: str) -> str:
    raw_url = html.unescape(raw_url).strip()
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url

    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return ""

    query = parse_qs(parsed.query)
    for key in ("uddg", "url", "target"):
        values = query.get(key)
        if values:
            candidate = unquote(values[0]).strip()
            if valid_http_url(candidate):
                return candidate

    if valid_http_url(raw_url):
        return raw_url
    return ""


def normalize_search_query(query: str) -> str:
    return normalize_text(query)[:MAX_SEARCH_QUERY_LENGTH]


# ----------------------------- safe calculator ---------------

MATH_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

MATH_FUNCTIONS = {
    "sqrt": (math.sqrt, 1, 1),
    "sin": (math.sin, 1, 1),
    "cos": (math.cos, 1, 1),
    "tan": (math.tan, 1, 1),
    "log": (math.log, 1, 2),
    "log10": (math.log10, 1, 1),
    "ceil": (math.ceil, 1, 1),
    "floor": (math.floor, 1, 1),
    "fabs": (math.fabs, 1, 1),
    "factorial": (math.factorial, 1, 1),
    "abs": (abs, 1, 1),
    "round": (round, 1, 2),
}

BINARY_OPERATORS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}

UNARY_OPERATORS = {
    ast.UAdd: lambda value: +value,
    ast.USub: lambda value: -value,
}

MAX_CALC_DEPTH = 25
MAX_ABS_RESULT = 1e100
MAX_INTEGER_BITS = 340


def validate_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Only finite numbers are allowed.")

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("The result is not finite.")
        if abs(value) > MAX_ABS_RESULT:
            raise ValueError("The result is too large.")

    if isinstance(value, int):
        if value.bit_length() > MAX_INTEGER_BITS:
            raise ValueError("The result is too large.")

    return value


def safe_calculate(expression: str):
    expression = normalize_text(expression)
    if not expression:
        raise ValueError("No expression was provided.")
    if len(expression) > 250:
        raise ValueError("That expression is too long.")

    # Friendly syntax for common calculator input.
    expression = expression.replace("^", "**")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(
            "That is not a valid mathematical expression."
        ) from exc

    def evaluate(node, depth=0):
        if depth > MAX_CALC_DEPTH:
            raise ValueError("That expression is too deeply nested.")

        if isinstance(node, ast.Expression):
            return evaluate(node.body, depth + 1)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(
                node.value, bool
            ):
                return validate_number(node.value)
            raise ValueError("Invalid value.")

        if isinstance(node, ast.Name):
            if node.id in MATH_CONSTANTS:
                return MATH_CONSTANTS[node.id]
            raise ValueError(f"'{node.id}' is not allowed.")

        if isinstance(node, ast.UnaryOp):
            operator = UNARY_OPERATORS.get(type(node.op))
            if operator is None:
                raise ValueError("That operator is not allowed.")
            return validate_number(
                operator(evaluate(node.operand, depth + 1))
            )

        if isinstance(node, ast.BinOp):
            operator = BINARY_OPERATORS.get(type(node.op))
            if operator is None:
                raise ValueError("That operator is not allowed.")

            left = evaluate(node.left, depth + 1)
            right = evaluate(node.right, depth + 1)

            if isinstance(node.op, ast.Pow):
                if isinstance(right, (int, float)) and abs(right) > 100:
                    raise ValueError("That power is too large.")
                if isinstance(left, (int, float)) and abs(left) > 1e6:
                    raise ValueError("That power base is too large.")

            try:
                result = operator(left, right)
            except (ArithmeticError, OverflowError, ValueError) as exc:
                raise ValueError(
                    "The calculation could not be completed."
                ) from exc

            return validate_number(result)

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("That function is not allowed.")

            entry = MATH_FUNCTIONS.get(node.func.id)
            if entry is None:
                raise ValueError(
                    f"'{node.func.id}' is not an allowed function."
                )

            function, minimum, maximum = entry
            argc = len(node.args)
            if not minimum <= argc <= maximum:
                raise ValueError(
                    f"{node.func.id} expects {minimum}–{maximum} argument(s)."
                )

            arguments = [
                evaluate(argument, depth + 1)
                for argument in node.args
            ]

            if node.func.id == "factorial":
                value = arguments[0]
                if not isinstance(value, int) or value < 0 or value > 1000:
                    raise ValueError(
                        "factorial() accepts integers from 0 to 1000."
                    )

            try:
                result = function(*arguments)
            except (ArithmeticError, OverflowError, ValueError) as exc:
                raise ValueError(
                    "The calculation could not be completed."
                ) from exc

            return validate_number(result)

        raise ValueError(
            "That expression contains something the calculator "
            "does not support."
        )

    return evaluate(tree)


# ----------------------------- search -------------------------

SEARCH_PREFIXES = (
    "search for ",
    "search ",
    "look up ",
    "look for ",
    "find online ",
    "web search ",
    "google ",
)


def get_search_query(message: str) -> str | None:
    lowered = message.casefold().strip()
    for prefix in SEARCH_PREFIXES:
        if lowered.startswith(prefix):
            query = normalize_search_query(message[len(prefix):])
            return query or None
    return None


class SearchResultParser(HTMLParser):
    """Small, dependency-free parser for search-engine result cards."""

    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.results: list[dict] = []
        self._current: dict | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._seen: set[str] = set()

    def _finish_capture(self) -> None:
        if self._current is None or self._capture is None:
            return
        text = clean_html(" ".join(self._buffer))
        if self._capture == "title":
            self._current["title"] = clamp_text(text, 250)
        elif self._capture == "snippet":
            self._current["snippet"] = clamp_text(text, 600)
        self._capture = None
        self._buffer.clear()

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)
        classes = set((attrs_dict.get("class") or "").split())

        if tag == "a" and "result__a" in classes:
            self._finish_capture()
            url = extract_search_url(attrs_dict.get("href", ""))
            if (
                url
                and url not in self._seen
                and len(self.results) < self.limit
            ):
                self._seen.add(url)
                self._current = {
                    "title": "",
                    "url": url,
                    "snippet": "",
                    "source": urlparse(url).netloc.lower(),
                }
                self.results.append(self._current)
                self._capture = "title"
                self._buffer.clear()
            return

        if (
            self._current is not None
            and tag in {"div", "a", "span"}
            and "result__snippet" in classes
        ):
            self._finish_capture()
            self._capture = "snippet"
            self._buffer.clear()

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a":
            self._finish_capture()
        elif self._capture == "snippet" and tag in {"div", "a", "span"}:
            self._finish_capture()

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)


class BingResultParser(HTMLParser):
    """Dependency-free parser for Bing result cards."""

    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.results: list[dict] = []
        self._inside_result = False
        self._current: dict | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._seen: set[str] = set()
        self._depth = 0

    def _finish_capture(self) -> None:
        if self._current is None or self._capture is None:
            return
        text = clean_html(" ".join(self._buffer))
        if self._capture == "title":
            self._current["title"] = clamp_text(text, 250)
        elif self._capture == "snippet":
            self._current["snippet"] = clamp_text(text, 600)
        self._capture = None
        self._buffer.clear()

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)
        classes = set((attrs_dict.get("class") or "").split())

        if tag == "li" and "b_algo" in classes:
            self._finish_capture()
            self._inside_result = True
            self._depth = 1
            self._current = None
            self._capture = None
            self._buffer.clear()
            return

        if not self._inside_result:
            return

        self._depth += 1

        if tag == "h2":
            self._finish_capture()
            self._capture = "title"
            self._buffer.clear()
            return

        if tag == "a" and self._current is None:
            url = extract_search_url(attrs_dict.get("href", ""))
            if url and url not in self._seen:
                self._seen.add(url)
                self._current = {
                    "title": "",
                    "url": url,
                    "snippet": "",
                    "source": urlparse(url).netloc.lower(),
                }
                self.results.append(self._current)
            return

        if tag == "p" and self._current is not None:
            self._finish_capture()
            self._capture = "snippet"
            self._buffer.clear()

    def handle_endtag(self, tag: str) -> None:
        if not self._inside_result:
            return

        if self._capture == "title" and tag == "h2":
            self._finish_capture()
        elif self._capture == "snippet" and tag == "p":
            self._finish_capture()

        self._depth -= 1
        if tag == "li" and self._depth <= 0:
            self._finish_capture()
            self._inside_result = False
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)


def parse_ddg_results(source: str, limit: int) -> list[dict]:
    parser = SearchResultParser(limit)
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        logger.exception("DuckDuckGo HTML parsing failed")
    return [
        result for result in parser.results
        if result.get("title") and valid_http_url(result.get("url", ""))
    ][:limit]


def parse_bing_results(source: str, limit: int) -> list[dict]:
    parser = BingResultParser(limit)
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        logger.exception("Bing HTML parsing failed")
    return [
        result for result in parser.results
        if result.get("title") and valid_http_url(result.get("url", ""))
    ][:limit]

def fetch_search_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    with urlopen(request, timeout=SEARCH_TIMEOUT) as response:
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise ValueError("Invalid search response size.") from exc
            if declared_length > MAX_SEARCH_RESPONSE_BYTES:
                raise ValueError("Search response is too large.")

        data = response.read(MAX_SEARCH_RESPONSE_BYTES + 1)
        if len(data) > MAX_SEARCH_RESPONSE_BYTES:
            raise ValueError("Search response is too large.")

        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")


def search_duckduckgo(query: str, limit: int = MAX_SEARCH_RESULTS) -> list[dict]:
    query = normalize_search_query(query)
    if not query:
        return []

    key = hashlib.sha256(
        query.casefold().encode("utf-8")
    ).hexdigest()

    cached = search_cache.get(key)
    if cached is not None:
        return cached[:limit]

    urls = [
        (
            "https://html.duckduckgo.com/html/"
            f"?q={quote_plus(query)}"
        ),
        (
            "https://www.google.com/search?"
            f"q={quote_plus(query)}&hl=en"
        ),
    ]

    parsers = [parse_ddg_results, parse_bing_results]

    for index, search_url in enumerate(urls):
        try:
            source = fetch_search_page(search_url)
            results = parsers[index](source, limit)
            if results:
                search_cache.put(key, results)
                return results
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("Search provider %s failed: %s", index + 1, exc)
        except Exception:
            logger.exception("Unexpected search parser error")

    return []


# ----------------------------- assistant ---------------------

def is_time_query(message: str) -> bool:
    return normalize_text(message).casefold() in {
        "time",
        "what time is it",
        "what's the time",
        "current time",
        "what is the current time",
    }


def is_version_query(message: str) -> bool:
    return normalize_text(message).casefold() in {
        "version",
        "what version are you",
        "what version is this",
    }


def is_help_query(message: str) -> bool:
    return normalize_text(message).casefold() in {
        "help",
        "commands",
        "features",
        "what can you do",
    }


def assistant_response(message: str) -> dict:
    message = normalize_text(message)

    if not message:
        return {
            "type": "error",
            "message": "Please enter a message.",
        }

    calculator_match = re.match(
        r"^(?:calculate|calc)\s+(.+)$",
        message,
        flags=re.I,
    )
    if calculator_match:
        expression = calculator_match.group(1).strip()
        try:
            result = safe_calculate(expression)
            return {
                "type": "calculator",
                "message": f"**{expression}** = **{result}**",
                "result": result,
            }
        except ValueError as exc:
            return {
                "type": "error",
                "message": str(exc),
            }

    search_query = get_search_query(message)
    if search_query:
        started = time.monotonic()
        results = search_duckduckgo(search_query)
        duration_ms = round((time.monotonic() - started) * 1000)

        if not results:
            return {
                "type": "search",
                "message": (
                    f"I couldn't retrieve usable results for "
                    f"**{search_query}** right now."
                ),
                "results": [],
                "query": search_query,
                "duration_ms": duration_ms,
            }

        return {
            "type": "search",
            "message": (
                f"Found {len(results)} web result(s) for "
                f"**{search_query}**."
            ),
            "results": results,
            "query": search_query,
            "duration_ms": duration_ms,
        }

    if is_help_query(message):
        return {
            "type": "chat",
            "message": (
                "### Nexora\n\n"
                "🔎 **Web search** — `search <topic>`\n\n"
                "🧮 **Calculator** — `calculate 125 * 48`\n\n"
                "🕒 **Time** — ask `time`\n\n"
                "ℹ️ **Version** — ask `version`\n\n"
                "💬 Normal conversation is supported by the local "
                "assistant shell. Nexora does not include a built-in "
                "language model or require an OpenAI API key."
            ),
        }

    if message.casefold() in {"hi", "hello", "hey", "yo", "hiya"}:
        return {
            "type": "chat",
            "message": "Hey! 👋 Nexora is online and ready.",
        }

    if is_time_query(message):
        return {
            "type": "chat",
            "message": (
                f"The server time is **"
                f"{datetime.now().astimezone().strftime('%H:%M:%S')}** "
                f"(server timezone)."
            ),
        }

    if is_version_query(message):
        return {
            "type": "chat",
            "message": f"You're running **{SERVER_NAME} {SERVER_VERSION}**.",
        }

    return {
        "type": "chat",
        "message": (
            "I can handle web searches, calculations, time, and "
            "Nexora commands. Try `help`, or start a search with "
            "`search ...`."
        ),
    }


# ----------------------------- HTML ---------------------------

INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#070a12">
<meta name="description" content="Nexora 5.0 local assistant workspace">
<title>Nexora 5.0</title>
<style>
:root{
  --bg:#070a12;--panel:#0d121d;--panel2:#101725;--line:#20293a;
  --text:#f4f7ff;--muted:#96a1b5;--dim:#687389;--accent:#5cecff;
  --accent2:#9c6cff;--danger:#ff6b7a;--radius:18px;
}
*{box-sizing:border-box}
html,body{width:100%;height:100%;margin:0}
body{
  overflow:hidden;color:var(--text);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:
    radial-gradient(circle at 85% 0,rgba(92,236,255,.10),transparent 28%),
    radial-gradient(circle at 0 100%,rgba(156,108,255,.10),transparent 30%),
    var(--bg);
}
button,textarea{font:inherit}
button{cursor:pointer}
.app{height:100%;display:flex}
.sidebar{
  width:270px;flex:0 0 270px;padding:20px 15px;display:flex;flex-direction:column;
  border-right:1px solid var(--line);background:rgba(7,10,18,.82);backdrop-filter:blur(20px)
}
.brand{display:flex;gap:12px;align-items:center;padding:4px 8px 22px}
.brand-icon,.welcome-icon{
  display:grid;place-items:center;color:var(--accent);
  background:linear-gradient(135deg,rgba(92,236,255,.10),rgba(156,108,255,.12));
  border:1px solid rgba(92,236,255,.28);box-shadow:0 0 40px rgba(92,236,255,.07)
}
.brand-icon{width:42px;height:42px;border-radius:14px;font-size:20px}
.brand-name{font-size:15px;font-weight:900;letter-spacing:3px}
.brand-version{font-size:9px;color:var(--dim);font-weight:800;letter-spacing:1.5px;margin-top:3px}
.new-chat,.side-button,.quick-action,.icon-button{
  color:var(--text);background:transparent;border:1px solid transparent;border-radius:12px;
  transition:.18s ease
}
.new-chat{
  display:flex;gap:9px;align-items:center;width:100%;padding:12px;
  background:linear-gradient(135deg,rgba(92,236,255,.08),rgba(156,108,255,.08));
  border-color:rgba(92,236,255,.24)
}
.new-chat:hover,.side-button:hover,.quick-action:hover,.icon-button:hover{
  transform:translateY(-1px);border-color:rgba(92,236,255,.28);background:rgba(255,255,255,.04)
}
.sidebar-title{margin:28px 10px 9px;color:var(--dim);font-size:9px;font-weight:900;letter-spacing:1.7px}
.side-button{width:100%;display:flex;gap:11px;align-items:center;padding:10px 11px;color:var(--muted);text-align:left}
.side-button.active{color:var(--text);background:rgba(255,255,255,.035);border-color:var(--line)}
.side-icon{width:20px;color:var(--dim);text-align:center}.side-button.active .side-icon{color:var(--accent)}
.sidebar-footer{margin-top:auto}
.system-status{display:flex;gap:10px;align-items:center;padding:12px;border:1px solid var(--line);border-radius:13px;background:rgba(255,255,255,.025)}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 12px var(--accent)}
.system-status strong{display:block;font-size:11px}.system-status small{display:block;margin-top:3px;color:var(--dim);font-size:9px}
.main{min-width:0;flex:1;display:flex;flex-direction:column}
.topbar{height:64px;flex:0 0 64px;display:flex;align-items:center;padding:0 24px;border-bottom:1px solid var(--line);background:rgba(7,10,18,.45);backdrop-filter:blur(18px)}
.mobile-brand{display:none;font-size:13px;font-weight:900;letter-spacing:2px}
.topbar-right{margin-left:auto;display:flex;gap:10px;align-items:center}
.online{display:flex;gap:7px;align-items:center;color:var(--muted);font-size:11px}
.online-dot{width:6px;height:6px;border-radius:50%;background:var(--accent);box-shadow:0 0 10px var(--accent)}
.online.offline .online-dot{background:var(--danger);box-shadow:none}
.icon-button{width:35px;height:35px;display:grid;place-items:center;color:var(--muted)}
.chat{flex:1;overflow-y:auto;padding:34px 7%}
.chat::-webkit-scrollbar{width:7px}.chat::-webkit-scrollbar-thumb{background:rgba(255,255,255,.08);border-radius:10px}
.welcome{max-width:800px;margin:7vh auto 0;text-align:center}
.welcome-icon{width:68px;height:68px;margin:0 auto 22px;border-radius:21px;font-size:28px}
.eyebrow{color:var(--accent);font-size:10px;font-weight:900;letter-spacing:3px}
h1{margin:12px 0 16px;font-size:clamp(42px,6vw,72px);line-height:.98;letter-spacing:-4px}
h1 span{background:linear-gradient(100deg,var(--accent),#fff 48%,var(--accent2));color:transparent;-webkit-background-clip:text;background-clip:text}
.welcome-description{max-width:600px;margin:0 auto 28px;color:var(--muted);font-size:14px;line-height:1.7}
.quick-actions{display:flex;justify-content:center;gap:8px;flex-wrap:wrap}
.quick-action{display:flex;gap:8px;align-items:center;padding:9px 12px;color:#b7c0d0;background:rgba(255,255,255,.032);border-color:var(--line)}
.quick-action span{color:var(--accent)}
.message{max-width:850px;margin:0 auto 14px;padding:15px 17px;border-radius:16px;line-height:1.65;animation:in .2s ease}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.message.user{margin-right:0;background:linear-gradient(135deg,rgba(92,236,255,.07),rgba(156,108,255,.07));border:1px solid rgba(92,236,255,.12)}
.message.assistant{margin-left:0;background:rgba(255,255,255,.032);border:1px solid var(--line)}
.message-label{margin-bottom:7px;color:var(--accent);font-size:9px;font-weight:900;letter-spacing:1.5px}
.search-results{display:grid;gap:8px;margin-top:14px}
.search-result{display:block;padding:13px;color:var(--text);text-decoration:none;background:rgba(0,0,0,.16);border:1px solid var(--line);border-radius:12px;transition:.18s}
.search-result:hover{transform:translateX(2px);border-color:rgba(92,236,255,.3)}
.result-title{font-size:13px;font-weight:750}.result-url{margin-top:4px;color:var(--accent);font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.result-snippet{margin-top:7px;color:var(--muted);font-size:11px;line-height:1.55}
.meta{margin-top:9px;color:var(--dim);font-size:9px}
.composer-area{padding:0 7% 20px}
.composer{max-width:850px;margin:0 auto;display:flex;align-items:flex-end;gap:9px;padding:9px 9px 9px 16px;background:rgba(13,18,29,.93);border:1px solid rgba(255,255,255,.1);border-radius:17px;box-shadow:0 18px 65px rgba(0,0,0,.3);backdrop-filter:blur(20px)}
.composer:focus-within{border-color:rgba(92,236,255,.3)}
#messageInput{flex:1;min-width:0;max-height:145px;resize:none;padding:8px 0;color:var(--text);background:transparent;border:0;outline:0;line-height:1.5}
#messageInput::placeholder{color:#687286}
.send-button{width:42px;height:42px;flex:0 0 42px;display:grid;place-items:center;color:#041016;background:linear-gradient(135deg,var(--accent),#b7fbff);border-radius:12px;font-size:21px;font-weight:900}
.send-button:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(92,236,255,.19)}
.send-button:disabled{opacity:.42;cursor:default;transform:none;box-shadow:none}
.hint{max-width:850px;margin:7px auto 0;color:var(--dim);font-size:9px;text-align:center}
.typing-dots{display:inline-flex;gap:3px;margin-left:4px}.typing-dots span{width:4px;height:4px;border-radius:50%;background:var(--accent);animation:blink 1.1s infinite}.typing-dots span:nth-child(2){animation-delay:.15s}.typing-dots span:nth-child(3){animation-delay:.3s}
@keyframes blink{0%,70%,100%{opacity:.25}35%{opacity:1}}
@media(max-width:760px){
  .sidebar{display:none}.mobile-brand{display:block}.topbar{height:58px;flex-basis:58px;padding:0 14px}.chat{padding:24px 12px}.welcome{margin-top:5vh}h1{font-size:43px;letter-spacing:-2.5px}.welcome-description{font-size:13px}.composer-area{padding:0 10px 12px}.hint{display:none}.message{padding:13px 14px}
}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
  <div class="brand">
    <div class="brand-icon">✦</div>
    <div><div class="brand-name">NEXORA</div><div class="brand-version">VERSION 5.0</div></div>
  </div>
  <button class="new-chat" id="newChat"><span>＋</span> New conversation</button>
  <div class="sidebar-title">WORKSPACE</div>
  <button class="side-button active"><span class="side-icon">◈</span>Assistant</button>
  <button class="side-button" id="searchShortcut"><span class="side-icon">⌕</span>Web search</button>
  <button class="side-button" id="calculatorShortcut"><span class="side-icon">∑</span>Calculator</button>
  <div class="sidebar-footer">
    <div class="system-status"><span class="status-dot"></span><div><strong>System online</strong><small>Local assistant shell</small></div></div>
  </div>
</aside>
<main class="main">
  <header class="topbar">
    <div class="mobile-brand">✦ NEXORA</div>
    <div class="topbar-right">
      <div class="online" id="onlineStatus"><span class="online-dot"></span><span id="onlineText">Connecting</span></div>
      <button class="icon-button" id="clearHistory" title="Clear conversation" aria-label="Clear conversation">⌫</button>
    </div>
  </header>
  <section class="chat" id="chat">
    <div class="welcome" id="welcome">
      <div class="welcome-icon">✦</div>
      <div class="eyebrow">NEXORA 5.0</div>
      <h1>Intelligence, <span>simplified.</span></h1>
      <p class="welcome-description">A clean, session-aware workspace for web search, calculations, and everyday exploration.</p>
      <div class="quick-actions">
        <button class="quick-action" data-prompt="search latest technology news"><span>⌕</span>Search the web</button>
        <button class="quick-action" data-prompt="calculate 125 * 48"><span>∑</span>Calculate</button>
        <button class="quick-action" data-prompt="help"><span>✦</span>Explore Nexora</button>
      </div>
    </div>
  </section>
  <div class="composer-area">
    <div class="composer">
      <textarea id="messageInput" rows="1" maxlength="4000" placeholder="Ask Nexora anything..." autocomplete="off" aria-label="Message Nexora"></textarea>
      <button class="send-button" id="sendButton" aria-label="Send message">↑</button>
    </div>
    <div class="hint">Enter to send · Shift + Enter for a new line</div>
  </div>
</main>
</div>
<script>
"use strict";

let csrfToken = "";
let sessionReady = false;
let activeRequest = null;

const chat = document.getElementById("chat");
const welcome = document.getElementById("welcome");
const input = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const onlineStatus = document.getElementById("onlineStatus");
const onlineText = document.getElementById("onlineText");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
    .replaceAll('"',"&quot;").replaceAll("'","&#039;");
}

function formatText(value) {
  let text = escapeHtml(value);
  text = text.replace(/\*\*(.*?)\*\*/g,"<strong>$1</strong>");
  text = text.replace(/\n/g,"<br>");
  return text;
}

function scrollToBottom(smooth = true) {
  chat.scrollTo({top:chat.scrollHeight,behavior:smooth ? "smooth" : "auto"});
}

function addMessage(role, content, results = [], meta = "") {
  if (welcome) welcome.style.display = "none";

  const message = document.createElement("article");
  message.className = `message ${role}`;

  const label = role === "user" ? "YOU" : "NEXORA";
  message.innerHTML = `
    <div class="message-label">${label}</div>
    <div>${formatText(content)}</div>
  `;

  if (Array.isArray(results) && results.length) {
    const wrap = document.createElement("div");
    wrap.className = "search-results";

    results.forEach((result) => {
      if (!result || typeof result !== "object") return;
      const url = typeof result.url === "string" ? result.url : "";
      if (!/^https?:\/\//i.test(url)) return;

      const link = document.createElement("a");
      link.className = "search-result";
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";

      const title = document.createElement("div");
      title.className = "result-title";
      title.textContent = result.title || "Untitled result";

      const urlEl = document.createElement("div");
      urlEl.className = "result-url";
      urlEl.textContent = result.source || url;

      const snippet = document.createElement("div");
      snippet.className = "result-snippet";
      snippet.textContent = result.snippet || "";

      link.append(title,urlEl,snippet);
      wrap.appendChild(link);
    });

    message.appendChild(wrap);
  }

  if (meta) {
    const metaEl = document.createElement("div");
    metaEl.className = "meta";
    metaEl.textContent = meta;
    message.appendChild(metaEl);
  }

  chat.appendChild(message);
  scrollToBottom();
}

function showTyping() {
  if (document.getElementById("typing")) return;
  const typing = document.createElement("article");
  typing.id = "typing";
  typing.className = "message assistant";
  typing.innerHTML = `
    <div class="message-label">NEXORA</div>
    <div>Working <span class="typing-dots"><span></span><span></span><span></span></span></div>
  `;
  chat.appendChild(typing);
  scrollToBottom();
}

function removeTyping() {
  document.getElementById("typing")?.remove();
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight,145)}px`;
}

function setOnline(ok) {
  onlineStatus.classList.toggle("offline", !ok);
  onlineText.textContent = ok ? "Online" : "Offline";
}

async function apiFetch(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  activeRequest = controller;
  try {
    const headers = new Headers(options.headers || {});
    headers.set("Accept","application/json");
    const response = await fetch(url,{...options,headers,signal:controller.signal,credentials:"same-origin"});
    return response;
  } finally {
    clearTimeout(timer);
    if (activeRequest === controller) activeRequest = null;
  }
}

async function initialize() {
  try {
    const response = await apiFetch("/api/session",{},5000);
    if (!response.ok) throw new Error("Session initialization failed.");
    const data = await response.json();
    csrfToken = data.csrf_token || "";
    sessionReady = Boolean(csrfToken);
    setOnline(sessionReady);
    await restoreHistory();
  } catch (error) {
    setOnline(false);
    console.error(error);
  }
}

async function restoreHistory() {
  if (!sessionReady) return;
  try {
    const response = await apiFetch("/api/history",{},5000);
    if (!response.ok) return;
    const data = await response.json();
    if (!Array.isArray(data.history) || !data.history.length) return;

    welcome.style.display = "none";
    data.history.forEach(item => {
      if (!item || !["user","assistant"].includes(item.role)) return;
      addMessage(item.role,item.message || "",item.results || [],item.timestamp ? new Date(item.timestamp * 1000).toLocaleTimeString() : "");
    });
    scrollToBottom(false);
  } catch (error) {
    console.error("History restore error:",error);
  }
}

async function sendMessage() {
  if (sendButton.disabled || !sessionReady) return;

  const message = input.value.trim();
  if (!message) return;

  addMessage("user",message);
  input.value = "";
  resizeInput();
  sendButton.disabled = true;
  showTyping();

  try {
    const response = await apiFetch(
      "/api/chat",
      {
        method:"POST",
        headers:{
          "Content-Type":"application/json",
          "X-Nexora-CSRF":csrfToken
        },
        body:JSON.stringify({message})
      },
      20000
    );

    let data = {};
    try { data = await response.json(); } catch {}

    removeTyping();

    if (!response.ok) {
      addMessage("assistant",data.error?.message || data.error || "The request failed.");
      return;
    }

    const meta = data.duration_ms ? `Search completed in ${data.duration_ms} ms` : "";
    addMessage("assistant",data.message || "No response was returned.",data.results || [],meta);
  } catch (error) {
    removeTyping();
    addMessage("assistant",error.name === "AbortError"
      ? "The request timed out. Please try again."
      : "I couldn't connect to Nexora. Check that the server is running.");
    console.error("Nexora error:",error);
    setOnline(false);
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

async function clearConversation() {
  if (!sessionReady) return;
  try {
    const response = await apiFetch(
      "/api/history/clear",
      {method:"POST",headers:{"X-Nexora-CSRF":csrfToken}},
      5000
    );
    if (!response.ok) throw new Error("Clear failed.");
  } catch (error) {
    console.error(error);
  }

  chat.querySelectorAll(".message").forEach(el => el.remove());
  welcome.style.display = "";
  input.value = "";
  resizeInput();
  input.focus();
}

document.querySelectorAll("[data-prompt]").forEach(button => {
  button.addEventListener("click",() => {
    input.value = button.dataset.prompt || "";
    resizeInput();
    sendMessage();
  });
});

document.getElementById("searchShortcut").addEventListener("click",() => {
  input.value = "search ";
  resizeInput();
  input.focus();
});

document.getElementById("calculatorShortcut").addEventListener("click",() => {
  input.value = "calculate ";
  resizeInput();
  input.focus();
});

document.getElementById("newChat").addEventListener("click",clearConversation);
document.getElementById("clearHistory").addEventListener("click",clearConversation);
input.addEventListener("input",resizeInput);

input.addEventListener("keydown",(event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

document.getElementById("sendButton").addEventListener("click",sendMessage);

document.addEventListener("keydown",(event) => {
  const modifier = event.ctrlKey || event.metaKey;
  if (modifier && event.key.toLowerCase() === "k") {
    event.preventDefault();
    input.focus();
  }
});

window.addEventListener("online",() => setOnline(true));
window.addEventListener("offline",() => setOnline(false));

resizeInput();
initialize();
</script>
</body>
</html>'''


# ----------------------------- HTTP server -------------------

server: ThreadingHTTPServer | None = None
connection_semaphore = threading.BoundedSemaphore(MAX_CONNECTIONS)


def client_ip(handler: BaseHTTPRequestHandler) -> str:
    value = handler.client_address[0]
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        return "unknown"


def make_cookie(session_id: str) -> str:
    return (
        f"{SESSION_COOKIE}={session_id}; "
        f"Max-Age={SESSION_MAX_AGE}; Path=/; "
        "HttpOnly; SameSite=Lax"
    )


class NexoraHandler(BaseHTTPRequestHandler):
    server_version = f"Nexora/{SERVER_VERSION}"
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection_ok = connection_semaphore.acquire(timeout=2)

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            if getattr(self, "connection_ok", False):
                connection_semaphore.release()
                self.connection_ok = False

    def _session(self) -> tuple[str, SessionState]:
        cookie_header = self.headers.get("Cookie", "")
        session_id = None

        for item in cookie_header.split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name == SESSION_COOKIE:
                session_id = value.strip()
                break

        return sessions.get_or_create(session_id)

    def _set_common_headers(
        self,
        content_type: str,
        content_length: int,
        session_id: str | None = None,
    ) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header(
            "Referrer-Policy",
            "strict-origin-when-cross-origin",
        )
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'none'; "
            "form-action 'self'",
        )
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if session_id:
            self.send_header("Set-Cookie", make_cookie(session_id))

    def send_json(
        self,
        status: int,
        data: object,
        session_id: str | None = None,
    ) -> None:
        body = json_bytes(data)
        try:
            self.send_response(status)
            self._set_common_headers(
                "application/json; charset=utf-8",
                len(body),
                session_id,
            )
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            logger.info("Client disconnected while sending JSON.")

    def send_html(self, html_text: str, session_id: str | None = None) -> None:
        body = html_text.encode("utf-8")
        try:
            self.send_response(200)
            self._set_common_headers(
                "text/html; charset=utf-8",
                len(body),
                session_id,
            )
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            logger.info("Client disconnected while sending HTML.")

    def _rate_allowed(self, search: bool = False) -> bool:
        key = f"{client_ip(self)}:{'search' if search else 'general'}"
        return rate_limiter.allow(
            key,
            SEARCH_RATE_MAX if search else RATE_MAX_REQUESTS,
        )

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True

        parsed = urlparse(origin)
        host = self.headers.get("Host", "")
        expected = host.split(":", 1)[0].lower()
        return parsed.hostname and parsed.hostname.lower() == expected

    def _csrf_ok(self, state: SessionState) -> bool:
        supplied = self.headers.get("X-Nexora-CSRF", "")
        return bool(
            supplied
            and secrets.compare_digest(supplied, state.csrf_token)
        )

    def _read_json_body(self) -> dict | None:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            self.send_json(
                415,
                {
                    "success": False,
                    "error": {
                        "code": "UNSUPPORTED_MEDIA_TYPE",
                        "message": "Content-Type must be application/json.",
                    },
                },
            )
            return None

        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError:
            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_CONTENT_LENGTH",
                        "message": "Invalid Content-Length.",
                    },
                },
            )
            return None

        if length <= 0:
            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "code": "EMPTY_BODY",
                        "message": "Request body cannot be empty.",
                    },
                },
            )
            return None

        if length > MAX_REQUEST_SIZE:
            self.send_json(
                413,
                {
                    "success": False,
                    "error": {
                        "code": "REQUEST_TOO_LARGE",
                        "message": "Request is too large.",
                    },
                },
            )
            return None

        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_JSON",
                        "message": "Request body must be valid JSON.",
                    },
                },
            )
            return None
        except (ConnectionResetError, BrokenPipeError):
            return None

        if not isinstance(payload, dict):
            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_BODY",
                        "message": "JSON body must be an object.",
                    },
                },
            )
            return None

        return payload

    # ------------------------- OPTIONS ------------------------

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Allow", ALLOWED_METHODS)
        self.send_header(
            "Access-Control-Allow-Methods",
            ALLOWED_METHODS,
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Nexora-CSRF",
        )
        self.send_header(
            "Access-Control-Allow-Origin",
            self.headers.get("Origin", ""),
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    # ------------------------- GET ----------------------------

    def do_GET(self) -> None:
        if not getattr(self, "connection_ok", True):
            self.send_json(503, {"error": "Server is busy."})
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path in {"/", "/index.html"}:
            session_id, _ = self._session()
            self.send_html(INDEX_HTML, session_id)
            return

        if path == "/health":
            self.send_json(
                200,
                {
                    "success": True,
                    "status": "healthy",
                    "service": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "uptime_seconds": round(
                        time.monotonic() - START_MONOTONIC,
                        2,
                    ),
                    "api_key_required": False,
                },
            )
            return

        if path == "/api":
            self.send_json(
                200,
                {
                    "success": True,
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "status": "online",
                    "api_key_required": False,
                    "features": [
                        "sessions",
                        "web_search",
                        "calculator",
                        "history",
                        "health",
                    ],
                },
            )
            return

        if path == "/api/session":
            session_id, state = self._session()
            self.send_json(
                200,
                {
                    "success": True,
                    "csrf_token": state.csrf_token,
                    "version": SERVER_VERSION,
                },
                session_id,
            )
            return

        if path == "/api/history":
            session_id, state = self._session()
            self.send_json(
                200,
                {
                    "success": True,
                    "history": list(state.history),
                },
                session_id,
            )
            return

        if path == "/api/search":
            if not self._rate_allowed(search=True):
                self.send_json(
                    429,
                    {
                        "success": False,
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many search requests. Try again shortly.",
                        },
                    },
                )
                return

            params = parse_qs(
                parsed.query,
                keep_blank_values=False,
                strict_parsing=False,
            )
            query = normalize_search_query(
                params.get("q", [""])[0]
            )
            if not query:
                self.send_json(
                    400,
                    {
                        "success": False,
                        "error": {
                            "code": "MISSING_QUERY",
                            "message": "Missing search query.",
                        },
                    },
                )
                return

            started = time.monotonic()
            results = search_duckduckgo(query)
            self.send_json(
                200,
                {
                    "success": True,
                    "query": query,
                    "results": results,
                    "duration_ms": round(
                        (time.monotonic() - started) * 1000
                    ),
                },
            )
            return

        self.send_json(
            404,
            {
                "success": False,
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Route not found.",
                },
            },
        )

    # ------------------------- POST ---------------------------

    def do_POST(self) -> None:
        if not self._rate_allowed():
            self.send_json(
                429,
                {
                    "success": False,
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests. Try again shortly.",
                    },
                },
            )
            return

        if not self._same_origin():
            self.send_json(
                403,
                {
                    "success": False,
                    "error": {
                        "code": "BAD_ORIGIN",
                        "message": "Request origin is not allowed.",
                    },
                },
            )
            return

        session_id, state = self._session()

        if not self._csrf_ok(state):
            self.send_json(
                403,
                {
                    "success": False,
                    "error": {
                        "code": "CSRF_FAILED",
                        "message": "Invalid CSRF token.",
                    },
                },
                session_id,
            )
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/history/clear":
            state.history.clear()
            self.send_json(
                200,
                {"success": True},
                session_id,
            )
            return

        if path != "/api/chat":
            self.send_json(
                404,
                {
                    "success": False,
                    "error": {
                        "code": "NOT_FOUND",
                        "message": "Route not found.",
                    },
                },
                session_id,
            )
            return

        payload = self._read_json_body()
        if payload is None:
            return

        message = payload.get("message", "")
        if not isinstance(message, str):
            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "code": "INVALID_MESSAGE",
                        "message": "Message must be text.",
                    },
                },
                session_id,
            )
            return

        message = message.strip()
        if not message:
            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "code": "EMPTY_MESSAGE",
                        "message": "Message cannot be empty.",
                    },
                },
                session_id,
            )
            return

        if len(message) > MAX_MESSAGE_LENGTH:
            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "code": "MESSAGE_TOO_LONG",
                        "message": "Message is too long.",
                    },
                },
                session_id,
            )
            return

        state.history.append(
            {
                "role": "user",
                "message": message,
                "type": "chat",
                "timestamp": now_timestamp(),
            }
        )

        try:
            result = assistant_response(message)
        except Exception:
            logger.exception("Assistant error")
            result = {
                "type": "error",
                "message": "Nexora encountered an internal error.",
            }

        assistant_entry = {
            "role": "assistant",
            "message": clamp_text(
                str(result.get("message", "")),
                MAX_MESSAGE_LENGTH,
            ),
            "type": str(result.get("type", "chat")),
            "timestamp": now_timestamp(),
        }

        if result.get("results"):
            assistant_entry["results"] = result["results"]

        state.history.append(assistant_entry)

        result["success"] = True
        self.send_json(200, result, session_id)

    # ------------------------- logging ------------------------

    def log_message(self, format_string: str, *args) -> None:
        logger.info(
            "%s - %s",
            client_ip(self),
            format_string % args,
        )


# ----------------------------- startup -----------------------

START_MONOTONIC = time.monotonic()


def shutdown_server(signum=None, frame=None) -> None:
    global server
    logger.info("Shutdown signal received.")
    if server is not None:
        threading.Thread(
            target=server.shutdown,
            daemon=True,
        ).start()


def install_signal_handlers() -> None:
    try:
        signal.signal(signal.SIGTERM, shutdown_server)
        signal.signal(signal.SIGINT, shutdown_server)
    except (ValueError, OSError):
        logger.warning("Signal handlers could not be installed.")


def startup() -> None:
    global server

    logger.info("Starting %s %s", SERVER_NAME, SERVER_VERSION)

    try:
        server = ThreadingHTTPServer(
            (HOST, PORT),
            NexoraHandler,
        )
        server.daemon_threads = True
        server.request_queue_size = 64
    except OSError:
        logger.exception("Could not bind to %s:%s", HOST, PORT)
        raise

    logger.info("Nexora listening on %s:%s", HOST, PORT)

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        logger.info("Closing Nexora server.")
        server.server_close()
        server = None


if __name__ == "__main__":
    install_signal_handlers()
    startup()

