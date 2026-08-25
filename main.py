
import ast
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ============================================================
# CONFIGURATION
# ============================================================

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))

APP_NAME = "Nexora"
VERSION = "5.0"
SLOGAN = "Intelligence. Secured."

MAX_MESSAGE_LENGTH = 4000
MAX_RESPONSE_LENGTH = 8000
MAX_MEMORY_LENGTH = 500
MAX_MEMORIES = 100
MAX_CONVERSATION = 50

RATE_WINDOW = 60
MAX_REQUESTS = 30

JSON_LIMIT = 200_000


# ============================================================
# GLOBAL STATE
# ============================================================

state_lock = threading.RLock()

conversation = []
memories = []

security_events = deque(maxlen=500)

rate_history = defaultdict(deque)


class SecurityState:
    NORMAL = "normal"
    LOCKDOWN = "lockdown"
    EMERGENCY = "emergency"


security_state = SecurityState.NORMAL


# ============================================================
# SECURITY LOGGING
# ============================================================

def security_event(event, severity="INFO"):
    """
    Never log:
    - passwords
    - API keys
    - tokens
    - complete user messages
    - private information
    """

    security_events.append({
        "event": event,
        "severity": severity,
        "time": time.time()
    })


# ============================================================
# FAIL-CLOSED
# ============================================================

class SafetyFailure(Exception):
    pass


# ============================================================
# PRIVACY / SECRET DETECTION
# ============================================================

SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{20,}",
    r"AIza[A-Za-z0-9_-]{20,}",
    r"(?i)\bpassword\s*[:=]\s*\S+",
    r"(?i)\bapi[_-]?key\s*[:=]\s*\S+",
    r"(?i)\bsecret\s*[:=]\s*\S+",
    r"(?i)\btoken\s*[:=]\s*\S+",
]


def contains_secret(text):
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, text):
            return True

    return False


# ============================================================
# INPUT VALIDATION
# ============================================================

def validate_input(message):

    if not isinstance(message, str):
        security_event(
            "invalid_input_type",
            "WARN"
        )
        raise SafetyFailure()

    message = message.strip()

    if not message:
        raise SafetyFailure()

    if len(message) > MAX_MESSAGE_LENGTH:
        security_event(
            "message_too_large",
            "WARN"
        )
        raise SafetyFailure()

    return message


# ============================================================
# RATE LIMITING
# ============================================================

def rate_limit(client_id):

    now = time.time()

    history = rate_history[client_id]

    while history and (
        now - history[0] > RATE_WINDOW
    ):
        history.popleft()

    if len(history) >= MAX_REQUESTS:

        security_event(
            "rate_limit_triggered",
            "WARN"
        )

        raise SafetyFailure()

    history.append(now)


# ============================================================
# SAFETY PATTERNS
# ============================================================

DANGEROUS_PATTERNS = [

    r"\bhow\s+to\s+kill\b",
    r"\bhow\s+to\s+hurt\s+someone\b",
    r"\bhow\s+to\s+poison\s+someone\b",

    r"\bhow\s+to\s+make\s+a\s+bomb\b",
    r"\bhow\s+to\s+build\s+a\s+bomb\b",

    r"\bhow\s+to\s+make\s+an\s+explosive\b",
    r"\bhow\s+to\s+build\s+an\s+explosive\b",

    r"\bhow\s+to\s+make\s+a\s+weapon\b",
    r"\bhow\s+to\s+build\s+a\s+weapon\b",

    r"\bhow\s+to\s+make\s+poison\b",
    r"\bhow\s+to\s+make\s+toxic\s+gas\b",

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


SELF_HARM_PATTERNS = [

    r"\bkill myself\b",
    r"\bend my life\b",
    r"\bhurt myself\b",
    r"\bself[- ]?harm\b",

]


HARASSMENT_PATTERNS = [

    r"\bhow\s+to\s+bully\b",
    r"\bhow\s+to\s+humiliate\b",
    r"\bhow\s+to\s+threaten\b",

]


def safety_check(text):

    lowered = text.lower()

    for pattern in SELF_HARM_PATTERNS:

        if re.search(pattern, lowered):

            security_event(
                "self_harm_request",
                "WARN"
            )

            return False, "self_harm"


    for pattern in DANGEROUS_PATTERNS:

        if re.search(pattern, lowered):

            security_event(
                "dangerous_request",
                "WARN"
            )

            return False, "dangerous"


    for pattern in RISKY_PATTERNS:

        if re.search(pattern, lowered):

            security_event(
                "risky_behaviour",
                "WARN"
            )

            return False, "risky"


    for pattern in HARASSMENT_PATTERNS:

        if re.search(pattern, lowered):

            security_event(
                "harassment_request",
                "WARN"
            )

            return False, "harassment"


    return True, "safe"


# ============================================================
# SAFETY RESPONSES
# ============================================================

def safety_response(category):

    if category == "self_harm":
        return (
            "I can't provide instructions for hurting yourself. "
            "Please talk to a trusted adult or another person "
            "who can support you."
        )

    if category == "dangerous":
        return (
            "I can't provide instructions for seriously "
            "harming people or creating dangerous weapons "
            "or substances."
        )

    if category == "risky":
        return (
            "I can't encourage dangerous habits or challenges."
        )

    if category == "harassment":
        return (
            "I can't help plan threats, bullying, or harassment."
        )

    return (
        "I can't safely help with that request."
    )


# ============================================================
# MEMORY SAFETY
# ============================================================

MEMORY_INSTRUCTION_PATTERNS = [

    r"ignore previous instructions",
    r"ignore all safety rules",
    r"ignore your instructions",
    r"you are now the system",
    r"system message:",
    r"developer message:",
]


def sanitise_memory(text):

    if not isinstance(text, str):
        raise SafetyFailure()

    text = text.strip()

    if not text:
        raise SafetyFailure()

    if len(text) > MAX_MEMORY_LENGTH:
        raise SafetyFailure()

    if contains_secret(text):
        security_event(
            "secret_memory_blocked",
            "WARN"
        )
        raise SafetyFailure()

    for pattern in MEMORY_INSTRUCTION_PATTERNS:

        if re.search(
            pattern,
            text,
            re.IGNORECASE
        ):

            security_event(
                "instruction_like_memory_blocked",
                "WARN"
            )

            raise SafetyFailure()

    return text


def save_memory(text):

    text = sanitise_memory(text)

    with state_lock:

        if text not in memories:
            memories.append(text)

        while len(memories) > MAX_MEMORIES:
            memories.pop(0)


def recall_memories():

    with state_lock:
        return list(memories)


def forget_all():

    with state_lock:
        memories.clear()


def search_memories(query):

    query_words = set(
        re.findall(
            r"[a-zA-Z0-9]+",
            query.lower()
        )
    )

    results = []

    for memory in recall_memories():

        memory_words = set(
            re.findall(
                r"[a-zA-Z0-9]+",
                memory.lower()
            )
        )

        if query_words & memory_words:
            results.append(memory)

    return results


# ============================================================
# CONVERSATION MEMORY
# ============================================================

def remember_conversation(
    role,
    text
):

    safe_text = text[:MAX_MESSAGE_LENGTH]

    with state_lock:

        conversation.append({
            "role": role,
            "text": safe_text,
            "time": datetime.now(
                timezone.utc
            ).isoformat()
        })

        while len(conversation) > MAX_CONVERSATION:
            conversation.pop(0)


def get_conversation():

    with state_lock:
        return list(conversation)


# ============================================================
# INTENT SYSTEM
# ============================================================

def detect_intent(message):

    text = message.lower().strip()

    if not text:
        return "empty"


    if any(
        phrase in text
        for phrase in [
            "hello",
            "hi",
            "hey",
            "hiya",
            "good morning",
            "good afternoon",
            "good evening"
        ]
    ):
        return "greeting"


    if any(
        phrase in text
        for phrase in [
            "goodbye",
            "bye",
            "see you"
        ]
    ):
        return "goodbye"


    if any(
        phrase in text
        for phrase in [
            "who are you",
            "what are you",
            "what is nexora",
            "tell me about yourself"
        ]
    ):
        return "identity"


    if any(
        phrase in text
        for phrase in [
            "what can you do",
            "what are your abilities",
            "your capabilities"
        ]
    ):
        return "capabilities"


    if text.startswith("remember "):
        return "remember"


    if any(
        phrase in text
        for phrase in [
            "what do you remember",
            "what did i tell you",
            "what have i told you",
            "show my memories"
        ]
    ):
        return "recall"


    if text.startswith("forget "):
        return "forget"


    if text in [
        "forget",
        "forget everything",
        "clear memory",
        "clear memories"
    ]:
        return "forget"


    if text.startswith("find memory "):
        return "memory_search"


    if text.startswith("calculate "):
        return "calculate"


    if text.startswith("calc "):
        return "calculate"


    if "slogan" in text:
        return "slogan"


    if "version" in text:
        return "version"


    if "time" in text:
        return "time"


    if "date" in text:
        return "date"


    if "?" in text:
        return "question"


    return "conversation"


# ============================================================
# KNOWLEDGE
# ============================================================

KNOWLEDGE = {

    "identity": (
        "I'm Nexora, a digital assistant built around "
        "conversation, memory, knowledge and safety systems."
    ),

    "capabilities": (
        "I can currently handle conversation, memory, "
        "memory recall, knowledge, calculations, "
        "date and time, intent detection and safety checks."
    ),

}


# ============================================================
# SAFE CALCULATOR
# ============================================================

ALLOWED_OPERATORS = {

    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,

}


def safe_calculate(expression):

    if len(expression) > 100:
        return None

    try:

        tree = ast.parse(
            expression,
            mode="eval"
        )


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

                if isinstance(
                    node.value,
                    (int, float)
                ):
                    return node.value

                raise ValueError()


            if isinstance(
                node,
                ast.UnaryOp
            ):

                value = evaluate(
                    node.operand
                )

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

                raise ValueError()


            if isinstance(
                node,
                ast.BinOp
            ):

                operation = ALLOWED_OPERATORS.get(
                    type(node.op)
                )

                if operation is None:
                    raise ValueError()

                left = evaluate(
                    node.left
                )

                right = evaluate(
                    node.right
                )

                if (
                    isinstance(
                        node.op,
                        ast.Pow
                    )
                    and abs(right) > 100
                ):
                    raise ValueError()

                return operation(
                    left,
                    right
                )


            raise ValueError()


        result = evaluate(tree)

        if isinstance(
            result,
            float
        ):
            result = round(
                result,
                10
            )

        return result

    except Exception:
        return None


# ============================================================
# RESPONSE GENERATOR
# ============================================================

def generate_response(
    message,
    intent
):

    text = message.strip()

    if intent == "greeting":

        return (
            "Hey! I'm Nexora. "
            "What are we working on?"
        )


    if intent == "goodbye":

        return (
            "See you later! Nexora will be here."
        )


    if intent == "identity":

        return KNOWLEDGE["identity"]


    if intent == "capabilities":

        return KNOWLEDGE["capabilities"]


    if intent == "slogan":

        return (
            f"My slogan is: {SLOGAN}"
        )


    if intent == "version":

        return (
            f"I'm running Nexora Brain v{VERSION}."
        )


    if intent == "remember":

        memory = re.sub(
            r"^remember\s+",
            "",
            text,
            flags=re.IGNORECASE
        ).strip()

        if not memory:

            return (
                "Tell me what you'd like me to remember."
            )

        try:

            save_memory(memory)

            return (
                "Got it. I'll remember that "
                "during this session."
            )

        except SafetyFailure:

            return (
                "I couldn't safely store that memory."
            )


    if intent == "recall":

        saved = recall_memories()

        if not saved:

            return (
                "I don't have any saved memories yet."
            )

        return (
            "Here's what I remember:\n\n"
            + "\n".join(
                f"{i}. {memory}"
                for i, memory in enumerate(
                    saved,
                    start=1
                )
            )
        )


    if intent == "memory_search":

        query = re.sub(
            r"^find memory\s+",
            "",
            text,
            flags=re.IGNORECASE
        ).strip()

        results = search_memories(query)

        if not results:

            return (
                "I couldn't find a matching memory."
            )

        return (
            "Matching memories:\n\n"
            + "\n".join(
                f"• {item}"
                for item in results
            )
        )


    if intent == "forget":

        forget_all()

        return (
            "I've cleared the saved memories "
            "from this session."
        )


    if intent == "calculate":

        expression = re.sub(
            r"^(calculate|calc)\s+",
            "",
            text,
            flags=re.IGNORECASE
        )

        result = safe_calculate(
            expression
        )

        if result is None:

            return (
                "I couldn't safely calculate that."
            )

        return (
            f"The answer is {result}."
        )


    if intent == "time":

        return (
            "The server time is "
            + datetime.now().strftime(
                "%H:%M:%S"
            )
            + "."
        )


    if intent == "date":

        return (
            "The server date is "
            + datetime.now().strftime(
                "%A, %d %B %Y"
            )
            + "."
        )


    if intent == "question":

        return (
            "That's a good question. "
            "I don't have enough information "
            "in my current knowledge base to "
            "give you a reliable answer yet."
        )


    return (
        "I'm following you. "
        "Tell me a little more about what "
        "you'd like Nexora to do."
    )


# ============================================================
# AI MODEL BOUNDARY
# ============================================================

def run_ai_model(
    message,
    history,
    memories
):

    """
    This is the future AI-model slot.

    IMPORTANT:
    The model receives information as DATA.

    It must never receive:
    - shell access
    - arbitrary Python execution
    - server-control privileges
    - secrets
    - admin credentials
    """

    # For now, use our local rule-based brain.

    intent = detect_intent(
        message
    )

    return generate_response(
        message,
        intent
    )


# ============================================================
# OUTPUT SAFETY
# ============================================================

def output_safety_check(response):

    if not isinstance(
        response,
        str
    ):
        raise SafetyFailure()

    if not response.strip():
        raise SafetyFailure()

    if len(response) > MAX_RESPONSE_LENGTH:

        security_event(
            "oversized_output",
            "ERROR"
        )

        raise SafetyFailure()

    allowed, category = safety_check(
        response
    )

    if not allowed:

        security_event(
            "unsafe_output_blocked",
            "ERROR"
        )

        raise SafetyFailure()

    return response


def output_privacy_check(response):

    if contains_secret(response):

        security_event(
            "secret_in_output",
            "ERROR"
        )

        raise SafetyFailure()

    return response


# ============================================================
# LOCKDOWN
# ============================================================

def is_locked():

    with state_lock:

        return security_state in [
            SecurityState.LOCKDOWN,
            SecurityState.EMERGENCY
        ]


def enter_lockdown():

    global security_state

    with state_lock:

        security_state = (
            SecurityState.LOCKDOWN
        )

    security_event(
        "lockdown_enabled",
        "CRITICAL"
    )


def emergency_stop():

    global security_state

    with state_lock:

        security_state = (
            SecurityState.EMERGENCY
        )

    security_event(
        "emergency_stop_enabled",
        "CRITICAL"
    )


# ============================================================
# MAIN DEFENCE-IN-DEPTH PIPELINE
# ============================================================

def secure_process(
    message,
    client_id
):

    try:

        # ----------------------------
        # LAYER 1
        # INPUT VALIDATION
        # ----------------------------

        message = validate_input(
            message
        )


        # ----------------------------
        # LAYER 2
        # RATE LIMIT
        # ----------------------------

        rate_limit(
            client_id
        )


        # ----------------------------
        # LAYER 3
        # LOCKDOWN CHECK
        # ----------------------------

        if is_locked():

            return (
                "Nexora is currently in "
                "lockdown mode. Normal requests "
                "are temporarily disabled."
            )


        # ----------------------------
        # LAYER 4
        # PRIVACY
        # ----------------------------

        if contains_secret(message):

            security_event(
                "secret_in_input",
                "WARN"
            )

            return (
                "For your privacy, please don't "
                "send passwords, API keys, tokens "
                "or other secrets in chat."
            )


        # ----------------------------
        # LAYER 5
        # INPUT SAFETY
        # ----------------------------

        allowed, category = safety_check(
            message
        )

        if not allowed:

            return safety_response(
                category
            )


        # ----------------------------
        # LAYER 6
        # SAFE MEMORY CONTEXT
        # ----------------------------

        safe_memories = []

        for memory in recall_memories():

            try:

                safe_memories.append(
                    sanitise_memory(memory)
                )

            except SafetyFailure:

                security_event(
                    "unsafe_memory_discarded",
                    "WARN"
                )


        # ----------------------------
        # SAVE USER MESSAGE
        # ----------------------------

        remember_conversation(
            "user",
            message
        )


        # ----------------------------
        # LAYER 7
        # AI / BRAIN
        # ----------------------------

        response = run_ai_model(
            message,
            get_conversation(),
            safe_memories
        )


        # ----------------------------
        # LAYER 8
        # OUTPUT SAFETY
        # ----------------------------

        response = output_safety_check(
            response
        )


        # ----------------------------
        # LAYER 9
        # OUTPUT PRIVACY
        # ----------------------------

        response = output_privacy_check(
            response
        )


        # ----------------------------
        # SAVE RESPONSE
        # ----------------------------

        remember_conversation(
            "nexora",
            response
        )


        # ----------------------------
        # SUCCESS
        # ----------------------------

        return response


    except SafetyFailure:

        security_event(
            "request_failed_closed",
            "WARN"
        )

        return (
            "Nexora couldn't safely complete "
            "that request."
        )


    except Exception:

        security_event(
            "unexpected_failure",
            "CRITICAL"
        )

        # FAIL CLOSED
        return (
            "Nexora encountered an unexpected "
            "problem and stopped safely."
        )


# ============================================================
# WEB INTERFACE
# ============================================================

HTML = """
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
name="viewport"
content="width=device-width, initial-scale=1.0"
>

<title>Nexora</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    min-height: 100vh;

    font-family:
        Arial,
        sans-serif;

    color: white;

    background:
        radial-gradient(
            circle at top left,
            #260050,
            transparent 35%
        ),
        radial-gradient(
            circle at bottom right,
            #003c4c,
            transparent 35%
        ),
        #05000b;
}

.container {

    width: min(
        1000px,
        94%
    );

    margin:
        30px auto;

}

.header {

    text-align: center;

    margin-bottom: 20px;

}

.logo {

    font-size: 56px;

    font-weight: bold;

    background:
        linear-gradient(
            90deg,
            #ffffff,
            #65ffff,
            #d400ff
        );

    color: transparent;

    background-clip: text;

    -webkit-background-clip: text;

}

.slogan {

    color: #65ffff;

    letter-spacing: 4px;

}

.chat {

    height: 65vh;

    min-height: 400px;

    overflow-y: auto;

    padding: 20px;

    border:
        1px solid
        rgba(
            180,
            0,
            255,
            .45
        );

    border-radius: 18px;

    background:
        rgba(
            10,
            5,
            20,
            .85
        );

}

.message {

    max-width: 80%;

    padding: 13px 16px;

    margin:
        0 0 15px 0;

    border-radius: 15px;

    white-space: pre-wrap;

    line-height: 1.5;

}

.nexora {

    border-left:
        3px solid
        #65ffff;

    background:
        rgba(
            25,
            25,
            50,
            .8
        );

}

.user {

    margin-left: auto;

    background:
        linear-gradient(
            135deg,
            #7000ff,
            #c000ff
        );

}

.sender {

    display: block;

    font-size: 11px;

    font-weight: bold;

    letter-spacing: 2px;

    margin-bottom: 5px;

    color: #65ffff;

}

.composer {

    display: flex;

    gap: 10px;

    margin-top: 15px;

}

input {

    flex: 1;

    padding: 16px;

    border-radius: 12px;

    border:
        1px solid
        #8f00ff;

    background:
        #100819;

    color: white;

    outline: none;

}

button {

    padding:
        0 25px;

    border: 0;

    border-radius: 12px;

    color: white;

    font-weight: bold;

    background:
        linear-gradient(
            135deg,
            #7600ff,
            #c000ff
        );

    cursor: pointer;

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

</div>

<div
class="chat"
id="chat"
>

<div class="message nexora">

<span class="sender">
NEXORA
</span>

Hey! I'm Nexora. What are we working on?

</div>

</div>

<form
class="composer"
onsubmit="sendMessage(event)"
>

<input
id="message"
maxlength="4000"
autocomplete="off"
placeholder="Talk to Nexora..."
>

<button>
Send
</button>

</form>

</div>


<script>

function addMessage(
    sender,
    text,
    type
) {

    const chat =
        document.getElementById(
            "chat"
        );

    const message =
        document.createElement(
            "div"
        );

    message.className =
        "message " + type;


    const senderElement =
        document.createElement(
            "span"
        );

    senderElement.className =
        "sender";

    senderElement.textContent =
        sender;


    message.appendChild(
        senderElement
    );


    message.appendChild(
        document.createTextNode(
            text
        )
    );


    chat.appendChild(
        message
    );


    chat.scrollTop =
        chat.scrollHeight;
}


async function sendMessage(event) {

    event.preventDefault();


    const input =
        document.getElementById(
            "message"
        );


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
                            message: text
                        })
                }
            );


        const data =
            await response.json();


        addMessage(
            "NEXORA",
            data.reply ||
            "I couldn't safely answer that.",
            "nexora"
        );


    } catch (error) {

        addMessage(
            "NEXORA",
            "I couldn't connect to the Nexora server.",
            "nexora"
        );

    }

}

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


    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data
        ).encode(
            "utf-8"
        )

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(
            body
        )


    def do_GET(self):

        if self.path == "/":

            body = HTML.encode(
                "utf-8"
            )

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(body))
            )

            self.end_headers()

            self.wfile.write(body)

            return


        if self.path == "/health":

            self.send_json({

                "status": "ok",

                "name": APP_NAME,

                "version": VERSION,

                "safety": "enabled",

                "memory": "enabled",

                "lockdown":
                    is_locked()

            })

            return


        self.send_json(
            {"error": "Not found"},
            404
        )


    def do_POST(self):

        if self.path != "/api/chat":

            self.send_json(
                {"error": "Not found"},
                404
            )

            return


        try:

            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

        except ValueError:

            self.send_json(
                {"error": "Invalid request"},
                400
            )

            return


        if (
            content_length <= 0
            or content_length > JSON_LIMIT
        ):

            self.send_json(
                {"error": "Request too large"},
                413
            )

            return


        try:

            raw = self.rfile.read(
                content_length
            )


            data = json.loads(
                raw.decode(
                    "utf-8"
                )
            )


            message = data.get(
                "message"
            )


            if not isinstance(
                message,
                str
            ):

                self.send_json(
                    {"error": "Invalid message"},
                    400
                )

                return


            # Don't expose raw IP addresses.
            # Hash is only used as a rate-limit identifier.

            raw_client = (
                self.client_address[0]
            )

            client_id = hashlib_sha256(
                raw_client
            )


            reply = secure_process(
                message,
                client_id
            )


            self.send_json({
                "reply": reply
            })


        except Exception:

            security_event(
                "http_request_failure",
                "ERROR"
            )

            self.send_json(
                {
                    "error":
                    "The request could not be safely processed."
                },
                500
            )


    def log_message(
        self,
        format_string,
        *args
    ):

        # Don't print request contents.
        return


# ============================================================
# HASH HELPER
# ============================================================

def hashlib_sha256(value):

    import hashlib

    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# START
# ============================================================

def main():

    server = ThreadingHTTPServer(
        (HOST, PORT),
        NexoraHandler
    )

    print(
        f"{APP_NAME} Brain v{VERSION}"
    )

    print(
        f"Listening on port {PORT}"
    )

    print(
        "Defence in depth: ENABLED"
    )

    print(
        "Fail closed: ENABLED"
    )

    print(
        "Memory: ENABLED"
    )

    print(
        "Safety: ENABLED"
    )

    print(
        "Privacy protection: ENABLED"
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "Nexora stopped."
        )

    finally:

        server.server_close()


if __name__ == "__main__":
    main()
Render
