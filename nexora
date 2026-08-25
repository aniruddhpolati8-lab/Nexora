import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nexora — Intelligence. Secured.</title>

    <style>
        @import url("https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@600;700&display=swap");

        :root {
            --background: #080512;
            --panel: rgba(22, 12, 39, 0.86);
            --panel-light: rgba(42, 20, 69, 0.8);
            --purple: #a100ff;
            --electric-purple: #d000ff;
            --violet: #661cff;
            --cyan: #6ffcff;
            --text: #fffaff;
            --muted: #b9a9c9;
        }

        * {
            box-sizing: border-box;
        }

        body {
            min-height: 100vh;
            margin: 0;
            color: var(--text);
            font-family: "DM Sans", Arial, sans-serif;
            background:
                radial-gradient(circle at 15% 15%, rgba(112, 20, 255, .36), transparent 30%),
                radial-gradient(circle at 85% 20%, rgba(208, 0, 255, .28), transparent 30%),
                radial-gradient(circle at 55% 100%, rgba(0, 220, 255, .15), transparent 34%),
                linear-gradient(135deg, #080512, #150623 48%, #26053c);
        }

        .page {
            display: flex;
            justify-content: center;
            min-height: 100vh;
            padding: 32px 18px;
        }

        .app {
            display: flex;
            width: min(1080px, 100%);
            min-height: calc(100vh - 64px);
            overflow: hidden;
            border: 1px solid rgba(208, 0, 255, .45);
            border-radius: 26px;
            background: rgba(8, 5, 18, .62);
            box-shadow:
                0 0 35px rgba(208, 0, 255, .2),
                0 25px 90px rgba(0, 0, 0, .42);
            backdrop-filter: blur(18px);
        }

        .sidebar {
            width: 245px;
            flex-shrink: 0;
            padding: 30px 20px;
            border-right: 1px solid rgba(208, 0, 255, .25);
            background: rgba(13, 7, 25, .8);
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo {
            display: grid;
            place-items: center;
            width: 46px;
            height: 46px;
            border: 2px solid var(--cyan);
            border-radius: 15px;
            color: white;
            font: 700 25px "Playfair Display", Georgia, serif;
            background: linear-gradient(135deg, var(--electric-purple), var(--violet));
            box-shadow: 0 0 25px rgba(208, 0, 255, .7);
        }

        .brand-name {
            font: 700 24px "Playfair Display", Georgia, serif;
        }

        .slogan {
            margin: 9px 0 42px 3px;
            color: var(--cyan);
            font-size: 12px;
            letter-spacing: .8px;
        }

        .sidebar-button {
            width: 100%;
            margin: 5px 0;
            padding: 13px;
            border: 1px solid transparent;
            border-radius: 12px;
            color: var(--muted);
            text-align: left;
            font: inherit;
            background: transparent;
            cursor: pointer;
        }

        .sidebar-button:hover {
            border-color: rgba(208, 0, 255, .3);
            color: white;
            background: rgba(208, 0, 255, .15);
        }

        .connection {
            margin-top: 42px;
            padding: 14px;
            border: 1px solid rgba(111, 252, 255, .2);
            border-radius: 14px;
            color: var(--muted);
            font-size: 12px;
        }

        .online {
            margin-bottom: 7px;
            color: #58f39a;
            font-weight: 700;
        }

        .content {
            display: flex;
            flex: 1;
            flex-direction: column;
            min-width: 0;
            padding: 42px clamp(20px, 5vw, 62px);
        }

        .header {
            margin-bottom: 28px;
            text-align: center;
        }

        .header-label {
            margin: 0 0 8px;
            color: var(--cyan);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 3px;
        }

        h1 {
            margin: 0;
            font: 700 clamp(38px, 6vw, 64px) "Playfair Display", Georgia, serif;
            background: linear-gradient(90deg, white, var(--cyan), #e09aff);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }

        .header-slogan {
            margin: 10px 0 0;
            color: var(--muted);
            font-size: 14px;
            letter-spacing: 2px;
        }

        .chat {
            flex: 1;
            min-height: 360px;
            overflow-y: auto;
            padding: 25px;
            border: 1px solid rgba(208, 0, 255, .4);
            border-radius: 18px;
            background: rgba(10, 5, 22, .68);
        }

        .message {
            max-width: 82%;
            margin-bottom: 22px;
            line-height: 1.6;
            white-space: pre-wrap;
        }

        .message.nexora {
            padding-left: 14px;
            border-left: 2px solid var(--cyan);
        }

        .message.user {
            margin-left: auto;
            padding: 13px 17px;
            border-radius: 16px 16px 3px 16px;
            background: linear-gradient(135deg, #8d19df, #5315bb);
            box-shadow: 0 8px 25px rgba(91, 0, 170, .25);
        }

        .sender {
            display: block;
            margin-bottom: 5px;
            color: var(--cyan);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 1.5px;
        }

        .user .sender {
            color: #f1caff;
        }

        .composer {
            display: flex;
            gap: 10px;
            margin-top: 17px;
        }

        input {
            flex: 1;
            min-width: 0;
            padding: 16px 18px;
            outline: none;
            border: 1px solid rgba(208, 0, 255, .7);
            border-radius: 13px;
            color: white;
            font: inherit;
            background: var(--panel-light);
        }

        input::placeholder {
            color: #a894b8;
        }

        input:focus {
            border-color: var(--cyan);
            box-shadow: 0 0 18px rgba(111, 252, 255, .2);
        }

        .send {
            padding: 0 22px;
            border: 0;
            border-radius: 13px;
            color: white;
            font: inherit;
            font-weight: 700;
            background: linear-gradient(135deg, var(--electric-purple), var(--violet));
            box-shadow: 0 0 22px rgba(208, 0, 255, .4);
            cursor: pointer;
        }

        .send:hover {
            filter: brightness(1.2);
        }

        .note {
            margin: 12px 0 0;
            color: #796b86;
            text-align: center;
            font-size: 11px;
        }

        @media (max-width: 700px) {
            .page {
                padding: 0;
            }

            .app {
                min-height: 100vh;
                border: 0;
                border-radius: 0;
            }

            .sidebar {
                display: none;
            }

            .content {
                padding: 28px 16px;
            }

            .chat {
                padding: 18px;
            }

            .composer {
                flex-wrap: wrap;
            }

            input {
                flex-basis: 100%;
            }

            .send {
                height: 48px;
            }
        }
    </style>
</head>
<body>
    <div class="page">
        <div class="app">
            <aside class="sidebar">
                <div class="brand">
                    <div class="logo">N</div>
                    <div class="brand-name">Nexora</div>
                </div>

                <p class="slogan">Intelligence. Secured.</p>

                <button class="sidebar-button" onclick="newConversation()">
                    ＋ New conversation
                </button>

                <button class="sidebar-button" onclick="showNotice('Your local research workspace is ready.')">
                    ⌕ Research workspace
                </button>

                <button class="sidebar-button" onclick="showNotice('Nexora is running without an external API key.')">
                    ⚙ Local settings
                </button>

                <div class="connection">
                    <div class="online">● ONLINE</div>
                    Local Nexora server<br>
                    No API key required
                </div>
            </aside>

            <main class="content">
                <header class="header">
                    <p class="header-label">WELCOME TO</p>
                    <h1>Nexora</h1>
                    <p class="header-slogan">Intelligence. Secured.</p>
                </header>

                <section class="chat" id="chat">
                    <div class="message nexora">
                        <span class="sender">NEXORA</span>
                        Welcome. Type a message below and I’ll respond with a temporary local placeholder.
                    </div>
                </section>

                <form class="composer" onsubmit="sendMessage(event)">
                    <input
                        id="message"
                        type="text"
                        autocomplete="off"
                        placeholder="Ask Nexora anything..."
                        autofocus
                    >
                    <button class="send" type="submit">Send</button>
                </form>

                <p class="note">Nexora is currently using placeholder responses. An AI model can be connected later.</p>
            </main>
        </div>
    </div>

    <script>
        function escapeHtml(value) {
            const element = document.createElement("div");
            element.textContent = value;
            return element.innerHTML;
        }

        function addMessage(sender, text, type) {
            const message = document.createElement("div");
            message.className = "message " + type;
            message.innerHTML =
                '<span class="sender">' + sender + "</span>" +
                escapeHtml(text);

            const chat = document.getElementById("chat");
            chat.appendChild(message);
            chat.scrollTop = chat.scrollHeight;
        }

        function showNotice(text) {
            addMessage("NEXORA", text, "nexora");
        }

        function newConversation() {
            document.getElementById("chat").innerHTML = "";
            showNotice("A new conversation is ready.");
        }

        async function sendMessage(event) {
            event.preventDefault();

            const input = document.getElementById("message");
            const text = input.value.trim();

            if (!text) {
                return;
            }

            addMessage("YOU", text, "user");
            input.value = "";
            input.disabled = true;

            try {
                const response = await fetch("/api/chat", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ message: text })
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || "Request failed");
                }

                addMessage("NEXORA", data.reply, "nexora");
            } catch (error) {
                showNotice("The server could not process that message.");
            } finally {
                input.disabled = false;
                input.focus();
            }
        }
    </script>
</body>
</html>
"""


class NexoraHandler(BaseHTTPRequestHandler):
    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self.send_bytes(HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/health":
            self.send_json({"status": "ok", "agent": "Nexora"})
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self.send_json({"error": "Not found"}, 404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))

            if content_length > 1_000_000:
                self.send_json({"error": "Request is too large"}, 413)
                return

            raw_body = self.rfile.read(content_length)
            data = json.loads(raw_body.decode("utf-8"))
            message = str(data.get("message", "")).strip()

            if not message:
                self.send_json({"error": "Message cannot be empty"}, 400)
                return

            reply = (
                f"I received your message: “{message}”\n\n"
                "This is a temporary Nexora placeholder response. "
                "The backend is connected and ready for an AI model."
            )

            self.send_json({"reply": reply})

        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json({"error": "Invalid JSON request"}, 400)
        except Exception:
            self.send_json({"error": "Internal server error"}, 500)

    def log_message(self, format_string, *args):
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), NexoraHandler)

    print(f"Nexora is running on port {PORT}")
    print("Listening on 0.0.0.0")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nNexora stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
