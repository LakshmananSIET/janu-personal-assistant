from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import suppress

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .ai import get_ai_result
from .conversation import add_message, get_history, clear_session
from .task_parser import parse_task
from .task_store import get_due_reminders, list_tasks, mark_reminder_sent, save_task, update_task_status
from .push_store import list_subscriptions, remove_subscription, save_subscription

app = FastAPI(title="Janu Personal Assistant", version="0.9.0")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict


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
                "reminder_at": ai_result.get("reminder_at"),
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


def _vapid_public_key() -> str | None:
    return os.getenv("VAPID_PUBLIC_KEY")


async def reminder_worker():
    while True:
        try:
            from datetime import datetime, timezone
            from pywebpush import webpush, WebPushException
            private_key = os.getenv("VAPID_PRIVATE_KEY")
            if private_key and _vapid_public_key():
                for _, task in get_due_reminders(datetime.now(timezone.utc)):
                    payload = json.dumps({"title":"Janu reminder","body":f"Lakshman, remember: {task['task']}","url":f"/?reminder={task['id']}","task_id":task["id"]})
                    for subscription in list_subscriptions():
                        try:
                            webpush(subscription_info=subscription,data=payload,vapid_private_key=private_key,vapid_claims={"sub":os.getenv("VAPID_SUBJECT","mailto:admin@example.com")})
                        except WebPushException as exc:
                            if getattr(exc.response,"status_code",None) in (404,410):
                                remove_subscription(subscription.get("endpoint",""))
                    mark_reminder_sent(task["id"])
        except Exception:
            pass
        await asyncio.sleep(20)


@app.on_event("startup")
async def startup_event():
    app.state.reminder_task = asyncio.create_task(reminder_worker())


@app.on_event("shutdown")
async def shutdown_event():
    task = getattr(app.state, "reminder_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@app.get("/push/public-key")
async def push_public_key():
    return {"public_key": _vapid_public_key()}


@app.post("/push/subscribe")
async def push_subscribe(subscription: PushSubscription):
    save_subscription(subscription.model_dump())
    return {"status":"subscribed"}


@app.delete("/push/subscribe")
async def push_unsubscribe(subscription: PushSubscription):
    remove_subscription(subscription.endpoint)
    return {"status":"unsubscribed"}


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
#conversation{max-height:360px;overflow:auto;margin-top:12px;border-top:1px solid #eee;padding-top:8px}.msg{padding:11px 14px;margin:8px 0;
border-radius:15px;background:#f1f3f6}.user{background:#e8f0ff}.assistant{background:#f4f4f4}.label{font-size:12px;color:#777;margin-bottom:3px}
#liveTranscript{margin-top:12px;padding:12px 14px;border-radius:14px;background:#fafafa;border:1px dashed #ccc;color:#555;min-height:46px;text-align:left}
#liveTranscript strong{color:#222}
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
<div id="liveTranscript"><strong>Live:</strong> Waiting for conversation...</div>
<section id="conversation"></section>
</main>
<script>
const voiceButton=document.getElementById("voiceButton");
const stopButton=document.getElementById("stopButton");
const status=document.getElementById("status");
const conversation=document.getElementById("conversation");
const liveTranscript=document.getElementById("liveTranscript");
let recognition=null, active=false, speaking=false;
let recorder=null, mediaStream=null, silenceTimer=null, recordStartedAt=0;
let localTranscriber=null, localTranscriberPromise=null;
let sessionId=localStorage.getItem("janu_session_id");
if(!sessionId){sessionId=crypto.randomUUID();localStorage.setItem("janu_session_id",sessionId);}

function addMessage(who,text,cls){
  liveTranscript.innerHTML="<strong>"+who+":</strong> "+text;
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
async function speak(text){
  speaking=true;
  try{
    const r=await fetch("/speak",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text})});
    if(!r.ok)throw new Error("Neural voice unavailable");
    const blob=await r.blob();
    const url=URL.createObjectURL(blob);
    const audio=new Audio(url);
    audio.volume=1;
    await audio.play();
    await new Promise(resolve=>{
      audio.onended=resolve;
      audio.onerror=resolve;
    });
    URL.revokeObjectURL(url);
    speaking=false;
    return;
  }catch(err){
    if(!("speechSynthesis" in window)){speaking=false;return}
    await new Promise(resolve=>{
      speechSynthesis.cancel();
      const u=new SpeechSynthesisUtterance(text);
      u.lang="en-IN"; u.rate=.92; u.pitch=1.05;
      const voice=chooseFemaleVoice(); if(voice) u.voice=voice;
      u.onend=()=>resolve(); u.onerror=()=>resolve();
      speechSynthesis.speak(u);
    });
  }
  speaking=false;
}
async function askJanu(text){
  const r=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({message:text,session_id:sessionId})});
  if(!r.ok) throw new Error("Backend error");
  return r.json();
}
async function startConversation(){
  active=true; voiceButton.disabled=true; stopButton.disabled=false;
  status.textContent="Janu is greeting you...";
  const greeting="Hi Lakshmanan, I am Janu. How can I help you?";
  addMessage("Janu",greeting,"assistant");
  await speak(greeting);
  if(!active)return;
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  const isIOS=/iPhone|iPad|iPod/i.test(navigator.userAgent);
  if(Recognition){
    recognition=new Recognition(); recognition.lang="en-IN"; recognition.interimResults=false; recognition.continuous=false;
    recognition.onstart=()=>{status.textContent="Listening...";liveTranscript.innerHTML="<strong>You:</strong> Listening...";};
    recognition.onresult=async e=>{
      const text=e.results[0][0].transcript; await handleUserText(text);
    };
    recognition.onerror=e=>{
      if(!active)return;
      if(e.error==="not-allowed"||e.error==="service-not-allowed"){
        status.textContent="Microphone/speech permission was blocked. Please allow microphone access.";
        return;
      }
      if(e.error==="no-speech"||e.error==="aborted")setTimeout(startListening,300);
      else setTimeout(startListening,1000);
    };
    recognition.onend=()=>{if(active&&!speaking)setTimeout(startListening,250)};
    startListening();
  } else {
    startRecorder();
  }
}
async function handleUserText(text){
  if(!text)return;
  addMessage("You",text,"user"); status.textContent="Janu is thinking...";
  try{
    const result=await askJanu(text); addMessage("Janu",result.reply,"assistant");
    status.textContent="Janu is speaking..."; await speak(result.reply);
    if(active){
      if(recognition)setTimeout(startListening,250);
      else setTimeout(startRecorder,250);
    }
  }catch(err){
    status.textContent="Could not contact Janu.";
    if(active)setTimeout(()=>recognition?startListening():startRecorder(),1000);
  }
}
function startListening(){
  if(!active||speaking||!recognition)return;
  try{recognition.start()}catch(e){setTimeout(startListening,500)}
}
async function getLocalTranscriber(){
  if(localTranscriber)return localTranscriber;
  if(localTranscriberPromise)return localTranscriberPromise;
  localTranscriberPromise=(async()=>{
    status.textContent="Loading free voice model (first time only)...";
    const mod=await import("https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1");
    mod.env.allowRemoteModels=true;
    mod.env.allowLocalModels=false;
    mod.env.useBrowserCache=true;
    localTranscriber=await mod.pipeline(
      "automatic-speech-recognition",
      "Xenova/whisper-tiny.en",
      {device:"wasm"}
    );
    return localTranscriber;
  })();
  try{return await localTranscriberPromise}
  catch(err){localTranscriberPromise=null;throw err}
}

async function blobTo16kMono(blob){
  const AudioCtx=window.AudioContext||window.webkitAudioContext;
  if(!AudioCtx)throw new Error("This browser cannot decode recorded audio locally.");
  const ctx=new AudioCtx();
  try{
    const buffer=await ctx.decodeAudioData(await blob.arrayBuffer());
    const input=buffer.getChannelData(0);
    const targetRate=16000;
    const length=Math.max(1,Math.round(input.length*targetRate/buffer.sampleRate));
    const output=new Float32Array(length);
    const ratio=buffer.sampleRate/targetRate;
    for(let i=0;i<length;i++){
      const pos=i*ratio;
      const left=Math.floor(pos);
      const right=Math.min(left+1,input.length-1);
      const frac=pos-left;
      output[i]=input[left]*(1-frac)+input[right]*frac;
    }
    return output;
  }finally{
    try{await ctx.close()}catch(e){}
  }
}

async function transcribeLocally(blob){
  const transcriber=await getLocalTranscriber();
  const audio=await blobTo16kMono(blob);
  status.textContent="Running speech recognition on your device...";
  const result=await transcriber(audio,{chunk_length_s:20,stride_length_s:3});
  return (result.text||"").trim();
}

async function startRecorder(){
  if(!active||speaking)return;
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw new Error("Microphone is not available");
    if(!mediaStream)mediaStream=await navigator.mediaDevices.getUserMedia({audio:true});
    const options={};
    if(MediaRecorder.isTypeSupported("audio/mp4"))options.mimeType="audio/mp4";
    else if(MediaRecorder.isTypeSupported("audio/webm;codecs=opus"))options.mimeType="audio/webm;codecs=opus";
    else if(MediaRecorder.isTypeSupported("audio/webm"))options.mimeType="audio/webm";
    recorder=new MediaRecorder(mediaStream,options);
    const chunks=[];
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
    recorder.onstart=()=>{
      recordStartedAt=Date.now();
      status.textContent="Listening...";
      liveTranscript.innerHTML="<strong>You:</strong> Listening... Speak now.";
      startSilenceDetection();
    };
    recorder.onstop=async()=>{
      stopSilenceDetection();
      const blob=new Blob(chunks,{type:recorder.mimeType||"audio/webm"});
      if(blob.size<1000){if(active)setTimeout(startRecorder,500);return}
      status.textContent="Transcribing on your device...";
      liveTranscript.innerHTML="<strong>You:</strong> Loading free on-device speech recognition...";
      try{
        const text=await transcribeLocally(blob);
        if(!text)throw new Error("No speech detected");
        await handleUserText(text);
      }catch(err){
        status.textContent="Free voice transcription failed. Please try again.";
        liveTranscript.innerHTML="<strong>System:</strong> "+(err.message||"Local voice processing failed");
        if(active)setTimeout(startRecorder,1200);
      }
    };
    recorder.start();
  }catch(err){
    status.textContent="Please allow microphone access and try again.";
    stopConversation();
  }
}
function startSilenceDetection(){
  const AudioCtx=window.AudioContext||window.webkitAudioContext;
  if(!AudioCtx||!mediaStream||!recorder)return;
  const ctx=new AudioCtx(), source=ctx.createMediaStreamSource(mediaStream), analyser=ctx.createAnalyser();
  analyser.fftSize=2048; source.connect(analyser);
  const data=new Uint8Array(analyser.fftSize);
  let quietSince=0;
  const check=()=>{
    if(!recorder||recorder.state!=="recording"){ctx.close();return}
    analyser.getByteTimeDomainData(data);
    let sum=0;
    for(let i=0;i<data.length;i++){const v=(data[i]-128)/128;sum+=v*v}
    const rms=Math.sqrt(sum/data.length);
    const quiet=rms<0.018;
    if(quiet){if(!quietSince)quietSince=Date.now()}else quietSince=0;
    const elapsed=Date.now()-recordStartedAt;
    if(elapsed>1200&&quietSince&&Date.now()-quietSince>1200){recorder.stop();ctx.close();return}
    if(elapsed>12000){recorder.stop();ctx.close();return}
    silenceTimer=requestAnimationFrame(check);
  };
  silenceTimer=requestAnimationFrame(check);
}
function stopSilenceDetection(){
  if(silenceTimer)cancelAnimationFrame(silenceTimer);
  silenceTimer=null;
}
function stopConversation(){
  active=false; speaking=false;
  try{recognition&&recognition.stop()}catch(e){}
  try{recorder&&recorder.stop()}catch(e){}
  stopSilenceDetection();
  if(mediaStream){mediaStream.getTracks().forEach(t=>t.stop());mediaStream=null}
  speechSynthesis?.cancel(); voiceButton.disabled=false; stopButton.disabled=true; status.textContent="Conversation stopped";
}
async function setupNotifications(){if(!(\"serviceWorker\" in navigator)||!(\"PushManager\" in window)||!(\"Notification\" in window))return;try{const reg=await navigator.serviceWorker.register(\"/service-worker.js\");const keyResponse=await fetch(\"/push/public-key\");const data=await keyResponse.json();if(!data.public_key)return;const permission=await Notification.requestPermission();if(permission!==\"granted\")return;let sub=await reg.pushManager.getSubscription();if(!sub){const raw=atob(data.public_key.replace(/-/g,\"+\").replace(/_/g,\"/\")+\"=\".repeat((4-data.public_key.length%4)%4));const key=Uint8Array.from([...raw].map(ch=>ch.charCodeAt(0)));sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});}await fetch(\"/push/subscribe\",{method:\"POST\",headers:{\"Content-Type\":\"application/json\"},body:JSON.stringify(sub.toJSON())});}catch(e){}}
setupNotifications();
navigator.serviceWorker?.addEventListener(\"message\",event=>{if(event.data?.type===\"janu-reminder\"){window.focus();startConversation();}});
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

@app.get("/service-worker.js", response_class=HTMLResponse)
async def service_worker():
    return HTMLResponse(SERVICE_WORKER, media_type="application/javascript")


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML


@app.get("/health")
async def health():
    return {"status": "ok", "assistant": "Janu", "version": "0.9.0", "free_mode": os.getenv("JANU_FREE_MODE", "true").lower() in {"1","true","yes","on"}}



class SpeakRequest(BaseModel):
    text: str


@app.post("/speak")
async def speak(request: SpeakRequest):
    text = request.text.strip()
    if not text:
        return Response(content=b"", media_type="audio/mpeg")
    try:
        import edge_tts
        communicate = edge_tts.Communicate(
            text,
            voice=os.getenv("JANU_TTS_VOICE", "en-IN-AartiNeural"),
            rate=os.getenv("JANU_TTS_RATE", "-5%"),
            pitch=os.getenv("JANU_TTS_PITCH", "+2Hz"),
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                audio.extend(chunk.get("data", b""))
        return Response(content=bytes(audio), media_type="audio/mpeg")
    except Exception as exc:
        return Response(content=b"", media_type="audio/mpeg", status_code=503)


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"text": "", "error": "OPENAI_API_KEY is not configured."}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        result = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=(audio.filename or "voice.webm", audio.file, audio.content_type or "audio/webm"),
            language="en",
        )
        return {"text": (result.text or "").strip()}
    except Exception as exc:
        return {"text": "", "error": str(exc)}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    return janu_reply(request.message, session_id)


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    clear_session(session_id)
    return {"status": "ok"}
