import ast
import json
import os
import random
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))

# ============================================================
# NEXORA
# ============================================================

NAME = "Nexora"
SLOGAN = "Intelligence. Secured."

# ============================================================
# CONVERSATION MEMORY
# ============================================================

MAX_MEMORY = 30
memory = []


def remember(role, text):
    memory.append({
        "role": role,
        "text": text
    })

    if len(memory) > MAX_MEMORY:
        del memory[0]


def recent_memory():
    return memory[-MAX_MEMORY:]


# ============================================================
# KNOWLEDGE BASE
# ============================================================

KNOWLEDGE = {
    "name": "Nexora",
    "slogan": SLOGAN,
    "description": (
        "Nexora is a coded AI assistant designed to be "
        "helpful, useful and safety-conscious."
    ),
    "version": "2.0",
    "creator": "Nexora's creator",
}


# ============================================================
# SAFETY SYSTEM
# ============================================================

BLOCKED_PATTERNS = [
    r"\bhow to make a bomb\b",
    r"\bhow to make an explosive\b",
    r"\bhow to poison someone\b",
    r"\bhow to hurt someone\b",
]


def safety_check(text):
    lowered = text.lower()

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, lowered):
            return False

    return True


# ============================================================
# INTENT SYSTEM
# ============================================================

def detect_intent(text):
    t = text.lower().strip()

    if not t:
        return "empty"

    if any(x in t for x in [
        "hello",
        "hi",
        "hey",
        "hiya",
        "good morning",
        "good afternoon",
        "good evening"
    ]):
        return "greeting"

    if any(x in t for x in [
        "bye",
        "goodbye",
        "see you",
        "see ya"
    ]):
        return "goodbye"

    if any(x in t for x in [
        "who are you",
        "what are you",
        "what is nexora"
    ]):
        return "identity"

    if any(x in t for x in [
        "what can you do",
        "help me",
        "help",
        "capabilities"
    ]):
        return "help"

    if any(x in t for x in [
        "what time",
        "current time",
        "time is it"
    ]):
        return "time"

    if any(x in t for x in [
        "what date",
        "today's date",
        "what day"
    ]):
        return "date"

    if t.startswith("calculate "):
        return "calculate"

    if t.startswith("calc "):
        return "calculate"

    if t.startswith("remember "):
        return "remember"

    if t in ["forget", "forget everything", "clear memory"]:
        return "forget"

    if "?" in t:
        return "question"

    question_words = (
        "what ",
        "why ",
        "when ",
        "where ",
        "who ",
        "how ",
        "can ",
        "could ",
        "would ",
        "is ",
        "are ",
        "do ",
        "does "
    )

    if t.startswith(question_words):
        return "question"

    return "conversation"


# ============================================================
# KNOWLEDGE SYSTEM
# ============================================================

def knowledge_lookup(text):
    t = text.lower()

    if "your name" in t:
        return f"My name is {NAME}."

    if "slogan" in t:
        return f"My slogan is: {SLOGAN}"

    if "version" in t:
        return f"I'm running Nexora version {KNOWLEDGE['version']}."

    if "who created you" in t or "who made you" in t:
        return f"I was created by {KNOWLEDGE['creator']}."

    if "what is nexora" in t:
        return KNOWLEDGE["description"]

    return None


# ============================================================
# SAFE CALCULATOR
# ============================================================

ALLOWED_OPERATORS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}


def safe_calculate(expression):
    expression = expression.strip()

    if len(expression) > 100:
        return None

    try:
        tree = ast.parse(
            expression,
            mode="eval"
        )

        def evaluate(node):

            if isinstance(node, ast.Expression):
                return evaluate(node.body)

            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)):
                    return node.value
                raise ValueError()

            if isinstance(node, ast.BinOp):
                operator = ALLOWED_OPERATORS.get(
                    type(node.op)
                )

                if operator is None:
                    raise ValueError()

                left = evaluate(node.left)
                right = evaluate(node.right)

                return operator(left, right)

            if isinstance(node, ast.UnaryOp):
                value = evaluate(node.operand)

                if isinstance(node.op, ast.USub):
                    return -value

                if isinstance(node.op, ast.UAdd):
                    return value

            raise ValueError()

        result = evaluate(tree)

        if isinstance(result, float):
            return round(result, 10)

        return result

    except Exception:
        return None


# ============================================================
# RESPONSE GENERATOR
# ============================================================

def generate_response(message, intent):

    text = message.strip()

    # Knowledge comes first
    answer = knowledge_lookup(text)

    if answer:
        return answer

    # Greeting
    if intent == "greeting":

        return random.choice([
            "Hello! Nexora is online. What can I help you with?",
            "Hey! I'm Nexora. What are we working on today?",
            "Hello! I'm ready when you are.",
            "Hi! What would you like to explore?"
        ])

    # Goodbye
    if intent == "goodbye":

        return random.choice([
            "Goodbye! I'll be here when you return.",
            "See you later!",
            "Take care!",
            "Nexora signing off."
        ])

    # Identity
    if intent == "identity":

        return (
            "I'm Nexora — a coded AI assistant. "
            "My current brain uses memory, intent detection, "
            "knowledge, tools, response generation and safety checks."
        )

    # Help
    if intent == "help":

        return (
            "I can remember our current conversation, "
            "recognise different types of requests, "
            "answer questions from my knowledge base, "
            "perform calculations and handle several commands."
        )

    # Time
    if intent == "time":

        now = datetime.now()

        return (
            "The current server time is "
            + now.strftime("%H:%M:%S")
            + "."
        )

    # Date
    if intent == "date":

        now = datetime.now()

        return (
            "Today's date is "
            + now.strftime("%A, %d %B %Y")
            + "."
        )

    # Calculator
    if intent == "calculate":

        expression = re.sub(
            r"^(calculate|calc)\s+",
            "",
            text,
            flags=re.IGNORECASE
        )

        result = safe_calculate(expression)

        if result is None:
            return (
                "I couldn't safely calculate that. "
                "Try something like: calculate 25 * 4"
            )

        return f"The answer is {result}."

    # Remember
    if intent == "remember":

        information = re.sub(
            r"^remember\s+",
            "",
            text,
            flags=re.IGNORECASE
        ).strip()

        if not information:
            return "Tell me what you'd like me to remember."

        remember(
            "memory",
            information
        )

        return (
            "I'll keep that in the current conversation."
        )

    # Forget
    if intent == "forget":

        memory.clear()

        return (
            "Current conversation memory cleared."
        )

    # Question
    if intent == "question":

        return random.choice([
            "That's a good question. I don't have enough information in my current knowledge base to answer it yet.",
            "I understand the question, but my current knowledge system doesn't contain that information yet.",
            "I'd need more knowledge to give you a reliable answer to that.",
        ])

    # General conversation
    return random.choice([
        "Interesting. Tell me more.",
        "I'm following you. What should we look at next?",
        "Got it. What would you like to do with that?",
        "I understand. Keep going.",
        "That makes sense.",
    ])


# ============================================================
# AI MODEL CONNECTOR
# ============================================================

def ai_model(message, history):

    """
    This is the future model connection point.

    For now, Nexora's coded brain handles the response.

    Later, a real pretrained language model can replace
    this function without rebuilding the whole website.
    """

    intent = detect_intent(message)

    return generate_response(
        message,
        intent
    )


# ============================================================
# NEXORA BRAIN
# ============================================================

def process_message(message):

    message = message.strip()

    if not message:
        return "Please type a message."

    # Input safety
    if not safety_check(message):

        return (
            "I can't help with dangerous instructions. "
            "Let's try something safer."
        )

    # Remember user message
    remember(
        "user",
        message
    )

    # Generate response
    response = ai_model(
        message,
        recent_memory()
    )

    # Output safety
    if not safety_check(response):

        response = (
            "I can't provide that response."
        )

    # Remember Nexora response
    remember(
        "nexora",
        response
    )

    return response


# ============================================================
# WEB INTERFACE
# ============================================================

HTML = r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>Nexora — Intelligence. Secured.</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    min-height: 100vh;

    font-family: Arial, sans-serif;

    color: white;

    background:
        radial-gradient(
            circle at 15% 20%,
            rgba(0,255,255,.22),
            transparent 30%
        ),
        radial-gradient(
            circle at 85% 20%,
            rgba(190,0,255,.28),
            transparent 35%
        ),
        linear-gradient(
            135deg,
            #05000d,
            #12001f,
            #080018
        );
}

.app {

    width: min(1000px, 92%);

    min-height: 90vh;

    margin: 5vh auto;

    display: flex;

    flex-direction: column;

}

.header {

    text-align: center;

    padding: 25px;

}

.header h1 {

    margin: 0;

    font-size: 60px;

    background:
        linear-gradient(
            90deg,
            white,
            #6fffff,
            #d000ff
        );

    -webkit-background-clip: text;

    background-clip: text;

    color: transparent;

}

.header p {

    color: #6fffff;

    letter-spacing: 4px;

}

.chat {

    flex: 1;

    min-height: 450px;

    overflow-y: auto;

    padding: 25px;

    border: 1px solid rgba(208,0,255,.45);

    border-radius: 20px;

    background: rgba(10,5,22,.78);

    box-shadow:
        0 0 40px rgba(208,0,255,.12);

}

.message {

    max-width: 82%;

    margin-bottom: 18px;

    padding: 14px 17px;

    line-height: 1.6;

    border-radius: 15px;

    white-space: pre-wrap;

}

.message.nexora {

    border-left: 3px solid #6fffff;

    background: rgba(20,20,45,.65);

}

.message.user {

    margin-left: auto;

    background:
        linear-gradient(
            135deg,
            #7c00ff,
            #b000ff
        );

}

.sender {

    display: block;

    margin-bottom: 5px;

    color: #6fffff;

    font-size: 11px;

    font-weight: bold;

    letter-spacing: 2px;

}

.composer {

    display: flex;

    gap: 10px;

    margin-top: 15px;

}

input {

    flex: 1;

    min-width: 0;

    padding: 16px;

    border: 1px solid #a000ff;

    border-radius: 12px;

    outline: none;

    color: white;

    background: rgba(20,10,35,.9);

}

button {

    padding: 0 25px;

    border: 0;

    border-radius: 12px;

    color: white;

    font-weight: bold;

    background:
        linear-gradient(
            135deg,
            #d000ff,
            #6c00ff
        );

    cursor: pointer;

}

button:hover {

    filter: brightness(1.2);

}

</style>

</head>

<body>

<div class="app">

<div class="header">

<h1>Nexora</h1>

<p>INTELLIGENCE. SECURED.</p>

</div>

<div class="chat" id="chat">

<div class="message nexora">

<span class="sender">NEXORA</span>

Hello. I'm Nexora.

My Brain v2 is online.

</div>

</div>

<form
class="composer"
onsubmit="sendMessage(event)"
>

<input
id="message"
autocomplete="off"
placeholder="Ask Nexora anything..."
>

<button type="submit">
Send
</button>

</form>

</div>

<script>

function addMessage(sender, text, type) {

    const message =
        document.createElement("div");

    message.className =
        "message " + type;

    const senderElement =
        document.createElement("span");

    senderElement.className =
        "sender";

    senderElement.textContent =
        sender;

    message.appendChild(
        senderElement
    );

    message.appendChild(
        document.createTextNode(text)
    );

    const chat =
        document.getElementById("chat");

    chat.appendChild(message);

    chat.scrollTop =
        chat.scrollHeight;
}


async function sendMessage(event) {

    event.preventDefault();

    const input =
        document.getElementById("message");

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

    input.disabled = true;

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
            "I couldn't generate a response.",
            "nexora"
        );

    } catch (error) {

        addMessage(
            "NEXORA",
            "I couldn't connect to my backend.",
            "nexora"
        );

    } finally {

        input.disabled = false;

        input.focus();

    }

}

</script>

</body>

</html>
"""


# ============================================================
# HTTP SERVER
# ============================================================

class NexoraHandler(BaseHTTPRequestHandler):

    def send_bytes(
        self,
        body,
        content_type,
        status=200
    ):

        self.send_response(status)

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.end_headers()

        self.wfile.write(body)


    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data
        ).encode("utf-8")

        self.send_bytes(
            body,
            "application/json; charset=utf-8",
            status
        )


    def do_GET(self):

        path = urlparse(
            self.path
        ).path

        if path == "/":

            self.send_bytes(
                HTML.encode("utf-8"),
                "text/html; charset=utf-8"
            )

        elif path == "/health":

            self.send_json({
                "status": "ok",
                "agent": NAME,
                "brain": "v2"
            })

        else:

            self.send_json(
                {"error": "Not found"},
                404
            )


    def do_POST(self):

        path = urlparse(
            self.path
        ).path

        if path != "/api/chat":

            self.send_json(
                {"error": "Not found"},
                404
            )

            return

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            if length > 1_000_000:

                self.send_json(
                    {"error": "Request too large"},
                    413
                )

                return

            body = self.rfile.read(
                length
            )

            data = json.loads(
                body.decode("utf-8")
            )

            message = str(
                data.get("message", "")
            ).strip()

            if not message:

                self.send_json(
                    {"error": "Message cannot be empty"},
                    400
                )

                return

            reply = process_message(
                message
            )

            self.send_json({
                "reply": reply
            })

        except json.JSONDecodeError:

            self.send_json(
                {"error": "Invalid JSON"},
                400
            )

        except Exception as error:

            print(
                "SERVER ERROR:",
                error
            )

            self.send_json(
                {"error": "Internal server error"},
                500
            )


    def log_message(
        self,
        format_string,
        *args
    ):

        return


# ============================================================
# START SERVER
# ============================================================

def main():

    server = ThreadingHTTPServer(
        (HOST, PORT),
        NexoraHandler
    )

    print(
        f"{NAME} is running on port {PORT}"
    )

    print(
        "Brain v2: ONLINE"
    )

    print(
        "Memory: ENABLED"
    )

    print(
        "Intent system: ENABLED"
    )

    print(
        "Knowledge system: ENABLED"
    )

    print(
        "Calculator: ENABLED"
    )

    print(
        "Safety system: ENABLED"
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nNexora stopped."
        )

    finally:

        server.server_close()


if __name__ == "__main__":
    main()
