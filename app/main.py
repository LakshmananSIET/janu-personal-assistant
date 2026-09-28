from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .ai import get_ai_result
from .conversation import add_message, get_history, clear_session
from .task_parser import parse_task
from .task_store import list_tasks, save_task, update_task_status

app = FastAPI(title="Janu Personal Assistant", version="0.6.0")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    task_created: bool = False
    task_id: int | None = None
    session_id: str


def format_task_confirmation(task: dict, task_id: int) -> str:
    parts = [f"Okay Lakshman, I've noted: {task['task']}."]
    if task.get("due_date"):
        parts.append(f"Date: {task['due_date']}.")
    if task.get("deadline"):
        parts.append(f"Deadline: {task['deadline']}.")
    parts.append(f"I saved it as task {task_id}.")
    return " ".join(parts)


def format_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "You don't have any pending tasks right now."
    lines = ["Here are your pending tasks:"]
    for item in tasks:
        detail = f"{item['id']}. {item['task']}"
        if item.get("due_date"):
            detail += f" — {item['due_date']}"
        if item.get("deadline"):
            detail += f" by {item['deadline']}"
        lines.append(detail)
    return " ".join(lines)


def janu_reply(message: str, session_id: str) -> ChatResponse:
    history = get_history(session_id)
    try:
        ai_result = get_ai_result(message, history)
    except Exception:
        ai_result = None

    if ai_result:
        intent = ai_result.get("intent", "chat")

        if intent == "create_task" and ai_result.get("task"):
            task = {
                "task": ai_result["task"],
                "due_date": ai_result.get("due_date"),
                "deadline": ai_result.get("deadline"),
                "status": "pending",
                "source_text": message,
            }
            task_id = save_task(task)
            reply = ai_result.get("reply") or format_task_confirmation(task, task_id)
            add_message(session_id, "user", message)
            add_message(session_id, "assistant", reply)
            return ChatResponse(reply=reply, task_created=True, task_id=task_id, session_id=session_id)

        if intent == "list_tasks":
            reply = format_tasks(list_tasks())
        elif intent == "complete_task":
            task_id = ai_result.get("task_id")
            if task_id and update_task_status(task_id, "completed"):
                reply = ai_result.get("reply") or f"Done. I've marked task {task_id} as completed."
            else:
                reply = "I couldn't identify that task. Please tell me the task number."
        else:
            reply = ai_result.get("reply", "I'm listening, Lakshman.")

        add_message(session_id, "user", message)
        add_message(session_id, "assistant", reply)
        return ChatResponse(reply=reply, session_id=session_id)

    # Offline fallback when no API key is configured.
    task = parse_task(message)
    if task:
        task_id = save_task(task)
        reply = format_task_confirmation(task, task_id)
    else:
        text = message.strip()
        lower = text.lower()
        if not text:
            reply = "I'm listening, Lakshman."
        elif "show" in lower and "task" in lower:
            reply = format_tasks(list_tasks())
        elif "thank" in lower:
            reply = "You're welcome, Lakshman."
        elif "hello" in lower or lower == "hi":
            reply = "Hi Lakshman. I'm Janu. How can I help you?"
        else:
            reply = f"Okay Lakshman, I heard you say: {text}"

    add_message(session_id, "user", message)
    add_message(session_id, "assistant", reply)
    return ChatResponse(
        reply=reply,
        task_created=bool(task),
        task_id=task_id if task else None,
        session_id=session_id,
    )


HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Janu — Personal Assistant</title>
<style>
*{box-sizing:border-box} body{margin:0;min-height:100vh;display:grid;place-items:center;
background:linear-gradient(135deg,#f7f8fc,#eef2ff);font-family:Arial,sans-serif}
.card{width:min(94vw,620px);padding:28px 22px;background:#fff;border-radius:28px;
box-shadow:0 16px 50px rgba(0,0,0,.09)} h1{text-align:center;margin:0;font-size:36px}
.subtitle{text-align:center;color:#666;margin:8px 0 20px}.controls{text-align:center}
button{border:0;border-radius:999px;padding:13px 18px;margin:4px;font-size:16px;
cursor:pointer;background:#111;color:#fff}button:disabled{opacity:.5}
#status{text-align:center;color:#666;min-height:24px;margin:15px 0}
#conversation{max-height:360px;overflow:auto}.msg{padding:11px 14px;margin:8px 0;
border-radius:15px;background:#f1f3f6}.user{background:#e8f0ff}.label{font-size:12px;color:#777;margin-bottom:3px}
</style>
</head>
<body>
<main class="card">
<h1>Janu</h1>
<div class="subtitle">Hi Lakshman, I'm Janu. How can I help you?</div>
<div class="controls">
<button id="voiceButton" onclick="startConversation()">🎙️ Start Conversation</button>
<button id="stopButton" onclick="stopConversation()" disabled>⏹ Stop</button>
<button onclick="clearConversation()">🗑 Clear</button>
</div>
<div id="status">Ready</div>
<section id="conversation"></section>
</main>
<script>
const voiceButton=document.getElementById("voiceButton");
const stopButton=document.getElementById("stopButton");
const status=document.getElementById("status");
const conversation=document.getElementById("conversation");
let recognition=null, active=false, speaking=false;
let sessionId=localStorage.getItem("janu_session_id");
if(!sessionId){sessionId=crypto.randomUUID();localStorage.setItem("janu_session_id",sessionId);}

function addMessage(who,text,cls){
  const div=document.createElement("div"); div.className="msg "+cls;
  const label=document.createElement("div"); label.className="label"; label.textContent=who;
  const body=document.createElement("div"); body.textContent=text;
  div.append(label,body); conversation.appendChild(div); conversation.scrollTop=conversation.scrollHeight;
}
function chooseFemaleVoice(){
  const voices=speechSynthesis.getVoices();
  const preferred=["female","samantha","zira","heera","google uk english female","microsoft heera"];
  return voices.find(v=>v.lang.toLowerCase().startsWith("en-in") && preferred.some(x=>v.name.toLowerCase().includes(x)))
      || voices.find(v=>preferred.some(x=>v.name.toLowerCase().includes(x)))
      || voices.find(v=>v.lang.toLowerCase().startsWith("en-in"))
      || null;
}
function speak(text){
  return new Promise(resolve=>{
    if(!("speechSynthesis" in window)) return resolve();
    speaking=true; speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(text); u.lang="en-IN"; u.rate=.95; u.pitch=1.05;
    const voice=chooseFemaleVoice(); if(voice) u.voice=voice;
    u.onend=()=>{speaking=false;resolve()}; u.onerror=()=>{speaking=false;resolve()};
    speechSynthesis.speak(u);
  });
}
async function askJanu(text){
  const r=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({message:text,session_id:sessionId})});
  if(!r.ok) throw new Error("Backend error");
  return r.json();
}
function startConversation(){
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Recognition){status.textContent="Speech recognition is not supported in this browser.";return}
  active=true; voiceButton.disabled=true; stopButton.disabled=false;
  recognition=new Recognition(); recognition.lang="en-IN"; recognition.interimResults=false; recognition.continuous=false;
  recognition.onstart=()=>status.textContent="Listening...";
  recognition.onresult=async e=>{
    const text=e.results[0][0].transcript; addMessage("You",text,"user"); status.textContent="Janu is thinking...";
    try{
      const result=await askJanu(text); addMessage("Janu",result.reply,"assistant");
      status.textContent="Janu is speaking..."; await speak(result.reply);
      if(active)setTimeout(startListening,250);
    }catch(err){status.textContent="Could not contact Janu.";if(active)setTimeout(startListening,1000)}
  };
  recognition.onerror=e=>{if(!active)return;if(e.error==="no-speech"||e.error==="aborted")setTimeout(startListening,300);else setTimeout(startListening,1000)};
  recognition.onend=()=>{if(active&&!speaking)setTimeout(startListening,250)};
  startListening();
}
function startListening(){if(!active||speaking||!recognition)return;try{recognition.start()}catch(e){setTimeout(startListening,500)}}
function stopConversation(){
  active=false; speaking=false; try{recognition&&recognition.stop()}catch(e){}
  speechSynthesis?.cancel(); voiceButton.disabled=false; stopButton.disabled=true; status.textContent="Conversation stopped";
}
async function clearConversation(){
  stopConversation(); conversation.innerHTML="";
  const oldSession=sessionId;
  sessionId=crypto.randomUUID(); localStorage.setItem("janu_session_id",sessionId);
  try{await fetch("/session/"+oldSession,{method:"DELETE"})}catch(e){}
  status.textContent="New conversation ready";
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
    return {"status": "ok", "assistant": "Janu", "version": "0.6.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    return janu_reply(request.message, session_id)


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    clear_session(session_id)
    return {"status": "ok"}
