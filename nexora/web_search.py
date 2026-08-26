

from __future__ import annotations

import html
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import (
    parse_qs,
    quote_plus,
    unquote,
    urljoin,
    urlparse,
)
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


# ============================================================
# CONFIGURATION
# ============================================================

SEARCH_URL = (
    "https://html.duckduckgo.com/html/?q={}"
)

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; NexoraWebSearch/2.0)"
)

MAX_QUERY_LENGTH = 300
MAX_RESULTS = 10

SEARCH_TIMEOUT = 10
PAGE_TIMEOUT = 12

MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_LENGTH = 50_000

MIN_TITLE_LENGTH = 2

ALLOWED_SCHEMES = {
    "http",
    "https",
}


# ============================================================
# DATA TYPES
# ============================================================

@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    domain: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class WebPage:
    url: str
    final_url: str
    title: str
    text: str
    status: int
    content_type: str = ""


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(text: str) -> str:
    """
    Convert HTML-ish text into readable plain text.
    """

    if not isinstance(text, str):
        return ""

    text = html.unescape(text)

    # Remove scripts/styles.
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
        r"<noscript\b[^>]*>.*?</noscript>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Convert common structural tags to spaces.
    text = re.sub(
        r"</?(?:p|div|br|li|tr|td|th|h[1-6])\b[^>]*>",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # Remove remaining tags.
    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    # Decode entities again after tag removal.
    text = html.unescape(text)

    # Normalise whitespace.
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalise(text: str) -> str:
    return " ".join(
        str(text).lower().split()
    )


def words(text: str) -> set[str]:
    return set(
        re.findall(
            r"[a-z0-9]+",
            normalise(text),
        )
    )


# ============================================================
# URL HELPERS
# ============================================================

def valid_url(url: str) -> bool:
    """
    Check that a URL is HTTP(S) and not obviously local/private.
    """

    if not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url)

        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            return False

        if not parsed.hostname:
            return False

        hostname = parsed.hostname.lower().rstrip(".")

        # Localhost / local names.
        if hostname in {
            "localhost",
            "localhost.localdomain",
        }:
            return False

        # Direct IP addresses.
        try:
            address = ipaddress.ip_address(
                hostname
            )

            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
            ):
                return False

        except ValueError:
            pass

        return True

    except ValueError:
        return False


def domain_from_url(url: str) -> str:
    try:
        hostname = urlparse(url).hostname

        if not hostname:
            return ""

        return hostname.lower()

    except ValueError:
        return ""


def clean_search_url(url: str) -> str:
    """
    DuckDuckGo sometimes returns redirect URLs.
    Attempt to extract the real destination.
    """

    url = html.unescape(
        str(url).strip()
    )

    parsed = urlparse(url)

    query = parse_qs(
        parsed.query
    )

    for key in (
        "uddg",
        "url",
        "target",
    ):

        values = query.get(key)

        if values:

            candidate = unquote(
                values[0]
            )

            if valid_url(candidate):
                return candidate

    return url


# ============================================================
# SAFE REQUEST HANDLING
# ============================================================

class SafeRedirectHandler(
    HTTPRedirectHandler
):
    """
    Only follow redirects to valid HTTP(S)
    URLs.
    """

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        newurl = urljoin(
            req.full_url,
            newurl,
        )

        if not valid_url(newurl):
            return None

        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        )


OPENER = build_opener(
    SafeRedirectHandler()
)


def _request(
    url: str,
    timeout: int,
    accept: str,
) -> bytes | None:

    if not valid_url(url):
        return None

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": (
                "en-GB,en;q=0.9"
            ),
        },
    )

    try:

        with OPENER.open(
            request,
            timeout=timeout,
        ) as response:

            content_length = response.headers.get(
                "Content-Length"
            )

            if content_length:

                try:
                    if (
                        int(content_length)
                        > MAX_PAGE_BYTES
                    ):
                        return None
                except ValueError:
                    pass

            chunks = []
            total = 0

            while True:

                chunk = response.read(
                    min(
                        64 * 1024,
                        MAX_PAGE_BYTES - total,
                    )
                )

                if not chunk:
                    break

                chunks.append(chunk)
                total += len(chunk)

                if total >= MAX_PAGE_BYTES:
                    break

            return b"".join(chunks)

    except Exception:
        return None


# ============================================================
# SEARCH
# ============================================================

def _search_score(
    query: str,
    result: SearchResult,
) -> float:

    query_words = words(query)

    if not query_words:
        return 0.0

    title_words = words(
        result.title
    )

    snippet_words = words(
        result.snippet
    )

    title_matches = len(
        query_words & title_words
    )

    snippet_matches = len(
        query_words & snippet_words
    )

    score = (
        title_matches * 3.0
        + snippet_matches * 1.0
    )

    if normalise(query) in normalise(
        result.title
    ):
        score += 5.0

    return score


def search(
    query: str,
    limit: int = MAX_RESULTS,
) -> list[dict[str, str]]:

    if not isinstance(
        query,
        str,
    ):
        return []

    query = query.strip()

    if not query:
        return []

    if len(query) > MAX_QUERY_LENGTH:
        return []

    try:
        limit = int(limit)
    except (
        TypeError,
        ValueError,
    ):
        limit = MAX_RESULTS

    limit = max(
        1,
        min(
            limit,
            MAX_RESULTS,
        ),
    )

    url = SEARCH_URL.format(
        quote_plus(query)
    )

    page = _request(
        url,
        SEARCH_TIMEOUT,
        "text/html",
    )

    if not page:
        return []

    document = page.decode(
        "utf-8",
        errors="replace",
    )

    results: list[SearchResult] = []
    seen: set[str] = set()

    # More flexible result extraction.
    blocks = re.findall(
        r'<div[^>]+class="[^"]*result[^"]*"'
        r'[^>]*>.*?'
        r'(?=<div[^>]+class="[^"]*result[^"]*"'
        r'|</body>)',
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Fallback if the layout changes.
    if not blocks:

        blocks = re.findall(
            r'<a[^>]+class="[^"]*result__a[^"]*"'
            r'[^>]*>.*?</a>',
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )

    for block in blocks:

        if len(results) >= MAX_RESULTS * 2:
            break

        title_match = re.search(
            r'class="[^"]*result__a[^"]*"'
            r'[^>]*>(.*?)</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if not title_match:
            continue

        title = clean_text(
            title_match.group(1)
        )

        href_match = re.search(
            r'class="[^"]*result__a[^"]*"'
            r'[^>]+href=["\']([^"\']+)["\']',
            block,
            flags=re.IGNORECASE,
        )

        if not href_match:
            continue

        result_url = clean_search_url(
            href_match.group(1)
        )

        if not valid_url(result_url):
            continue

        snippet_match = re.search(
            r'class="[^"]*result__snippet[^"]*"'
            r'[^>]*>(.*?)</',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

        snippet = ""

        if snippet_match:
            snippet = clean_text(
                snippet_match.group(1)
            )

        if len(title) < MIN_TITLE_LENGTH:
            continue

        canonical = result_url.rstrip(
            "/"
        ).lower()

        if canonical in seen:
            continue

        seen.add(canonical)

        result = SearchResult(
            title=title,
            url=result_url,
            snippet=snippet,
            domain=domain_from_url(
                result_url
            ),
        )

        result = SearchResult(
            title=result.title,
            url=result.url,
            snippet=result.snippet,
            domain=result.domain,
            score=_search_score(
                query,
                result,
            ),
        )

        results.append(result)

    results.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    return [
        {
            "title": result.title,
            "url": result.url,
            "snippet": result.snippet,
            "domain": result.domain,
        }
        for result in results[:limit]
    ]


# ============================================================
# FETCH WEBPAGE
# ============================================================

def fetch_page(
    url: str,
) -> WebPage | None:
    """
    Fetch and extract readable text from a webpage.
    """

    if not valid_url(url):
        return None

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "text/plain;q=0.8"
            ),
            "Accept-Language": (
                "en-GB,en;q=0.9"
            ),
        },
    )

    try:

        with OPENER.open(
            request,
            timeout=PAGE_TIMEOUT,
        ) as response:

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
            )

            final_url = response.geturl()

            if not valid_url(
                final_url
            ):
                return None

            content_length = response.headers.get(
                "Content-Length"
            )

            if content_length:

                try:
                    if (
                        int(content_length)
                        > MAX_PAGE_BYTES
                    ):
                        return None
                except ValueError:
                    pass

            data = response.read(
                MAX_PAGE_BYTES
            )

            charset_match = re.search(
                r"charset=([A-Za-z0-9._-]+)",
                content_type,
                re.IGNORECASE,
            )

            encoding = (
                charset_match.group(1)
                if charset_match
                else "utf-8"
            )

            document = data.decode(
                encoding,
                errors="replace",
            )

            title_match = re.search(
                r"<title[^>]*>"
                r"(.*?)"
                r"</title>",
                document,
                flags=re.IGNORECASE | re.DOTALL,
            )

            title = ""

            if title_match:
                title = clean_text(
                    title_match.group(1)
                )

            text = clean_text(
                document
            )

            if len(text) > MAX_TEXT_LENGTH:
                text = text[
                    :MAX_TEXT_LENGTH
                ]

            return WebPage(
                url=url,
                final_url=final_url,
                title=title,
                text=text,
                status=getattr(
                    response,
                    "status",
                    200,
                ),
                content_type=content_type,
            )

    except Exception:
        return None


# ============================================================
# SEARCH + FETCH
# ============================================================

def search_and_read(
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Search the web and fetch the most useful pages.
    """

    results = search(
        query,
        limit=limit,
    )

    output = []

    for result in results:

        page = fetch_page(
            result["url"]
        )

        item = {
            "title": result["title"],
            "url": result["url"],
            "snippet": result["snippet"],
            "domain": result["domain"],
            "content": "",
        }

        if page:

            item["final_url"] = (
                page.final_url
            )

            item["page_title"] = (
                page.title
            )

            item["content"] = (
                page.text
            )

            item["status"] = (
                page.status
            )

        output.append(item)

    return output


# ============================================================
# FIRST RESULT
# ============================================================

def search_one(
    query: str,
) -> dict[str, str] | None:

    results = search(
        query,
        limit=1,
    )

    if not results:
        return None

    return results[0]


# ============================================================
# PAGE TEXT EXTRACTION
# ============================================================

def extract_relevant_text(
    text: str,
    query: str,
    max_length: int = 8000,
) -> str:
    """
    Find portions of a page that contain
    words related to the query.
    """

    if not text:
        return ""

    if not query:
        return text[:max_length]

    query_words = words(query)

    if not query_words:
        return text[:max_length]

    sentences = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    scored = []

    for index, sentence in enumerate(
        sentences
    ):

        sentence_words = words(
            sentence
        )

        score = len(
            query_words & sentence_words
        )

        if score:
            scored.append(
                (
                    score,
                    index,
                    sentence,
                )
            )

    if not scored:
        return text[:max_length]

    scored.sort(
        reverse=True
    )

    selected = [
        sentence
        for _, _, sentence
        in scored
    ]

    result = " ".join(
        selected
    )

    return result[:max_length]


# ============================================================
# FORMAT RESULTS
# ============================================================

def format_results(
    results: list[dict[str, Any]],
) -> str:

    if not results:
        return (
            "I couldn't find any "
            "web results for that search."
        )

    output = [
        "Web search results:",
        "",
    ]

    for index, result in enumerate(
        results,
        1,
    ):

        output.append(
            f"{index}. "
            f"{result.get('title', '')}"
        )

        if result.get("domain"):
            output.append(
                f"   Source: "
                f"{result['domain']}"
            )

        if result.get("snippet"):
            output.append(
                f"   {result['snippet']}"
            )

        output.append(
            f"   {result.get('url', '')}"
        )

        output.append("")

    return "\n".join(
        output
    ).strip()


# ============================================================
# SIMPLE WEB QUESTION HELPER
# ============================================================

def answer_from_web(
    query: str,
    limit: int = 3,
) -> str:
    """
    Retrieve relevant web content and return
    a compact source-backed text bundle.

    This does NOT pretend that Nexora's own
    language model generated a verified answer.
    """

    pages = search_and_read(
        query,
        limit=limit,
    )

    if not pages:
        return (
            "I couldn't find reliable "
            "web results for that."
        )

    output = [
        f"Web information for: {query}",
        "",
    ]

    for index, page in enumerate(
        pages,
        1,
    ):

        content = extract_relevant_text(
            page.get("content", ""),
            query,
            max_length=2500,
        )

        output.append(
            f"[Source {index}] "
            f"{page.get('title', '')}"
        )

        output.append(
            f"URL: {page.get('final_url', page.get('url', ''))}"
        )

        if content:
            output.append(
                content
            )

        elif page.get("snippet"):
            output.append(
                page["snippet"]
            )

        output.append("")

    return "\n".join(
        output
    ).strip()


# ============================================================
# STATUS
# ============================================================

def status() -> dict[str, Any]:

    return {
        "enabled": True,
        "engine": "DuckDuckGo HTML",
        "search_timeout": SEARCH_TIMEOUT,
        "page_timeout": PAGE_TIMEOUT,
        "max_results": MAX_RESULTS,
        "max_page_bytes": MAX_PAGE_BYTES,
        "webpage_fetching": True,
        "html_extraction": True,
    }


# ============================================================
# TESTS
# ============================================================

def self_test() -> dict[str, bool]:

    tests = {}

    tests["normalise"] = (
        normalise(
            "  Hello   World  "
        )
        == "hello world"
    )

    tests["url_validation"] = (
        valid_url(
            "https://example.com"
        )
        and not valid_url(
            "ftp://example.com"
        )
    )

    tests["domain"] = (
        domain_from_url(
            "https://www.example.com/test"
        )
        == "www.example.com"
    )

    tests["clean_text"] = (
        clean_text(
            "<p>Hello</p><p>World</p>"
        )
        == "Hello World"
    )

    tests["word_extraction"] = (
        "nexora" in words(
            "Nexora is awesome!"
        )
    )

    return tests


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    print(
        "Nexora Advanced Web Search"
    )

    print(
        "=" * 40
    )

    print(
        status()
    )

    print()

    tests = self_test()

    print("Self-test:")

    for name, passed in tests.items():
        print(
            f"  {name}: "
            f"{'PASS' if passed else 'FAIL'}"
        )

    print()

    query = input(
        "Nexora web search: "
    ).strip()

    if query:

        results = search(
            query
        )

        print()

        print(
            format_results(
                results
            )
        )
