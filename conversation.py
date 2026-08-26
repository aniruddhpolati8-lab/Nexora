
from __future__ import annotations

import random
import re
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Intent(Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"
    THANKS = "thanks"
    IDENTITY = "identity"
    HELP = "help"
    QUESTION = "question"
    OPINION = "opinion"
    EXPLANATION = "explanation"
    CALCULATION = "calculation"
    SEARCH = "search"
    FOLLOW_UP = "follow_up"
    CASUAL = "casual"
    UNKNOWN = "unknown"


@dataclass
class Message:
    role: str
    content: str


@dataclass
class ConversationContext:
    history: deque[Message] = field(
        default_factory=lambda: deque(maxlen=20)
    )
    last_topic: str = ""
    last_user_message: str = ""
    last_response: str = ""
    turns: int = 0

    def add_user(self, message: str) -> None:
        self.history.append(Message("user", message))
        self.last_user_message = message
        self.turns += 1

    def add_assistant(self, message: str) -> None:
        self.history.append(Message("assistant", message))
        self.last_response = message


class IntentDetector:
    """Detect common user intents without an external model."""

    GREETINGS = {
        "hi",
        "hello",
        "hey",
        "hiya",
        "yo",
        "sup",
        "good morning",
        "good afternoon",
        "good evening",
    }

    FAREWELLS = {
        "bye",
        "goodbye",
        "see you",
        "see ya",
        "later",
    }

    THANKS = {
        "thanks",
        "thank you",
        "thx",
        "cheers",
    }

    def detect(self, text: str) -> Intent:
        clean = self._normalise(text)
        lower = clean.lower()

        if lower in self.GREETINGS:
            return Intent.GREETING

        if lower in self.FAREWELLS:
            return Intent.FAREWELL

        if lower in self.THANKS:
            return Intent.THANKS

        if lower in {
            "help",
            "what can you do",
            "commands",
            "what commands do you have",
        }:
            return Intent.HELP

        if re.search(
            r"\b(who are you|what are you|what is nexora)\b",
            lower,
        ):
            return Intent.IDENTITY

        if re.search(
            r"\b(what do you think|what's your opinion|your opinion)\b",
            lower,
        ):
            return Intent.OPINION

        if re.search(
            r"\b(explain|how does|why does|why is|what does .* mean)\b",
            lower,
        ):
            return Intent.EXPLANATION

        if self._looks_like_calculation(lower):
            return Intent.CALCULATION

        if re.match(
            r"^(search|look up|find information about)\b",
            lower,
        ):
            return Intent.SEARCH

        if self._looks_like_follow_up(lower):
            return Intent.FOLLOW_UP

        if "?" in text:
            return Intent.QUESTION

        if self._looks_casual(lower):
            return Intent.CASUAL

        return Intent.UNKNOWN

    @staticmethod
    def _normalise(text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _looks_like_calculation(text: str) -> bool:
        return bool(
            re.search(
                r"\b(calculate|work out|what is)\b.*"
                r"[\d\(\)\+\-\*\/\^%]",
                text,
            )
        )

    @staticmethod
    def _looks_like_follow_up(text: str) -> bool:
        return bool(
            re.match(
                r"^(and|also|what about|how about|why|how|"
                r"what if|then|that|it|this|more)\b",
                text,
            )
        )

    @staticmethod
    def _looks_casual(text: str) -> bool:
        return bool(
            re.search(
                r"\b(thats cool|that's cool|nice|cool|lol|haha|"
                r"really|interesting|wow)\b",
                text,
            )
        )


class ConversationEngine:
    """
    Advanced rule-based conversation engine.

    This is intentionally not presented as an LLM.
    """

    def __init__(self) -> None:
        self.context = ConversationContext()
        self.detector = IntentDetector()

        self._recent_responses: deque[str] = deque(maxlen=8)

    def respond(self, message: str) -> str:
        message = self._clean_input(message)

        if not message:
            return "I didn't catch that. Try saying that again."

        self.context.add_user(message)

        intent = self.detector.detect(message)

        response = self._handle_intent(intent, message)

        response = self._avoid_repetition(response)

        self.context.add_assistant(response)

        return response

    def _handle_intent(
        self,
        intent: Intent,
        message: str,
    ) -> str:

        if intent is Intent.GREETING:
            return self._greeting()

        if intent is Intent.FAREWELL:
            return random.choice([
                "See you later! 👋",
                "Bye! Take care.",
                "Catch you later!",
            ])

        if intent is Intent.THANKS:
            return random.choice([
                "You're welcome!",
                "No problem!",
                "Anytime!",
                "Glad I could help.",
            ])

        if intent is Intent.IDENTITY:
            return (
                "I'm Nexora — a rule-based assistant built to handle "
                "conversation, commands, calculations, searches and "
                "other useful tasks."
            )

        if intent is Intent.HELP:
            return self._help()

        if intent is Intent.OPINION:
            return self._opinion(message)

        if intent is Intent.EXPLANATION:
            return self._explanation(message)

        if intent is Intent.CALCULATION:
            return (
                "That looks like a calculation. "
                "I'll pass it to Nexora's calculator."
            )

        if intent is Intent.SEARCH:
            return (
                "That looks like a web search. "
                "I'll pass it to Nexora's search system."
            )

        if intent is Intent.FOLLOW_UP:
            return self._follow_up(message)

        if intent is Intent.QUESTION:
            return self._question(message)

        if intent is Intent.CASUAL:
            return self._casual(message)

        return self._unknown(message)

    def _greeting(self) -> str:
        return random.choice([
            "Hey! 👋 What can I help you with?",
            "Hi! What's up?",
            "Hey! I'm Nexora. What are you working on?",
            "Hello! What would you like to do?",
        ])

    def _help(self) -> str:
        return (
            "Here's what I can currently do:\n\n"
            "• 💬 Conversation\n"
            "• 🔎 Web searches\n"
            "• 🔢 Calculations\n"
            "• 🕒 Time/date commands\n"
            "• 🧠 Conversation context\n"
            "• 🛡️ Safety checks\n"
            "• ⚙️ Nexora commands\n\n"
            "Try asking me something naturally, or use `help` "
            "for command information."
        )

    def _opinion(self, message: str) -> str:
        topic = self._extract_topic(message)

        if topic:
            return (
                f"I can give you a balanced take on {topic}, but I don't "
                "have personal opinions or feelings. If you want, I can "
                "compare the pros and cons."
            )

        return (
            "I don't have personal opinions, but I can give you a "
            "balanced view and explain different perspectives."
        )

    def _explanation(self, message: str) -> str:
        topic = self._extract_topic(message)

        if topic:
            return (
                f"I can explain {topic}. I don't have a full language "
                "model behind me, though, so for detailed or current "
                "information I'd recommend using Nexora's search feature."
            )

        return (
            "Sure — tell me what you'd like explained and I'll break "
            "it down as clearly as I can."
        )

    def _follow_up(self, message: str) -> str:
        previous = self.context.last_user_message

        if previous and self._contains_reference(message):
            return (
                f"I can continue from what you just said. "
                f"Your previous message was: \"{previous}\""
            )

        return (
            "Sure — I can continue. Give me a little more detail about "
            "what you'd like to know."
        )

    def _question(self, message: str) -> str:
        topic = self._extract_topic(message)

        if topic:
            return (
                f"That's a good question about {topic}. "
                "I don't have enough built-in knowledge to give you a "
                "reliable detailed answer yet. Try `search ...` and "
                "Nexora can look it up."
            )

        return (
            "I can try to help. Could you make the question a little "
            "more specific?"
        )

    def _casual(self, message: str) -> str:
        lower = message.lower()

        if "lol" in lower or "haha" in lower:
            return "😂 Fair enough!"

        if "wow" in lower:
            return "Yeah, pretty interesting!"

        if "interesting" in lower:
            return "Definitely! There's quite a lot to explore there."

        return "Nice! What do you want to explore next?"

    def _unknown(self, message: str) -> str:
        return (
            "I understand you're talking to me, but I don't have enough "
            "built-in knowledge to answer that properly yet. "
            "You can ask me something specific or use `search ...` "
            "to look something up."
        )

    def _extract_topic(self, message: str) -> str:
        patterns = [
            r"\babout\s+(.+)",
            r"\bexplain\s+(.+)",
            r"\bmean\s+(.+)",
            r"\bwhat\s+is\s+(.+)",
            r"\bwhy\s+is\s+(.+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)

            if match:
                topic = match.group(1).strip(" ?.!")
                if topic:
                    return topic[:100]

        return ""

    @staticmethod
    def _contains_reference(text: str) -> bool:
        return bool(
            re.search(
                r"\b(it|that|this|they|them|he|she|those|"
                r"the previous|the last one)\b",
                text.lower(),
            )
        )

    @staticmethod
    def _clean_input(text: str) -> str:
        if not isinstance(text, str):
            return ""

        # Remove invisible characters.
        text = re.sub(
            r"[\u200b-\u200f\u2060\ufeff]",
            "",
            text,
        )

        # Collapse whitespace.
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    def _avoid_repetition(self, response: str) -> str:
        if response not in self._recent_responses:
            self._recent_responses.append(response)
            return response

        alternatives = [
            response + " What would you like to do next?",
            response + " I'm ready for the next question.",
            response + " You can also try `help`.",
        ]

        new_response = random.choice(alternatives)

        self._recent_responses.append(new_response)

        return new_response

    def get_context(self) -> ConversationContext:
        return self.context

    def clear_context(self) -> None:
        self.context = ConversationContext()
        self._recent_responses.clear()
