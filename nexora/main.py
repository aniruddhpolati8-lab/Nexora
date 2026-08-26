from __future__ import annotations

import ast
import hashlib
import html
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import signal
import socket
import threading
import time

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen


# ============================================================
# NEXORA 10.0
# ============================================================
#
# Expert-level single-file assistant/search shell.
#
# No external Python packages.
#
# Features:
#   - DuckDuckGo + Bing search providers
#   - Parallel provider execution
#   - Provider fallback
#   - Advanced relevance scoring
#   - Query token weighting
#   - Phrase matching
#   - URL/domain quality scoring
#   - Spam detection
#   - Low-value domain penalties
#   - Suspicious URL filtering
#   - URL canonicalisation
#   - Duplicate removal
#   - Cross-provider duplicate merging
#   - Domain diversity control
#   - Result quality thresholds
#   - Search caching
#   - Stale cache protection
#   - Thread-safe state
#   - Session cookies
#   - CSRF protection
#   - Same-origin protection
#   - Request-size limits
#   - Search/message rate limiting
#   - Connection limiting
#   - Safe calculator using AST
#   - Graceful shutdown
#   - Health endpoint
#   - JSON API
#   - Responsive UI
#
# ============================================================


# ============================================================
# CONFIGURATION
# ============================================================

HOST = "0.0.0.0"

try:
    PORT = int(os.environ.get("PORT", "10000"))
except (TypeError, ValueError):
    PORT = 10000

if not 1 <= PORT <= 65535:
    PORT = 10000


SERVER_NAME = "Nexora"
SERVER_VERSION = "10.0"

MAX_MESSAGE_LENGTH = 4000
MAX_HISTORY_ITEMS = 100

MAX_SEARCH_RESULTS = 8
MAX_SEARCH_QUERY_LENGTH = 500
MAX_PROVIDER_RESULTS = 14

MAX_REQUEST_SIZE = 100_000
MAX_SEARCH_RESPONSE_BYTES = 2_000_000

SEARCH_TIMEOUT = 7
MAX_CONNECTIONS = 80

RATE_WINDOW_SECONDS = 60
RATE_MAX_REQUESTS = 30
SEARCH_RATE_MAX = 10

SESSION_COOKIE = "nexora_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7
MAX_SESSIONS = 5000

CACHE_TTL = 120
CACHE_MAX_ITEMS = 256

MAX_REDIRECTS = 3
MAX_URL_LENGTH = 4096

MIN_RESULT_SCORE = 2.0

USER_AGENT = (
    "Nexora/10.0 "
    "(+https://nexora.local) "
    "Mozilla/5.0 "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)

ALLOWED_METHODS = "GET, POST, OPTIONS"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("nexora")


# ============================================================
# GLOBAL SERVER STATE
# ============================================================

server: ThreadingHTTPServer | None = None
START_MONOTONIC = time.monotonic()

connection_semaphore = threading.BoundedSemaphore(MAX_CONNECTIONS)


# ============================================================
# SESSION MANAGEMENT
# ============================================================

@dataclass
class SessionState:
    csrf_token: str

    history: deque[dict] = field(
        default_factory=lambda: deque(maxlen=MAX_HISTORY_ITEMS)
    )

    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


class SessionStore:

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionState] = {}

    def create(self):
        with self._lock:

            self._prune_locked()

            sid = secrets.token_urlsafe(32)

            state = SessionState(
                csrf_token=secrets.token_urlsafe(32)
            )

            self._sessions[sid] = state

            return sid, state

    def get(self, sid: str | None):

        if not sid:
            return None

        with self._lock:

            state = self._sessions.get(sid)

            if state:
                state.last_seen = time.time()

            return state

    def get_or_create(self, sid: str | None):

        state = self.get(sid)

        if state:
            return sid, state

        return self.create()

    def _prune_locked(self):

        now = time.time()

        expired = [
            sid
            for sid, state in self._sessions.items()
            if now - state.last_seen > SESSION_MAX_AGE
        ]

        for sid in expired:
            self._sessions.pop(sid, None)

        while len(self._sessions) >= MAX_SESSIONS:

            oldest_sid = min(
                self._sessions,
                key=lambda key: self._sessions[key].last_seen,
            )

            self._sessions.pop(oldest_sid, None)


sessions = SessionStore()


# ============================================================
# RATE LIMITER
# ============================================================

class RateLimiter:

    def __init__(self):

        self._lock = threading.RLock()
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int):

        now = time.monotonic()
        cutoff = now - RATE_WINDOW_SECONDS

        with self._lock:

            hits = self._hits.setdefault(key, deque())

            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= limit:
                return False

            hits.append(now)

            if len(self._hits) > 10000:

                stale = [
                    k
                    for k, values in self._hits.items()
                    if not values or values[-1] <= cutoff
                ]

                for key_to_remove in stale[:2000]:
                    self._hits.pop(key_to_remove, None)

            return True


rate_limiter = RateLimiter()


# ============================================================
# SEARCH CACHE
# ============================================================

class SearchCache:

    def __init__(
        self,
        ttl: int = CACHE_TTL,
        max_items: int = CACHE_MAX_ITEMS,
    ):

        self.ttl = ttl
        self.max_items = max_items

        self._lock = threading.RLock()

        self._items: dict[
            str,
            tuple[float, list[dict]]
        ] = {}

    def get(self, key: str):

        with self._lock:

            item = self._items.get(key)

            if item is None:
                return None

            expires_at, results = item

            if expires_at <= time.monotonic():

                self._items.pop(key, None)

                return None

            return [
                dict(result)
                for result in results
            ]

    def put(self, key: str, results: list[dict]):

        with self._lock:

            self._items[key] = (
                time.monotonic() + self.ttl,
                [dict(result) for result in results],
            )

            while len(self._items) > self.max_items:

                oldest = min(
                    self._items,
                    key=lambda k: self._items[k][0],
                )

                self._items.pop(oldest, None)


search_cache = SearchCache()


# ============================================================
# GENERAL HELPERS
# ============================================================

def normalize_text(value) -> str:

    if value is None:
        return ""

    value = str(value)

    value = value.replace("\x00", " ")

    return re.sub(r"\s+", " ", value).strip()


def clamp_text(value, maximum: int) -> str:

    value = value or ""

    if len(value) <= maximum:
        return value

    return value[:maximum].rstrip() + "…"


def json_bytes(data) -> bytes:

    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def utc_iso(ts=None):

    if ts is None:
        ts = time.time()

    return (
        datetime
        .fromtimestamp(ts, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def clean_html(value) -> str:

    if not value:
        return ""

    value = re.sub(
        r"<(script|style|noscript|template)\b[^>]*>.*?</\1>",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<[^>]*>",
        " ",
        value,
    )

    return normalize_text(
        html.unescape(value)
    )


def tokenize(text: str) -> list[str]:

    return re.findall(
        r"[a-z0-9][a-z0-9'-]{1,}",
        text.casefold(),
    )


def unique_preserve(values):

    seen = set()
    output = []

    for value in values:

        if value in seen:
            continue

        seen.add(value)
        output.append(value)

    return output


# ============================================================
# URL SECURITY
# ============================================================

def valid_http_url(raw_url: str) -> bool:

    if not raw_url:
        return False

    if len(raw_url) > MAX_URL_LENGTH:
        return False

    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return False

    if parsed.scheme.lower() not in {"http", "https"}:
        return False

    if not parsed.hostname:
        return False

    if parsed.username or parsed.password:
        return False

    if parsed.fragment:
        # Fragments are irrelevant to fetching/search identity.
        pass

    return True


def is_private_ip(host: str) -> bool:

    try:

        ip = ipaddress.ip_address(host)

        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )

    except ValueError:

        return False


def resolve_host_safely(host: str) -> bool:

    host = (host or "").lower().rstrip(".")

    if not host:
        return False

    if host in {
        "localhost",
        "localhost.localdomain",
    }:
        return False

    if host.endswith(".local"):
        return False

    if is_private_ip(host):
        return False

    try:

        addresses = socket.getaddrinfo(
            host,
            None,
            type=socket.SOCK_STREAM,
        )

    except OSError:

        return False

    if not addresses:
        return False

    for item in addresses:

        sockaddr = item[4]

        if not sockaddr:
            return False

        address = sockaddr[0]

        if is_private_ip(address):
            return False

    return True


def safe_fetch_target(raw_url: str) -> bool:

    if not valid_http_url(raw_url):
        return False

    try:

        parsed = urlparse(raw_url)

        host = (
            parsed.hostname or ""
        ).lower().rstrip(".")

        return resolve_host_safely(host)

    except Exception:

        return False


def canonical_url(raw_url: str) -> str:

    try:

        parsed = urlparse(raw_url)

        scheme = parsed.scheme.lower()

        host = (
            parsed.hostname or ""
        ).lower()

        if host.startswith("www."):
            host = host[4:]

        port = parsed.port

        if port and not (
            (scheme == "http" and port == 80)
            or
            (scheme == "https" and port == 443)
        ):

            host = f"{host}:{port}"

        path = parsed.path or "/"

        path = re.sub(
            r"/{2,}",
            "/",
            path,
        )

        path = path.rstrip("/") or "/"

        query_pairs = parse_qs(
            parsed.query,
            keep_blank_values=False,
        )

        ignored_parameters = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "gclid",
            "fbclid",
            "ref",
            "ref_src",
            "mc_cid",
            "mc_eid",
        }

        clean_pairs = []

        for key, values in query_pairs.items():

            if key.casefold() in ignored_parameters:
                continue

            for value in values:
                clean_pairs.append(
                    (
                        key,
                        value,
                    )
                )

        clean_pairs.sort()

        query = "&".join(
            f"{key}={value}"
            for key, value in clean_pairs
        )

        result = f"{scheme}://{host}{path}"

        if query:
            result += "?" + query

        return result

    except Exception:

        return raw_url.casefold()


def domain_of(url: str) -> str:

    try:

        host = (
            urlparse(url).hostname or ""
        ).lower()

        if host.startswith("www."):
            host = host[4:]

        return host

    except Exception:

        return ""


# ============================================================
# SEARCH QUERY PROCESSING
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

SEARCH_TRIGGERS = (
    "latest ",
    "latest",
    "today ",
    "today's ",
    "current ",
    "current",
    "now ",
    "news ",
    "news about ",
    "who won ",
    "what happened ",
    "standings ",
    "price ",
    "weather ",
    "score ",
)

STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "was",
    "were",
    "what",
    "who",
    "how",
    "when",
    "where",
    "why",
    "with",
    "about",
    "latest",
    "current",
    "today",
}


def normalize_search_query(query: str) -> str:

    query = normalize_text(query)

    query = re.sub(
        r"[\x00-\x1f\x7f]",
        " ",
        query,
    )

    return query[:MAX_SEARCH_QUERY_LENGTH].strip()


def get_search_query(message: str):

    lowered = message.casefold().strip()

    for prefix in SEARCH_PREFIXES:

        if lowered.startswith(prefix):

            query = normalize_search_query(
                message[len(prefix):]
            )

            return query or None

    return None


def infer_search_query(message: str):

    message = normalize_text(message)

    if not (
        5 <= len(message)
        <= MAX_SEARCH_QUERY_LENGTH
    ):
        return None

    lowered = message.casefold()

    if any(
        lowered.startswith(trigger)
        for trigger in SEARCH_TRIGGERS
    ):
        return message

    return None


def query_tokens(query: str) -> list[str]:

    tokens = tokenize(query)

    meaningful = [
        token
        for token in tokens
        if token not in STOPWORDS
        and len(token) >= 2
    ]

    return unique_preserve(
        meaningful
    )


def build_provider_urls(query: str):

    encoded = quote_plus(query)

    return {
        "duckduckgo": (
            "https://html.duckduckgo.com/html/"
            f"?q={encoded}"
        ),
        "bing": (
            "https://www.bing.com/search"
            f"?q={encoded}&setlang=en-GB"
        ),
    }


# ============================================================
# SEARCH FETCHING
# ============================================================

def fetch_search_page(url: str) -> str:

    if not safe_fetch_target(url):

        raise ValueError(
            "Unsafe search target."
        )

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml"
            ),
            "Accept-Language": (
                "en-GB,en;q=0.9"
            ),
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
        method="GET",
    )

    with urlopen(
        request,
        timeout=SEARCH_TIMEOUT,
    ) as response:

        content_length = response.headers.get(
            "Content-Length"
        )

        if content_length:

            try:

                if (
                    int(content_length)
                    > MAX_SEARCH_RESPONSE_BYTES
                ):
                    raise ValueError(
                        "Search response is too large."
                    )

            except ValueError:
                pass

        data = response.read(
            MAX_SEARCH_RESPONSE_BYTES + 1
        )

        if len(data) > MAX_SEARCH_RESPONSE_BYTES:

            raise ValueError(
                "Search response is too large."
            )

        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        return data.decode(
            charset,
            errors="replace",
        )


# ============================================================
# URL EXTRACTION
# ============================================================

def extract_search_url(raw_url: str) -> str:

    raw_url = html.unescape(
        (raw_url or "").strip()
    )

    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url

    try:

        parsed = urlparse(raw_url)

    except ValueError:

        return ""

    query = parse_qs(
        parsed.query,
        keep_blank_values=False,
    )

    for key in (
        "uddg",
        "url",
        "target",
        "u",
    ):

        for candidate in query.get(
            key,
            [],
        ):

            candidate = unquote(
                candidate
            ).strip()

            if valid_http_url(candidate):
                return candidate

    if valid_http_url(raw_url):
        return raw_url

    return ""


# ============================================================
# DUCKDUCKGO PARSER
# ============================================================

class DDGParser(HTMLParser):

    def __init__(self, limit=MAX_PROVIDER_RESULTS):

        super().__init__(
            convert_charrefs=True
        )

        self.limit = limit
        self.results = []

        self.current = None
        self.capture = None
        self.buffer = []

    def finish_capture(self):

        if (
            self.current is not None
            and self.capture
        ):

            text = clamp_text(
                normalize_text(
                    " ".join(self.buffer)
                ),
                700,
            )

            self.current[
                self.capture
            ] = text

        self.capture = None
        self.buffer = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        attrs = dict(attrs)

        classes = set(
            (attrs.get("class") or "").split()
        )

        if (
            tag == "a"
            and "result__a" in classes
        ):

            self.finish_capture()

            url = extract_search_url(
                attrs.get("href", "")
            )

            if (
                url
                and len(self.results)
                < self.limit
            ):

                self.current = {
                    "title": "",
                    "url": url,
                    "snippet": "",
                    "source": domain_of(url),
                    "provider": "duckduckgo",
                }

                self.results.append(
                    self.current
                )

                self.capture = "title"

        elif (
            self.current
            and "result__snippet" in classes
        ):

            self.finish_capture()

            self.capture = "snippet"

    def handle_endtag(self, tag):

        if (
            self.capture == "title"
            and tag == "a"
        ):
            self.finish_capture()

        elif (
            self.capture == "snippet"
            and tag in {
                "div",
                "a",
                "span",
            }
        ):
            self.finish_capture()

    def handle_data(self, data):

        if self.capture:
            self.buffer.append(data)


# ============================================================
# BING PARSER
# ============================================================

class BingParser(HTMLParser):

    def __init__(self, limit=MAX_PROVIDER_RESULTS):

        super().__init__(
            convert_charrefs=True
        )

        self.limit = limit
        self.results = []

        self.in_result = False
        self.current = None
        self.capture = None
        self.buffer = []

        self.depth = 0

    def finish_capture(self):

        if (
            self.current is not None
            and self.capture
        ):

            text = clamp_text(
                normalize_text(
                    " ".join(self.buffer)
                ),
                700,
            )

            self.current[
                self.capture
            ] = text

        self.capture = None
        self.buffer = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        attrs = dict(attrs)

        classes = set(
            (attrs.get("class") or "").split()
        )

        if (
            tag == "li"
            and "b_algo" in classes
        ):

            self.finish_capture()

            if (
                len(self.results)
                >= self.limit
            ):
                return

            self.in_result = True
            self.depth = 1
            self.current = None

            return

        if not self.in_result:
            return

        self.depth += 1

        if tag == "h2":

            self.finish_capture()

            self.capture = "title"

        elif (
            tag == "a"
            and self.current is None
        ):

            url = extract_search_url(
                attrs.get("href", "")
            )

            if url:

                self.current = {
                    "title": "",
                    "url": url,
                    "snippet": "",
                    "source": domain_of(url),
                    "provider": "bing",
                }

                self.results.append(
                    self.current
                )

        elif (
            tag == "p"
            and self.current
        ):

            self.finish_capture()

            self.capture = "snippet"

    def handle_endtag(self, tag):

        if not self.in_result:
            return

        if (
            self.capture == "title"
            and tag == "h2"
        ):
            self.finish_capture()

        elif (
            self.capture == "snippet"
            and tag == "p"
        ):
            self.finish_capture()

        self.depth -= 1

        if (
            tag == "li"
            and self.depth <= 0
        ):

            self.finish_capture()

            self.in_result = False
            self.current = None
            self.depth = 0

    def handle_data(self, data):

        if self.capture:
            self.buffer.append(data)


# ============================================================
# PARSER DISPATCH
# ============================================================

def parse_provider(
    source: str,
    provider: str,
    limit: int = MAX_PROVIDER_RESULTS,
):

    if provider == "duckduckgo":
        parser = DDGParser(limit)

    elif provider == "bing":
        parser = BingParser(limit)

    else:
        return []

    try:

        parser.feed(source)
        parser.close()

    except Exception:

        logger.exception(
            "%s parser failed",
            provider,
        )

    return parser.results


# ============================================================
# SEARCH QUALITY FILTER
# ============================================================

LOW_VALUE_DOMAINS = {
    "pinterest.com",
    "quora.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "reddit.com",
}

HIGH_QUALITY_DOMAINS = {
    "reuters.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "apnews.com",
    "nasa.gov",
    "gov.uk",
    "who.int",
    "un.org",
    "wikipedia.org",
    "microsoft.com",
    "apple.com",
    "google.com",
    "openai.com",
    "github.com",
    "python.org",
    "mozilla.org",
}

GENERIC_TITLES = {
    "home",
    "homepage",
    "welcome",
    "untitled",
    "login",
    "sign in",
}

SPAM_TERMS = {
    "casino",
    "betting",
    "porn",
    "xxx",
    "crack download",
    "free money",
    "earn money fast",
    "miracle cure",
}

SUSPICIOUS_PATH_TERMS = {
    "/malware/",
    "/phishing/",
    "/casino/",
    "/porn/",
}

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
}


def basic_result_valid(result: dict) -> bool:

    title = normalize_text(
        result.get("title", "")
    )

    url = result.get("url", "")

    snippet = normalize_text(
        result.get("snippet", "")
    )

    if not title:
        return False

    if len(title) < 3:
        return False

    if title.casefold() in GENERIC_TITLES:
        return False

    if len(title) > 500:
        return False

    if not valid_http_url(url):
        return False

    if not safe_fetch_target(url):
        return False

    domain = domain_of(url)

    if not domain:
        return False

    if len(domain) > 253:
        return False

    combined = (
        title
        + " "
        + snippet
        + " "
        + url
    ).casefold()

    for term in SPAM_TERMS:

        if term in combined:
            return False

    for path_term in SUSPICIOUS_PATH_TERMS:

        if path_term in url.casefold():
            return False

    return True


# ============================================================
# ADVANCED SEARCH SCORING
# ============================================================

def relevance_score(
    result: dict,
    query: str,
) -> float:

    title = normalize_text(
        result.get("title", "")
    ).casefold()

    snippet = normalize_text(
        result.get("snippet", "")
    ).casefold()

    url = result.get("url", "")

    domain = domain_of(url).casefold()

    query_lower = query.casefold()

    tokens = query_tokens(query)

    score = 0.0

    # --------------------------------------------------------
    # Exact phrase
    # --------------------------------------------------------

    if query_lower in title:
        score += 14.0

    elif query_lower in snippet:
        score += 7.0

    # --------------------------------------------------------
    # Token matching
    # --------------------------------------------------------

    matched_tokens = 0

    for token in tokens:

        if token in title:
            score += 5.0
            matched_tokens += 1

        if token in snippet:
            score += 2.2

        if token in domain:
            score += 1.5

    # --------------------------------------------------------
    # Coverage bonus
    # --------------------------------------------------------

    if tokens:

        coverage = (
            matched_tokens
            / len(tokens)
        )

        score += coverage * 8.0

    # --------------------------------------------------------
    # Domain quality
    # --------------------------------------------------------

    if domain in HIGH_QUALITY_DOMAINS:
        score += 5.0

    if domain in LOW_VALUE_DOMAINS:
        score -= 3.0

    # --------------------------------------------------------
    # Search intent hints
    # --------------------------------------------------------

    if any(
        word in query_lower
        for word in (
            "latest",
            "news",
            "today",
            "current",
        )
    ):

        if domain in {
            "reuters.com",
            "bbc.com",
            "bbc.co.uk",
            "apnews.com",
            "theguardian.com",
        }:
            score += 4.0

    # --------------------------------------------------------
    # URL quality
    # --------------------------------------------------------

    parsed = urlparse(url)

    path = parsed.path.casefold()

    if path in {"", "/"}:
        score += 0.5

    if len(path) < 180:
        score += 0.5

    if len(url) > 1000:
        score -= 1.0

    # --------------------------------------------------------
    # Snippet quality
    # --------------------------------------------------------

    if snippet:

        score += 1.0

        if len(snippet) >= 80:
            score += 0.8

        if len(snippet) >= 160:
            score += 0.5

    else:

        score -= 1.5

    # --------------------------------------------------------
    # Title quality
    # --------------------------------------------------------

    if 15 <= len(title) <= 140:
        score += 0.8

    if title == query_lower:
        score += 8.0

    # --------------------------------------------------------
    # Keyword stuffing penalty
    # --------------------------------------------------------

    words = tokenize(
        title + " " + snippet
    )

    if words:

        repeated = (
            len(words)
            - len(set(words))
        )

        if repeated > 12:
            score -= 2.0

    return round(
        score,
        4,
    )


# ============================================================
# RESULT FILTERING + DEDUPLICATION
# ============================================================

def filter_and_rank(
    results: list[dict],
    query: str,
    limit: int = MAX_SEARCH_RESULTS,
):

    dedup: dict[str, dict] = {}

    rejected = 0

    for original in results:

        result = dict(original)

        if not basic_result_valid(result):

            rejected += 1
            continue

        result["title"] = clamp_text(
            normalize_text(
                result.get("title", "")
            ),
            240,
        )

        result["snippet"] = clamp_text(
            normalize_text(
                result.get("snippet", "")
            ),
            700,
        )

        result["source"] = domain_of(
            result["url"]
        )

        key = canonical_url(
            result["url"]
        )

        # ----------------------------------------------------
        # Duplicate URL handling
        # ----------------------------------------------------

        if key in dedup:

            existing = dedup[key]

            existing_snippet = (
                existing.get("snippet", "")
            )

            current_snippet = (
                result.get("snippet", "")
            )

            # Keep the richer version.
            if len(current_snippet) > len(
                existing_snippet
            ):

                dedup[key] = result

            continue

        result["_score"] = relevance_score(
            result,
            query,
        )

        if result["_score"] < MIN_RESULT_SCORE:

            rejected += 1
            continue

        dedup[key] = result

    ranked = sorted(
        dedup.values(),
        key=lambda result: (
            result.get("_score", 0),
            bool(result.get("snippet")),
        ),
        reverse=True,
    )

    # ========================================================
    # ADVANCED DOMAIN DIVERSITY
    # ========================================================

    chosen = []
    domain_counts: dict[str, int] = {}

    for result in ranked:

        domain = result["source"]

        count = domain_counts.get(
            domain,
            0,
        )

        # First two from a domain are allowed.
        # Additional ones are only allowed when
        # there are not enough alternatives.
        if count >= 2 and len(chosen) < limit - 2:
            continue

        chosen.append(result)

        domain_counts[domain] = count + 1

        if len(chosen) >= limit:
            break

    # --------------------------------------------------------
    # Remove internal score.
    # --------------------------------------------------------

    for result in chosen:

        result.pop(
            "_score",
            None,
        )

    return chosen, rejected


# ============================================================
# SEARCH ENGINE
# ============================================================

def search_web(
    query: str,
    limit: int = MAX_SEARCH_RESULTS,
):

    query = normalize_search_query(query)

    if not query:

        return {
            "results": [],
            "providers": [],
            "filtered": 0,
            "cached": False,
        }

    limit = max(
        1,
        min(
            int(limit),
            MAX_SEARCH_RESULTS,
        ),
    )

    cache_key = hashlib.sha256(
        (
            query.casefold()
            + f"|{limit}"
        ).encode("utf-8")
    ).hexdigest()

    cached = search_cache.get(
        cache_key
    )

    if cached is not None:

        return {
            "results": cached[:limit],
            "providers": ["cache"],
            "filtered": 0,
            "cached": True,
        }

    provider_urls = build_provider_urls(
        query
    )

    collected: list[dict] = []
    providers: list[str] = []

    lock = threading.Lock()

    def worker(
        provider: str,
        url: str,
    ):

        try:

            source = fetch_search_page(
                url
            )

            parsed = parse_provider(
                source,
                provider,
                limit=MAX_PROVIDER_RESULTS,
            )

            if parsed:

                with lock:

                    collected.extend(
                        parsed
                    )

                    providers.append(
                        provider
                    )

        except (
            HTTPError,
            URLError,
            TimeoutError,
            ValueError,
            OSError,
        ) as exc:

            logger.warning(
                "%s search failed: %s",
                provider,
                exc,
            )

        except Exception:

            logger.exception(
                "Unexpected %s search error",
                provider,
            )

    threads = []

    for provider, url in provider_urls.items():

        thread = threading.Thread(
            target=worker,
            args=(provider, url),
            daemon=True,
        )

        threads.append(thread)
        thread.start()

    deadline = (
        time.monotonic()
        + SEARCH_TIMEOUT
        + 1
    )

    for thread in threads:

        remaining = (
            deadline
            - time.monotonic()
        )

        if remaining <= 0:
            break

        thread.join(
            timeout=remaining
        )

    results, filtered = filter_and_rank(
        collected,
        query,
        limit,
    )

    providers = unique_preserve(
        providers
    )

    if results:

        search_cache.put(
            cache_key,
            results,
        )

    return {
        "results": results,
        "providers": providers,
        "filtered": filtered,
        "cached": False,
    }


# ============================================================
# CALCULATOR
# ============================================================

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
    ast.UAdd: lambda x: +x,
    ast.USub: lambda x: -x,
}


def validate_number(value):

    if isinstance(value, bool):

        raise ValueError(
            "Only finite numbers are allowed."
        )

    if not isinstance(
        value,
        (int, float),
    ):

        raise ValueError(
            "Only finite numbers are allowed."
        )

    if isinstance(value, float):

        if not math.isfinite(value):

            raise ValueError(
                "The result is not finite."
            )

        if abs(value) > 1e100:

            raise ValueError(
                "The result is too large."
            )

    if isinstance(value, int):

        if value.bit_length() > 340:

            raise ValueError(
                "The result is too large."
            )

    return value


def safe_calculate(expression: str):

    expression = normalize_text(
        expression
    ).replace(
        "^",
        "**",
    )

    if not expression:

        raise ValueError(
            "Please provide a mathematical expression."
        )

    if len(expression) > 250:

        raise ValueError(
            "Expression must be under 250 characters."
        )

    try:

        tree = ast.parse(
            expression,
            mode="eval",
        )

    except SyntaxError as exc:

        raise ValueError(
            "That is not a valid mathematical expression."
        ) from exc

    def evaluate(
        node,
        depth=0,
    ):

        if depth > 25:

            raise ValueError(
                "Expression is too deeply nested."
            )

        if isinstance(
            node,
            ast.Expression,
        ):

            return evaluate(
                node.body,
                depth + 1,
            )

        if isinstance(
            node,
            ast.Constant,
        ):

            if (
                isinstance(
                    node.value,
                    (int, float),
                )
                and not isinstance(
                    node.value,
                    bool,
                )
            ):

                return validate_number(
                    node.value
                )

            raise ValueError(
                "Invalid value."
            )

        if isinstance(
            node,
            ast.Name,
        ):

            if node.id in MATH_CONSTANTS:

                return MATH_CONSTANTS[
                    node.id
                ]

            raise ValueError(
                f"'{node.id}' is not allowed."
            )

        if isinstance(
            node,
            ast.UnaryOp,
        ):

            function = UNARY_OPERATORS.get(
                type(node.op)
            )

            if function is None:

                raise ValueError(
                    "That operator is not allowed."
                )

            value = evaluate(
                node.operand,
                depth + 1,
            )

            return validate_number(
                function(value)
            )

        if isinstance(
            node,
            ast.BinOp,
        ):

            function = BINARY_OPERATORS.get(
                type(node.op)
            )

            if function is None:

                raise ValueError(
                    "That operator is not allowed."
                )

            left = evaluate(
                node.left,
                depth + 1,
            )

            right = evaluate(
                node.right,
                depth + 1,
            )

            if isinstance(
                node.op,
                ast.Pow,
            ):

                if abs(right) > 100:

                    raise ValueError(
                        "That power is too large."
                    )

                if abs(left) > 1e6:

                    raise ValueError(
                        "That power is too large."
                    )

            try:

                return validate_number(
                    function(
                        left,
                        right,
                    )
                )

            except (
                ArithmeticError,
                OverflowError,
                ValueError,
            ) as exc:

                raise ValueError(
                    "The calculation could not be completed."
                ) from exc

        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Name,
            )
        ):

            entry = MATH_FUNCTIONS.get(
                node.func.id
            )

            if entry is None:

                raise ValueError(
                    f"'{node.func.id}' is not allowed."
                )

            function, minimum, maximum = entry

            if not (
                minimum
                <= len(node.args)
                <= maximum
            ):

                raise ValueError(
                    f"{node.func.id} expects "
                    f"{minimum}–{maximum} "
                    "argument(s)."
                )

            args = [
                evaluate(
                    argument,
                    depth + 1,
                )
                for argument in node.args
            ]

            if (
                node.func.id
                == "factorial"
            ):

                value = args[0]

                if (
                    not isinstance(
                        value,
                        int,
                    )
                    or not (
                        0
                        <= value
                        <= 1000
                    )
                ):

                    raise ValueError(
                        "factorial() accepts integers from 0 to 1000."
                    )

            try:

                return validate_number(
                    function(*args)
                )

            except (
                ArithmeticError,
                OverflowError,
                ValueError,
            ) as exc:

                raise ValueError(
                    "The calculation could not be completed."
                ) from exc

        raise ValueError(
            "That expression contains unsupported syntax."
        )

    return evaluate(tree)


# ============================================================
# ASSISTANT COMMANDS
# ============================================================

def is_time_query(message):

    return normalize_text(
        message
    ).casefold() in {
        "time",
        "what time is it",
        "what's the time",
        "current time",
        "what is the current time",
    }


def is_version_query(message):

    return normalize_text(
        message
    ).casefold() in {
        "version",
        "what version are you",
        "what version is this",
    }


def is_help_query(message):

    return normalize_text(
        message
    ).casefold() in {
        "help",
        "commands",
        "features",
        "what can you do",
    }


def assistant_response(message: str):

    message = normalize_text(
        message
    )

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
        re.I,
    )

    if calculator_match:

        expression = (
            calculator_match
            .group(1)
            .strip()
        )

        try:

            result = safe_calculate(
                expression
            )

            return {
                "type": "calculator",
                "message": (
                    f"**{expression}** = "
                    f"**{result}**"
                ),
                "result": result,
            }

        except ValueError as exc:

            return {
                "type": "error",
                "message": str(exc),
            }

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------

    query = (
        get_search_query(message)
        or infer_search_query(message)
    )

    if query:

        started = time.monotonic()

        data = search_web(query)

        duration = round(
            (
                time.monotonic()
                - started
            ) * 1000
        )

        results = data["results"]

        if not results:

            return {
                "type": "search",
                "message": (
                    "I couldn't find reliable "
                    f"web results for **{query}** "
                    "right now. Try a more specific search."
                ),
                "results": [],
                "query": query,
                "duration_ms": duration,
                "providers": data["providers"],
                "filtered": data["filtered"],
            }

        return {
            "type": "search",
            "message": (
                f"Found **{len(results)}** "
                f"filtered web result(s) "
                f"for **{query}**."
            ),
            "results": results,
            "query": query,
            "duration_ms": duration,
            "providers": data["providers"],
            "filtered": data["filtered"],
            "cached": data["cached"],
        }

    # --------------------------------------------------------
    # Help
    # --------------------------------------------------------

    if is_help_query(message):

        return {
            "type": "chat",
            "message": (
                "### Nexora 10.0\n\n"
                "🔎 **Web search** — "
                "`search <topic>` or ask a "
                "current/latest question.\n\n"
                "🧮 **Calculator** — "
                "`calculate 125 * 48`\n\n"
                "🕒 **Time** — ask `time`\n\n"
                "ℹ️ **Version** — ask `version`\n\n"
                "Nexora uses parallel search providers, "
                "advanced relevance scoring, "
                "URL validation, spam filtering, "
                "deduplication, domain diversity, "
                "caching and security controls."
            ),
        }

    # --------------------------------------------------------
    # Greetings
    # --------------------------------------------------------

    if message.casefold() in {
        "hi",
        "hello",
        "hey",
        "yo",
        "hiya",
    }:

        return {
            "type": "chat",
            "message": (
                "Hey! 👋 Nexora is online "
                "and ready."
            ),
        }

    # --------------------------------------------------------
    # Time
    # --------------------------------------------------------

    if is_time_query(message):

        local_time = (
            datetime
            .now()
            .astimezone()
            .strftime("%H:%M:%S")
        )

        return {
            "type": "chat",
            "message": (
                "The server time is "
                f"**{local_time}**."
            ),
        }

    # --------------------------------------------------------
    # Version
    # --------------------------------------------------------

    if is_version_query(message):

        return {
            "type": "chat",
            "message": (
                f"You're running "
                f"**{SERVER_NAME} "
                f"{SERVER_VERSION}**."
            ),
        }

    # --------------------------------------------------------
    # Default
    # --------------------------------------------------------

    return {
        "type": "chat",
        "message": (
            "I can search the web, "
            "calculate expressions, "
            "tell you the server time, "
            "and explain my features.\n\n"
            "Try `search Premier League "
            "standings 2026/27` or "
            "`calculate 125 * 48`."
        ),
    }


# ============================================================
# HTML UI
# ============================================================

INDEX_HTML = r"""<!doctype html>
<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<meta
    name="theme-color"
    content="#070a12"
>

<title>Nexora 10.0</title>

<style>

:root{
    --bg:#070a12;
    --panel:#0d121d;
    --line:#20293a;
    --text:#f4f7ff;
    --muted:#96a1b5;
    --dim:#687389;
    --accent:#5cecff;
    --accent2:#9c6cff;
    --danger:#ff6b7a;
}

*{
    box-sizing:border-box;
}

html,
body{
    width:100%;
    height:100%;
    margin:0;
}

body{
    overflow:hidden;
    color:var(--text);
    font-family:Inter,system-ui,sans-serif;
    background:
        radial-gradient(
            circle at 85% 0,
            rgba(92,236,255,.1),
            transparent 28%
        ),
        radial-gradient(
            circle at 0 100%,
            rgba(156,108,255,.1),
            transparent 30%
        ),
        var(--bg);
}

button,
textarea{
    font:inherit;
}

button{
    cursor:pointer;
}

.app{
    height:100%;
    display:flex;
}

.sidebar{
    width:270px;
    flex:0 0 270px;
    padding:20px 15px;
    display:flex;
    flex-direction:column;
    border-right:1px solid var(--line);
    background:rgba(7,10,18,.82);
    backdrop-filter:blur(20px);
}

.brand{
    display:flex;
    gap:12px;
    align-items:center;
    padding:4px 8px 22px;
}

.brand-icon,
.welcome-icon{
    display:grid;
    place-items:center;
    color:var(--accent);
    background:
        linear-gradient(
            135deg,
            rgba(92,236,255,.1),
            rgba(156,108,255,.12)
        );
    border:1px solid rgba(92,236,255,.28);
}

.brand-icon{
    width:42px;
    height:42px;
    border-radius:14px;
}

.brand-name{
    font-size:15px;
    font-weight:900;
    letter-spacing:3px;
}

.brand-version{
    font-size:9px;
    color:var(--dim);
    font-weight:800;
    letter-spacing:1.5px;
    margin-top:3px;
}

.new-chat,
.side-button,
.quick-action,
.icon-button{
    color:var(--text);
    background:transparent;
    border:1px solid transparent;
    border-radius:12px;
    transition:.18s;
}

.new-chat{
    display:flex;
    gap:9px;
    align-items:center;
    width:100%;
    padding:12px;
    background:
        linear-gradient(
            135deg,
            rgba(92,236,255,.08),
            rgba(156,108,255,.08)
        );
    border-color:rgba(92,236,255,.24);
}

.new-chat:hover,
.side-button:hover,
.quick-action:hover,
.icon-button:hover{
    transform:translateY(-1px);
    border-color:rgba(92,236,255,.28);
    background:rgba(255,255,255,.04);
}

.sidebar-title{
    margin:28px 10px 9px;
    color:var(--dim);
    font-size:9px;
    font-weight:900;
    letter-spacing:1.7px;
}

.side-button{
    width:100%;
    display:flex;
    gap:11px;
    align-items:center;
    padding:10px 11px;
    color:var(--muted);
    text-align:left;
}

.side-button.active{
    color:var(--text);
    background:rgba(255,255,255,.035);
    border-color:var(--line);
}

.side-icon{
    width:20px;
    color:var(--dim);
    text-align:center;
}

.side-button.active .side-icon{
    color:var(--accent);
}

.sidebar-footer{
    margin-top:auto;
}

.system-status{
    display:flex;
    gap:10px;
    align-items:center;
    padding:12px;
    border:1px solid var(--line);
    border-radius:13px;
    background:rgba(255,255,255,.025);
}

.status-dot{
    width:8px;
    height:8px;
    border-radius:50%;
    background:var(--accent);
    box-shadow:0 0 12px var(--accent);
}

.system-status strong{
    display:block;
    font-size:11px;
}

.system-status small{
    display:block;
    margin-top:3px;
    color:var(--dim);
    font-size:9px;
}

.main{
    min-width:0;
    flex:1;
    display:flex;
    flex-direction:column;
}

.topbar{
    height:64px;
    flex:0 0 64px;
    display:flex;
    align-items:center;
    padding:0 24px;
    border-bottom:1px solid var(--line);
    background:rgba(7,10,18,.45);
    backdrop-filter:blur(18px);
}

.mobile-brand{
    display:none;
    font-size:13px;
    font-weight:900;
    letter-spacing:2px;
}

.topbar-right{
    margin-left:auto;
    display:flex;
    gap:10px;
    align-items:center;
}

.online{
    display:flex;
    gap:7px;
    align-items:center;
    color:var(--muted);
    font-size:11px;
}

.online-dot{
    width:6px;
    height:6px;
    border-radius:50%;
    background:var(--accent);
    box-shadow:0 0 10px var(--accent);
}

.online.offline .online-dot{
    background:var(--danger);
    box-shadow:none;
}

.icon-button{
    width:35px;
    height:35px;
    display:grid;
    place-items:center;
    color:var(--muted);
}

.chat{
    flex:1;
    overflow-y:auto;
    padding:34px 7%;
}

.welcome{
    max-width:800px;
    margin:7vh auto 0;
    text-align:center;
}

.welcome-icon{
    width:68px;
    height:68px;
    margin:0 auto 22px;
    border-radius:21px;
    font-size:28px;
}

.eyebrow{
    color:var(--accent);
    font-size:10px;
    font-weight:900;
    letter-spacing:3px;
}

h1{
    margin:12px 0 16px;
    font-size:clamp(42px,6vw,72px);
    line-height:.98;
    letter-spacing:-4px;
}

h1 span{
    background:
        linear-gradient(
            100deg,
            var(--accent),
            #fff 48%,
            var(--accent2)
        );
    color:transparent;
    -webkit-background-clip:text;
    background-clip:text;
}

.welcome-description{
    max-width:600px;
    margin:0 auto 28px;
    color:var(--muted);
    font-size:14px;
    line-height:1.7;
}

.quick-actions{
    display:flex;
    justify-content:center;
    gap:8px;
    flex-wrap:wrap;
}

.quick-action{
    display:flex;
    gap:8px;
    align-items:center;
    padding:9px 12px;
    color:#b7c0d0;
    background:rgba(255,255,255,.032);
    border-color:var(--line);
}

.quick-action span{
    color:var(--accent);
}

.message{
    max-width:850px;
    margin:0 auto 14px;
    padding:15px 17px;
    border-radius:16px;
    line-height:1.65;
}

.message.user{
    margin-right:0;
    background:
        linear-gradient(
            135deg,
            rgba(92,236,255,.07),
            rgba(156,108,255,.07)
        );
    border:1px solid rgba(92,236,255,.12);
}

.message.assistant{
    margin-left:0;
    background:rgba(255,255,255,.032);
    border:1px solid var(--line);
}

.message-label{
    margin-bottom:7px;
    color:var(--accent);
    font-size:9px;
    font-weight:900;
    letter-spacing:1.5px;
}

.search-results{
    display:grid;
    gap:8px;
    margin-top:14px;
}

.search-result{
    display:block;
    padding:13px;
    color:var(--text);
    text-decoration:none;
    background:rgba(0,0,0,.16);
    border:1px solid var(--line);
    border-radius:12px;
    transition:.18s;
}

.search-result:hover{
    transform:translateX(2px);
    border-color:rgba(92,236,255,.3);
}

.result-title{
    font-size:13px;
    font-weight:750;
}

.result-url{
    margin-top:4px;
    color:var(--accent);
    font-size:9px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}

.result-snippet{
    margin-top:7px;
    color:var(--muted);
    font-size:11px;
    line-height:1.55;
}

.meta{
    margin-top:9px;
    color:var(--dim);
    font-size:9px;
}

.composer-area{
    padding:0 7% 20px;
}

.composer{
    max-width:850px;
    margin:0 auto;
    display:flex;
    align-items:flex-end;
    gap:9px;
    padding:9px 9px 9px 16px;
    background:rgba(13,18,29,.93);
    border:1px solid rgba(255,255,255,.1);
    border-radius:17px;
    box-shadow:0 18px 65px rgba(0,0,0,.3);
}

#messageInput{
    flex:1;
    min-width:0;
    max-height:145px;
    resize:none;
    padding:8px 0;
    color:var(--text);
    background:transparent;
    border:0;
    outline:0;
    line-height:1.5;
}

#messageInput::placeholder{
    color:#687286;
}

.send-button{
    width:42px;
    height:42px;
    flex:0 0 42px;
    display:grid;
    place-items:center;
    color:#041016;
    background:
        linear-gradient(
            135deg,
            var(--accent),
            #b7fbff
        );
    border:0;
    border-radius:12px;
    font-size:21px;
    font-weight:900;
}

.send-button:disabled{
    opacity:.42;
    cursor:default;
}

.hint{
    max-width:850px;
    margin:7px auto 0;
    color:var(--dim);
    font-size:9px;
    text-align:center;
}

@media(max-width:760px){

    .sidebar{
        display:none;
    }

    .mobile-brand{
        display:block;
    }

    .topbar{
        height:58px;
        flex-basis:58px;
        padding:0 14px;
    }

    .chat{
        padding:24px 12px;
    }

    .welcome{
        margin-top:5vh;
    }

    h1{
        font-size:43px;
        letter-spacing:-2.5px;
    }

    .composer-area{
        padding:0 10px 12px;
    }

    .hint{
        display:none;
    }

    .message{
        padding:13px 14px;
    }
}

</style>

</head>

<body>

<div class="app">

<aside class="sidebar">

<div class="brand">

<div class="brand-icon">✦</div>

<div>

<div class="brand-name">
NEXORA
</div>

<div class="brand-version">
VERSION 10.0
</div>

</div>

</div>

<button
    class="new-chat"
    id="newChat"
>
＋ New conversation
</button>

<div class="sidebar-title">
WORKSPACE
</div>

<button
    class="side-button active"
>
<span class="side-icon">◈</span>
Assistant
</button>

<button
    class="side-button"
    id="searchShortcut"
>
<span class="side-icon">⌕</span>
Web search
</button>

<button
    class="side-button"
    id="calculatorShortcut"
>
<span class="side-icon">∑</span>
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
Advanced web filtering
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

<div
    class="online"
    id="onlineStatus"
>

<span class="online-dot"></span>

<span id="onlineText">
Connecting
</span>

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
NEXORA 10.0
</div>

<h1>
Intelligence,
<span>simplified.</span>
</h1>

<p class="welcome-description">
Advanced web search with parallel providers,
relevance scoring, duplicate removal,
source diversity, security filtering
and quality controls.
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

"use strict";

let csrfToken = "";
let sessionReady = false;

const chat =
    document.getElementById("chat");

const welcome =
    document.getElementById("welcome");

const input =
    document.getElementById("messageInput");

const sendButton =
    document.getElementById("sendButton");

const onlineStatus =
    document.getElementById("onlineStatus");

const onlineText =
    document.getElementById("onlineText");


function escapeHtml(value){

    return String(
        value ?? ""
    )
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#039;");
}


function formatText(value){

    return escapeHtml(value)
        .replace(
            /\*\*(.*?)\*\*/g,
            "<strong>$1</strong>"
        )
        .replace(
            /\n/g,
            "<br>"
        );
}


function scrollToBottom(){

    chat.scrollTo({
        top:chat.scrollHeight,
        behavior:"smooth"
    });
}


function addMessage(
    role,
    content,
    results=[],
    meta=""
){

    welcome.style.display = "none";

    const article =
        document.createElement("article");

    article.className =
        `message ${role}`;

    article.innerHTML =
        `<div class="message-label">
            ${role === "user" ? "YOU" : "NEXORA"}
        </div>
        <div>
            ${formatText(content)}
        </div>`;

    if(
        Array.isArray(results)
    ){

        const wrapper =
            document.createElement("div");

        wrapper.className =
            "search-results";

        results.forEach(
            result => {

                if(
                    !result
                    || typeof result !== "object"
                    || !/^https?:\/\//i.test(
                        result.url || ""
                    )
                ){
                    return;
                }

                const link =
                    document.createElement("a");

                link.className =
                    "search-result";

                link.href =
                    result.url;

                link.target =
                    "_blank";

                link.rel =
                    "noopener noreferrer";

                link.innerHTML =
                    `<div class="result-title"></div>
                     <div class="result-url"></div>
                     <div class="result-snippet"></div>`;

                link.children[0]
                    .textContent =
                    result.title ||
                    "Untitled result";

                link.children[1]
                    .textContent =
                    result.source ||
                    result.url;

                link.children[2]
                    .textContent =
                    result.snippet ||
                    "";

                wrapper.appendChild(
                    link
                );
            }
        );

        if(wrapper.children.length){
            article.appendChild(
                wrapper
            );
        }
    }

    if(meta){

        const metaElement =
            document.createElement("div");

        metaElement.className =
            "meta";

        metaElement.textContent =
            meta;

        article.appendChild(
            metaElement
        );
    }

    chat.appendChild(
        article
    );

    scrollToBottom();
}


function showTyping(){

    if(
        document.getElementById(
            "typing"
        )
    ){
        return;
    }

    const article =
        document.createElement("article");

    article.id =
        "typing";

    article.className =
        "message assistant";

    article.innerHTML =
        `<div class="message-label">
            NEXORA
        </div>
        <div>
            Working…
        </div>`;

    chat.appendChild(
        article
    );

    scrollToBottom();
}


function resizeInput(){

    input.style.height =
        "auto";

    input.style.height =
        Math.min(
            input.scrollHeight,
            145
        ) + "px";
}


function setOnline(
    online
){

    onlineStatus.classList.toggle(
        "offline",
        !online
    );

    onlineText.textContent =
        online
            ? "Online"
            : "Offline";
}


async function fetchApi(
    url,
    options={},
    timeout=15000
){

    const controller =
        new AbortController();

    const timer =
        setTimeout(
            () => controller.abort(),
            timeout
        );

    try{

        return await fetch(
            url,
            {
                ...options,
                signal:
                    controller.signal,
                credentials:
                    "same-origin"
            }
        );

    }finally{

        clearTimeout(
            timer
        );
    }
}


async function initialize(){

    try{

        const response =
            await fetchApi(
                "/api/session",
                {},
                5000
            );

        if(!response.ok){
            throw new Error(
                "Session initialization failed."
            );
        }

        const data =
            await response.json();

        csrfToken =
            data.csrf_token || "";

        sessionReady =
            Boolean(
                csrfToken
            );

        setOnline(
            sessionReady
        );

        await restoreHistory();

    }catch(error){

        setOnline(false);

        console.error(
            error
        );
    }
}


async function restoreHistory(){

    try{

        const response =
            await fetchApi(
                "/api/history",
                {},
                5000
            );

        if(!response.ok){
            return;
        }

        const data =
            await response.json();

        if(
            !Array.isArray(
                data.history
            )
            || !data.history.length
        ){
            return;
        }

        welcome.style.display =
            "none";

        data.history.forEach(
            item => {

                if(
                    item
                    && (
                        item.role === "user"
                        ||
                        item.role === "assistant"
                    )
                ){

                    addMessage(
                        item.role,
                        item.message || "",
                        item.results || [],
                        item.timestamp
                            ? new Date(
                                item.timestamp * 1000
                            ).toLocaleTimeString()
                            : ""
                    );
                }
            }
        );

    }catch(error){

        console.error(
            error
        );
    }
}


async function sendMessage(){

    const text =
        input.value.trim();

    if(
        !text
        || sendButton.disabled
        || !sessionReady
    ){
        return;
    }

    addMessage(
        "user",
        text
    );

    input.value = "";

    resizeInput();

    sendButton.disabled = true;

    showTyping();

    try{

        const response =
            await fetchApi(
                "/api/chat",
                {
                    method:"POST",

                    headers:{
                        "Content-Type":
                            "application/json",

                        "X-Nexora-CSRF":
                            csrfToken
                    },

                    body:JSON.stringify({
                        message:text
                    })
                },
                20000
            );

        let data = {};

        try{
            data =
                await response.json();
        }catch{
            data = {};
        }

        document
            .getElementById("typing")
            ?.remove();

        if(!response.ok){

            addMessage(
                "assistant",
                data.error?.message
                ||
                "The request failed."
            );

            return;
        }

        let meta =
            data.duration_ms
                ? `Completed in ${data.duration_ms} ms`
                : "";

        if(
            Array.isArray(
                data.providers
            )
            && data.providers.length
        ){

            meta +=
                ` · ${data.providers.join(", ")}`;
        }

        if(
            Number.isInteger(
                data.filtered
            )
            && data.filtered > 0
        ){

            meta +=
                ` · ${data.filtered} result(s) filtered`;
        }

        addMessage(
            "assistant",
            data.message
                || "No response returned.",
            data.results
                || [],
            meta
        );

    }catch(error){

        document
            .getElementById("typing")
            ?.remove();

        addMessage(
            "assistant",
            error.name === "AbortError"
                ? "The request timed out. Please try again."
                : "I couldn't connect to Nexora."
        );

        setOnline(false);

    }finally{

        sendButton.disabled =
            false;

        input.focus();
    }
}


async function clearHistory(){

    if(!sessionReady){
        return;
    }

    try{

        await fetchApi(
            "/api/history/clear",
            {
                method:"POST",
                headers:{
                    "X-Nexora-CSRF":
                        csrfToken
                }
            },
            5000
        );

    }catch{}

    chat
        .querySelectorAll(
            ".message"
        )
        .forEach(
            element =>
                element.remove()
        );

    welcome.style.display =
        "";

    input.value = "";

    resizeInput();

    input.focus();
}


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
                        button.dataset.prompt
                        || "";

                    resizeInput();

                    sendMessage();
                }
            );
        }
    );


document.getElementById(
    "searchShortcut"
).onclick = () => {

    input.value =
        "search ";

    resizeInput();

    input.focus();
};


document.getElementById(
    "calculatorShortcut"
).onclick = () => {

    input.value =
        "calculate ";

    resizeInput();

    input.focus();
};


document.getElementById(
    "newChat"
).onclick =
    clearHistory;


document.getElementById(
    "clearHistory"
).onclick =
    clearHistory;


input.oninput =
    resizeInput;


input.onkeydown =
    event => {

        if(
            event.key === "Enter"
            && !event.shiftKey
        ){

            event.preventDefault();

            sendMessage();
        }
    };


sendButton.onclick =
    sendMessage;


resizeInput();

initialize();

</script>

</body>

</html>
"""


# ============================================================
# HTTP SERVER HELPERS
# ============================================================

def client_ip(handler) -> str:

    value = handler.client_address[0]

    try:

        ipaddress.ip_address(value)

        return value

    except ValueError:

        return "unknown"


def make_cookie(sid: str) -> str:

    return (
        f"{SESSION_COOKIE}={sid}; "
        f"Max-Age={SESSION_MAX_AGE}; "
        "Path=/; "
        "HttpOnly; "
        "SameSite=Lax"
    )


# ============================================================
# REQUEST HANDLER
# ============================================================

class NexoraHandler(
    BaseHTTPRequestHandler
):

    server_version = (
        f"Nexora/{SERVER_VERSION}"
    )

    protocol_version = "HTTP/1.1"

    # --------------------------------------------------------
    # Connection control
    # --------------------------------------------------------

    def setup(self):

        super().setup()

        self.connection_ok = (
            connection_semaphore.acquire(
                timeout=2
            )
        )

        if not self.connection_ok:

            try:

                self.send_error(
                    503,
                    "Server is busy."
                )

            except Exception:
                pass

    def finish(self):

        try:

            super().finish()

        finally:

            if getattr(
                self,
                "connection_ok",
                False,
            ):

                connection_semaphore.release()

                self.connection_ok = False

    # --------------------------------------------------------
    # Session
    # --------------------------------------------------------

    def _session(self):

        sid = None

        cookie_header = (
            self.headers.get(
                "Cookie",
                ""
            )
        )

        for item in cookie_header.split(";"):

            name, separator, value = (
                item.strip().partition("=")
            )

            if (
                separator
                and name == SESSION_COOKIE
            ):

                sid = value.strip()

                break

        return sessions.get_or_create(
            sid
        )

    # --------------------------------------------------------
    # Security headers
    # --------------------------------------------------------

    def _headers(
        self,
        content_type,
        length,
        sid=None,
    ):

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(length),
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
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )

        self.send_header(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'self'; "
                "base-uri 'none'; "
                "form-action 'self'"
            ),
        )

        if sid:

            self.send_header(
                "Set-Cookie",
                make_cookie(sid),
            )

    # --------------------------------------------------------
    # JSON response
    # --------------------------------------------------------

    def send_json(
        self,
        status,
        data,
        sid=None,
    ):

        body = json_bytes(
            data
        )

        try:

            self.send_response(
                status
            )

            self._headers(
                "application/json; charset=utf-8",
                len(body),
                sid,
            )

            self.end_headers()

            self.wfile.write(
                body
            )

        except (
            BrokenPipeError,
            ConnectionResetError,
        ):
            pass

    # --------------------------------------------------------
    # HTML response
    # --------------------------------------------------------

    def send_html(
        self,
        text,
        sid=None,
    ):

        body = text.encode(
            "utf-8"
        )

        try:

            self.send_response(
                200
            )

            self._headers(
                "text/html; charset=utf-8",
                len(body),
                sid,
            )

            self.end_headers()

            self.wfile.write(
                body
            )

        except (
            BrokenPipeError,
            ConnectionResetError,
        ):
            pass

    # --------------------------------------------------------
    # Rate limiting
    # --------------------------------------------------------

    def _rate(
        self,
        search=False,
    ):

        prefix = (
            "search"
            if search
            else "general"
        )

        key = (
            f"{client_ip(self)}:"
            f"{prefix}"
        )

        return rate_limiter.allow(
            key,
            (
                SEARCH_RATE_MAX
                if search
                else RATE_MAX_REQUESTS
            ),
        )

    # --------------------------------------------------------
    # Same-origin protection
    # --------------------------------------------------------

    def _same_origin(self):

        origin = self.headers.get(
            "Origin"
        )

        if not origin:
            return True

        try:

            parsed = urlparse(
                origin
            )

            origin_host = (
                parsed.hostname
                or ""
            ).lower()

            host_header = (
                self.headers.get(
                    "Host",
                    ""
                )
                .split(":", 1)[0]
                .lower()
            )

            return (
                origin_host
                == host_header
            )

        except Exception:

            return False

    # --------------------------------------------------------
    # CSRF
    # --------------------------------------------------------

    def _csrf(self, state):

        token = self.headers.get(
            "X-Nexora-CSRF",
            ""
        )

        if not token:
            return False

        try:

            return secrets.compare_digest(
                token,
                state.csrf_token,
            )

        except (
            TypeError,
            ValueError,
        ):

            return False

    # --------------------------------------------------------
    # JSON request body
    # --------------------------------------------------------

    def _body(self):

        content_type = (
            self.headers.get(
                "Content-Type",
                ""
            )
            .lower()
        )

        if not content_type.startswith(
            "application/json"
        ):

            self.send_json(
                415,
                {
                    "success": False,
                    "error": {
                        "message":
                            "Content-Type must be application/json."
                    },
                },
            )

            return None

        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

        except ValueError:

            content_length = -1

        if content_length <= 0:

            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "message":
                            "Request body cannot be empty."
                    },
                },
            )

            return None

        if content_length > MAX_REQUEST_SIZE:

            self.send_json(
                413,
                {
                    "success": False,
                    "error": {
                        "message":
                            "Request is too large."
                    },
                },
            )

            return None

        try:

            raw = self.rfile.read(
                content_length
            )

            data = json.loads(
                raw.decode(
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
                    "success": False,
                    "error": {
                        "message":
                            "Invalid JSON."
                    },
                },
            )

            return None

        if not isinstance(
            data,
            dict,
        ):

            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "message":
                            "JSON body must be an object."
                    },
                },
            )

            return None

        return data

    # ========================================================
    # OPTIONS
    # ========================================================

    def do_OPTIONS(self):

        self.send_response(
            204
        )

        self.send_header(
            "Allow",
            ALLOWED_METHODS,
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            ALLOWED_METHODS,
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Nexora-CSRF",
        )

        self.send_header(
            "Content-Length",
            "0",
        )

        self.end_headers()

    # ========================================================
    # GET
    # ========================================================

    def do_GET(self):

        path = urlparse(
            self.path
        ).path

        # ----------------------------------------------------
        # Main UI
        # ----------------------------------------------------

        if path in {
            "/",
            "/index.html",
        }:

            sid, _ = self._session()

            self.send_html(
                INDEX_HTML,
                sid,
            )

            return

        # ----------------------------------------------------
        # Health
        # ----------------------------------------------------

        if path == "/health":

            self.send_json(
                200,
                {
                    "success": True,
                    "status": "healthy",
                    "service": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "uptime_seconds": round(
                        time.monotonic()
                        - START_MONOTONIC,
                        2,
                    ),
                    "api_key_required": False,
                },
            )

            return

        # ----------------------------------------------------
        # API info
        # ----------------------------------------------------

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
                        "parallel_web_search",
                        "provider_fallback",
                        "advanced_filtering",
                        "relevance_ranking",
                        "url_security",
                        "deduplication",
                        "domain_diversity",
                        "search_cache",
                        "calculator",
                        "history",
                        "csrf",
                        "rate_limiting",
                        "health",
                    ],
                },
            )

            return

        # ----------------------------------------------------
        # Session
        # ----------------------------------------------------

        if path == "/api/session":

            sid, state = (
                self._session()
            )

            self.send_json(
                200,
                {
                    "success": True,
                    "csrf_token":
                        state.csrf_token,
                    "version":
                        SERVER_VERSION,
                },
                sid,
            )

            return

        # ----------------------------------------------------
        # History
        # ----------------------------------------------------

        if path == "/api/history":

            sid, state = (
                self._session()
            )

            self.send_json(
                200,
                {
                    "success": True,
                    "history":
                        list(state.history),
                },
                sid,
            )

            return

        # ----------------------------------------------------
        # Direct search API
        # ----------------------------------------------------

        if path == "/api/search":

            if not self._rate(
                search=True
            ):

                self.send_json(
                    429,
                    {
                        "success": False,
                        "error": {
                            "message":
                                "Too many search requests. Try again shortly."
                        },
                    },
                )

                return

            query_values = parse_qs(
                urlparse(
                    self.path
                ).query
            ).get(
                "q",
                [""],
            )

            query = normalize_search_query(
                query_values[0]
            )

            if not query:

                self.send_json(
                    400,
                    {
                        "success": False,
                        "error": {
                            "message":
                                "Missing search query."
                        },
                    },
                )

                return

            started = time.monotonic()

            data = search_web(
                query
            )

            duration = round(
                (
                    time.monotonic()
                    - started
                ) * 1000
            )

            self.send_json(
                200,
                {
                    "success": True,
                    "query": query,
                    **data,
                    "duration_ms":
                        duration,
                },
            )

            return

        # ----------------------------------------------------
        # Unknown route
        # ----------------------------------------------------

        self.send_json(
            404,
            {
                "success": False,
                "error": {
                    "message":
                        "Route not found."
                },
            },
        )

    # ========================================================
    # POST
    # ========================================================

    def do_POST(self):

        if not self._rate():

            self.send_json(
                429,
                {
                    "success": False,
                    "error": {
                        "message":
                            "Too many requests. Try again shortly."
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
                        "message":
                            "Request origin is not allowed."
                    },
                },
            )

            return

        sid, state = (
            self._session()
        )

        if not self._csrf(state):

            self.send_json(
                403,
                {
                    "success": False,
                    "error": {
                        "message":
                            "Invalid CSRF token."
                    },
                },
                sid,
            )

            return

        path = urlparse(
            self.path
        ).path

        # ----------------------------------------------------
        # Clear history
        # ----------------------------------------------------

        if path == "/api/history/clear":

            state.history.clear()

            self.send_json(
                200,
                {
                    "success": True
                },
                sid,
            )

            return

        # ----------------------------------------------------
        # Chat endpoint
        # ----------------------------------------------------

        if path != "/api/chat":

            self.send_json(
                404,
                {
                    "success": False,
                    "error": {
                        "message":
                            "Route not found."
                    },
                },
                sid,
            )

            return

        payload = self._body()

        if payload is None:
            return

        message = payload.get(
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
                    "success": False,
                    "error": {
                        "message":
                            "Message must be text."
                    },
                },
                sid,
            )

            return

        message = message.strip()

        if not message:

            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "message":
                            "Message cannot be empty."
                    },
                },
                sid,
            )

            return

        if len(message) > MAX_MESSAGE_LENGTH:

            self.send_json(
                400,
                {
                    "success": False,
                    "error": {
                        "message":
                            "Message is too long."
                    },
                },
                sid,
            )

            return

        # ----------------------------------------------------
        # Store user message
        # ----------------------------------------------------

        state.history.append(
            {
                "role": "user",
                "message": message,
                "type": "chat",
                "timestamp":
                    time.time(),
            }
        )

        # ----------------------------------------------------
        # Generate response
        # ----------------------------------------------------

        try:

            result = assistant_response(
                message
            )

        except Exception:

            logger.exception(
                "Assistant error"
            )

            result = {
                "type": "error",
                "message":
                    "Nexora encountered an internal error.",
            }

        # ----------------------------------------------------
        # Store assistant message
        # ----------------------------------------------------

        entry = {
            "role": "assistant",
            "message": clamp_text(
                str(
                    result.get(
                        "message",
                        "",
                    )
                ),
                MAX_MESSAGE_LENGTH,
            ),
            "type": str(
                result.get(
                    "type",
                    "chat",
                )
            ),
            "timestamp":
                time.time(),
        }

        if result.get(
            "results"
        ):

            entry["results"] = (
                result["results"]
            )

        state.history.append(
            entry
        )

        result["success"] = True

        self.send_json(
            200,
            result,
            sid,
        )

    # ========================================================
    # Logging
    # ========================================================

    def log_message(
        self,
        fmt,
        *args,
    ):

        logger.info(
            "%s - %s",
            client_ip(self),
            fmt % args,
        )


# ============================================================
# GRACEFUL SHUTDOWN
# ============================================================

def shutdown_server(
    signum=None,
    frame=None,
):

    global server

    if server is None:
        return

    logger.info(
        "Shutdown signal received."
    )

    threading.Thread(
        target=server.shutdown,
        daemon=True,
    ).start()


# ============================================================
# STARTUP
# ============================================================

def startup():

    global server

    logger.info(
        "Starting %s %s",
        SERVER_NAME,
        SERVER_VERSION,
    )

    try:

        server = ThreadingHTTPServer(
            (
                HOST,
                PORT,
            ),
            NexoraHandler,
        )

        server.daemon_threads = True

        server.request_queue_size = 64

        logger.info(
            "Nexora listening on %s:%s",
            HOST,
            PORT,
        )

        server.serve_forever(
            poll_interval=0.5
        )

    except OSError:

        logger.exception(
            "Could not start server."
        )

        raise

    finally:

        if server is not None:

            try:
                server.server_close()
            except Exception:
                pass

            server = None

        logger.info(
            "Nexora stopped."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        signal.signal(
            signal.SIGTERM,
            shutdown_server,
        )

        signal.signal(
            signal.SIGINT,
            shutdown_server,
        )

    except (
        ValueError,
        OSError,
    ):

        pass

    startup()

