from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Janu Personal Assistant", version="0.1.0")

HTML = """
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Janu</title>
    <style>
        body {
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: #f7f7f7;
            font-family: Arial, sans-serif;
        }
        .card {
            width: min(92%, 520px);
            padding: 32px;
            text-align: center;
            background: white;
            border-radius: 24px;
            box-shadow: 0 10px 35px rgba(0,0,0,.08);
        }
        h1 { margin-bottom: 8px; }
        p { color: #666; }
        button {
            border: 0;
            border-radius: 999px;
            padding: 16px 28px;
            font-size: 18px;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <main class="card">
        <h1>Janu</h1>
        <p>Hi Lakshman, I'm Janu. How can I help you?</p>
        <button onclick="startVoice()">🎙️ Start Voice</button>
        <p id="status">Ready</p>
    </main>
    <script>
        function startVoice() {
            const status = document.getElementById("status");
            const SpeechRecognition =
                window.SpeechRecognition || window.webkitSpeechRecognition;

            if (!SpeechRecognition) {
                status.textContent = "Voice recognition is not supported in this browser.";
                return;
            }

            const recognition = new SpeechRecognition();
            recognition.lang = "en-IN";
            recognition.interimResults = false;
            recognition.continuous = false;

            recognition.onstart = () => {
                status.textContent = "Listening...";
            };

            recognition.onresult = (event) => {
                const text = event.results[0][0].transcript;
                status.textContent = "You said: " + text;
            };

            recognition.onerror = (event) => {
                status.textContent = "Voice error: " + event.error;
            };

            recognition.onend = () => {
                if (status.textContent === "Listening...") {
                    status.textContent = "Ready";
                }
            };

            recognition.start();
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML

@app.get("/health")
async def health():
    return {"status": "ok", "assistant": "Janu", "version": "0.1.0"}
