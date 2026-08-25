

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any


# ============================================================
# CONFIGURATION
# ============================================================

MAX_ITEMS = 500
DEFAULT_TTL = 300       # 5 minutes
MAX_KEY_LENGTH = 500


# ============================================================
# STATE
# ============================================================

LOCK = threading.RLock()

_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()


# ============================================================
# KEY GENERATION
# ============================================================

def make_key(
    value: str
) -> str:

    if not isinstance(value, str):
        value = str(value)

    value = value.strip().lower()

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


# ============================================================
# CLEANUP
# ============================================================

def cleanup() -> None:

    now = time.time()

    with LOCK:

        expired = [
            key
            for key, item
            in _cache.items()
            if item["expires"] <= now
        ]

        for key in expired:
            _cache.pop(
                key,
                None
            )

        while len(_cache) > MAX_ITEMS:
            _cache.popitem(
                last=False
            )


# ============================================================
# SET
# ============================================================

def set(
    key: str,
    value: Any,
    ttl: int = DEFAULT_TTL
) -> bool:

    if not isinstance(
        key,
        str
    ):
        return False

    key = key.strip()

    if not key:
        return False

    if len(key) > MAX_KEY_LENGTH:
        return False

    try:
        ttl = int(ttl)
    except (TypeError, ValueError):
        return False

    if ttl <= 0:
        return False

    now = time.time()

    with LOCK:

        _cache[key] = {
            "value": value,
            "created": now,
            "expires": now + ttl
        }

        _cache.move_to_end(
            key
        )

        cleanup()

    return True


# ============================================================
# GET
# ============================================================

def get(
    key: str,
    default: Any = None
) -> Any:

    if not isinstance(
        key,
        str
    ):
        return default

    with LOCK:

        item = _cache.get(
            key
        )

        if item is None:
            return default

        if item["expires"] <= time.time():

            _cache.pop(
                key,
                None
            )

            return default

        # Mark as recently used.
        _cache.move_to_end(
            key
        )

        return item["value"]


# ============================================================
# EXISTS
# ============================================================

def exists(
    key: str
) -> bool:

    marker = object()

    return get(
        key,
        marker
    ) is not marker


# ============================================================
# DELETE
# ============================================================

def delete(
    key: str
) -> bool:

    with LOCK:

        if key not in _cache:
            return False

        del _cache[key]

        return True


# ============================================================
# CLEAR
# ============================================================

def clear() -> None:

    with LOCK:
        _cache.clear()


# ============================================================
# GET OR CREATE
# ============================================================

def get_or_set(
    key: str,
    factory,
    ttl: int = DEFAULT_TTL
) -> Any:

    existing = get(
        key
    )

    if existing is not None:
        return existing

    try:
        value = factory()
    except Exception:
        return None

    set(
        key,
        value,
        ttl
    )

    return value


# ============================================================
# QUERY CACHE
# ============================================================

def cache_query(
    query: str,
    value: Any,
    ttl: int = DEFAULT_TTL
) -> bool:

    key = (
        "query:"
        + make_key(query)
    )

    return set(
        key,
        value,
        ttl
    )


def get_query(
    query: str
) -> Any:

    key = (
        "query:"
        + make_key(query)
    )

    return get(
        key
    )


# ============================================================
# STATISTICS
# ============================================================

def size() -> int:

    cleanup()

    with LOCK:
        return len(
            _cache
        )


def status() -> dict:

    cleanup()

    with LOCK:

        return {
            "enabled": True,
            "items": len(_cache),
            "maximum_items": MAX_ITEMS,
            "default_ttl": DEFAULT_TTL
        }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "Nexora Cache Engine"
    )

    print(
        "-" * 30
    )

    set(
        "test",
        "Hello Nexora!",
        ttl=60
    )

    print(
        "Stored:",
        get("test")
    )

    print(
        "Exists:",
        exists("test")
    )

    print(
        "Status:",
        status()
    )

    delete(
        "test"
    )

    print(
        "After delete:",
        get("test")
    )
