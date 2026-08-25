
from __future__ import annotations

import os


# ============================================================
# APPLICATION
# ============================================================

APP_NAME = "Nexora"
VERSION = "10.1"
SLOGAN = "Intelligence. Secured."


# ============================================================
# SERVER
# ============================================================

HOST = os.environ.get(
    "NEXORA_HOST",
    "0.0.0.0"
)

PORT = int(
    os.environ.get(
        "PORT",
        "8000"
    )
)


# ============================================================
# DATA
# ============================================================

DATA_FILE = os.environ.get(
    "NEXORA_DATA_FILE",
    "nexora_data.json"
)

CORE_KNOWLEDGE_FILE = os.environ.get(
    "NEXORA_CORE_KNOWLEDGE",
    "core_knowledge.json"
)


# ============================================================
# API AUTHENTICATION
# ============================================================

API_KEY = os.environ.get(
    "NEXORA_API_KEY",
    ""
).strip()


def authentication_enabled() -> bool:
    return bool(API_KEY)


# ============================================================
# INPUT / OUTPUT LIMITS
# ============================================================

MAX_INPUT = 5000
MAX_OUTPUT = 10000

MAX_MEMORY_LENGTH = 800
MAX_MEMORIES = 500

MAX_KNOWLEDGE_KEY = 200
MAX_KNOWLEDGE_VALUE = 4000

MAX_CONTEXT = 40


# ============================================================
# RATE LIMITING
# ============================================================

RATE_WINDOW = 60
RATE_LIMIT = 60


# ============================================================
# SECURITY
# ============================================================

SECURITY_EVENT_LIMIT = 500

SECURITY_STATES = {
    "normal",
    "lockdown",
    "emergency"
}


# ============================================================
# RESPONSE SETTINGS
# ============================================================

DEFAULT_MODE = "friendly"

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

RESPONSE_LENGTHS = {
    "short",
    "normal",
    "long",
}


# ============================================================
# LIVE DATA
# ============================================================

LIVE_DATA_ENABLED = True

WEB_SEARCH_ENABLED = True
WEATHER_ENABLED = True
SPORTS_ENABLED = True
FINANCE_ENABLED = True


# ============================================================
# EXTERNAL AI
# ============================================================

# Nexora remains local-first.
# Set these through environment variables if you
# later connect an external model.

EXTERNAL_AI_ENABLED = (
    os.environ.get(
        "NEXORA_EXTERNAL_AI",
        "false"
    ).lower()
    == "true"
)

EXTERNAL_AI_API_KEY = os.environ.get(
    "NEXORA_EXTERNAL_AI_KEY",
    ""
).strip()

EXTERNAL_AI_MODEL = os.environ.get(
    "NEXORA_EXTERNAL_AI_MODEL",
    ""
).strip()


# ============================================================
# SECURITY HELPERS
# ============================================================

def get_config() -> dict:

    return {
        "app": {
            "name": APP_NAME,
            "version": VERSION,
            "slogan": SLOGAN,
        },

        "server": {
            "host": HOST,
            "port": PORT,
        },

        "data": {
            "data_file": DATA_FILE,
            "core_knowledge_file":
                CORE_KNOWLEDGE_FILE,
        },

        "authentication": {
            "enabled":
                authentication_enabled(),
        },

        "limits": {
            "max_input": MAX_INPUT,
            "max_output": MAX_OUTPUT,
            "max_memories": MAX_MEMORIES,
            "max_context": MAX_CONTEXT,
        },

        "live_data": {
            "enabled":
                LIVE_DATA_ENABLED,
            "web_search":
                WEB_SEARCH_ENABLED,
            "weather":
                WEATHER_ENABLED,
            "sports":
                SPORTS_ENABLED,
            "finance":
                FINANCE_ENABLED,
        },

        "external_ai": {
            "enabled":
                EXTERNAL_AI_ENABLED,
            "configured":
                bool(EXTERNAL_AI_API_KEY),
            "model":
                EXTERNAL_AI_MODEL,
        },
    }


# ============================================================
# STARTUP CHECK
# ============================================================

def validate_config() -> list[str]:

    problems = []

    if PORT < 1 or PORT > 65535:
        problems.append(
            "PORT must be between 1 and 65535."
        )

    if MAX_INPUT <= 0:
        problems.append(
            "MAX_INPUT must be positive."
        )

    if MAX_OUTPUT <= 0:
        problems.append(
            "MAX_OUTPUT must be positive."
        )

    if (
        EXTERNAL_AI_ENABLED
        and not EXTERNAL_AI_API_KEY
    ):
        problems.append(
            "External AI is enabled but "
            "no API key is configured."
        )

    return problems


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 50)
    print("NEXORA CONFIGURATION")
    print("=" * 50)

    problems = validate_config()

    if problems:

        print("Configuration problems:")

        for problem in problems:
            print(
                " -",
                problem
            )

    else:

        print(
            "Configuration OK."
        )

    print()

    print(
        get_config()
    )
