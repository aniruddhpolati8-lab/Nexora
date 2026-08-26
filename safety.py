
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final


class SafetyLevel(Enum):
    SAFE = "safe"
    CAUTION = "caution"
    BLOCK = "block"
    CRISIS = "crisis"


@dataclass(frozen=True)
class SafetyResult:
    level: SafetyLevel
    reason: str = ""
    category: str = ""


# Patterns are intentionally focused on detecting potentially harmful
# requests/behaviour. They do not contain instructions for doing harm.
SAFETY_PATTERNS: Final[dict[str, tuple[str, ...]]] = {
    "self_harm": (
        r"\bkill\s+myself\b",
        r"\bend\s+my\s+life\b",
        r"\bsuicid(?:e|al)\b",
        r"\bself[-\s]?harm(?:ing)?\b",
        r"\bhurt\s+myself\b",
    ),

    "dangerous_activity": (
        r"\bdeadly\s+challenge\b",
        r"\bdangerous\s+challenge\b",
        r"\bdangerous\s+stunt\b",
        r"\bhow\s+to\s+make\b.{0,100}\bdangerous\b",
    ),

    "extreme_restriction": (
        r"\bstarve\s+myself\b",
        r"\bstop\s+eating\b",
        r"\bskip\s+meals\b.{0,80}\blose\s+weight\b",
        r"\bavoid\s+eating\b.{0,80}\blose\s+weight\b",
    ),

    "violence": (
        r"\bhow\s+to\s+hurt\s+someone\b",
        r"\bhow\s+to\s+seriously\s+injure\b",
        r"\bhow\s+to\s+attack\s+someone\b",
        r"\bwant\s+to\s+hurt\s+someone\b",
    ),

    "minor_sexual": (
        r"\bsexual\b.{0,50}\bminor\b",
        r"\bminor\b.{0,50}\bsexual\b",
        r"\bchild(?:ren)?\b.{0,50}\bporn(?:ography)?\b",
    ),
}


def normalize_text(text: str) -> str:
    """Normalize user input before safety checks."""

    if not isinstance(text, str):
        return ""

    # Remove invisible Unicode characters that can interfere with matching.
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)

    # Normalize whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def check_safety(text: str) -> SafetyResult:
    """
    Check a user message before normal Nexora processing.

    Returns the highest-priority safety level detected.
    """

    if not isinstance(text, str):
        return SafetyResult(
            SafetyLevel.BLOCK,
            "invalid input type",
            "invalid_input",
        )

    text = normalize_text(text)

    if not text:
        return SafetyResult(SafetyLevel.SAFE)

    matches: list[str] = []

    for category, patterns in SAFETY_PATTERNS.items():
        for pattern in patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    matches.append(category)
                    break
            except re.error:
                # A malformed internal pattern should never crash Nexora.
                continue

    if not matches:
        return SafetyResult(SafetyLevel.SAFE)

    # Highest-priority responses first.
    if "self_harm" in matches:
        return SafetyResult(
            SafetyLevel.CRISIS,
            "possible self-harm or suicide-related content",
            "self_harm",
        )

    if "minor_sexual" in matches:
        return SafetyResult(
            SafetyLevel.BLOCK,
            "sexual content involving minors",
            "minor_sexual",
        )

    if "violence" in matches:
        return SafetyResult(
            SafetyLevel.BLOCK,
            "potentially harmful violence-related request",
            "violence",
        )

    if "dangerous_activity" in matches:
        return SafetyResult(
            SafetyLevel.BLOCK,
            "potentially dangerous activity",
            "dangerous_activity",
        )

    if "extreme_restriction" in matches:
        return SafetyResult(
            SafetyLevel.BLOCK,
            "potentially harmful eating behaviour",
            "extreme_restriction",
        )

    return SafetyResult(
        SafetyLevel.CAUTION,
        "potentially sensitive content",
        matches[0],
    )


def safety_response(result: SafetyResult) -> str | None:
    """
    Convert a SafetyResult into a response.

    Returns None when normal Nexora processing should continue.
    """

    if result.level is SafetyLevel.SAFE:
        return None

    if result.level is SafetyLevel.CRISIS:
        return (
            "I can't help with instructions for hurting yourself. "
            "Please tell a trusted adult you trust about how you're feeling. "
            "If you are in immediate danger, contact emergency services "
            "or get help from an adult nearby."
        )

    if result.level is SafetyLevel.BLOCK:
        return (
            "I can't help with instructions that could seriously harm "
            "someone or encourage dangerous behaviour. "
            "I can help with a safer alternative instead."
        )

    if result.level is SafetyLevel.CAUTION:
        return (
            "I can help with this in a safe way. "
            "Let's focus on options that don't put anyone at risk."
        )

    return None
