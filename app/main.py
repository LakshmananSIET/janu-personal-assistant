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

app = FastAPI(title="Jaanu Personal Assistant", version="0.9.0")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict


class ChatResponse(BaseModel):
    reply: str
    tts_text: str | None = None
    task_created: bool = False
    task_id: int | None = None
    session_id: str


def format_task_confirmation(task: dict, task_id: int) -> str:
    if task.get("kind") == "reminder" or task.get("reminder_at"):
        parts = [f"Okay Lakshman, I'll remind you: {task['task']}."]
    else:
        parts = [f"Okay Lakshman, I've added the task: {task['task']}."]
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

        if intent in {"create_task", "create_reminder"} and ai_result.get("task"):
            task = {
                "task": ai_result["task"],
                "kind": "reminder" if intent == "create_reminder" else "task",
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
            return ChatResponse(reply=reply, tts_text=ai_result.get("tts_text") or reply, task_created=True, task_id=task_id, session_id=session_id)

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
        return ChatResponse(reply=reply, tts_text=ai_result.get("tts_text") or reply, session_id=session_id)

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
            reply = "Hi Lakshman. I'm Jaanu. How can I help you?"
        elif lower in {"what time is it", "what is the time", "time"}:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            reply = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("It is %I:%M %p in India.")
        elif lower in {"what is today", "what date is it", "today"}:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            reply = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("Today is %A, %d %B %Y.")
        else:
            reply = "I can chat normally, but the free trial does not currently have a general AI knowledge engine enabled. General questions need the AI provider to be connected."

    add_message(session_id, "user", message)
    add_message(session_id, "assistant", reply)
    return ChatResponse(
        reply=reply,
        tts_text=reply,
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
                    payload = json.dumps({"title":"Jaanu reminder","body":f"Lakshman, remember: {task['task']}","url":f"/?reminder={task['id']}","task_id":task["id"]})
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


SERVICE_WORKER = """
self.addEventListener("push", event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}
  event.waitUntil(self.registration.showNotification(
    data.title || "Jaanu reminder",
    {body: data.body || "You have a reminder from Jaanu.", data:{url:data.url || "/"}}
  ));
});
self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(clients.matchAll({type:"window", includeUncontrolled:true}).then(list => {
    for (const client of list) {
      if ("focus" in client) { client.navigate(url); return client.focus(); }
    }
    return clients.openWindow ? clients.openWindow(url) : undefined;
  }));
});
"""

HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Jaanu">
<link rel="manifest" href="/manifest.json">
<title>Jaanu — Personal Assistant</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;background:#080b12;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
body{min-height:100vh;color:#fff}
.card{width:100%;min-height:100vh;background:radial-gradient(circle at 50% 28%,#26314a 0%,#111827 34%,#070a10 72%);display:flex;flex-direction:column;overflow:hidden}
.topbar{height:76px;display:flex;align-items:center;justify-content:space-between;padding:0 22px;color:#fff}
.brand{font-size:21px;font-weight:650;letter-spacing:.2px}
.topbar button{border:0;background:rgba(255,255,255,.09);color:#fff;border-radius:50%;width:42px;height:42px;font-size:18px;cursor:pointer}
.landing{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:30px 22px 55px;text-align:center}
.landing .avatar{width:118px;height:118px;margin-bottom:24px}
h1{font-size:38px;margin:0 0 8px;font-weight:650}
.subtitle{color:#b9c0cf;font-size:16px;max-width:340px;line-height:1.5;margin-bottom:30px}
#voiceButton{border:0;border-radius:999px;padding:16px 30px;font-size:17px;font-weight:600;cursor:pointer;background:#fff;color:#111;box-shadow:0 8px 30px rgba(0,0,0,.25)}
#voiceButton:disabled{opacity:.5}
#status{display:none}
#conversation{display:flex;flex-direction:column;gap:8px;width:min(620px,100%);max-height:150px;overflow-y:auto;padding:10px 4px;margin-top:4px;text-align:left;scroll-behavior:smooth}
.msg{padding:9px 12px;border-radius:14px;font-size:14px;line-height:1.35;word-break:break-word}
.msg.user{align-self:flex-end;background:rgba(92,124,255,.25);color:#eef2ff;max-width:88%}
.msg.assistant{align-self:flex-start;background:rgba(255,255,255,.09);color:#f2f4f8;max-width:88%}
.msg .label{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#9fa8b8;margin-bottom:3px}
#liveTranscript{display:block;width:min(620px,100%);min-height:20px;margin-top:6px;padding:7px 12px;border-radius:12px;background:rgba(255,255,255,.055);color:#aeb7c8;font-size:13px;line-height:1.35;text-align:left;overflow:hidden}
#liveTranscript strong{color:#e7eaf0}

.call-screen{display:none;flex:1;min-height:calc(100vh - 76px);flex-direction:column;align-items:center;text-align:center;padding:22px 24px 38px}
.call-screen.active{display:flex}
.call-name{font-size:25px;font-weight:650;margin-top:8px}
.call-status{font-size:15px;color:#aeb7c8;margin-top:7px;min-height:22px}
.avatar{position:relative;width:154px;height:154px;border-radius:50%;display:grid;place-items:center;margin-top:14vh;margin-bottom:25px;background:linear-gradient(145deg,#ffb5cf,#9d7cff 52%,#5c7cff);box-shadow:0 0 0 1px rgba(255,255,255,.15),0 20px 70px rgba(111,93,255,.35)}
.avatar::before,.avatar::after{content:"";position:absolute;inset:-13px;border:1px solid rgba(255,255,255,.13);border-radius:50%;animation:ring 2.2s infinite ease-out}
.avatar::after{inset:-28px;animation-delay:1.1s}
.avatar.listening::before,.avatar.listening::after{border-color:rgba(132,170,255,.32)}
.avatar.speaking{box-shadow:0 0 0 1px rgba(255,255,255,.18),0 0 70px rgba(255,145,196,.4)}
.avatar-core{font-size:48px;font-weight:700;color:#fff;text-shadow:0 2px 14px rgba(0,0,0,.2)}
@keyframes ring{0%{transform:scale(.92);opacity:.7}100%{transform:scale(1.14);opacity:0}}
.call-caption{min-height:56px;max-width:620px;padding:0 20px;color:#e6e9ef;font-size:18px;line-height:1.45;display:flex;align-items:center;justify-content:center}
.call-controls{margin-top:auto;display:flex;align-items:center;justify-content:center;gap:28px;padding-top:34px}
.call-control{width:62px;height:62px;border:0;border-radius:50%;cursor:pointer;font-size:24px;color:#fff;background:rgba(255,255,255,.12);backdrop-filter:blur(12px)}
.call-control span{display:block;font-size:11px;margin-top:5px;color:#d8dce5}
.call-control.end{width:72px;height:72px;background:#ef4444;font-size:27px}
.call-control.muted{background:#fff;color:#111}
#clearButton{border:0;background:transparent;color:#9da6b7;margin-top:18px;font-size:14px;cursor:pointer}
.timer{font-variant-numeric:tabular-nums;color:#9fa8b8;font-size:14px;margin-top:5px}
@media(max-width:600px){
  .topbar{height:68px;padding:0 18px}
  .landing{padding-bottom:45px}
  .avatar{margin-top:12vh;width:138px;height:138px}
  .avatar-core{font-size:43px}
  .call-name{font-size:24px}
  .call-caption{font-size:17px;max-width:350px}
}
</style>
</head>
<body>
<main class="card">
<header class="topbar">
  <div class="brand">Jaanu</div>
  <button onclick="clearConversation()" aria-label="Clear conversation">⋯</button>
</header>

<section id="landing" class="landing">
  <div class="avatar"><div class="avatar-core">J</div></div>
  <h1>Jaanu</h1>
  <div class="subtitle">Your personal AI assistant. Talk naturally, just like a phone call.</div>
  <button id="voiceButton" onclick="startConversation()">☎️ Start Call</button>
  <button id="clearButton" onclick="clearConversation()">New conversation</button>
</section>

<section id="callScreen" class="call-screen">
  <div class="call-name">Jaanu</div>
  <div id="callStatus" class="call-status">Connecting...</div>
  <div id="callTimer" class="timer">00:00</div>
  <div id="callAvatar" class="avatar"><div class="avatar-core">J</div></div>
  <div id="callCaption" class="call-caption">Hi Lakshman, I'm listening.</div>
  <section id="conversation"></section>
  <div id="liveTranscript"><strong>Live:</strong> Waiting for conversation...</div>
  <div class="call-controls">
    <button id="notifyButton" class="call-control" onclick="enableNotifications()" aria-label="Enable reminders">🔔<span>Reminders</span></button>
    <button id="muteButton" class="call-control" onclick="toggleMute()" aria-label="Mute microphone">🎙️<span>Mute</span></button>
    <button id="stopButton" class="call-control end" onclick="stopConversation()" aria-label="End call">☎<span>End</span></button>
  </div>
</section>

<div id="status">Ready</div>
</main>
<script>
const voiceButton=document.getElementById("voiceButton");
const stopButton=document.getElementById("stopButton");
const status=document.getElementById("status");
const landing=document.getElementById("landing");
const callScreen=document.getElementById("callScreen");
const callStatus=document.getElementById("callStatus");
const callTimer=document.getElementById("callTimer");
const callCaption=document.getElementById("callCaption");
const callAvatar=document.getElementById("callAvatar");
const muteButton=document.getElementById("muteButton");
const conversation=document.getElementById("conversation");
const liveTranscript=document.getElementById("liveTranscript");
const notifyButton=document.getElementById("notifyButton");
let recognition=null, active=false, speaking=false, processing=false, muted=false;
let recorder=null, mediaStream=null, silenceTimer=null, recordStartedAt=0;
let currentPlayer=null, bargeInTimer=null;
let callStartedAt=0, callTimerInterval=null;
let localTranscriber=null, localTranscriberPromise=null;
let sessionId=localStorage.getItem("janu_session_id");
if(!sessionId){sessionId=crypto.randomUUID();localStorage.setItem("janu_session_id",sessionId);}

function setCallStatus(text){
  callStatus.textContent=text;
  status.textContent=text;
}
function setCallCaption(text){callCaption.textContent=text||"";}
function startCallTimer(){
  callStartedAt=Date.now();
  clearInterval(callTimerInterval);
  const tick=()=>{const sec=Math.floor((Date.now()-callStartedAt)/1000);callTimer.textContent=String(Math.floor(sec/60)).padStart(2,"0")+":"+String(sec%60).padStart(2,"0")};
  tick(); callTimerInterval=setInterval(tick,1000);
}
function stopCallTimer(){clearInterval(callTimerInterval);callTimerInterval=null;callTimer.textContent="00:00";}
function toggleMute(){
  muted=!muted;
  if(mediaStream)mediaStream.getAudioTracks().forEach(t=>t.enabled=!muted);
  muteButton.classList.toggle("muted",muted);
  muteButton.innerHTML=muted?"🔇<span>Unmute</span>":"🎙️<span>Mute</span>";
  setCallStatus(muted?"Microphone muted":"Listening...");
}
function addMessage(who,text,cls){
  const div=document.createElement("div"); div.className="msg "+cls;
  const label=document.createElement("div"); label.className="label"; label.textContent=who;
  const body=document.createElement("div"); body.textContent=text;
  div.append(label,body); conversation.appendChild(div);
  conversation.scrollTop=conversation.scrollHeight;
  liveTranscript.innerHTML="<strong>"+who+":</strong> "+text;
}
function setLiveTranscript(text){
  liveTranscript.innerHTML="<strong>You:</strong> "+(text||"");
}
function chooseFemaleVoice(){
  const voices=speechSynthesis.getVoices();
  const preferred=["female","samantha","zira","heera","google uk english female","microsoft heera"];
  return voices.find(v=>v.lang.toLowerCase().startsWith("en-in") && preferred.some(x=>v.name.toLowerCase().includes(x)))
      || voices.find(v=>preferred.some(x=>v.name.toLowerCase().includes(x)))
      || voices.find(v=>v.lang.toLowerCase().startsWith("en-in"))
      || null;
}
let localTTS=null, localTTSPromise=null;

function browserSpeak(text,lang="en-IN"){
  return new Promise(resolve=>{
    if(!("speechSynthesis" in window)){resolve();return}
    speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(text);
    u.lang=lang; u.rate=.92; u.pitch=1.05;
    const voice=chooseFemaleVoice(); if(voice) u.voice=voice;
    u.onend=()=>resolve(); u.onerror=()=>resolve();
    speechSynthesis.speak(u);
  });
}

async function serverSpeak(ttsText,fallbackText){
  try{
    const r=await fetch("/speak",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:ttsText})});
    if(!r.ok)throw new Error("TTS server error");
    const blob=await r.blob();
    if(!blob.size)throw new Error("Empty TTS audio");
    const url=URL.createObjectURL(blob);
    const player=new Audio(url);
    player.volume=1;
    currentPlayer=player;
    try{
      await player.play();
      if(recognition && active && !muted){
        clearTimeout(bargeInTimer);
        bargeInTimer=setTimeout(()=>startListening(true),450);
      }
      await new Promise(resolve=>{
        const timer=setTimeout(resolve,15000);
        const done=()=>{clearTimeout(timer);resolve()};
        player.onended=done; player.onerror=done; player.onpause=done;
      });
    }finally{
      if(currentPlayer===player)currentPlayer=null;
      clearTimeout(bargeInTimer); bargeInTimer=null;
      URL.revokeObjectURL(url);
    }
  }catch(err){
    await browserSpeak(fallbackText);
  }
}

async function loadLocalTTS(){
  if(localTTS)return localTTS;
  if(localTTSPromise)return localTTSPromise;
  localTTSPromise=(async()=>{
    status.textContent="Loading Jaanu's free natural voice (first time only)...";
    const mod=await import("https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/+esm");
    localTTS=await mod.KokoroTTS.from_pretrained(
      "onnx-community/Kokoro-82M-v1.0-ONNX",
      {dtype:"q8",device:"wasm"}
    );
    return localTTS;
  })();
  try{return await localTTSPromise}
  catch(err){localTTSPromise=null; throw err}
}

async function speak(text,ttsText=text){
  speaking=true;
  try{
    await serverSpeak(ttsText,text);
  }finally{
    speaking=false;
  }
}
async function askJaanu(text){
  const r=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({message:text,session_id:sessionId})});
  if(!r.ok) throw new Error("Backend error");
  return r.json();
}
async function registerPushSubscription(){
  try{
    if(!("serviceWorker" in navigator)||!("PushManager" in window)||!("Notification" in window)){
      throw new Error("This browser does not support web notifications.");
    }
    const isIOS=/iPhone|iPad|iPod/i.test(navigator.userAgent);
    const standalone=window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone===true;
    if(isIOS && !standalone){
      throw new Error("On iPhone, add Jaanu to the Home Screen first, then open it from the Home Screen.");
    }
    const reg=await navigator.serviceWorker.register("/service-worker.js");
    await navigator.serviceWorker.ready;
    const keyResponse=await fetch("/push/public-key",{cache:"no-store"});
    const data=await keyResponse.json();
    if(!data.public_key)throw new Error("VAPID public key is missing on the server.");
    let sub=await reg.pushManager.getSubscription();
    if(!sub){
      const raw=atob(data.public_key.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-data.public_key.length%4)%4));
      const key=Uint8Array.from([...raw].map(ch=>ch.charCodeAt(0)));
      sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
    }
    const response=await fetch("/push/subscribe",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(sub.toJSON())});
    if(!response.ok)throw new Error("Jaanu could not save this notification subscription.");
    await reg.showNotification("Jaanu reminders enabled",{
      body:"Notification test successful. I can now send your reminders.",
      tag:"jaanu-notification-test"
    });
    notifyButton.innerHTML="🔔<span>Enabled</span>";
    notifyButton.classList.add("muted");
    setCallStatus("Reminders enabled.");
    return true;
  }catch(e){
    setCallStatus("Reminder notifications not enabled.");
    setLiveTranscript("<strong>Notification:</strong> "+(e.message||"Setup failed"));
    return false;
  }
}

async function enableNotifications(){
  if(!("Notification" in window)){
    setCallStatus("This browser does not support notifications.");
    return;
  }
  if(Notification.permission==="denied"){
    setCallStatus("Notifications are blocked. Allow notifications for Jaanu in browser site settings.");
    setLiveTranscript("<strong>Notification:</strong> Permission is blocked. Open the site lock/settings and allow Notifications.");
    return;
  }
  try{
    const permission=Notification.permission==="granted" ? "granted" : await Notification.requestPermission();
    if(permission!=="granted"){
      setCallStatus("Please allow notifications for Jaanu.");
      setLiveTranscript("<strong>Notification:</strong> Permission was not granted.");
      return;
    }
    await registerPushSubscription();
  }catch(e){
    setCallStatus("Notification setup failed.");
    setLiveTranscript("<strong>Notification:</strong> "+(e.message||"Unknown error"));
  }
}

function autoEnableRemindersFromGesture(){
  if("Notification" in window && Notification.permission==="granted")registerPushSubscription();
}
async function startConversation(){
  if(active)return;
  autoEnableRemindersFromGesture();
  active=true; voiceButton.disabled=true; landing.style.display="none"; callScreen.classList.add("active");
  stopButton.disabled=false; muteButton.disabled=false; muted=false;
  muteButton.classList.remove("muted"); muteButton.innerHTML="🎙️<span>Mute</span>";
  startCallTimer();
  setCallStatus("Calling...");
  setCallCaption("Hi Lakshman, I'm Jaanu. How can I help you?");
  const greeting="Hi Lakshman sir! Enna help venum?";
  const greetingTts="ஹாய் லக்ஷ்மன் சார்! என்ன ஹெல்ப் வேணும்?";
  addMessage("Jaanu",greeting,"assistant");

  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  const isIOS=/iPhone|iPad|iPod/i.test(navigator.userAgent);

  if(Recognition){
    recognition=new Recognition();
    recognition.lang="en-IN";
    recognition.interimResults=true;
    recognition.continuous=false;
    recognition.onstart=()=>{
      setCallStatus(muted?"Microphone muted":"Listening...");
      callAvatar.classList.add("listening");
      callAvatar.classList.remove("speaking");
      setCallCaption(muted?"Microphone is muted":"Listening...");
    };
    recognition.onresult=async e=>{
      let transcript="";
      let finalResult=false;
      for(let i=e.resultIndex;i<e.results.length;i++){
        transcript+=e.results[i][0].transcript;
        if(e.results[i].isFinal)finalResult=true;
      }
      transcript=transcript.trim();
      if(transcript)setLiveTranscript(transcript);
      if(finalResult && transcript){
        try{recognition.stop()}catch(err){}
        if(speaking)interruptJaanuSpeech();
        await handleUserText(transcript);
      }
    };
    recognition.onaudiostart=()=>{ if(active && !speaking)setCallStatus("Listening..."); };
    recognition.onsoundstart=()=>{ if(active && !speaking)setCallStatus("Hearing you..."); };
    recognition.onspeechstart=()=>{ if(active)setCallStatus("Hearing you..."); };
    recognition.onspeechend=()=>{ if(active && !speaking)setCallStatus("Processing..."); };
    recognition.onaudioend=()=>{ if(active && !processing && !speaking)setCallStatus("Listening..."); };
    recognition.onerror=e=>{
      if(!active)return;
      if(e.error==="not-allowed"||e.error==="service-not-allowed"){
        setCallStatus("Microphone permission is needed. Please allow it in your browser.");
        setLiveTranscript("<strong>System:</strong> Microphone permission was denied.");
        return;
      }
      if(e.error==="no-speech"){setCallStatus(speaking?"Jaanu is speaking — you can interrupt":"Listening...");setTimeout(()=>startListening(speaking),700);}
      else if(e.error==="aborted"){if(active)setTimeout(()=>startListening(speaking),500);}
      else {setCallStatus("Microphone listening error: "+e.error);setTimeout(()=>startListening(speaking),1200);}
    };
    recognition.onend=()=>{
      if(active&&!speaking&&!processing)setTimeout(startListening,isIOS?3500:250);
    };

    // iOS Safari has a WebKit bug where audio playback can break the next
    // SpeechRecognition session. We therefore use the reliable iPhone
    // browser voice for speech, then wait before reopening recognition.
    if(!isIOS){
      try{
        mediaStream=await navigator.mediaDevices.getUserMedia({
          audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}
        });
      }catch(e){
        setCallStatus("Please allow microphone access to talk to Jaanu.");
        setLiveTranscript("<strong>System:</strong> Microphone permission is required.");
        stopConversation();
        return;
      }
    }

    if(isIOS){
      // IMPORTANT for iPhone Safari: start SpeechRecognition directly from the
      // Start Conversation button gesture. Starting it only after an awaited
      // greeting can lose the user-activation required by Safari.
      setCallStatus("Listening...");
      startListening();
      await serverSpeak(greetingTts,greeting);
      if(!active)return;
      // The first recognition session may have ended while Jaanu was speaking.
      // Re-open it after the greeting; on iOS this is now a continuation of
      // the user-started recognition flow rather than the first start.
      setTimeout(()=>startListening(),500);
    }else{
      const voiceWarmup=loadLocalTTS().catch(()=>null);
      await browserSpeak(greeting);
      if(!active)return;
      voiceWarmup.catch(()=>null);
      startListening();
    }
    return;
  }

  // Recorder + local Whisper is only a fallback for browsers without
  // SpeechRecognition. It can exceed iPhone Safari's WASM memory limit.
  if(isIOS){
    status.textContent="This iPhone browser cannot access speech recognition. Please use Safari with Siri/Dictation enabled.";
    stopConversation();
    return;
  }
  startRecorder();
}
async function handleUserText(text){
  if(!text||processing)return;
  processing=true;
  setLiveTranscript(text);
  addMessage("You",text,"user"); setCallStatus("Jaanu is thinking...");
  setCallCaption(text); callAvatar.classList.remove("listening");
  try{
    const result=await askJaanu(text); addMessage("Jaanu",result.reply,"assistant");
    setCallStatus("Jaanu is speaking...");
    setCallCaption(result.reply); callAvatar.classList.add("speaking");
    if(/iPhone|iPad|iPod/i.test(navigator.userAgent)){
      await serverSpeak(result.tts_text || result.reply,result.reply);
      callAvatar.classList.remove("speaking");
      if(active)setTimeout(startListening,3500);
    }else{
      await speak(result.reply,result.tts_text || result.reply);
      callAvatar.classList.remove("speaking");
      if(active){
        if(recognition)setTimeout(startListening,250);
        else setTimeout(startRecorder,250);
      }
    }
  }catch(err){
    setCallStatus("Jaanu could not reply.");
    setCallCaption("I could not reach the assistant. Please try again.");
    setLiveTranscript("Connection error: "+(err.message||"unknown error"));
    callAvatar.classList.remove("speaking");
  }finally{
    processing=false;
    if(active){
      if(recognition)setTimeout(startListening,350);
      else setTimeout(startRecorder,350);
    }
  }
}
function startListening(allowDuringSpeech=false){
  if(!active||processing||!recognition||muted)return;
  if(speaking&&!allowDuringSpeech)return;
  try{
    const track=mediaStream?.getAudioTracks?.()[0];
    if(track && track.readyState==="live") recognition.start(track);
    else recognition.start();
  }catch(e){setTimeout(()=>startListening(allowDuringSpeech),500)}
}
function interruptJaanuSpeech(){
  clearTimeout(bargeInTimer);
  bargeInTimer=null;
  speaking=false;
  if(currentPlayer){
    try{currentPlayer.pause()}catch(e){}
    try{currentPlayer.currentTime=0}catch(e){}
    currentPlayer=null;
  }
  try{speechSynthesis.cancel()}catch(e){}
  callAvatar.classList.remove("speaking");
  setCallStatus("Listening...");
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
  if(!active||speaking||muted)return;
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
      setCallStatus(muted?"Microphone muted":"Listening...");
      callAvatar.classList.add("listening");
      callAvatar.classList.remove("speaking");
      setCallCaption(muted?"Microphone is muted":"Listening...");
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
  active=false; speaking=false; muted=false;
  clearTimeout(bargeInTimer); bargeInTimer=null;
  if(currentPlayer){try{currentPlayer.pause()}catch(e){} currentPlayer=null;}
  try{recognition&&recognition.stop()}catch(e){}
  try{recorder&&recorder.stop()}catch(e){}
  stopSilenceDetection();
  if(mediaStream){mediaStream.getTracks().forEach(t=>t.stop());mediaStream=null}
  speechSynthesis?.cancel();
  stopCallTimer();
  callAvatar.classList.remove("listening","speaking");
  callScreen.classList.remove("active");
  landing.style.display="flex";
  voiceButton.disabled=false; stopButton.disabled=true;
  muteButton.disabled=false; muteButton.classList.remove("muted"); muteButton.innerHTML="🎙️<span>Mute</span>";
  setCallStatus("Conversation ended");
  setCallCaption("");
}
navigator.serviceWorker?.addEventListener(\"message\",event=>{if(event.data?.type===\"jaanu-reminder\"){window.focus();startConversation();}});
async function clearConversation(){
  stopConversation(); conversation.innerHTML="";
  const oldSession=sessionId;
  sessionId=crypto.randomUUID(); localStorage.setItem("janu_session_id",sessionId);
  try{await fetch("/session/"+oldSession,{method:"DELETE"})}catch(e){}
  landing.style.display="flex"; callScreen.classList.remove("active");
  status.textContent="New conversation ready";
}
</script>
</body>
</html>
"""

@app.get("/service-worker.js", response_class=HTMLResponse)
async def service_worker():
    return HTMLResponse(SERVICE_WORKER, media_type="application/javascript")

@app.get("/manifest.json")
async def manifest():
    return Response(content=json.dumps({
        "name":"Jaanu Personal Assistant",
        "short_name":"Jaanu",
        "start_url":"/",
        "display":"standalone",
        "background_color":"#080b12",
        "theme_color":"#080b12",
        "icons":[]
    }), media_type="application/manifest+json")


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(content=HTML, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache", "Expires": "0"})


@app.get("/health")
async def health():
    return {"status": "ok", "assistant": "Jaanu", "version": "0.9.0", "free_mode": os.getenv("JANU_FREE_MODE", "true").lower() in {"1","true","yes","on"}}



class SpeakRequest(BaseModel):
    text: str


async def _indic_parler_speak(text: str) -> bytes:
    """Use the free public AI4Bharat Indic Parler-TTS Space."""
    from gradio_client import Client
    client = Client("ai4bharat/indic-parler-tts")
    description = (
        "A young Indian female speaker with a very soft, gentle and warm voice, "
        "medium-high pitch, calm intimate conversational delivery, slightly slow pace, "
        "subtle emotion, natural pauses and realistic close-microphone sound. "
        "She speaks clear Indian English naturally. Never deep, never bold, never loud. "
        "The recording is very high quality with no background noise."
    )
    result = client.predict(text, description, api_name="/generate_finetuned")
    audio_path = result[0] if isinstance(result, (list, tuple)) else result
    if not audio_path:
        raise RuntimeError("Indic Parler-TTS returned no audio")
    with open(audio_path, "rb") as audio_file:
        return audio_file.read()


@app.post("/speak")
async def speak(request: SpeakRequest):
    text = request.text.strip()
    if not text:
        return Response(content=b"", media_type="audio/mpeg")
    try:
        backend = os.getenv("JANU_TTS_BACKEND", "edge_tts").lower()
        if backend == "indic_parler":
            audio = await asyncio.to_thread(_indic_parler_speak, text)
            return Response(content=audio, media_type="audio/mpeg")

        import edge_tts
        # Tamil-script TTS gives Tanglish replies a natural Tamil pronunciation.
        has_tamil = any("\u0b80" <= ch <= "\u0bff" for ch in text)
        default_voice = "ta-IN-PallaviNeural" if has_tamil else "en-IN-AartiNeural"
        communicate = edge_tts.Communicate(
            text,
            voice=os.getenv("JANU_TTS_VOICE", default_voice),
            rate=os.getenv("JANU_TTS_RATE", "-5%"),
            pitch=os.getenv("JANU_TTS_PITCH", "+2Hz"),
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                audio.extend(chunk.get("data", b""))
        return Response(content=bytes(audio), media_type="audio/mpeg")
    except Exception:
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
