from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
import signal
import threading
import time
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen


# ============================================================
# NEXORA 3.0
# API-FREE • RENDER READY • SINGLE FILE
# ============================================================


# ============================================================
# CONFIGURATION
# ============================================================

HOST = "0.0.0.0"

try:
    PORT = int(os.environ.get("PORT", "10000"))
except ValueError:
    PORT = 10000


SERVER_NAME = "Nexora"
SERVER_VERSION = "3.0"

MAX_MESSAGE_LENGTH = 4000
MAX_HISTORY_ITEMS = 100
MAX_SEARCH_RESULTS = 8
MAX_REQUEST_SIZE = 100_000

SEARCH_TIMEOUT = 12

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("nexora")


# ============================================================
# GLOBAL STATE
# ============================================================

history_lock = threading.RLock()

conversation_history: list[dict] = []


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def now_timestamp() -> float:
    """Return the current Unix timestamp."""

    return time.time()


def clean_html(text: str) -> str:
    """Convert basic HTML into readable plain text."""

    if not text:
        return ""

    text = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = unescape(text)

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def json_bytes(data: object) -> bytes:
    """Serialize JSON safely as UTF-8."""

    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def clamp_text(text: str, maximum: int) -> str:
    """Limit text to a maximum number of characters."""

    if len(text) <= maximum:
        return text

    return text[:maximum].rstrip() + "…"


# ============================================================
# SAFE CALCULATOR
# ============================================================

MATH_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}


MATH_FUNCTIONS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "ceil": math.ceil,
    "floor": math.floor,
    "fabs": math.fabs,
    "factorial": math.factorial,
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


def validate_number(value):
    """Prevent dangerous or unreasonable numeric results."""

    if isinstance(value, bool):
        raise ValueError("Boolean values are not allowed.")

    if isinstance(value, int):

        if abs(value) > 10**100:
            raise ValueError(
                "The result is too large."
            )

    elif isinstance(value, float):

        if not math.isfinite(value):
            raise ValueError(
                "The result is not finite."
            )

        if abs(value) > 1e100:
            raise ValueError(
                "The result is too large."
            )

    return value


def safe_calculate(expression: str):
    """
    Safely evaluate mathematical expressions.

    Only explicitly allowed AST nodes are accepted.
    """

    expression = expression.strip()

    if not expression:
        raise ValueError(
            "No expression was provided."
        )

    if len(expression) > 250:
        raise ValueError(
            "That expression is too long."
        )

    try:
        tree = ast.parse(
            expression,
            mode="eval",
        )
    except SyntaxError:
        raise ValueError(
            "That is not a valid mathematical expression."
        )

    def evaluate(node):

        if isinstance(node, ast.Expression):
            return evaluate(node.body)

        if isinstance(node, ast.Constant):

            if isinstance(node.value, (int, float)):
                return validate_number(node.value)

            raise ValueError(
                "Invalid value."
            )

        if isinstance(node, ast.BinOp):

            operator = BINARY_OPERATORS.get(
                type(node.op)
            )

            if operator is None:
                raise ValueError(
                    "That operator is not allowed."
                )

            left = evaluate(node.left)
            right = evaluate(node.right)

            if (
                isinstance(node.op, ast.Pow)
                and abs(right) > 100
            ):
                raise ValueError(
                    "That power is too large."
                )

            result = operator(
                left,
                right,
            )

            return validate_number(result)

        if isinstance(node, ast.UnaryOp):

            operator = UNARY_OPERATORS.get(
                type(node.op)
            )

            if operator is None:
                raise ValueError(
                    "That operator is not allowed."
                )

            result = operator(
                evaluate(node.operand)
            )

            return validate_number(result)

        if isinstance(node, ast.Name):

            if node.id in MATH_CONSTANTS:
                return MATH_CONSTANTS[node.id]

            if node.id in MATH_FUNCTIONS:
                return MATH_FUNCTIONS[node.id]

            raise ValueError(
                f"'{node.id}' is not allowed."
            )

        if isinstance(node, ast.Call):

            if not isinstance(
                node.func,
                ast.Name,
            ):
                raise ValueError(
                    "That function is not allowed."
                )

            function = MATH_FUNCTIONS.get(
                node.func.id
            )

            if function is None:
                raise ValueError(
                    "That function is not allowed."
                )

            if len(node.args) > 5:
                raise ValueError(
                    "Too many function arguments."
                )

            arguments = [
                evaluate(argument)
                for argument in node.args
            ]

            try:
                result = function(*arguments)
            except Exception:
                raise ValueError(
                    "The calculation could not be completed."
                )

            return validate_number(result)

        raise ValueError(
            "That expression contains something "
            "the calculator does not support."
        )

    return evaluate(tree)


# ============================================================
# WEB SEARCH
# ============================================================

def extract_search_url(raw_url: str) -> str:
    """Extract the actual URL from common DuckDuckGo redirects."""

    raw_url = unescape(raw_url)

    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url

    parsed = urlparse(raw_url)

    query = parse_qs(parsed.query)

    if "uddg" in query and query["uddg"]:
        return unquote(
            query["uddg"][0]
        )

    return raw_url


def search_duckduckgo(
    query: str,
    limit: int = MAX_SEARCH_RESULTS,
) -> list[dict]:
    """
    Search DuckDuckGo's HTML interface.

    This does not use an API key.
    """

    query = query.strip()

    if not query:
        return []

    query = clamp_text(
        query,
        500,
    )

    search_url = (
        "https://html.duckduckgo.com/html/"
        f"?q={quote_plus(query)}"
    )

    request = Request(
        search_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )

    try:

        with urlopen(
            request,
            timeout=SEARCH_TIMEOUT,
        ) as response:

            html = response.read(
                2_000_000
            ).decode(
                "utf-8",
                errors="ignore",
            )

    except Exception as exc:

        logger.warning(
            "Web search failed: %s",
            exc,
        )

        return []

    results: list[dict] = []

    # --------------------------------------------------------
    # Result blocks
    # --------------------------------------------------------

    blocks = re.findall(
        r'<div[^>]*class="[^"]*result[^"]*"[^>]*>'
        r"(.*?)"
        r"</div>\s*</div>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Some DuckDuckGo responses don't match the block parser.
    # Fall back to scanning individual result links.
    if not blocks:

        links = re.findall(
            r'<a[^>]+class="[^"]*result__a[^"]*"'
            r'[^>]+href="([^"]+)"'
            r'[^>]*>(.*?)</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        for raw_url, raw_title in links:

            if len(results) >= limit:
                break

            title = clean_html(raw_title)

            if not title:
                continue

            results.append(
                {
                    "title": title,
                    "url": extract_search_url(raw_url),
                    "snippet": "",
                }
            )

        return results

    # --------------------------------------------------------
    # Parse result blocks
    # --------------------------------------------------------

    for block in blocks:

        if len(results) >= limit:
            break

        link_match = re.search(
            r'<a[^>]+class="[^"]*result__a[^"]*"'
            r'[^>]+href="([^"]+)"'
            r'[^>]*>(.*?)</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if not link_match:
            continue

        raw_url = link_match.group(1)
        raw_title = link_match.group(2)

        title = clean_html(
            raw_title
        )

        if not title:
            continue

        snippet_match = re.search(
            r'class="[^"]*result__snippet[^"]*"'
            r'[^>]*>(.*?)</',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

        snippet = ""

        if snippet_match:

            snippet = clean_html(
                snippet_match.group(1)
            )

        results.append(
            {
                "title": clamp_text(
                    title,
                    250,
                ),
                "url": extract_search_url(
                    raw_url
                ),
                "snippet": clamp_text(
                    snippet,
                    600,
                ),
            }
        )

    return results


# ============================================================
# SEARCH INTENT
# ============================================================

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
    """Detect explicit search requests."""

    lowered = message.lower().strip()

    for prefix in SEARCH_PREFIXES:

        if lowered.startswith(prefix):

            query = message[
                len(prefix):
            ].strip()

            if query:
                return query

    return None


# ============================================================
# HISTORY
# ============================================================

def add_history(
    role: str,
    message: str,
    message_type: str = "chat",
) -> None:

    with history_lock:

        conversation_history.append(
            {
                "role": role,
                "message": clamp_text(
                    message,
                    MAX_MESSAGE_LENGTH,
                ),
                "type": message_type,
                "timestamp": now_timestamp(),
            }
        )

        if len(conversation_history) > MAX_HISTORY_ITEMS:

            del conversation_history[
                :len(conversation_history)
                - MAX_HISTORY_ITEMS
            ]


def get_history() -> list[dict]:

    with history_lock:
        return list(
            conversation_history
        )


def clear_history() -> None:

    with history_lock:
        conversation_history.clear()


# ============================================================
# LOCAL ASSISTANT
# ============================================================

def assistant_response(
    message: str,
) -> dict:

    message = message.strip()

    if not message:

        return {
            "type": "error",
            "message": (
                "Please enter a message."
            ),
        }

    # --------------------------------------------------------
    # Calculator
    # --------------------------------------------------------

    calculator_match = re.match(
        r"^(?:calculate|calc)\s+(.+)$",
        message,
        flags=re.IGNORECASE,
    )

    if calculator_match:

        expression = (
            calculator_match.group(1)
            .strip()
        )

        try:

            result = safe_calculate(
                expression
            )

            return {
                "type": "calculator",
                "message": (
                    f"**{expression}** = **{result}**"
                ),
                "result": result,
            }

        except ValueError as exc:

            return {
                "type": "error",
                "message": str(exc),
            }

    # --------------------------------------------------------
    # Web search
    # --------------------------------------------------------

    search_query = get_search_query(
        message
    )

    if search_query:

        results = search_duckduckgo(
            search_query
        )

        if not results:

            return {
                "type": "search",
                "message": (
                    f"I couldn't retrieve search "
                    f"results for **{search_query}** "
                    "right now."
                ),
                "results": [],
            }

        return {
            "type": "search",
            "message": (
                f"Here are the web results for "
                f"**{search_query}**."
            ),
            "results": results,
        }

    # --------------------------------------------------------
    # Help
    # --------------------------------------------------------

    if message.lower() in {
        "help",
        "commands",
        "what can you do",
        "features",
    }:

        return {
            "type": "chat",
            "message": (
                "### What I can do\n\n"
                "🔎 **Web search**\n"
                "Use `search <topic>` to search "
                "the web.\n\n"
                "🧮 **Calculator**\n"
                "Use `calculate 25 * 18` for "
                "a calculation.\n\n"
                "💬 **Conversation**\n"
                "Chat with me normally.\n\n"
                "⚡ **Fast local processing**\n"
                "Nexora doesn't require an OpenAI API "
                "key to run."
            ),
        }

    # --------------------------------------------------------
    # Greetings
    # --------------------------------------------------------

    if message.lower() in {
        "hi",
        "hello",
        "hey",
        "yo",
        "hiya",
    }:

        return {
            "type": "chat",
            "message": (
                "Hey! 👋\n\n"
                "Nexora is online and ready."
            ),
        }

    # --------------------------------------------------------
    # Time
    # --------------------------------------------------------

    if message.lower() in {
        "time",
        "what time is it",
        "what's the time",
    }:

        current_time = time.strftime(
            "%H:%M:%S"
        )

        return {
            "type": "chat",
            "message": (
                f"The server time is "
                f"**{current_time}**."
            ),
        }

    # --------------------------------------------------------
    # Version
    # --------------------------------------------------------

    if message.lower() in {
        "version",
        "what version are you",
    }:

        return {
            "type": "chat",
            "message": (
                f"You're running **Nexora "
                f"{SERVER_VERSION}**."
            ),
        }

    # --------------------------------------------------------
    # Default
    # --------------------------------------------------------

    return {
        "type": "chat",
        "message": (
            "I'm Nexora. ⚡\n\n"
            "I can search the web, perform "
            "calculations, and handle local "
            "conversation features without "
            "an OpenAI API.\n\n"
            "Try:\n"
            "- `search latest technology news`\n"
            "- `calculate 125 * 48`\n"
            "- `help`"
        ),
    }


# ============================================================
# HTML
# ============================================================

INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="en">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
    >

    <meta
        name="theme-color"
        content="#06080d"
    >

    <meta
        name="description"
        content="Nexora — intelligent tools in one sleek workspace."
    >

    <title>Nexora</title>

    <style>

        :root {
            --bg: #05070b;
            --panel: rgba(11, 15, 24, 0.82);
            --panel-2: rgba(16, 20, 31, 0.88);

            --border: rgba(255, 255, 255, 0.075);
            --border-hover: rgba(92, 240, 255, 0.30);

            --text: #f4f7ff;
            --muted: #8d97aa;
            --dim: #596274;

            --cyan: #55efff;
            --purple: #a25cff;

            --cyan-soft: rgba(85, 239, 255, 0.10);
            --purple-soft: rgba(162, 92, 255, 0.11);

            --radius: 17px;
        }


        * {
            box-sizing: border-box;
        }


        html,
        body {
            width: 100%;
            height: 100%;
            margin: 0;
        }


        body {
            overflow: hidden;

            color: var(--text);

            background:
                radial-gradient(
                    circle at 85% 10%,
                    rgba(85, 239, 255, 0.065),
                    transparent 27%
                ),
                radial-gradient(
                    circle at 15% 90%,
                    rgba(162, 92, 255, 0.065),
                    transparent 28%
                ),
                var(--bg);

            font-family:
                Inter,
                ui-sans-serif,
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
        }


        button,
        textarea {
            font: inherit;
        }


        button {
            border: 0;
        }


        /* ==================================================
           APP
           ================================================== */

        .app {
            display: flex;

            width: 100%;
            height: 100%;
        }


        /* ==================================================
           SIDEBAR
           ================================================== */

        .sidebar {
            width: 265px;

            display: flex;
            flex-direction: column;

            padding: 23px 17px;

            background:
                rgba(6, 9, 15, 0.76);

            border-right:
                1px solid var(--border);

            backdrop-filter:
                blur(25px);
        }


        .brand {
            display: flex;
            align-items: center;
            gap: 12px;

            padding:
                2px 9px 25px;
        }


        .brand-icon {
            width: 40px;
            height: 40px;

            display: grid;
            place-items: center;

            border-radius: 13px;

            color: var(--cyan);

            background:
                linear-gradient(
                    135deg,
                    var(--cyan-soft),
                    var(--purple-soft)
                );

            border:
                1px solid var(--border-hover);

            box-shadow:
                0 0 35px rgba(85, 239, 255, 0.08);

            font-size: 20px;
        }


        .brand-name {
            font-size: 15px;
            font-weight: 850;

            letter-spacing: 3px;
        }


        .brand-version {
            margin-top: 2px;

            color: var(--dim);

            font-size: 9px;
            font-weight: 700;

            letter-spacing: 1.5px;
        }


        .new-chat {
            width: 100%;

            display: flex;
            align-items: center;
            gap: 9px;

            padding: 12px 13px;

            color: var(--text);

            background:
                linear-gradient(
                    135deg,
                    rgba(85, 239, 255, 0.075),
                    rgba(162, 92, 255, 0.075)
                );

            border:
                1px solid var(--border-hover);

            border-radius: 12px;

            cursor: pointer;

            transition:
                transform .18s ease,
                border-color .18s ease,
                background .18s ease;
        }


        .new-chat:hover {
            transform: translateY(-1px);

            border-color:
                rgba(85, 239, 255, 0.48);

            background:
                linear-gradient(
                    135deg,
                    rgba(85, 239, 255, 0.12),
                    rgba(162, 92, 255, 0.12)
                );
        }


        .sidebar-title {
            margin:
                28px 10px 9px;

            color: var(--dim);

            font-size: 9px;
            font-weight: 800;

            letter-spacing: 1.7px;
        }


        .side-button {
            width: 100%;

            display: flex;
            align-items: center;
            gap: 11px;

            padding: 10px 11px;

            margin-bottom: 3px;

            color: var(--muted);

            background: transparent;

            border:
                1px solid transparent;

            border-radius: 11px;

            cursor: pointer;

            text-align: left;

            transition:
                color .18s ease,
                background .18s ease,
                border-color .18s ease;
        }


        .side-button:hover,
        .side-button.active {
            color: var(--text);

            background:
                rgba(255, 255, 255, 0.038);

            border-color:
                var(--border);
        }


        .side-icon {
            width: 20px;

            color: var(--dim);

            text-align: center;
        }


        .side-button.active .side-icon {
            color: var(--cyan);
        }


        .sidebar-footer {
            margin-top: auto;
        }


        .system-status {
            display: flex;
            align-items: center;
            gap: 10px;

            padding: 12px;

            background:
                rgba(255, 255, 255, 0.025);

            border:
                1px solid var(--border);

            border-radius: 13px;
        }


        .status-dot {
            width: 8px;
            height: 8px;

            flex-shrink: 0;

            border-radius: 50%;

            background: var(--cyan);

            box-shadow:
                0 0 12px var(--cyan);
        }


        .system-status strong {
            display: block;

            font-size: 11px;
        }


        .system-status small {
            display: block;

            margin-top: 3px;

            color: var(--dim);

            font-size: 9px;
        }


        /* ==================================================
           MAIN
           ================================================== */

        .main {
            min-width: 0;

            flex: 1;

            display: flex;
            flex-direction: column;
        }


        .topbar {
            height: 68px;

            display: flex;
            align-items: center;

            padding:
                0 24px;

            border-bottom:
                1px solid var(--border);

            background:
                rgba(5, 7, 11, 0.38);

            backdrop-filter:
                blur(22px);
        }


        .mobile-brand {
            display: none;

            font-size: 13px;
            font-weight: 850;

            letter-spacing: 2px;
        }


        .topbar-right {
            margin-left: auto;

            display: flex;
            align-items: center;
            gap: 12px;
        }


        .online {
            display: flex;
            align-items: center;
            gap: 7px;

            color: var(--muted);

            font-size: 11px;
        }


        .online::before {
            content: "";

            width: 6px;
            height: 6px;

            border-radius: 50%;

            background: var(--cyan);

            box-shadow:
                0 0 10px var(--cyan);
        }


        .icon-button {
            width: 34px;
            height: 34px;

            display: grid;
            place-items: center;

            color: var(--muted);

            background: transparent;

            border:
                1px solid transparent;

            border-radius: 9px;

            cursor: pointer;

            transition: .18s ease;
        }


        .icon-button:hover {
            color: var(--text);

            background:
                rgba(255, 255, 255, 0.04);

            border-color:
                var(--border);
        }


        /* ==================================================
           CHAT
           ================================================== */

        .chat {
            flex: 1;

            overflow-y: auto;

            padding:
                38px 7%;
        }


        .chat::-webkit-scrollbar {
            width: 7px;
        }


        .chat::-webkit-scrollbar-thumb {
            background:
                rgba(255, 255, 255, 0.08);

            border-radius: 10px;
        }


        .welcome {
            max-width: 760px;

            margin:
                7vh auto 0;

            text-align: center;
        }


        .welcome-icon {
            width: 65px;
            height: 65px;

            display: grid;
            place-items: center;

            margin:
                0 auto 23px;

            color: var(--cyan);

            background:
                linear-gradient(
                    135deg,
                    var(--cyan-soft),
                    var(--purple-soft)
                );

            border:
                1px solid var(--border-hover);

            border-radius: 20px;

            font-size: 27px;

            box-shadow:
                0 0 55px rgba(85, 239, 255, 0.07);
        }


        .eyebrow {
            color: var(--cyan);

            font-size: 10px;
            font-weight: 850;

            letter-spacing: 3px;
        }


        h1 {
            margin:
                12px 0 16px;

            font-size:
                clamp(40px, 6vw, 70px);

            line-height: .98;

            letter-spacing: -3.5px;
        }


        h1 span {
            background:
                linear-gradient(
                    100deg,
                    var(--cyan),
                    #ffffff 48%,
                    var(--purple)
                );

            color: transparent;

            -webkit-background-clip: text;
            background-clip: text;
        }


        .welcome-description {
            max-width: 570px;

            margin:
                0 auto 27px;

            color: var(--muted);

            font-size: 14px;

            line-height: 1.7;
        }


        .quick-actions {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;

            gap: 8px;
        }


        .quick-action {
            display: flex;
            align-items: center;
            gap: 8px;

            padding:
                9px 12px;

            color: #aeb7c7;

            background:
                rgba(255, 255, 255, 0.032);

            border:
                1px solid var(--border);

            border-radius: 10px;

            cursor: pointer;

            transition:
                transform .18s ease,
                border-color .18s ease,
                color .18s ease;
        }


        .quick-action:hover {
            color: var(--text);

            border-color:
                rgba(85, 239, 255, 0.25);

            transform:
                translateY(-2px);
        }


        .quick-action span {
            color: var(--cyan);
        }


        /* ==================================================
           MESSAGES
           ================================================== */

        .message {
            max-width: 850px;

            margin:
                0 auto 15px;

            padding:
                15px 17px;

            border-radius: 15px;

            line-height: 1.65;

            animation:
                messageIn .22s ease;
        }


        @keyframes messageIn {

            from {
                opacity: 0;
                transform:
                    translateY(6px);
            }

            to {
                opacity: 1;
                transform:
                    translateY(0);
            }

        }


        .message.user {
            margin-right: 0;

            background:
                linear-gradient(
                    135deg,
                    rgba(85, 239, 255, 0.07),
                    rgba(162, 92, 255, 0.07)
                );

            border:
                1px solid
                rgba(85, 239, 255, 0.10);
        }


        .message.assistant {
            margin-left: 0;

            background:
                rgba(255, 255, 255, 0.032);

            border:
                1px solid var(--border);
        }


        .message-label {
            margin-bottom: 6px;

            color: var(--cyan);

            font-size: 9px;
            font-weight: 850;

            letter-spacing: 1.5px;
        }


        .search-results {
            display: grid;

            gap: 8px;

            margin-top: 14px;
        }


        .search-result {
            display: block;

            padding: 12px;

            color: var(--text);

            background:
                rgba(0, 0, 0, 0.16);

            border:
                1px solid var(--border);

            border-radius: 11px;

            text-decoration: none;

            transition:
                transform .18s ease,
                border-color .18s ease;
        }


        .search-result:hover {
            transform:
                translateX(2px);

            border-color:
                rgba(85, 239, 255, 0.28);
        }


        .result-title {
            font-size: 13px;
            font-weight: 700;
        }


        .result-url {
            margin-top: 3px;

            overflow: hidden;

            color: var(--cyan);

            font-size: 9px;

            white-space: nowrap;
            text-overflow: ellipsis;
        }


        .result-snippet {
            margin-top: 6px;

            color: var(--muted);

            font-size: 11px;

            line-height: 1.55;
        }


        /* ==================================================
           COMPOSER
           ================================================== */

        .composer-area {
            padding:
                0 7% 22px;
        }


        .composer {
            max-width: 850px;

            margin: 0 auto;

            display: flex;
            align-items: flex-end;
            gap: 9px;

            padding:
                9px 9px 9px 16px;

            background:
                rgba(12, 16, 25, 0.90);

            border:
                1px solid
                rgba(255, 255, 255, 0.10);

            border-radius: 17px;

            box-shadow:
                0 18px 65px
                rgba(0, 0, 0, 0.30);

            backdrop-filter:
                blur(25px);

            transition:
                border-color .18s ease,
                box-shadow .18s ease;
        }


        .composer:focus-within {
            border-color:
                rgba(85, 239, 255, 0.30);

            box-shadow:
                0 18px 65px
                rgba(0, 0, 0, 0.32),
                0 0 35px
                rgba(85, 239, 255, 0.045);
        }


        #messageInput {
            flex: 1;

            min-width: 0;

            max-height: 145px;

            resize: none;

            padding:
                8px 0;

            color: var(--text);

            background: transparent;

            border: 0;

            outline: 0;

            line-height: 1.5;
        }


        #messageInput::placeholder {
            color: #687286;
        }


        .send-button {
            width: 42px;
            height: 42px;

            flex-shrink: 0;

            display: grid;
            place-items: center;

            color: #041016;

            background:
                linear-gradient(
                    135deg,
                    var(--cyan),
                    #a9f9ff
                );

            border-radius: 12px;

            cursor: pointer;

            font-size: 21px;
            font-weight: 800;

            transition:
                transform .18s ease,
                box-shadow .18s ease,
                opacity .18s ease;
        }


        .send-button:hover {
            transform:
                translateY(-2px);

            box-shadow:
                0 8px 25px
                rgba(85, 239, 255, 0.19);
        }


        .send-button:disabled {
            opacity: .42;

            cursor: default;

            transform: none;

            box-shadow: none;
        }


        .hint {
            max-width: 850px;

            margin:
                7px auto 0;

            color: var(--dim);

            font-size: 9px;

            text-align: center;
        }


        /* ==================================================
           TYPING
           ================================================== */

        .typing-dots {
            display: inline-flex;

            gap: 3px;

            margin-left: 4px;
        }


        .typing-dots span {
            width: 4px;
            height: 4px;

            border-radius: 50%;

            background: var(--cyan);

            animation:
                blink 1.1s infinite;
        }


        .typing-dots span:nth-child(2) {
            animation-delay: .15s;
        }


        .typing-dots span:nth-child(3) {
            animation-delay: .30s;
        }


        @keyframes blink {

            0%,
            70%,
            100% {
                opacity: .25;
            }

            35% {
                opacity: 1;
            }

        }


        /* ==================================================
           MOBILE
           ================================================== */

        @media (max-width: 760px) {

            body {
                overflow: hidden;
            }


            .sidebar {
                display: none;
            }


            .mobile-brand {
                display: block;
            }


            .topbar {
                height: 59px;

                padding:
                    0 15px;
            }


            .chat {
                padding:
                    24px 13px;
            }


            .welcome {
                margin-top:
                    5vh;
            }


            h1 {
                font-size: 43px;

                letter-spacing: -2.5px;
            }


            .welcome-description {
                font-size: 13px;
            }


            .composer-area {
                padding:
                    0 11px 13px;
            }


            .hint {
                display: none;
            }


            .message {
                padding:
                    13px 14px;
            }

        }

    </style>

</head>


<body>

    <div class="app">

        <aside class="sidebar">

            <div class="brand">

                <div class="brand-icon">
                    ✦
                </div>

                <div>

                    <div class="brand-name">
                        NEXORA
                    </div>

                    <div class="brand-version">
                        VERSION 3.0
                    </div>

                </div>

            </div>


            <button
                class="new-chat"
                id="newChat"
            >
                <span>＋</span>
                New conversation
            </button>


            <div class="sidebar-title">
                WORKSPACE
            </div>


            <button
                class="side-button active"
            >
                <span class="side-icon">
                    ◈
                </span>
                Assistant
            </button>


            <button
                class="side-button"
                id="searchShortcut"
            >
                <span class="side-icon">
                    ⌕
                </span>
                Web search
            </button>


            <button
                class="side-button"
                id="calculatorShortcut"
            >
                <span class="side-icon">
                    ∑
                </span>
                Calculator
            </button>


            <div class="sidebar-footer">

                <div class="system-status">

                    <span class="status-dot"></span>

                    <div>

                        <strong>
                            System online
                        </strong>

                        <small>
                            API-free engine
                        </small>

                    </div>

                </div>

            </div>

        </aside>


        <main class="main">

            <header class="topbar">

                <div class="mobile-brand">
                    ✦ NEXORA
                </div>

                <div class="topbar-right">

                    <div class="online">
                        Online
                    </div>

                    <button
                        class="icon-button"
                        id="clearHistory"
                        title="Clear conversation"
                    >
                        ⌫
                    </button>

                </div>

            </header>


            <section
                class="chat"
                id="chat"
            >

                <div
                    class="welcome"
                    id="welcome"
                >

                    <div class="welcome-icon">
                        ✦
                    </div>

                    <div class="eyebrow">
                        NEXORA 3.0
                    </div>

                    <h1>
                        Intelligence,
                        <span>simplified.</span>
                    </h1>

                    <p class="welcome-description">
                        A fast, clean workspace for
                        web search, calculations,
                        and everyday exploration.
                    </p>


                    <div class="quick-actions">

                        <button
                            class="quick-action"
                            data-prompt="search latest technology news"
                        >
                            <span>⌕</span>
                            Search the web
                        </button>


                        <button
                            class="quick-action"
                            data-prompt="calculate 125 * 48"
                        >
                            <span>∑</span>
                            Calculate
                        </button>


                        <button
                            class="quick-action"
                            data-prompt="help"
                        >
                            <span>✦</span>
                            Explore Nexora
                        </button>

                    </div>

                </div>

            </section>


            <div class="composer-area">

                <div class="composer">

                    <textarea
                        id="messageInput"
                        rows="1"
                        maxlength="4000"
                        placeholder="Ask Nexora anything..."
                        autocomplete="off"
                    ></textarea>


                    <button
                        class="send-button"
                        id="sendButton"
                        aria-label="Send message"
                    >
                        ↑
                    </button>

                </div>


                <div class="hint">
                    Enter to send · Shift + Enter for a new line
                </div>

            </div>

        </main>

    </div>


    <script>

        // ====================================================
        // ELEMENTS
        // ====================================================

        const chat =
            document.getElementById("chat");

        const welcome =
            document.getElementById("welcome");

        const input =
            document.getElementById("messageInput");

        const sendButton =
            document.getElementById("sendButton");

        const newChat =
            document.getElementById("newChat");

        const clearHistory =
            document.getElementById("clearHistory");

        const searchShortcut =
            document.getElementById("searchShortcut");

        const calculatorShortcut =
            document.getElementById("calculatorShortcut");


        // ====================================================
        // HTML ESCAPING
        // ====================================================

        function escapeHtml(value) {

            return String(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }


        // ====================================================
        // SIMPLE MARKDOWN
        // ====================================================

        function formatText(value) {

            let text =
                escapeHtml(value);


            text = text.replace(
                /\*\*(.*?)\*\*/g,
                "<strong>$1</strong>"
            );


            text = text.replace(
                /\n/g,
                "<br>"
            );


            return text;
        }


        // ====================================================
        // SCROLL
        // ====================================================

        function scrollToBottom() {

            chat.scrollTo({
                top: chat.scrollHeight,
                behavior: "smooth"
            });
        }


        // ====================================================
        // ADD MESSAGE
        // ====================================================

        function addMessage(
            role,
            content,
            results = []
        ) {

            if (welcome) {
                welcome.style.display = "none";
            }


            const message =
                document.createElement("div");


            message.className =
                `message ${role}`;


            const label =
                role === "user"
                    ? "YOU"
                    : "NEXORA";


            let html = `
                <div class="message-label">
                    ${label}
                </div>

                
                   html += `
                    <div class="search-results">
                `;


                for (
                    const result of results
                ) {

                    const title =
                        escapeHtml(
                            result.title ||
                            "Untitled result"
                        );


                    const url =
                        escapeHtml(
                            result.url ||
                            "#"
                        );


                    const snippet =
                        escapeHtml(
                            result.snippet ||
                            ""
                        );


                    html += `
                        <a
                            class="search-result"
                            href="${url}"
                            target="_blank"
                            rel="noopener noreferrer"
                        >

                            <div class="result-title">
                                ${title}
                            </div>

                            <div class="result-url">
                                ${url}
                            </div>

                            <div class="result-snippet">
                                ${snippet}
                            </div>

                        </a>
                    `;
                }


                html += `
                    </div>
                `;
            }


            message.innerHTML =
                html;


            chat.appendChild(
                message
            );


            scrollToBottom();
        }


        // ====================================================
        // TYPING
        // ====================================================

        function showTyping() {

            const typing =
                document.createElement("div");


            typing.id =
                "typing";


            typing.className =
                "message assistant";


            typing.innerHTML = `
                <div class="message-label">
                    NEXORA
                </div>

                <div>
                    Working

                    <span class="typing-dots">
                        <span></span>
                        <span></span>
                        <span></span>
                    </span>
                </div>
            `;


            chat.appendChild(
                typing
            );


            scrollToBottom();
        }


        function removeTyping() {

            const typing =
                document.getElementById(
                    "typing"
                );


            if (typing) {
                typing.remove();
            }
        }


        // ====================================================
        // INPUT RESIZE
        // ====================================================

        function resizeInput() {

            input.style.height =
                "auto";


            input.style.height =
                Math.min(
                    input.scrollHeight,
                    145
                ) + "px";
        }


        // ====================================================
        // SEND
        // ====================================================

        async function sendMessage() {

            const message =
                input.value.trim();


            if (!message) {
                return;
            }


            addMessage(
                "user",
                message
            );


            input.value = "";

            resizeInput();

            sendButton.disabled = true;

            showTyping();


            try {

                const response =
                    await fetch(
                        "/api/chat",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body:
                                JSON.stringify({
                                    message
                                })
                        }
                    );


                let data;


                try {

                    data =
                        await response.json();

                } catch {

                    throw new Error(
                        "The server returned invalid JSON."
                    );
                }


                removeTyping();


                if (!response.ok) {

                    addMessage(
                        "assistant",
                        data.error ||
                        "The request failed."
                    );

                    return;
                }


                addMessage(
                    "assistant",
                    data.message ||
                    "No response was returned.",
                    data.results || []
                );


            } catch (error) {

                removeTyping();


                addMessage(
                    "assistant",
                    "I couldn't connect to Nexora. "
                    + "Check that the server is running."
                );


                console.error(
                    "Nexora error:",
                    error
                );

            } finally {

                sendButton.disabled =
                    false;

                input.focus();
            }
        }


        // ====================================================
        // NEW CHAT
        // ====================================================

        async function clearConversation() {

            try {

                await fetch(
                    "/api/history/clear",
                    {
                        method: "POST"
                    }
                );

            } catch (error) {

                console.error(error);
            }


            chat
                .querySelectorAll(
                    ".message"
                )
                .forEach(
                    element =>
                        element.remove()
                );


            if (welcome) {
                welcome.style.display =
                    "";
            }


            input.value = "";

            resizeInput();

            input.focus();
        }


        // ====================================================
        // QUICK PROMPTS
        // ====================================================

        document
            .querySelectorAll(
                "[data-prompt]"
            )
            .forEach(
                button => {

                    button.addEventListener(
                        "click",
                        () => {

                            input.value =
                                button.dataset.prompt;

                            resizeInput();

                            sendMessage();
                        }
                    );
                }
            );


        // ====================================================
        // SIDEBAR SHORTCUTS
        // ====================================================

        searchShortcut.addEventListener(
            "click",
            () => {

                input.value =
                    "search latest technology news";

                resizeInput();

                input.focus();
            }
        );


        calculatorShortcut.addEventListener(
            "click",
            () => {

                input.value =
                    "calculate ";

                resizeInput();

                input.focus();
            }
        );


        // ====================================================
        // EVENTS
        // ====================================================

        input.addEventListener(
            "input",
            resizeInput
        );


        input.addEventListener(
            "keydown",
            event => {

                if (
                    event.key === "Enter" &&
                    !event.shiftKey
                ) {

                    event.preventDefault();

                    sendMessage();
                }
            }
        );


        sendButton.addEventListener(
            "click",
            sendMessage
        );


        newChat.addEventListener(
            "click",
            clearConversation
        );


        clearHistory.addEventListener(
            "click",
            clearConversation
        );


        // ====================================================
        // STARTUP
        // ====================================================

        input.focus();

    </script>

</body>

</html>
"""


# ============================================================
# HTTP SERVER
# ============================================================

class NexoraHandler(
    BaseHTTPRequestHandler
):

    server_version = (
        f"Nexora/{SERVER_VERSION}"
    )

    # --------------------------------------------------------
    # Common headers
    # --------------------------------------------------------

    def send_common_headers(
        self,
        content_type: str,
        content_length: int,
    ) -> None:

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(content_length),
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )

        self.send_header(
            "X-Frame-Options",
            "SAMEORIGIN",
        )

        self.send_header(
            "Referrer-Policy",
            "strict-origin-when-cross-origin",
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

    # --------------------------------------------------------
    # JSON response
    # --------------------------------------------------------

    def send_json(
        self,
        status: int,
        data: object,
    ) -> None:

        body = json_bytes(data)

        self.send_response(
            status
        )

        self.send_common_headers(
            "application/json; charset=utf-8",
            len(body),
        )

        self.end_headers()

        self.wfile.write(body)

    # --------------------------------------------------------
    # HTML response
    # --------------------------------------------------------

    def send_html(
        self,
        html: str,
    ) -> None:

        body = html.encode(
            "utf-8"
        )

        self.send_response(
            200
        )

        self.send_common_headers(
            "text/html; charset=utf-8",
            len(body),
        )

        self.end_headers()

        self.wfile.write(body)

    # --------------------------------------------------------
    # OPTIONS
    # --------------------------------------------------------

    def do_OPTIONS(self) -> None:

        self.send_response(
            204
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS",
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type",
        )

        self.end_headers()

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self) -> None:

        parsed = urlparse(
            self.path
        )

        path = parsed.path


        # ----------------------------------------------------
        # Main UI
        # ----------------------------------------------------

        if path in {
            "/",
            "/index.html",
        }:

            self.send_html(
                INDEX_HTML
            )

            return


        # ----------------------------------------------------
        # Health
        # ----------------------------------------------------

        if path == "/health":

            self.send_json(
                200,
                {
                    "status": "healthy",
                    "service": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "api_required": False,
                },
            )

            return


        # ----------------------------------------------------
        # API information
        # ----------------------------------------------------

        if path == "/api":

            self.send_json(
                200,
                {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "status": "online",
                    "api_required": False,
                    "features": [
                        "chat",
                        "web_search",
                        "calculator",
                        "history",
                    ],
                },
            )

            return


        # ----------------------------------------------------
        # History
        # ----------------------------------------------------

        if path == "/api/history":

            self.send_json(
                200,
                {
                    "history": get_history(),
                },
            )

            return


        # ----------------------------------------------------
        # Search API
        # ----------------------------------------------------

        if path == "/api/search":

            params = parse_qs(
                parsed.query
            )

            query = params.get(
                "q",
                [""],
            )[0].strip()


            if not query:

                self.send_json(
                    400,
                    {
                        "error":
                            "Missing search query."
                    },
                )

                return


            results =
                search_duckduckgo(
                    query
                )


            self.send_json(
                200,
                {
                    "query": query,
                    "results": results,
                },
            )

            return


        # ----------------------------------------------------
        # 404
        # ----------------------------------------------------

        self.send_json(
            404,
            {
                "error": "Route not found.",
            },
        )

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    def do_POST(self) -> None:

        parsed = urlparse(
            self.path
        )

        path = parsed.path


        # ----------------------------------------------------
        # Chat
        # ----------------------------------------------------

        if path == "/api/chat":

            content_length_header =
                self.headers.get(
                    "Content-Length",
                    "0",
                )


            try:

                content_length =
                    int(
                        content_length_header
                    )

            except ValueError:

                self.send_json(
                    400,
                    {
                        "error":
                            "Invalid Content-Length."
                    },
                )

                return


            if (
                content_length <= 0
                or content_length >
                MAX_REQUEST_SIZE
            ):

                self.send_json(
                    413,
                    {
                        "error":
                            "Request is too large."
                    },
                )

                return


            try:

                raw_body =
                    self.rfile.read(
                        content_length
                    )

            except Exception:

                self.send_json(
                    400,
                    {
                        "error":
                            "Could not read request."
                    },
                )

                return


            try:

                payload =
                    json.loads(
                        raw_body.decode(
                            "utf-8"
                        )
                    )

            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):

                self.send_json(
                    400,
                    {
                        "error":
                            "Request body must be valid JSON."
                    },
                )

                return


            if not isinstance(
                payload,
                dict,
            ):

                self.send_json(
                    400,
                    {
                        "error":
                            "JSON body must be an object."
                    },
                )

                return


            message =
                payload.get(
                    "message",
                    "",
                )


            if not isinstance(
                message,
                str,
            ):

                self.send_json(
                    400,
                    {
                        "error":
                            "Message must be text."
                    },
                )

                return


            message =
                message.strip()


            if not message:

                self.send_json(
                    400,
                    {
                        "error":
                            "Message cannot be empty."
                    },
                )

                return


            if (
                len(message) >
                MAX_MESSAGE_LENGTH
            ):

                self.send_json(
                    400,
                    {
                        "error":
                            "Message is too long."
                    },
                )

                return


            # -----------------------------------------------
            # Process
            # -----------------------------------------------

            add_history(
                "user",
                message,
            )


            try:

                result =
                    assistant_response(
                        message
                    )

            except Exception as exc:

                logger.exception(
                    "Assistant error"
                )

                result = {
                    "type": "error",
                    "message":
                        "Nexora encountered "
                        "an internal error.",
                }


            add_history(
                "assistant",
                result.get(
                    "message",
                    "",
                ),
                result.get(
                    "type",
                    "chat",
                ),
            )


            self.send_json(
                200,
                result,
            )

            return


        # ----------------------------------------------------
        # Clear history
        # ----------------------------------------------------

        if path == "/api/history/clear":

            clear_history()

            self.send_json(
                200,
                {
                    "success": True,
                },
            )

            return


        # ----------------------------------------------------
        # 404
        # ----------------------------------------------------

        self.send_json(
            404,
            {
                "error":
                    "Route not found.",
            },
        )

    # --------------------------------------------------------
    # Logging
    # --------------------------------------------------------

    def log_message(
        self,
        format_string: str,
        *args,
    ) -> None:

        logger.info(
            "%s - %s",
            self.address_string(),
            format_string % args,
        )


# ============================================================
# SERVER
# ============================================================

server: ThreadingHTTPServer | None = None


def shutdown_server(
    signum=None,
    frame=None,
) -> None:

    global server

    logger.info(
        "Shutdown signal received."
    )

    if server is not None:

        threading.Thread(
            target=server.shutdown,
            daemon=True,
        ).start()


# ============================================================
# STARTUP
# ============================================================

def startup() -> None:

    global server


    logger.info(
        "Starting %s %s",
        SERVER_NAME,
        SERVER_VERSION,
    )


    try:

        server =
            ThreadingHTTPServer(
                (HOST, PORT),
                NexoraHandler,
            )

    except OSError as exc:

        logger.error(
            "Could not bind to %s:%s",
            HOST,
            PORT,
        )

        raise exc


    server.daemon_threads = True


    logger.info(
        "Nexora listening on %s:%s",
        HOST,
        PORT,
    )


    try:

        server.serve_forever(
            poll_interval=0.5
        )

    except KeyboardInterrupt:

        logger.info(
            "Keyboard interrupt received."
        )

    finally:

        logger.info(
            "Closing Nexora server."
        )

        server.server_close()

        server = None


# ============================================================
# SIGNAL HANDLERS
# ============================================================

try:

    signal.signal(
        signal.SIGTERM,
        shutdown_server,
    )

    signal.signal(
        signal.SIGINT,
        shutdown_server,
    )

except Exception:

    # Some environments do not allow
    # signal handlers to be installed.
    pass


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    startup()
