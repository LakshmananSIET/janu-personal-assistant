from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .task_parser import parse_task
from .task_store import save_task

app = FastAPI(title="Janu Personal Assistant", version="0.3.0")


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    task_created: bool = False
    task_id: int | None = None


def format_task_confirmation(task: dict, task_id: int) -> str:
    parts = [f"Okay Lakshman, I've noted: {task['task']}."]
    if task.get("due_date"):
        parts.append(f"Date: {task['due_date']}.")
    if task.get("deadline"):
        parts.append(f"Deadline: {task['deadline']}.")
    parts.append(f"I saved it as task {task_id}.")
    return " ".join(parts)


def janu_reply(message: str) -> ChatResponse:
    task = parse_task(message)

    if task:
        task_id = save_task(task)
        return ChatResponse(
            reply=format_task_confirmation(task, task_id),
            task_created=True,
            task_id=task_id,
        )

    text = message.strip()
    lower = text.lower()

    if not text:
        return ChatResponse(reply="I'm listening, Lakshman.")

    if "hello" in lower or "hi" in lower:
        return ChatResponse(reply="Hi Lakshman. I'm Janu. How can I help you?")

    if "thank" in lower:
        return ChatResponse(reply="You're welcome, Lakshman.")

    return ChatResponse(reply=f"Okay Lakshman, I heard you say: {text}")


HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Janu</title>
<style>
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; display:grid; place-items:center;
       background:#f5f7fb; font-family:Arial,sans-serif; }
.card { width:min(92vw,520px); padding:30px 24px; text-align:center;
        background:#fff; border-radius:28px; box-shadow:0 12px 40px rgba(0,0,0,.08); }
h1 { margin:0; font-size:34px; }
.subtitle { color:#666; margin:8px 0 24px; }
button { border:0; border-radius:999px; padding:16px 28px; font-size:18px;
         cursor:pointer; background:#111; color:white; }
button:disabled { opacity:.55; cursor:not-allowed; }
#status { color:#666; min-height:24px; margin-top:18px; }
#conversation { margin-top:20px; text-align:left; max-height:300px; overflow-y:auto; }
.msg { padding:10px 14px; margin:8px 0; border-radius:14px; background:#f0f2f5; }
.user { background:#e8f0ff; }
.label { font-size:12px; color:#777; }
</style>
</head>
<body>
<main class="card">
<h1>Janu</h1>
<div class="subtitle">Hi Lakshman, I'm Janu. How can I help you?</div>
<button id="voiceButton" onclick="startVoice()">🎙️ Talk to Janu</button>
<div id="status">Ready</div>
<section id="conversation"></section>
</main>

<script>
const button=document.getElementById("voiceButton");
const status=document.getElementById("status");
const conversation=document.getElementById("conversation");

function addMessage(who,text,cssClass) {
    const div=document.createElement("div");
    div.className="msg "+cssClass;
    const label=document.createElement("div");
    label.className="label";
    label.textContent=who;
    const body=document.createElement("div");
    body.textContent=text;
    div.append(label,body);
    conversation.appendChild(div);
    conversation.scrollTop=conversation.scrollHeight;
}

function speak(text) {
    return new Promise(resolve => {
        if (!("speechSynthesis" in window)) return resolve();
        window.speechSynthesis.cancel();
        const u=new SpeechSynthesisUtterance(text);
        u.lang="en-IN";
        u.rate=.95;
        u.pitch=1.05;
        u.onend=resolve;
        u.onerror=resolve;
        window.speechSynthesis.speak(u);
    });
}

async function askJanu(text) {
    const response=await fetch("/chat",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({message:text})
    });
    if(!response.ok) throw new Error("Backend error");
    return await response.json();
}

function startVoice() {
    const Recognition=window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!Recognition) {
        status.textContent="Speech recognition is not supported here.";
        return;
    }

    const recognition=new Recognition();
    recognition.lang="en-IN";
    recognition.interimResults=false;
    recognition.continuous=false;
    button.disabled=true;

    recognition.onstart=()=>status.textContent="Listening...";

    recognition.onresult=async event=>{
        const text=event.results[0][0].transcript;
        addMessage("You",text,"user");
        status.textContent="Janu is thinking...";

        try {
            const result=await askJanu(text);
            addMessage("Janu",result.reply,"assistant");
            status.textContent="Janu is speaking...";
            await speak(result.reply);
            status.textContent=result.task_created
                ? "Task saved ✓"
                : "Ready";
        } catch(error) {
            status.textContent="Could not contact Janu.";
        } finally {
            button.disabled=false;
        }
    };

    recognition.onerror=event=>{
        status.textContent="Voice error: "+event.error;
        button.disabled=false;
    };

    recognition.onend=()=>{
        if(button.disabled && status.textContent==="Listening...") {
            button.disabled=false;
            status.textContent="Ready";
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
    return {"status":"ok","assistant":"Janu","version":"0.3.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    return janu_reply(request.message)
