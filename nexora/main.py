

# ============================================================
# NEXORA
# Expert-Level Personal AI Assistant
# Single-file version
# No external packages required
# ============================================================

from __future__ import annotations

import html
import json
import logging
import math
import os
import random
import re
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen


# ============================================================
# CONFIGURATION
# ============================================================

APP_NAME = "Nexora"
VERSION = "11.0"

SEARCH_URL = "https://html.duckduckgo.com/html/?q={}"

MAX_QUERY_LENGTH = 300
MAX_RESULTS = 8
FINAL_SOURCE_COUNT = 3

REQUEST_TIMEOUT = 10
MAX_PAGE_BYTES = 1_500_000

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; NexoraWebSearch/11.0; +https://example.com/nexora)"
)

CACHE_SIZE = 128
CACHE_TTL = 300

LOG_LEVEL = logging.INFO


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(APP_NAME)


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    domain: str
    score: float = 0.0

    def to_dict(self):
        return asdict(self)


@dataclass
class Source:
    title: str
    url: str
    domain: str

    def to_dict(self):
        return asdict(self)


@dataclass
class NexoraResponse:
    answer: str
    sources: list[Source]
    searched: bool
    query: str | None = None

    def to_dict(self):
        return {
            "answer": self.answer,
            "sources": [s.to_dict() for s in self.sources],
            "searched": self.searched,
            "query": self.query,
        }


# ============================================================
# GENERAL UTILITIES
# ============================================================

def clean_text(value: str) -> str:
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_text(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def tokenize(value: str) -> list[str]:
    return normalize_text(value).split()


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# HTML PARSER
# ============================================================

class TextExtractor(HTMLParser):
    """
    Small, dependency-free HTML-to-text extractor.
    """

    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "main",
        "header",
        "footer",
        "li",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }

    IGNORE_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "iframe",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignore_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag in self.IGNORE_TAGS:
            self.ignore_depth += 1

        if tag in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag in self.IGNORE_TAGS and self.ignore_depth:
            self.ignore_depth -= 1

        if tag in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        if self.ignore_depth:
            return

        if data:
            self.parts.append(data)

    def text(self) -> str:
        return clean_text(" ".join(self.parts))


# ============================================================
# HTTP
# ============================================================

def http_get(
    url: str,
    timeout: int = REQUEST_TIMEOUT,
) -> str | None:

    if not valid_http_url(url):
        return None

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")

            if (
                "text/html" not in content_type
                and "application/xhtml+xml" not in content_type
            ):
                return None

            data = response.read(MAX_PAGE_BYTES)

            encoding = response.headers.get_content_charset() or "utf-8"

            return data.decode(
                encoding,
                errors="replace",
            )

    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logger.debug("HTTP failure for %s: %s", url, exc)
        return None


# ============================================================
# SEARCH ENGINE
# ============================================================

def parse_search_results(page: str) -> list[SearchResult]:
    """
    Extract DuckDuckGo HTML search results.

    This intentionally extracts only the useful fields instead
    of returning raw search-engine HTML.
    """

    if not page:
        return []

    results: list[SearchResult] = []

    # DuckDuckGo result blocks.
    blocks = re.findall(
        r'<div[^>]+class="result[^"]*"[^>]*>(.*?)</div>\s*</div>',
        page,
        flags=re.I | re.S,
    )

    if not blocks:
        # More tolerant fallback.
        blocks = re.findall(
            r'<div[^>]+class="result[^"]*"[^>]*>(.*?)'
            r'(?=<div[^>]+class="result|</body>)',
            page,
            flags=re.I | re.S,
        )

    for block in blocks:

        link_match = re.search(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>'
            r'(.*?)</a>',
            block,
            flags=re.I | re.S,
        )

        if not link_match:
            continue

        url = html.unescape(link_match.group(1))
        title = clean_text(
            re.sub(
                r"<[^>]+>",
                " ",
                link_match.group(2),
            )
        )

        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</',
            block,
            flags=re.I | re.S,
        )

        snippet = ""

        if snippet_match:
            snippet = clean_text(
                re.sub(
                    r"<[^>]+>",
                    " ",
                    snippet_match.group(1),
                )
            )

        if not valid_http_url(url):
            continue

        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                domain=domain_of(url),
            )
        )

    return results


# ============================================================
# SEARCH CACHE
# ============================================================

_SEARCH_CACHE: dict[str, tuple[float, list[SearchResult]]] = {}
_CACHE_LOCK = threading.Lock()


def cached_results(query: str) -> list[SearchResult] | None:

    key = normalize_text(query)

    with _CACHE_LOCK:
        entry = _SEARCH_CACHE.get(key)

        if not entry:
            return None

        timestamp, results = entry

        if time.time() - timestamp > CACHE_TTL:
            del _SEARCH_CACHE[key]
            return None

        return list(results)


def store_results(
    query: str,
    results: list[SearchResult],
) -> None:

    key = normalize_text(query)

    with _CACHE_LOCK:
        _SEARCH_CACHE[key] = (
            time.time(),
            list(results),
        )

        # Simple memory protection.
        if len(_SEARCH_CACHE) > CACHE_SIZE:
            oldest_key = min(
                _SEARCH_CACHE,
                key=lambda k: _SEARCH_CACHE[k][0],
            )
            _SEARCH_CACHE.pop(oldest_key, None)


# ============================================================
# SEARCH
# ============================================================

def raw_search(query: str) -> list[SearchResult]:

    query = clean_text(query)[:MAX_QUERY_LENGTH]

    if not query:
        return []

    cached = cached_results(query)

    if cached is not None:
        return cached

    encoded = quote_plus(query)

    url = SEARCH_URL.format(encoded)

    page = http_get(url)

    results = parse_search_results(page or "")

    store_results(query, results)

    return results


# ============================================================
# SEARCH FILTERING
# ============================================================

LOW_VALUE_DOMAINS = {
    "pinterest.com",
    "quora.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
}

HIGH_VALUE_DOMAINS = {
    "premierleague.com",
    "bbc.co.uk",
    "bbc.com",
    "skysports.com",
    "theguardian.com",
    "reuters.com",
    "espn.com",
    "uefa.com",
    "fifa.com",
    "gov.uk",
    "wikipedia.org",
}


def keyword_overlap(
    query: str,
    result: SearchResult,
) -> float:

    query_words = set(tokenize(query))

    if not query_words:
        return 0.0

    result_words = set(
        tokenize(
            f"{result.title} {result.snippet}"
        )
    )

    overlap = query_words & result_words

    return len(overlap) / len(query_words)


def score_result(
    query: str,
    result: SearchResult,
) -> float:

    score = 0.0

    q = normalize_text(query)

    title = normalize_text(result.title)
    snippet = normalize_text(result.snippet)
    domain = result.domain

    # Keyword relevance.
    score += keyword_overlap(query, result) * 60

    # Exact phrase bonus.
    if q and q in title:
        score += 25

    if q and q in snippet:
        score += 10

    # Trusted sources.
    if domain in HIGH_VALUE_DOMAINS:
        score += 15

    # Low-value sources.
    if domain in LOW_VALUE_DOMAINS:
        score -= 20

    # Prefer results that actually contain text.
    if len(result.snippet) >= 80:
        score += 5

    if len(result.title) >= 10:
        score += 2

    return score


def deduplicate_results(
    results: list[SearchResult],
) -> list[SearchResult]:

    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    output: list[SearchResult] = []

    for result in results:

        normalized_url = result.url.rstrip("/").lower()
        normalized_title = normalize_text(result.title)

        if normalized_url in seen_urls:
            continue

        if normalized_title and normalized_title in seen_titles:
            continue

        seen_urls.add(normalized_url)

        if normalized_title:
            seen_titles.add(normalized_title)

        output.append(result)

    return output


def filter_and_rank(
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:

    filtered = []

    for result in results:

        if not valid_http_url(result.url):
            continue

        result.score = score_result(
            query,
            result,
        )

        # Reject extremely irrelevant results.
        if result.score < 5:
            continue

        filtered.append(result)

    filtered = deduplicate_results(filtered)

    filtered.sort(
        key=lambda result: result.score,
        reverse=True,
    )

    return filtered


# ============================================================
# WEB SEARCH PIPELINE
# ============================================================

def search_web(
    query: str,
) -> list[SearchResult]:

    logger.info("Searching web: %s", query)

    raw_results = raw_search(query)

    if not raw_results:
        return []

    ranked = filter_and_rank(
        query,
        raw_results,
    )

    return ranked[:MAX_RESULTS]


# ============================================================
# PAGE EXTRACTION
# ============================================================

def extract_page_text(url: str) -> str:

    page = http_get(url)

    if not page:
        return ""

    parser = TextExtractor()

    try:
        parser.feed(page)
        parser.close()
    except Exception as exc:
        logger.debug(
            "HTML parsing failed for %s: %s",
            url,
            exc,
        )
        return ""

    return parser.text()


def useful_sentences(
    text: str,
    query: str,
    limit: int = 5,
) -> list[str]:

    if not text:
        return []

    sentences = re.split(
        r"(?<=[.!?])\s+",
        clean_text(text),
    )

    query_words = set(tokenize(query))

    scored = []

    for sentence in sentences:

        sentence = clean_text(sentence)

        if len(sentence) < 35:
            continue

        words = set(tokenize(sentence))

        overlap = len(
            words & query_words
        )

        score = overlap

        if len(sentence) > 500:
            score -= 1

        scored.append(
            (
                score,
                sentence,
            )
        )

    scored.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return [
        sentence
        for _, sentence in scored[:limit]
    ]


# ============================================================
# SEARCH INTENT
# ============================================================

CURRENT_TERMS = {
    "today",
    "tonight",
    "latest",
    "current",
    "currently",
    "now",
    "recent",
    "recently",
    "this week",
    "this season",
    "2026",
    "2027",
    "score",
    "scores",
    "fixture",
    "fixtures",
    "standings",
    "table",
    "transfer",
    "transfers",
    "injury",
    "injuries",
    "news",
    "result",
    "results",
}


def needs_web_search(text: str) -> bool:

    normalized = normalize_text(text)

    # Explicit request.
    explicit = (
        "search the web",
        "look it up",
        "look online",
        "search online",
        "google it",
        "find online",
        "what's happening",
        "what is happening",
    )

    if any(
        phrase in normalized
        for phrase in explicit
    ):
        return True

    # Current-information questions.
    if any(
        term in normalized
        for term in CURRENT_TERMS
    ):
        return True

    # Questions where fresh information is normally essential.
    if re.search(
        r"\b(who|what|where|when)\b.*\b("
        r"latest|current|now|today|recent"
        r")\b",
        normalized,
    ):
        return True

    return False


# ============================================================
# FOOTBALL KNOWLEDGE
# ============================================================

FOOTBALL_KNOWLEDGE = {

    "football": {
        "description": (
            "Football is a team sport played between two teams "
            "of eleven players. The objective is to score more "
            "goals than the opponent."
        ),
        "terms": {
            "goal": "A goal is scored when the ball completely crosses the goal line.",
            "offside": (
                "Offside is a positional offence involving an attacking "
                "player being ahead of the relevant second-last defender "
                "when a teammate plays the ball, subject to the laws."
            ),
            "penalty": (
                "A penalty kick is awarded for certain direct-free-kick "
                "offences committed by a defending player inside their own penalty area."
            ),
            "corner": (
                "A corner kick is awarded when the ball completely crosses "
                "the goal line after touching a defending player, without a goal being scored."
            ),
        },
    },

    "premier_league": {
        "description": (
            "The Premier League is England's top men's football league. "
            "It operates as a 20-team league, with clubs playing each other "
            "home and away."
        ),
        "clubs": [
            "Arsenal",
            "Aston Villa",
            "Bournemouth",
            "Brentford",
            "Brighton",
            "Burnley",
            "Chelsea",
            "Crystal Palace",
            "Everton",
            "Fulham",
            "Leeds United",
            "Liverpool",
            "Manchester City",
            "Manchester United",
            "Newcastle United",
            "Nottingham Forest",
            "Sunderland",
            "Tottenham Hotspur",
            "West Ham United",
            "Wolverhampton Wanderers",
        ],
    },

    "positions": {
        "GK": "Goalkeeper",
        "CB": "Centre-back",
        "LB": "Left-back",
        "RB": "Right-back",
        "DM": "Defensive midfielder",
        "CM": "Central midfielder",
        "AM": "Attacking midfielder",
        "LW": "Left winger",
        "RW": "Right winger",
        "ST": "Striker",
    },

    "clubs": {
        "arsenal": {
            "nickname": "The Gunners",
            "stadium": "Emirates Stadium",
        },
        "aston villa": {
            "nickname": "Villa",
            "stadium": "Villa Park",
        },
        "chelsea": {
            "nickname": "The Blues",
            "stadium": "Stamford Bridge",
        },
        "liverpool": {
            "nickname": "The Reds",
            "stadium": "Anfield",
        },
        "manchester united": {
            "nickname": "The Red Devils",
            "stadium": "Old Trafford",
        },
        "manchester city": {
            "nickname": "City",
            "stadium": "Etihad Stadium",
        },
        "tottenham": {
            "nickname": "Spurs",
            "stadium": "Tottenham Hotspur Stadium",
        },
    },
}


# ============================================================
# JOKE DATABASE
# ============================================================

JOKES = [

    # Football jokes
    "How many Everton fans does it take to screw in a light bulb? None — they're quite happy living in the shadows.",

    "What's the difference between Leeds United and a tea bag? The tea bag stays in the cup for longer.",

    "What does a West Ham United fan do after winning the Premier League? Turn off the Xbox.",

    "My mate left two Manchester United tickets on his car dashboard. Someone smashed the window and left a couple more!",

    "What's the difference between the Invisible Man and Fulham? You've got more chance of seeing the Invisible Man at a cup final.",

    "What is the difference between Tottenham and a triangle? A triangle has three points.",

    "Why is Old Trafford the best place to go during a thunderstorm? There's absolutely no chance of any silverware striking there.",

    "Why does the Arsenal manager only drink tea? Because he can't find a cup.",

    "What do Chelsea FC and a broken pencil have in common? They both have no point, and they're incredibly expensive to replace.",

    "Why do Liverpool fans never hide and seek? Because they spend all their time talking about where they used to be.",

    "Who is the slipperiest footballer on the planet? Antoine Grease-man.",

    "Which striker comes from a funny country? Erling Ha-Ha-Land.",

    "Which defender takes a long time to fall? Jurrien Timberrrrr!",

    "Why isn't Ange Postecoglou allowed to keep a dog? Because he can't keep hold of a lead.",

    "Who is the most self-obsessed Premier League player? Ben Mee.",

    "I didn't do very well in my football teamwork exam... I didn't pass!",

    "Playing football is addictive and I want to stop, but I just can't seem to kick the habit.",

    "My girlfriend is the star goalie of her local football team... she's a keeper.",

    "A wife says to her husband: 'Choose, it's either me or football.' The husband responds: 'Give me 90 minutes to think.'",

    "My dad was renowned for 'thinking outside of the box'. Great guy, but a terrible goalkeeper.",

    "Harry Kane went to a bakery and asked for a trophy. The baker said, 'Sorry, we only make things with fillings, not empty shelves.'",

    "Why does Romelu Lukaku wear such large boots? To accommodate his first touch, which always bounces five yards away.",

    "What is the difference between Darwin Nunez and a UFO? People actually claim to have seen a UFO hit its target.",

    "Why did Antony get lost on his way to training? He could only make right turns.",

    "Todd Boehly went to a library and tried to buy the building just because he liked one book.",

    # General jokes
    "Did you get a haircut? No, I got them all cut.",

    "Did you hear about the restaurant on the moon? Great food, no atmosphere.",

    "My dentist told me I need a crown. I said, 'I know, right? Finally, someone recognizes my royalty!'",

    "I excel at spreadsheets. Tom Microsoft Word.",

    "I ate a clock yesterday. It was very time-consuming.",

    "Velcro... what a rip-off.",

    "I love elevators. They are just so uplifting.",

    "Why did the scarecrow win an award? Because he was outstanding in his field.",

    "Why don't skeletons fight each other? They don't have the guts.",

    "What do you call cheese that isn't yours? Nacho cheese.",

    "Why was the math book sad? It had too many problems.",

    "What did the ocean say to the beach? Nothing, it just waved.",

    "Why can't you trust atoms? Because they make up everything.",

    "I told my doctor that I broke my arm in two places. He told me to stop going to those places.",

    "I'm reading a book on anti-gravity. I just can't put it down.",

    "My wife told me to stop impersonating a flamingo. I had to put my foot down.",
]


# ============================================================
# JOKE ENGINE
# ============================================================

def get_joke(
    football_only: bool = False,
) -> str:

    if football_only:

        football = [
            joke
            for joke in JOKES
            if any(
                word in normalize_text(joke)
                for word in (
                    "football",
                    "premier",
                    "arsenal",
                    "liverpool",
                    "chelsea",
                    "tottenham",
                    "united",
                    "leeds",
                    "everton",
                    "west ham",
                    "kane",
                    "nunez",
                    "lukaku",
                    "grealish",
                    "boehly",
                    "scarecrow",
                )
            )
        ]

        if football:
            return random.choice(football)

    return random.choice(JOKES)


# ============================================================
# NATURAL LANGUAGE HELPERS
# ============================================================

def is_joke_request(text: str) -> bool:

    normalized = normalize_text(text)

    keywords = (
        "tell me a joke",
        "tell me another joke",
        "make me laugh",
        "give me a joke",
        "football joke",
        "premier league joke",
    )

    return any(
        keyword in normalized
        for keyword in keywords
    )


def is_football_request(text: str) -> bool:

    normalized = normalize_text(text)

    football_terms = {
        "football",
        "soccer",
        "premier league",
        "arsenal",
        "chelsea",
        "liverpool",
        "manchester united",
        "manchester city",
        "tottenham",
        "aston villa",
        "everton",
        "leeds",
        "newcastle",
        "west ham",
        "champions league",
        "fa cup",
        "europa league",
        "goalkeeper",
        "striker",
        "midfielder",
        "defender",
    }

    return any(
        term in normalized
        for term in football_terms
    )


def casual_answer(text: str) -> str | None:

    normalized = normalize_text(text)

    greetings = {
        "hi",
        "hello",
        "hey",
        "yo",
        "hiya",
        "sup",
    }

    if normalized in greetings:
        return random.choice(
            [
                "Yo! Nexora online. What's up? 😎",
                "Hey! What are we cooking today?",
                "Hello! I'm ready. Hit me with it.",
            ]
        )

    if normalized in {
        "thanks",
        "thank you",
        "cheers",
    }:
        return random.choice(
            [
                "No problem! 😎",
                "Anytime.",
                "You've got it.",
            ]
        )

    return None


# ============================================================
# FOOTBALL ANSWERS
# ============================================================

def football_knowledge_answer(
    question: str,
) -> str | None:

    normalized = normalize_text(question)

    # Premier League.
    if (
        "what is the premier league" in normalized
        or "tell me about the premier league" in normalized
    ):
        return (
            "The Premier League is England's top men's football league. "
            "It has 20 clubs playing home and away, with three points for "
            "a win, one for a draw and zero for a defeat."
        )

    # Positions.
    for abbreviation, full_name in FOOTBALL_KNOWLEDGE[
        "positions"
    ].items():

        if normalized == abbreviation.lower():
            return f"{abbreviation} means {full_name}."

    # Club information.
    for club, info in FOOTBALL_KNOWLEDGE[
        "clubs"
    ].items():

        if club in normalized:

            if "stadium" in normalized:
                return (
                    f"{club.title()} play at "
                    f"{info['stadium']}."
                )

            if "nickname" in normalized:
                return (
                    f"{club.title()} are commonly known as "
                    f"{info['nickname']}."
                )

    # Football rules.
    for term, explanation in FOOTBALL_KNOWLEDGE[
        "football"
    ]["terms"].items():

        if normalized == term:
            return explanation

    return None


# ============================================================
# SOURCE SUMMARISER
# ============================================================

def build_evidence(
    query: str,
    results: list[SearchResult],
) -> list[dict]:

    evidence = []

    # We inspect only the strongest results.
    for result in results[:3]:

        page_text = extract_page_text(
            result.url
        )

        sentences = useful_sentences(
            page_text or result.snippet,
            query,
            limit=4,
        )

        evidence.append(
            {
                "title": result.title,
                "url": result.url,
                "domain": result.domain,
                "snippet": result.snippet,
                "sentences": sentences,
                "score": result.score,
            }
        )

    return evidence


def summarise_evidence(
    query: str,
    results: list[SearchResult],
) -> str:

    if not results:
        return ""

    evidence = build_evidence(
        query,
        results,
    )

    # Collect unique useful sentences.
    statements: list[str] = []
    seen: set[str] = set()

    for item in evidence:

        candidates = item["sentences"]

        if not candidates:
            candidates = [
                item["snippet"]
            ]

        for sentence in candidates:

            sentence = clean_text(sentence)

            key = normalize_text(sentence)

            if not key:
                continue

            if key in seen:
                continue

            seen.add(key)
            statements.append(sentence)

    if not statements:
        return (
            "I found some relevant pages, but they didn't "
            "give me enough readable information to confidently "
            "summarise them."
        )

    # Keep the response human-sized.
    statements = statements[:5]

    if len(statements) == 1:
        return statements[0]

    return " ".join(statements)


# ============================================================
# NATURAL SEARCH RESPONSE
# ============================================================

def natural_search_response(
    question: str,
    results: list[SearchResult],
) -> NexoraResponse:

    if not results:

        return NexoraResponse(
            answer=(
                "I couldn't find anything useful enough to "
                "give you a reliable answer. Try rewording "
                "the question and I'll have another crack at it."
            ),
            sources=[],
            searched=True,
            query=question,
        )

    summary = summarise_evidence(
        question,
        results,
    )

    # --------------------------------------------------------
    # THIS IS THE IMPORTANT PART:
    #
    # Search results are NOT dumped into the response.
    # Nexora summarises them first.
    # Then only the best 1–3 sources are exposed.
    # --------------------------------------------------------

    selected_sources = []

    for result in results[:FINAL_SOURCE_COUNT]:

        selected_sources.append(
            Source(
                title=result.title,
                url=result.url,
                domain=result.domain,
            )
        )

    answer = (
        "Here's what I found:\n\n"
        f"{summary}"
    )

    return NexoraResponse(
        answer=answer,
        sources=selected_sources,
        searched=True,
        query=question,
    )


# ============================================================
# RESPONSE FORMATTER
# ============================================================

def format_response(
    response: NexoraResponse,
) -> str:

    output = response.answer.strip()

    if response.sources:

        output += "\n\nSources:\n"

        # Equivalent to:
        #
        # results.slice(0, 3).forEach(...)
        #
        # in JavaScript.
        #
        # Python's equivalent is:
        #
        # for source in sources[:3]:

        for index, source in enumerate(
            response.sources[:3],
            start=1,
        ):

            output += (
                f"{index}. {source.title} "
                f"({source.domain})\n"
                f"   {source.url}\n"
            )

    return output


# ============================================================
# QUERY CLEANING
# ============================================================

def clean_query(question: str) -> str:

    question = clean_text(question)

    # Remove accidental command-like prefixes.
    question = re.sub(
        r"^(please\s+)?(search|look up)\s+",
        "",
        question,
        flags=re.I,
    )

    return question[:MAX_QUERY_LENGTH]


# ============================================================
# NEXORA CORE
# ============================================================

class Nexora:

    def __init__(self):

        self.name = APP_NAME
        self.version = VERSION

        self.conversation: list[dict] = []

    def remember_turn(
        self,
        user: str,
        assistant: str,
    ) -> None:

        self.conversation.append(
            {
                "user": user,
                "assistant": assistant,
                "timestamp": now_utc().isoformat(),
            }
        )

        # Prevent unlimited memory growth.
        self.conversation = self.conversation[-20:]

    def respond(
        self,
        question: str,
    ) -> NexoraResponse:

        question = clean_text(question)

        if not question:

            return NexoraResponse(
                answer="Give me something to work with 😭",
                sources=[],
                searched=False,
            )

        # ----------------------------------------------------
        # 1. Casual conversation.
        # ----------------------------------------------------

        casual = casual_answer(question)

        if casual:

            response = NexoraResponse(
                answer=casual,
                sources=[],
                searched=False,
            )

            self.remember_turn(
                question,
                response.answer,
            )

            return response

        # ----------------------------------------------------
        # 2. Jokes.
        # ----------------------------------------------------

        if is_joke_request(question):

            joke = get_joke(
                football_only=(
                    "football" in normalize_text(question)
                    or "premier league"
                    in normalize_text(question)
                )
            )

            response = NexoraResponse(
                answer=joke,
                sources=[],
                searched=False,
            )

            self.remember_turn(
                question,
                response.answer,
            )

            return response

        # ----------------------------------------------------
        # 3. Built-in football knowledge.
        # ----------------------------------------------------

        if is_football_request(question):

            known_answer = football_knowledge_answer(
                question
            )

            if known_answer and not needs_web_search(
                question
            ):

                response = NexoraResponse(
                    answer=known_answer,
                    sources=[],
                    searched=False,
                )

                self.remember_turn(
                    question,
                    response.answer,
                )

                return response

        # ----------------------------------------------------
        # 4. Web search when appropriate.
        # ----------------------------------------------------

        if needs_web_search(question):

            query = clean_query(question)

            results = search_web(query)

            response = natural_search_response(
                question,
                results,
            )

            self.remember_turn(
                question,
                response.answer,
            )

            return response

        # ----------------------------------------------------
        # 5. Offline fallback.
        # ----------------------------------------------------

        response = NexoraResponse(
            answer=(
                "I can answer from my built-in knowledge, but "
                "I don't have a full language model running behind "
                "me in this version. If this needs current information, "
                "ask me to search the web and I'll look for it."
            ),
            sources=[],
            searched=False,
        )

        self.remember_turn(
            question,
            response.answer,
        )

        return response


# ============================================================
# JSON API HELPERS
# ============================================================

def response_json(
    response: NexoraResponse,
) -> str:

    return json.dumps(
        response.to_dict(),
        ensure_ascii=False,
        indent=2,
    )


# ============================================================
# SIMPLE CLI
# ============================================================

def cli():

    nexora = Nexora()

    print("=" * 60)
    print(f"{APP_NAME} v{VERSION}")
    print("Expert search + football knowledge assistant")
    print("=" * 60)
    print("Type 'exit' to quit.")
    print()

    while True:

        try:
            question = input("You: ").strip()

        except (
            EOFError,
            KeyboardInterrupt,
        ):
            print("\nNexora: See you later! 👋")
            break

        if not question:
            continue

        if normalize_text(question) in {
            "exit",
            "quit",
            "bye",
        }:
            print("Nexora: See you later! 👋")
            break

        started = time.perf_counter()

        response = nexora.respond(
            question
        )

        elapsed = (
            time.perf_counter()
            - started
        )

        print()
        print("Nexora:")
        print(
            format_response(response)
        )

        logger.debug(
            "Response generated in %.3fs",
            elapsed,
        )

        print()


# ============================================================
# OPTIONAL HTTP SERVER
# ============================================================

from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)


class NexoraHTTPHandler(
    BaseHTTPRequestHandler
):

    nexora = Nexora()

    def _send_json(
        self,
        status: int,
        payload: dict,
    ):

        body = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*",
        )

        self.end_headers()

        self.wfile.write(body)

    def do_OPTIONS(self):

        self.send_response(204)

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

    def do_GET(self):

        if self.path == "/health":

            self._send_json(
                200,
                {
                    "ok": True,
                    "name": APP_NAME,
                    "version": VERSION,
                },
            )

            return

        if self.path == "/":

            self._send_json(
                200,
                {
                    "name": APP_NAME,
                    "version": VERSION,
                    "status": "online",
                },
            )

            return

        self._send_json(
            404,
            {
                "error": "Not found",
            },
        )

    def do_POST(self):

        if self.path != "/chat":

            self._send_json(
                404,
                {
                    "error": "Not found",
                },
            )

            return

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )

            if length <= 0 or length > 100_000:

                self._send_json(
                    400,
                    {
                        "error": "Invalid request size.",
                    },
                )

                return

            body = self.rfile.read(
                length
            )

            payload = json.loads(
                body.decode("utf-8")
            )

            question = str(
                payload.get(
                    "message",
                    "",
                )
            )

            if not question.strip():

                self._send_json(
                    400,
                    {
                        "error": "Missing message.",
                    },
                )

                return

            response = self.nexora.respond(
                question
            )

            self._send_json(
                200,
                response.to_dict(),
            )

        except json.JSONDecodeError:

            self._send_json(
                400,
                {
                    "error": "Invalid JSON.",
                },
            )

        except Exception as exc:

            logger.exception(
                "API error"
            )

            self._send_json(
                500,
                {
                    "error": (
                        "Nexora encountered an "
                        "internal error."
                    )
                },
            )

    def log_message(
        self,
        format,
        *args,
    ):
        logger.info(
            "HTTP: " + format,
            *args,
        )


def run_server(
    host: str = "0.0.0.0",
    port: int | None = None,
):

    if port is None:

        port = int(
            os.environ.get(
                "PORT",
                "8080",
            )
        )

    server = ThreadingHTTPServer(
        (host, port),
        NexoraHTTPHandler,
    )

    logger.info(
        "%s v%s listening on %s:%s",
        APP_NAME,
        VERSION,
        host,
        port,
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        logger.info("Server stopping.")

    finally:
        server.server_close()


# ============================================================
# STARTUP
# ============================================================

def startup():

    mode = os.environ.get(
        "NEXORA_MODE",
        "cli",
    ).lower()

    if mode == "server":
        run_server()
    else:
        cli()


if __name__ == "__main__":
    startup()
