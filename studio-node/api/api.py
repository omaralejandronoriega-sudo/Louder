#!/usr/bin/env python3
from __future__ import annotations
import asyncio, json, os, pathlib, random, re, secrets, subprocess, time
from dataclasses import dataclass, asdict
from typing import Any
from aiohttp import web, WSMsgType

ROOT=pathlib.Path(os.getenv("LOUDER_DATA_DIR","/data"))
ROOT.mkdir(parents=True,exist_ok=True)
STATE_FILE=ROOT/"studio-state.json"
AUTO_POOL_FILE=ROOT/"auto-pool.json"
VOICE_DIR=ROOT/"voice-tracks"; VOICE_DIR.mkdir(exist_ok=True)
FX_DIR=ROOT/"sound-fx"; FX_DIR.mkdir(exist_ok=True)
API_TOKEN=os.getenv("LOUDER_API_TOKEN","").strip()
INTERNAL_KEY=os.getenv("LOUDER_INTERNAL_KEY","").strip() or secrets.token_urlsafe(24)
LIQ_HOST=os.getenv("LIQUIDSOAP_HOST","liquidsoap")
LIQ_PORT=int(os.getenv("LIQUIDSOAP_PORT","1234"))
VOICE_HARBOR_HOST=os.getenv("VOICE_HARBOR_HOST","liquidsoap")
VOICE_HARBOR_PORT=int(os.getenv("VOICE_HARBOR_PORT","8005"))
VOICE_HARBOR_PASSWORD=os.getenv("VOICE_HARBOR_PASSWORD","change-me")
CORS=os.getenv("LOUDER_CORS_ORIGIN","*")
EMERGENCY_URI=os.getenv("EMERGENCY_URI","").strip()

DEFAULT_STATE={
 "mode":"auto","queue":[],"history":[],"now":None,
 "artist_separation_minutes":90,"track_separation_hours":120,
 "crossfade":{"duration":4.5,"fade_in":1.2,"fade_out":2.8},
 "voice":{"duck_db":-8.0,"fade_ms":350,"active":False},
 "dsp":{"agc":True,"target":-14.0,"stereo_width":0.0,"bass_gain":0.0,
        "compressor":True,"threshold":-10.0,"ratio":2.0,"limiter":True},
 "encoders":[{"id":"out","name":"YesStreaming Primary","format":"MP3","bitrate":320,"status":"unknown"}]
}
_lock=asyncio.Lock()

def load_json(path,default):
 try:return json.loads(path.read_text("utf-8"))
 except Exception:return default

state=load_json(STATE_FILE,DEFAULT_STATE.copy())
for k,v in DEFAULT_STATE.items(): state.setdefault(k,v)

async def save_state():
 async with _lock:
  tmp=STATE_FILE.with_suffix(".tmp")
  tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2),"utf-8")
  tmp.replace(STATE_FILE)

@web.middleware
async def cors_auth(request,handler):
 if request.method=="OPTIONS":
  r=web.Response(status=204)
 else:
  if request.path.startswith("/internal/"):
   key=request.query.get("key","")
   if INTERNAL_KEY and key!=INTERNAL_KEY: raise web.HTTPUnauthorized()
  elif request.path not in ("/health","/"):
   token=request.headers.get("Authorization","")
   if token.startswith("Bearer "): token=token[7:]
   if not token: token=request.query.get("token","")
   if API_TOKEN and token!=API_TOKEN: raise web.HTTPUnauthorized()
  r=await handler(request)
 r.headers["Access-Control-Allow-Origin"]=CORS
 r.headers["Access-Control-Allow-Headers"]="Authorization,Content-Type"
 r.headers["Access-Control-Allow-Methods"]="GET,POST,DELETE,OPTIONS"
 return r

async def liq(command:str,timeout=3.0)->str:
 reader,writer=await asyncio.wait_for(asyncio.open_connection(LIQ_HOST,LIQ_PORT),timeout)
 try:
  writer.write((command.strip()+"\n").encode()); await writer.drain()
  chunks=[]
  while True:
   line=await asyncio.wait_for(reader.readline(),timeout)
   if not line:break
   t=line.decode(errors="replace").rstrip("\r\n")
   if t=="END":break
   chunks.append(t)
  return "\n".join(chunks)
 finally:
  writer.close()
  try: await writer.wait_closed()
  except Exception: pass

def recent_conflict(item:dict)->bool:
 now=time.time()
 artist=str(item.get("artist","")).casefold().strip()
 title=str(item.get("title","")).casefold().strip()
 for h in reversed(state.get("history",[])[-1000:]):
  ts=float(h.get("ts",0) or 0)
  if artist and str(h.get("artist","")).casefold().strip()==artist:
   if now-ts < state.get("artist_separation_minutes",90)*60:return True
  if artist and title and str(h.get("artist","")).casefold().strip()==artist and str(h.get("title","")).casefold().strip()==title:
   if now-ts < state.get("track_separation_hours",120)*3600:return True
 return False

def current_clock_category()->str|None:
 blocks=state.get("clockwheel",[])
 if not blocks:return None
 minute=time.localtime().tm_min
 cursor=0
 for b in blocks:
  span=max(0,int(b.get("min",0) or 0))
  if cursor <= minute < cursor+span:return str(b.get("category","")).strip() or None
  cursor+=span
 return None

def choose_auto(category:str|None=None)->dict|None:
 pool=load_json(AUTO_POOL_FILE,[])
 wanted=category or current_clock_category()
 eligible=[x for x in pool if x.get("uri") and (not wanted or str(x.get("category","")).casefold()==wanted.casefold()) and not recent_conflict(x)]
 if not eligible:
  eligible=[x for x in pool if x.get("uri") and (not wanted or str(x.get("category","")).casefold()==wanted.casefold())]
 if not eligible: eligible=[x for x in pool if x.get("uri") and not recent_conflict(x)]
 if not eligible: eligible=[x for x in pool if x.get("uri")]
 return random.choice(eligible) if eligible else None

async def internal_next(request):
 mode=state.get("mode","auto")
 item=None
 async with _lock:
  q=state.setdefault("queue",[])
  if q:item=q.pop(0)
  elif mode in ("auto","recovery"): item=choose_auto()
  elif mode=="queue": item=None
  elif mode=="manual": item=None
  if item:
   state["now"]=item
 await save_state()
 if not item:
  if EMERGENCY_URI and mode=="recovery": return web.Response(text=EMERGENCY_URI)
  return web.Response(status=204)
 uri=str(item.get("uri","")).strip()
 if not uri:return web.Response(status=204)
 return web.Response(text=uri,content_type="text/plain")

async def health(request):
 ok=False; version=""
 try:
  version=await liq("version"); ok=True
 except Exception: pass
 return web.json_response({"ok":True,"liquidsoap":ok,"liquidsoap_version":version,"internal_key_configured":bool(INTERNAL_KEY)})

async def status(request):
 liq_ok=False; meta=""; remaining=""
 try:
  meta=await liq("auto.metadata")
  remaining=await liq("auto.remaining")
  liq_ok=True
 except Exception: pass
 return web.json_response({"node":"online","liquidsoap":liq_ok,"mode":state.get("mode"),"queue":state.get("queue",[]),
  "queue_count":len(state.get("queue",[])),"now":state.get("now"),"encoders":state.get("encoders",[]),
  "crossfade":state.get("crossfade"),"dsp":state.get("dsp"),"voice":state.get("voice"),
  "liquidsoap_metadata":meta,"remaining":remaining})

async def set_mode(request):
 data=await request.json(); mode=str(data.get("mode","")).lower()
 if mode not in {"auto","queue","manual","recovery"}: raise web.HTTPBadRequest(text="invalid mode")
 state["mode"]=mode; await save_state()
 try: await liq(f"var.set studio_mode = {mode}")
 except Exception: pass
 return web.json_response({"ok":True,"mode":mode})

async def get_queue(request): return web.json_response(state.get("queue",[]))
async def queue_add(request):
 data=await request.json()
 items=data.get("items") if isinstance(data,dict) else None
 if items is None: items=[data]
 if not isinstance(items,list): raise web.HTTPBadRequest()
 for x in items:
  if not isinstance(x,dict) or not x.get("uri"): raise web.HTTPBadRequest(text="queue item requires uri")
  state.setdefault("queue",[]).append(x)
 await save_state(); return web.json_response({"ok":True,"count":len(state["queue"])})

async def queue_set(request):
 data=await request.json()
 if not isinstance(data,list) or any(not isinstance(x,dict) or not x.get("uri") for x in data): raise web.HTTPBadRequest(text="array with uri required")
 state["queue"]=data; await save_state(); return web.json_response({"ok":True})

async def queue_move(request):
 d=await request.json(); i=int(d.get("from",-1)); j=int(d.get("to",-1)); q=state.get("queue",[])
 if not (0<=i<len(q) and 0<=j<len(q)): raise web.HTTPBadRequest()
 item=q.pop(i);q.insert(j,item);await save_state();return web.json_response({"ok":True})

async def queue_remove(request):
 i=int((await request.json()).get("index",-1));q=state.get("queue",[])
 if not 0<=i<len(q):raise web.HTTPBadRequest()
 q.pop(i);await save_state();return web.json_response({"ok":True})

async def queue_clear(request):
 state["queue"]=[];await save_state();return web.json_response({"ok":True})

async def deck_action(request):
 deck=request.match_info["deck"]; action=request.match_info["action"]
 if deck not in ("a","b") or action not in ("load","play","pause","stop","cue","air","skip","volume"):raise web.HTTPNotFound()
 data={}
 if request.can_read_body:
  try:data=await request.json()
  except Exception:data={}
 try:
  if action=="load":
   uri=str(data.get("uri","")).strip()
   if not uri: raise web.HTTPBadRequest(text="uri required")
   out=await liq(f"deck_{deck}.push {uri}")
  elif action=="skip": out=await liq(f"deck_{deck}.skip")
  elif action=="volume":
   v=max(0.0,min(1.5,float(data.get("value",100))/100.0));out=await liq(f"var.set deck_{deck}_gain = {v}")
  elif action in ("air","play"):
   out=await liq(f"var.set manual_deck = {deck}")
  elif action in ("stop","pause"):
   out=await liq("var.set manual_deck = none")
  else: out="cue handled by browser preview"
  return web.json_response({"ok":True,"result":out})
 except web.HTTPException: raise
 except Exception as e:raise web.HTTPServiceUnavailable(text=str(e))

async def encoder_action(request):
 action=request.match_info["action"]
 if action not in ("start","stop","restart"):raise web.HTTPNotFound()
 try:
  if action=="restart":
   a=await liq("out.stop");await asyncio.sleep(.5);b=await liq("out.start");result=a+"\n"+b
  else: result=await liq("out."+action)
  return web.json_response({"ok":True,"result":result})
 except Exception as e:raise web.HTTPServiceUnavailable(text=str(e))

async def crossfade_apply(request):
 d=await request.json()
 cfg={
  "duration":max(0.0,min(20.0,float(d.get("ms",d.get("duration",4500)))/1000.0 if float(d.get("ms",4500))>50 else float(d.get("duration",4.5)))),
  "fade_in":max(0.0,min(20.0,float(d.get("fadeIn",d.get("fade_in",1200)))/1000.0 if float(d.get("fadeIn",1200))>50 else float(d.get("fade_in",1.2)))),
  "fade_out":max(0.0,min(20.0,float(d.get("fadeOut",d.get("fade_out",2800)))/1000.0 if float(d.get("fadeOut",2800))>50 else float(d.get("fade_out",2.8))))
 }
 state["crossfade"]=cfg;await save_state()
 results=[]
 for name,val in (("xf_duration",cfg["duration"]),("xf_in",cfg["fade_in"]),("xf_out",cfg["fade_out"])):
  try:results.append(await liq(f"var.set {name} = {val}"))
  except Exception as e:results.append(str(e))
 return web.json_response({"ok":True,"crossfade":cfg,"result":results})

async def dsp_apply(request):
 d=await request.json(); p=d.get("processors",[])
 by={str(x.get("name","")).lower():x for x in p if isinstance(x,dict)}
 def val(name,i,default=50):
  try:return float(by.get(name,{}).get("values",[default])[i])
  except:return default
 cfg={
  "agc":bool(by.get("agc",{}).get("on",True)),
  "target":-24.0+(val("agc",0)/100.0)*18.0,
  "stereo_width":(val("stereo expander",0)-50)/50,
  "bass_gain":(val("bass eq",1)-50)/5 if len(by.get("bass eq",{}).get("values",[]))>1 else 0.0,
  "compressor":bool(by.get("compressor",{}).get("on",True)),
  "threshold":-40+(val("compressor",0)/100)*35,
  "ratio":1+(val("compressor",1)/100)*9 if len(by.get("compressor",{}).get("values",[]))>1 else 2,
  "limiter":bool(by.get("limiter",{}).get("on",True))
 }
 state["dsp"]=cfg;await save_state()
 commands=[
  ("agc_enabled","true" if cfg["agc"] else "false"),("agc_target",cfg["target"]),
  ("stereo_width",cfg["stereo_width"]),("bass_gain",cfg["bass_gain"]),
  ("comp_enabled","true" if cfg["compressor"] else "false"),("comp_threshold",cfg["threshold"]),
  ("comp_ratio",cfg["ratio"]),("limiter_enabled","true" if cfg["limiter"] else "false")
 ]
 out=[]
 for n,v in commands:
  try:out.append(await liq(f"var.set {n} = {v}"))
  except Exception as e:out.append(str(e))
 return web.json_response({"ok":True,"dsp":cfg,"result":out})

def db_to_gain(db:float)->float:return 10**(db/20)

async def voice_ptt(request):
 d=await request.json(); active=bool(d.get("active")); duck=float(d.get("duckDb",-8))
 state["voice"]={"active":active,"duck_db":duck,"fade_ms":int(d.get("fadeMs",350))};await save_state()
 try: await liq(f"var.set music_gain = {db_to_gain(duck) if active and d.get('autoDuck',True) else 1.0}")
 except Exception: pass
 return web.json_response({"ok":True})

async def voice_ws(request):
 ws=web.WebSocketResponse(max_msg_size=2*1024*1024,heartbeat=20);await ws.prepare(request)
 cmd=["ffmpeg","-hide_banner","-loglevel","error","-f","f32le","-ar","48000","-ac","1","-i","pipe:0",
      "-ar","44100","-ac","2","-c:a","libmp3lame","-b:a","128k","-content_type","audio/mpeg","-f","mp3",
      f"icecast://source:{VOICE_HARBOR_PASSWORD}@{VOICE_HARBOR_HOST}:{VOICE_HARBOR_PORT}/voice"]
 proc=await asyncio.create_subprocess_exec(*cmd,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
 try:
  async for msg in ws:
   if msg.type==WSMsgType.BINARY and proc.stdin:
    proc.stdin.write(msg.data);await proc.stdin.drain()
   elif msg.type==WSMsgType.ERROR:break
 finally:
  if proc.stdin:
   try:proc.stdin.close()
   except Exception:pass
  try:await asyncio.wait_for(proc.wait(),2)
  except asyncio.TimeoutError:proc.kill()
 return ws

async def voice_track_upload(request):
 reader=await request.multipart(); field=await reader.next()
 if field is None:raise web.HTTPBadRequest(text="file required")
 name=re.sub(r"[^A-Za-z0-9_.-]+","_",field.filename or f"voice-{int(time.time())}.webm")
 dest=VOICE_DIR/f"{int(time.time())}-{name}"
 with dest.open("wb") as f:
  while True:
   chunk=await field.read_chunk(1024*256)
   if not chunk:break
   f.write(chunk)
 return web.json_response({"ok":True,"path":str(dest),"uri":"file://"+str(dest)})


async def fx_upload(request):
 reader=await request.multipart(); field=await reader.next()
 if field is None:raise web.HTTPBadRequest(text="file required")
 name=re.sub(r"[^A-Za-z0-9_.-]+","_",field.filename or f"fx-{int(time.time())}.mp3")
 dest=FX_DIR/f"{int(time.time())}-{name}"
 with dest.open("wb") as f:
  while True:
   chunk=await field.read_chunk(1024*256)
   if not chunk:break
   f.write(chunk)
 return web.json_response({"ok":True,"name":name,"path":str(dest),"uri":"file://"+str(dest)})

async def fx_play(request):
 d=await request.json();uri=str(d.get("uri","")).strip()
 if not uri:raise web.HTTPBadRequest(text="uri required")
 try:out=await liq(f"fx.push {uri}")
 except Exception as e:raise web.HTTPServiceUnavailable(text=str(e))
 return web.json_response({"ok":True,"result":out})

async def get_clockwheel(request):return web.json_response(state.get("clockwheel",[]))
async def set_clockwheel(request):
 d=await request.json()
 if not isinstance(d,list):raise web.HTTPBadRequest()
 total=sum(max(0,int(x.get("min",0) or 0)) for x in d if isinstance(x,dict))
 if total>60:raise web.HTTPBadRequest(text="clock exceeds 60 minutes")
 state["clockwheel"]=d;await save_state();return web.json_response({"ok":True,"minutes":total})

async def get_schedule(request):return web.json_response(state.get("schedule",[]))
async def set_schedule(request):
 d=await request.json()
 if not isinstance(d,list):raise web.HTTPBadRequest()
 state["schedule"]=d;await save_state();return web.json_response({"ok":True,"count":len(d)})

async def execute_pal(script:str,log:list[str]|None=None):
 out=log if log is not None else []
 stopped=False
 for raw in script.splitlines():
  line=raw.strip()
  if not line or line.startswith("#"):continue
  m=re.match(r'^LOG\s+"(.*)"
 d=await request.json(); item={"ts":time.time(),"time":time.strftime("%H:%M:%S"),**d}
 state.setdefault("history",[]).append(item);state["history"]=state["history"][-5000:];state["now"]=d;await save_state()
 return web.json_response({"ok":True})

app=web.Application(middlewares=[cors_auth],client_max_size=64*1024*1024)
app.router.add_get("/",lambda r:web.json_response({"name":"Louder Playout Node","ok":True}))
app.router.add_get("/health",health);app.router.add_get("/status",status)
app.router.add_post("/mode",set_mode)
app.router.add_get("/queue",get_queue);app.router.add_post("/queue/add",queue_add);app.router.add_post("/queue/set",queue_set)
app.router.add_post("/queue/move",queue_move);app.router.add_post("/queue/remove",queue_remove);app.router.add_post("/queue/clear",queue_clear)
app.router.add_post("/deck/{deck}/{action}",deck_action)
app.router.add_post("/encoder/{action}",encoder_action)
app.router.add_post("/crossfade/apply",crossfade_apply);app.router.add_post("/dsp/apply",dsp_apply)
app.router.add_post("/voice/ptt",voice_ptt);app.router.add_get("/ws/voice",voice_ws);app.router.add_post("/voice-track",voice_track_upload)
app.router.add_post("/fx/upload",fx_upload);app.router.add_post("/fx/play",fx_play)
app.router.add_get("/clockwheel",get_clockwheel);app.router.add_post("/clockwheel",set_clockwheel)
app.router.add_get("/schedule",get_schedule);app.router.add_post("/schedule",set_schedule)
app.router.add_post("/pal/run",pal_run)
app.router.add_post("/history",history_event)
app.router.add_get("/internal/next",internal_next)
app.on_startup.append(on_startup);app.on_cleanup.append(on_cleanup)

if __name__=="__main__":
 web.run_app(app,host=os.getenv("LOUDER_API_BIND","0.0.0.0"),port=int(os.getenv("LOUDER_API_PORT","8787")))
,line,re.I)
  if m:out.append(m.group(1));continue
  m=re.match(r'^WAIT\s+(\d+(?:\.\d+)?)
 d=await request.json(); item={"ts":time.time(),"time":time.strftime("%H:%M:%S"),**d}
 state.setdefault("history",[]).append(item);state["history"]=state["history"][-5000:];state["now"]=d;await save_state()
 return web.json_response({"ok":True})

app=web.Application(middlewares=[cors_auth],client_max_size=64*1024*1024)
app.router.add_get("/",lambda r:web.json_response({"name":"Louder Playout Node","ok":True}))
app.router.add_get("/health",health);app.router.add_get("/status",status)
app.router.add_post("/mode",set_mode)
app.router.add_get("/queue",get_queue);app.router.add_post("/queue/add",queue_add);app.router.add_post("/queue/set",queue_set)
app.router.add_post("/queue/move",queue_move);app.router.add_post("/queue/remove",queue_remove);app.router.add_post("/queue/clear",queue_clear)
app.router.add_post("/deck/{deck}/{action}",deck_action)
app.router.add_post("/encoder/{action}",encoder_action)
app.router.add_post("/crossfade/apply",crossfade_apply);app.router.add_post("/dsp/apply",dsp_apply)
app.router.add_post("/voice/ptt",voice_ptt);app.router.add_get("/ws/voice",voice_ws);app.router.add_post("/voice-track",voice_track_upload)
app.router.add_post("/history",history_event)
app.router.add_get("/internal/next",internal_next)

if __name__=="__main__":
 web.run_app(app,host=os.getenv("LOUDER_API_BIND","0.0.0.0"),port=int(os.getenv("LOUDER_API_PORT","8787")))
,line,re.I)
  if m:await asyncio.sleep(min(3600,float(m.group(1))));continue
  m=re.match(r'^MODE\s+(AUTO|QUEUE|MANUAL|RECOVERY)
 d=await request.json(); item={"ts":time.time(),"time":time.strftime("%H:%M:%S"),**d}
 state.setdefault("history",[]).append(item);state["history"]=state["history"][-5000:];state["now"]=d;await save_state()
 return web.json_response({"ok":True})

app=web.Application(middlewares=[cors_auth],client_max_size=64*1024*1024)
app.router.add_get("/",lambda r:web.json_response({"name":"Louder Playout Node","ok":True}))
app.router.add_get("/health",health);app.router.add_get("/status",status)
app.router.add_post("/mode",set_mode)
app.router.add_get("/queue",get_queue);app.router.add_post("/queue/add",queue_add);app.router.add_post("/queue/set",queue_set)
app.router.add_post("/queue/move",queue_move);app.router.add_post("/queue/remove",queue_remove);app.router.add_post("/queue/clear",queue_clear)
app.router.add_post("/deck/{deck}/{action}",deck_action)
app.router.add_post("/encoder/{action}",encoder_action)
app.router.add_post("/crossfade/apply",crossfade_apply);app.router.add_post("/dsp/apply",dsp_apply)
app.router.add_post("/voice/ptt",voice_ptt);app.router.add_get("/ws/voice",voice_ws);app.router.add_post("/voice-track",voice_track_upload)
app.router.add_post("/history",history_event)
app.router.add_get("/internal/next",internal_next)

if __name__=="__main__":
 web.run_app(app,host=os.getenv("LOUDER_API_BIND","0.0.0.0"),port=int(os.getenv("LOUDER_API_PORT","8787")))
,line,re.I)
  if m:
   state["mode"]=m.group(1).lower();await save_state();out.append("MODE "+m.group(1).upper());continue
  m=re.match(r'^QUEUE\s+CATEGORY\s+"(.*)"\s+(\d+)
 d=await request.json(); item={"ts":time.time(),"time":time.strftime("%H:%M:%S"),**d}
 state.setdefault("history",[]).append(item);state["history"]=state["history"][-5000:];state["now"]=d;await save_state()
 return web.json_response({"ok":True})

app=web.Application(middlewares=[cors_auth],client_max_size=64*1024*1024)
app.router.add_get("/",lambda r:web.json_response({"name":"Louder Playout Node","ok":True}))
app.router.add_get("/health",health);app.router.add_get("/status",status)
app.router.add_post("/mode",set_mode)
app.router.add_get("/queue",get_queue);app.router.add_post("/queue/add",queue_add);app.router.add_post("/queue/set",queue_set)
app.router.add_post("/queue/move",queue_move);app.router.add_post("/queue/remove",queue_remove);app.router.add_post("/queue/clear",queue_clear)
app.router.add_post("/deck/{deck}/{action}",deck_action)
app.router.add_post("/encoder/{action}",encoder_action)
app.router.add_post("/crossfade/apply",crossfade_apply);app.router.add_post("/dsp/apply",dsp_apply)
app.router.add_post("/voice/ptt",voice_ptt);app.router.add_get("/ws/voice",voice_ws);app.router.add_post("/voice-track",voice_track_upload)
app.router.add_post("/history",history_event)
app.router.add_get("/internal/next",internal_next)

if __name__=="__main__":
 web.run_app(app,host=os.getenv("LOUDER_API_BIND","0.0.0.0"),port=int(os.getenv("LOUDER_API_PORT","8787")))
,line,re.I)
  if m:
   n=min(100,int(m.group(2)));added=0
   for _ in range(n):
    item=choose_auto(m.group(1))
    if item:state.setdefault("queue",[]).append(item);added+=1
   await save_state();out.append(f"QUEUED {added} {m.group(1)}");continue
  m=re.match(r'^QUEUE\s+URI\s+"(.*)"
 d=await request.json(); item={"ts":time.time(),"time":time.strftime("%H:%M:%S"),**d}
 state.setdefault("history",[]).append(item);state["history"]=state["history"][-5000:];state["now"]=d;await save_state()
 return web.json_response({"ok":True})

app=web.Application(middlewares=[cors_auth],client_max_size=64*1024*1024)
app.router.add_get("/",lambda r:web.json_response({"name":"Louder Playout Node","ok":True}))
app.router.add_get("/health",health);app.router.add_get("/status",status)
app.router.add_post("/mode",set_mode)
app.router.add_get("/queue",get_queue);app.router.add_post("/queue/add",queue_add);app.router.add_post("/queue/set",queue_set)
app.router.add_post("/queue/move",queue_move);app.router.add_post("/queue/remove",queue_remove);app.router.add_post("/queue/clear",queue_clear)
app.router.add_post("/deck/{deck}/{action}",deck_action)
app.router.add_post("/encoder/{action}",encoder_action)
app.router.add_post("/crossfade/apply",crossfade_apply);app.router.add_post("/dsp/apply",dsp_apply)
app.router.add_post("/voice/ptt",voice_ptt);app.router.add_get("/ws/voice",voice_ws);app.router.add_post("/voice-track",voice_track_upload)
app.router.add_post("/history",history_event)
app.router.add_get("/internal/next",internal_next)

if __name__=="__main__":
 web.run_app(app,host=os.getenv("LOUDER_API_BIND","0.0.0.0"),port=int(os.getenv("LOUDER_API_PORT","8787")))
,line,re.I)
  if m:
   state.setdefault("queue",[]).append({"artist":"","title":"PAL URI","uri":m.group(1),"category":"PAL"});await save_state();out.append("QUEUED URI");continue
  m=re.match(r'^ENCODER\s+(START|STOP|RESTART)
 d=await request.json(); item={"ts":time.time(),"time":time.strftime("%H:%M:%S"),**d}
 state.setdefault("history",[]).append(item);state["history"]=state["history"][-5000:];state["now"]=d;await save_state()
 return web.json_response({"ok":True})

app=web.Application(middlewares=[cors_auth],client_max_size=64*1024*1024)
app.router.add_get("/",lambda r:web.json_response({"name":"Louder Playout Node","ok":True}))
app.router.add_get("/health",health);app.router.add_get("/status",status)
app.router.add_post("/mode",set_mode)
app.router.add_get("/queue",get_queue);app.router.add_post("/queue/add",queue_add);app.router.add_post("/queue/set",queue_set)
app.router.add_post("/queue/move",queue_move);app.router.add_post("/queue/remove",queue_remove);app.router.add_post("/queue/clear",queue_clear)
app.router.add_post("/deck/{deck}/{action}",deck_action)
app.router.add_post("/encoder/{action}",encoder_action)
app.router.add_post("/crossfade/apply",crossfade_apply);app.router.add_post("/dsp/apply",dsp_apply)
app.router.add_post("/voice/ptt",voice_ptt);app.router.add_get("/ws/voice",voice_ws);app.router.add_post("/voice-track",voice_track_upload)
app.router.add_post("/history",history_event)
app.router.add_get("/internal/next",internal_next)

if __name__=="__main__":
 web.run_app(app,host=os.getenv("LOUDER_API_BIND","0.0.0.0"),port=int(os.getenv("LOUDER_API_PORT","8787")))
,line,re.I)
  if m:
   action=m.group(1).lower()
   if action=="restart":await liq("out.stop");await asyncio.sleep(.3);await liq("out.start")
   else:await liq("out."+action)
   out.append("ENCODER "+m.group(1).upper());continue
  m=re.match(r'^SKIP
 d=await request.json(); item={"ts":time.time(),"time":time.strftime("%H:%M:%S"),**d}
 state.setdefault("history",[]).append(item);state["history"]=state["history"][-5000:];state["now"]=d;await save_state()
 return web.json_response({"ok":True})

app=web.Application(middlewares=[cors_auth],client_max_size=64*1024*1024)
app.router.add_get("/",lambda r:web.json_response({"name":"Louder Playout Node","ok":True}))
app.router.add_get("/health",health);app.router.add_get("/status",status)
app.router.add_post("/mode",set_mode)
app.router.add_get("/queue",get_queue);app.router.add_post("/queue/add",queue_add);app.router.add_post("/queue/set",queue_set)
app.router.add_post("/queue/move",queue_move);app.router.add_post("/queue/remove",queue_remove);app.router.add_post("/queue/clear",queue_clear)
app.router.add_post("/deck/{deck}/{action}",deck_action)
app.router.add_post("/encoder/{action}",encoder_action)
app.router.add_post("/crossfade/apply",crossfade_apply);app.router.add_post("/dsp/apply",dsp_apply)
app.router.add_post("/voice/ptt",voice_ptt);app.router.add_get("/ws/voice",voice_ws);app.router.add_post("/voice-track",voice_track_upload)
app.router.add_post("/history",history_event)
app.router.add_get("/internal/next",internal_next)

if __name__=="__main__":
 web.run_app(app,host=os.getenv("LOUDER_API_BIND","0.0.0.0"),port=int(os.getenv("LOUDER_API_PORT","8787")))
,line,re.I)
  if m:
   await liq("auto.skip");out.append("SKIP");continue
  raise ValueError("Unsupported PAL command: "+line)
 return out

async def pal_run(request):
 d=await request.json();script=str(d.get("script",""))
 try:log=await execute_pal(script,[])
 except Exception as e:return web.json_response({"ok":False,"error":str(e)},status=400)
 return web.json_response({"ok":True,"log":log})

async def run_scheduled_event(event:dict):
 action=str(event.get("action","")).lower()
 if action in ("run pal","pal"):
  await execute_pal(str(event.get("script") or event.get("payload") or ""),[])
 elif action in ("queue category","category"):
  cat=str(event.get("category") or event.get("payload") or "")
  n=int(event.get("count",1) or 1)
  for _ in range(max(0,min(n,100))):
   item=choose_auto(cat)
   if item:state.setdefault("queue",[]).append(item)
  await save_state()
 elif action in ("load clock","clock"):
  if isinstance(event.get("clock"),list):state["clockwheel"]=event["clock"];await save_state()
 elif action in ("station id","id"):
  uri=str(event.get("uri",""))
  if uri:state.setdefault("queue",[]).insert(0,{"artist":"Louder","title":"Station ID","uri":uri,"category":"Station IDs"});await save_state()

async def scheduler_loop(app):
 while True:
  now=time.localtime();hhmm=f"{now.tm_hour:02d}:{now.tm_min:02d}";day=time.strftime("%Y-%m-%d",now)
  changed=False
  for e in state.get("schedule",[]):
   if str(e.get("time",""))==hhmm and e.get("_last")!=day:
    try:await run_scheduled_event(e)
    except Exception as ex:print("scheduler:",ex,flush=True)
    e["_last"]=day;changed=True
  if changed:await save_state()
  await asyncio.sleep(15)

async def on_startup(app):
 app["scheduler_task"]=asyncio.create_task(scheduler_loop(app))

async def on_cleanup(app):
 task=app.get("scheduler_task")
 if task:task.cancel()

async def history_event(request):
 d=await request.json(); item={"ts":time.time(),"time":time.strftime("%H:%M:%S"),**d}
 state.setdefault("history",[]).append(item);state["history"]=state["history"][-5000:];state["now"]=d;await save_state()
 return web.json_response({"ok":True})

app=web.Application(middlewares=[cors_auth],client_max_size=64*1024*1024)
app.router.add_get("/",lambda r:web.json_response({"name":"Louder Playout Node","ok":True}))
app.router.add_get("/health",health);app.router.add_get("/status",status)
app.router.add_post("/mode",set_mode)
app.router.add_get("/queue",get_queue);app.router.add_post("/queue/add",queue_add);app.router.add_post("/queue/set",queue_set)
app.router.add_post("/queue/move",queue_move);app.router.add_post("/queue/remove",queue_remove);app.router.add_post("/queue/clear",queue_clear)
app.router.add_post("/deck/{deck}/{action}",deck_action)
app.router.add_post("/encoder/{action}",encoder_action)
app.router.add_post("/crossfade/apply",crossfade_apply);app.router.add_post("/dsp/apply",dsp_apply)
app.router.add_post("/voice/ptt",voice_ptt);app.router.add_get("/ws/voice",voice_ws);app.router.add_post("/voice-track",voice_track_upload)
app.router.add_post("/history",history_event)
app.router.add_get("/internal/next",internal_next)

if __name__=="__main__":
 web.run_app(app,host=os.getenv("LOUDER_API_BIND","0.0.0.0"),port=int(os.getenv("LOUDER_API_PORT","8787")))
