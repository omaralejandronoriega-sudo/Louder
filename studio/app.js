const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
const store={get:(k,d)=>{try{const v=localStorage.getItem("lcs:"+k);return v?JSON.parse(v):d}catch{return d}},set:(k,v)=>localStorage.setItem("lcs:"+k,JSON.stringify(v))};
const state={mode:store.get("mode","auto"),queue:store.get("queue",[]),clock:store.get("clock",[]),events:store.get("events",[]),encoders:store.get("encoders",[{name:"YesStreaming Primary",codec:"MP3",bitrate:320,status:"Unknown"}]),history:store.get("history",[]),xf:store.get("xf",{}),dsp:store.get("dsp",{}),api:store.get("api",{url:"",token:""}),library:[],category:"All",selectedQueue:-1,mic:null,micCtx:null,micProcessor:null,micSending:false,voiceWs:null,recorder:null,chunks:[],lastVoiceBlob:null,palStop:false,nodeOnline:false,requests:[],selectedRequest:null,statsSamples:[]};
const log=m=>{const e=$("#eventLog");if(e){e.textContent+=new Date().toLocaleTimeString()+"  "+m+"\n";e.scrollTop=e.scrollHeight}};
const fmt=s=>!s?"—":String(s);
setInterval(()=>$("#clock").textContent=new Date().toLocaleTimeString("es-MX"),500);

$$(".desk").forEach(b=>b.onclick=()=>{$$(".desk").forEach(x=>x.classList.toggle("active",x===b));$$(".desktop").forEach(x=>x.classList.remove("active"));$("#desk"+b.dataset.desk).classList.add("active")});
$$(".mode").forEach(b=>{b.classList.toggle("active",b.dataset.mode===state.mode);b.onclick=()=>{state.mode=b.dataset.mode;store.set("mode",state.mode);$$(".mode").forEach(x=>x.classList.toggle("active",x===b));nodeAction("mode",{mode:state.mode});log("Mode -> "+state.mode)}});

async function loadLibrary(){
 try{
  const r=await fetch("../data/history/history_yesstreaming_catalog.json",{cache:"no-store"});
  if(!r.ok)throw new Error("catalog");
  const data=await r.json(),out=[];
  for(const [,entry] of Object.entries(data.artists||{})){
   const artist=entry?.[0]||"Unknown",tracks=entry?.[1]||[];
   for(const t of tracks){
    const title=t?.[0]||"Untitled",folder=t?.[1]||"Music",status=t?.[2]||"",path=t?.[3]||"",last=t?.[4]||"";
    out.push({artist,title,folder,status,path,last,duration:0,category:folder});
   }
  }
  state.library=out;
  log("Library loaded: "+out.length+" tracks");
 }catch(e){
  state.library=[
   {artist:"Fontaines D.C.",title:"Favourite",folder:"2023-2024",category:"2023-2024"},
   {artist:"Interpol",title:"Toni",folder:"2021-2022",category:"2021-2022"},
   {artist:"The Cure",title:"Alone",folder:"2025",category:"2025"},
   {artist:"Bloc Party",title:"Banquet",folder:"Louder",category:"Louder"}
  ];
  log("Catalog fallback loaded");
 }
 renderCategories();renderLibrary();
}

async function loadNodeCatalog(){
 if(!state.nodeOnline)return false;
 try{
  const rows=await apiFetch("catalog",{},true);
  if(!Array.isArray(rows))throw new Error("invalid catalog");
  state.library=rows.map(x=>({...x,folder:x.category||"Telegram",category:x.category||"Telegram"}));
  renderCategories();renderLibrary();
  log("Playable cloud catalog loaded: "+state.library.length+" tracks");
  return true;
 }catch(e){log("Cloud catalog failed: "+e.message);return false}
}
function cats(){return ["All",...new Set(state.library.map(x=>x.category)),"Station IDs","Jingles","Promos","Sound FX"]}
function renderCategories(){
 $("#categories").innerHTML=cats().map(c=>'<span class="cat '+(c===state.category?"active":"")+'" data-cat="'+esc(c)+'">'+esc(c)+'</span>').join("");
 $$(".cat").forEach(x=>x.onclick=()=>{state.category=x.dataset.cat;renderCategories();renderLibrary()});
 $("#clockCat").innerHTML=cats().filter(x=>x!=="All").map(x=>"<option>"+esc(x)+"</option>").join("");
}
function renderLibrary(){
 const q=$("#search").value.toLowerCase();
 const rows=state.library.filter(x=>(state.category==="All"||x.category===state.category)&&(!q||(x.artist+" "+x.title).toLowerCase().includes(q))).slice(0,350);
 $("#libraryRows").innerHTML=rows.map((x,i)=>'<tr><td>'+esc(x.artist)+'</td><td>'+esc(x.title)+'</td><td>'+esc(x.folder)+'</td><td><button data-add="'+i+'">+</button></td></tr>').join("");
 $$("[data-add]").forEach(b=>b.onclick=()=>{state.queue.push(rows[+b.dataset.add]);saveQueue()});
}
$("#search").oninput=renderLibrary;$("#clearSearch").onclick=()=>{$("#search").value="";renderLibrary()};

async function saveQueue(){store.set("queue",state.queue);renderQueue();if(state.nodeOnline&&state.queue.every(x=>x.uri||x.message_id!=null)){try{await apiFetch("queue/set",state.queue);await syncNodeState()}catch(e){log("Queue sync failed: "+e.message)}}}
function renderQueue(){
 $("#queueRows").innerHTML=state.queue.map((x,i)=>'<tr data-qi="'+i+'" class="'+(state.selectedQueue===i?"selected":"")+'"><td>'+(i+1)+'</td><td>—</td><td>'+esc(x.artist)+'</td><td>'+esc(x.title)+'</td></tr>').join("");
 $("#qCount").textContent=state.queue.length;
 $$("[data-qi]").forEach(r=>r.onclick=()=>{state.selectedQueue=+r.dataset.qi;renderQueue()});
}
function moveQ(d){const i=state.selectedQueue,j=i+d;if(i<0||j<0||j>=state.queue.length)return;[state.queue[i],state.queue[j]]=[state.queue[j],state.queue[i]];state.selectedQueue=j;saveQueue()}
$("#qUp").onclick=()=>moveQ(-1);$("#qDown").onclick=()=>moveQ(1);$("#qRemove").onclick=()=>{if(state.selectedQueue>=0){state.queue.splice(state.selectedQueue,1);state.selectedQueue=-1;saveQueue()}};$("#qClear").onclick=()=>{state.queue=[];state.selectedQueue=-1;saveQueue()};$("#qSave").onclick=()=>{store.set("queue",state.queue);log("Queue saved")};

let fxRuntime=[];
function renderFx(){const el=$("#fxPads");el.innerHTML="";for(let i=0;i<12;i++){const p=fxRuntime[i],b=document.createElement("button");b.className="pad";b.textContent=p?p.name.slice(0,18):"FX "+(i+1);b.disabled=!p;b.onclick=async()=>{if($("#fxTarget").value==="air"&&state.nodeOnline&&p.remoteUri){b.classList.add("playing");try{await apiFetch("fx/play",{uri:p.remoteUri});log("FX AIR: "+p.name)}catch(e){log("FX failed: "+e.message)}setTimeout(()=>b.classList.remove("playing"),700)}else{const a=new Audio(p.url);b.classList.add("playing");a.onended=()=>b.classList.remove("playing");a.play()}};el.appendChild(b)}}
$("#fxLoad").onclick=()=>$("#fxFile").click();$("#fxFile").onchange=async e=>{fxRuntime=[];for(const f of [...e.target.files].slice(0,12)){const item={name:f.name,url:URL.createObjectURL(f),remoteUri:null};if(state.nodeOnline){try{const fd=new FormData();fd.append("file",f,f.name);const r=await fetch(state.api.url+"/fx/upload",{method:"POST",headers:state.api.token?{Authorization:"Bearer "+state.api.token}:{},body:fd});if(r.ok){const d=await r.json();item.remoteUri=d.uri}}catch(err){log("FX upload failed: "+err.message)}}fxRuntime.push(item)}renderFx();log("Loaded "+fxRuntime.length+" FX")};

$("#micEnable").onclick=async()=>{try{state.mic=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});$("#micStatus").textContent="READY";$("#micLatch").disabled=!state.nodeOnline;$("#ptt").disabled=!state.nodeOnline;$("#vtRecord").disabled=false;setupMicStream(state.mic);meterMic(state.mic);log("Microphone enabled")}catch(e){log("Mic denied: "+e.message)}};
function meterMic(stream){const ctx=new AudioContext(),src=ctx.createMediaStreamSource(stream),an=ctx.createAnalyser();an.fftSize=256;src.connect(an);const buf=new Uint8Array(an.frequencyBinCount);(function tick(){an.getByteFrequencyData(buf);const avg=buf.reduce((a,b)=>a+b,0)/buf.length;$("#micLevel").style.width=Math.min(100,avg/1.4)+"%";requestAnimationFrame(tick)})()}
function wsUrl(){if(!state.api.url)return"";const base=state.api.url.replace(/^http:/,"ws:").replace(/^https:/,"wss:");const qs=new URLSearchParams();if(state.api.token)qs.set("token",state.api.token);qs.set("rate",String(state.micCtx?.sampleRate||48000));return base+"/ws/voice?"+qs.toString()}
function setupMicStream(stream){if(state.micCtx)return;state.micCtx=new AudioContext({sampleRate:48000});const src=state.micCtx.createMediaStreamSource(stream);const proc=state.micCtx.createScriptProcessor(2048,1,1);const sink=state.micCtx.createGain();sink.gain.value=0;proc.onaudioprocess=e=>{if(!state.micSending||!state.voiceWs||state.voiceWs.readyState!==WebSocket.OPEN)return;const data=e.inputBuffer.getChannelData(0);state.voiceWs.send(data.slice().buffer)};src.connect(proc);proc.connect(sink);sink.connect(state.micCtx.destination);state.micProcessor=proc}
async function openVoiceSocket(){if(state.voiceWs&&state.voiceWs.readyState===WebSocket.OPEN)return;await new Promise((resolve,reject)=>{const ws=new WebSocket(wsUrl());ws.binaryType="arraybuffer";ws.onopen=()=>{state.voiceWs=ws;resolve()};ws.onerror=()=>reject(new Error("Voice websocket failed"));ws.onclose=()=>{state.voiceWs=null;state.micSending=false}})}
async function ptt(active){if(!state.mic||!state.nodeOnline)return;try{if(active){await openVoiceSocket();state.micSending=true}else{state.micSending=false;if(state.voiceWs){state.voiceWs.close();state.voiceWs=null}}$("#micStatus").textContent=active?"LIVE":"READY";await nodeAction("voice/ptt",{active,duckDb:+$("#duckDb").value,fadeMs:+$("#micFade").value,autoDuck:$("#autoDuck").checked})}catch(e){log("PTT failed: "+e.message);$("#micStatus").textContent="ERROR"}}
$("#ptt").onpointerdown=()=>ptt(true);$("#ptt").onpointerup=()=>ptt(false);$("#micLatch").onclick=()=>ptt($("#micStatus").textContent!=="LIVE");
window.addEventListener("keydown",e=>{if(e.key==="F11"){e.preventDefault();ptt(true)}});window.addEventListener("keyup",e=>{if(e.key==="F11"){e.preventDefault();ptt(false)}});
$("#vtRecord").onclick=()=>{if(!state.mic)return;state.chunks=[];state.recorder=new MediaRecorder(state.mic);state.recorder.ondataavailable=e=>state.chunks.push(e.data);state.recorder.onstop=()=>{state.lastVoiceBlob=new Blob(state.chunks,{type:"audio/webm"});$("#vtPreview").src=URL.createObjectURL(state.lastVoiceBlob);$("#vtStore").disabled=!state.nodeOnline;log("Voice track recorded")};state.recorder.start();$("#vtStop").disabled=false};
$("#vtStop").onclick=()=>{if(state.recorder?.state==="recording")state.recorder.stop();$("#vtStop").disabled=true};
$("#vtStore").onclick=async()=>{if(!state.lastVoiceBlob||!state.nodeOnline)return;try{const fd=new FormData();fd.append("file",state.lastVoiceBlob,"voice-track-"+Date.now()+".webm");const r=await fetch(state.api.url+"/voice-track",{method:"POST",headers:state.api.token?{Authorization:"Bearer "+state.api.token}:{},body:fd});if(!r.ok)throw new Error("HTTP "+r.status);const d=await r.json();state.queue.push({artist:"Louder",title:"Voice Track",category:"Voice Track",uri:d.uri});await saveQueue();log("Voice Track stored and queued")}catch(e){log("Voice Track upload failed: "+e.message)}};

function renderEncoders(){$("#encoderRows").innerHTML=state.encoders.map((e,i)=>'<tr><td>'+(i+1)+'</td><td>'+esc(e.codec)+' '+e.bitrate+' kbps</td><td>'+esc(e.status)+'</td><td>'+esc(e.name)+'</td></tr>').join("")}
$("#encAdd").onclick=()=>{state.encoders.push({name:$("#encName").value||"Encoder",codec:$("#encCodec").value,bitrate:+$("#encBitrate").value,status:"Configured"});store.set("encoders",state.encoders);renderEncoders();log("Encoder added")};

function renderClock(){
 const total=state.clock.reduce((a,b)=>a+(+b.min||0),0);
 $("#clockBlocks").innerHTML=state.clock.map((x,i)=>'<div class="clockblock"><span>'+(i+1)+'. '+esc(x.category)+' — '+x.min+' min</span><button data-dc="'+i+'">×</button></div>').join("")||"<p>No blocks yet.</p>";
 const colors=["#3b88c7","#e0a13c","#5daf68","#9a63b0","#c84e57","#4eaaa0"];let acc=0,parts=[];
 state.clock.forEach((x,i)=>{const s=acc/60*100;acc+=+x.min||0;const e=Math.min(100,acc/60*100);parts.push(colors[i%colors.length]+" "+s+"% "+e+"%")});
 $("#clockFace").style.background=parts.length?"conic-gradient("+parts.join(",")+")":"#c9cfd4";$("#clockFace b").textContent=total+"/60";
 $$("[data-dc]").forEach(b=>b.onclick=()=>{state.clock.splice(+b.dataset.dc,1);renderClock()});
}
$("#clockAdd").onclick=()=>{state.clock.push({category:$("#clockCat").value,min:+$("#clockMin").value});renderClock()};$("#clockSave").onclick=async()=>{store.set("clock",state.clock);if(state.nodeOnline){try{await apiFetch("clockwheel",state.clock)}catch(e){log("Clock sync failed: "+e.message)}}log("Clockwheel saved")};

function renderEvents(){$("#eventRows").innerHTML=state.events.sort((a,b)=>a.time.localeCompare(b.time)).map((e,i)=>'<tr><td>'+e.time+'</td><td>'+esc(e.name)+'</td><td>'+esc(e.action)+'</td><td><button data-de="'+i+'">×</button></td></tr>').join("");$$("[data-de]").forEach(b=>b.onclick=()=>{state.events.splice(+b.dataset.de,1);store.set("events",state.events);renderEvents()})}
$("#eventAdd").onclick=async()=>{if(!$("#eventTime").value||!$("#eventName").value)return;state.events.push({time:$("#eventTime").value,name:$("#eventName").value,action:$("#eventAction").value,last:""});store.set("events",state.events);renderEvents();if(state.nodeOnline){try{await apiFetch("schedule",state.events)}catch(e){log("Schedule sync failed: "+e.message)}}log("Event scheduled")};
setInterval(()=>{const d=new Date(),hm=d.toTimeString().slice(0,5),today=d.toISOString().slice(0,10);state.events.forEach(e=>{if(e.time===hm&&e.last!==today){e.last=today;store.set("events",state.events);log("Scheduled event: "+e.name+" / "+e.action);if(e.action==="Run PAL")runPal()}})},15000);

function collectXf(){return {enable:$("#xfEnable").checked,mode:$("#xfMode").value,ms:+$("#xfMs").value,fadeIn:+$("#xfIn").value,fadeOut:+$("#xfOut").value,fadeInType:$("#xfInType").value,fadeOutType:$("#xfOutType").value,curve:+$("#xfCurve").value,overlapDb:+$("#xfOverlap").value,gapKiller:$("#gapKiller").checked,silenceDb:+$("#silenceDb").value,silenceMs:+$("#silenceMs").value,respectCue:$("#respectCue").checked,jingles:$("#xfJingles").checked}}
$("#xfSave").onclick=()=>{state.xf=collectXf();store.set("xf",state.xf);log("Crossfade rules saved")};
function restoreXf(){const x=state.xf;if(!Object.keys(x).length)return;$("#xfEnable").checked=x.enable;$("#xfMode").value=x.mode||"smart";$("#xfMs").value=x.ms;$("#xfIn").value=x.fadeIn;$("#xfOut").value=x.fadeOut;$("#xfInType").value=x.fadeInType||"lin";$("#xfOutType").value=x.fadeOutType||"lin";$("#xfCurve").value=x.curve||10;$("#xfOverlap").value=x.overlapDb;$("#gapKiller").checked=x.gapKiller;$("#silenceDb").value=x.silenceDb;$("#silenceMs").value=x.silenceMs;$("#respectCue").checked=x.respectCue;$("#xfJingles").checked=x.jingles}

function collectDsp(){return $$(".processor").map(p=>({name:p.querySelector("h3").textContent,on:p.querySelector('input[type="checkbox"]').checked,values:[...p.querySelectorAll('input[type="range"]')].map(x=>+x.value)}))}
$("#pipelineSave").onclick=()=>{state.dsp=collectDsp();store.set("dsp",state.dsp);log("DSP preset saved")};
function restoreDsp(){if(!Array.isArray(state.dsp))return;$$(".processor").forEach((p,i)=>{const d=state.dsp[i];if(!d)return;p.querySelector('input[type="checkbox"]').checked=d.on;[...p.querySelectorAll('input[type="range"]')].forEach((x,j)=>x.value=d.values[j]??x.value)})}

function palLines(){return $("#palEditor").value.split(/\r?\n/).map(x=>x.trim()).filter(x=>x&&!x.startsWith("#"))}
function validatePal(){const bad=[];palLines().forEach((l,i)=>{if(!/^(LOG\s+".*"|MODE\s+(AUTO|QUEUE|MANUAL|RECOVERY)|QUEUE\s+CATEGORY\s+".*"\s+\d+|WAIT\s+\d+)$/i.test(l))bad.push("Line "+(i+1)+": "+l)});$("#palLog").textContent=bad.length?bad.join("\n"):"Valid.";return !bad.length}
async function runPal(){if(!validatePal())return;state.palStop=false;$("#palLog").textContent="Running...\n";for(const line of palLines()){if(state.palStop)break;let m;if((m=line.match(/^LOG\s+"(.*)"$/i)))$("#palLog").textContent+=m[1]+"\n";else if((m=line.match(/^MODE\s+(AUTO|QUEUE|MANUAL|RECOVERY)$/i))){state.mode=m[1].toLowerCase();store.set("mode",state.mode);$("#palLog").textContent+="Mode "+m[1]+"\n"}else if((m=line.match(/^QUEUE\s+CATEGORY\s+"(.*)"\s+(\d+)$/i))){const pool=state.library.filter(x=>x.category.toLowerCase()===m[1].toLowerCase());for(let i=0;i<+m[2]&&pool.length;i++)state.queue.push(pool[Math.floor(Math.random()*pool.length)]);saveQueue();$("#palLog").textContent+="Queued "+m[2]+" from "+m[1]+"\n"}else if((m=line.match(/^WAIT\s+(\d+)$/i)))await new Promise(r=>setTimeout(r,+m[1]*1000))}$("#palLog").textContent+=state.palStop?"Stopped.":"Done."}
$("#palValidate").onclick=validatePal;$("#palRun").onclick=async()=>{if(!validatePal())return;if(state.nodeOnline){try{const r=await apiFetch("pal/run",{script:$("#palEditor").value});$("#palLog").textContent=(r.log||[]).join("\n")||"Done.";log("PAL executed on node")}catch(e){$("#palLog").textContent=e.message}}else runPal()};$("#palStop").onclick=()=>state.palStop=true;

async function refreshPalScripts(){if(!state.nodeOnline){$("#palScripts").innerHTML='<option value="">Saved scripts</option>';return}try{const rows=await apiFetch("pal/scripts",{},true);$("#palScripts").innerHTML='<option value="">Saved scripts</option>'+rows.map(x=>'<option value="'+esc(x.name)+'">'+esc(x.name)+'</option>').join("");state.palScripts=rows}catch(e){log("PAL list failed: "+e.message)}}
$("#palLoad").onclick=async()=>{const name=$("#palScripts").value;if(!name)return;try{const row=(state.palScripts||[]).find(x=>x.name===name)||await apiFetch("pal/scripts/"+encodeURIComponent(name),{},true);$("#palName").value=row.name;$("#palEditor").value=row.script;$("#palLog").textContent="Loaded "+row.name}catch(e){$("#palLog").textContent=e.message}};
$("#palSave").onclick=async()=>{const name=$("#palName").value.trim();if(!name){$("#palLog").textContent="Name required.";return}if(!validatePal())return;if(!state.nodeOnline){store.set("pal:"+name,$("#palEditor").value);$("#palLog").textContent="Saved locally: "+name;return}try{await apiFetch("pal/scripts/"+encodeURIComponent(name),{script:$("#palEditor").value});await refreshPalScripts();$("#palScripts").value=name;$("#palLog").textContent="Saved: "+name;log("PAL saved: "+name)}catch(e){$("#palLog").textContent=e.message}};
$("#palDelete").onclick=async()=>{const name=$("#palScripts").value||$("#palName").value.trim();if(!name||!state.nodeOnline)return;try{const headers={};if(state.api.token)headers.Authorization="Bearer "+state.api.token;const rr=await fetch(state.api.url+"/pal/scripts/"+encodeURIComponent(name),{method:"DELETE",headers});if(!rr.ok)throw new Error("HTTP "+rr.status);$("#palName").value="";await refreshPalScripts();$("#palLog").textContent="Deleted: "+name}catch(e){$("#palLog").textContent=e.message}};

$("#apiUrl").value=state.api.url||"";$("#apiToken").value=state.api.token||"";
$("#apiSave").onclick=()=>{state.api={url:$("#apiUrl").value.trim().replace(/\/$/,""),token:$("#apiToken").value};store.set("api",state.api);log("Node API settings saved");refreshNodeButtons()};
$("#apiTest").onclick=async()=>{state.api={url:$("#apiUrl").value.trim().replace(/\/$/,""),token:$("#apiToken").value};try{const r=await apiFetch("status",{},true);state.nodeOnline=!!r;$("#apiLog").textContent=JSON.stringify(r,null,2);setNode(true);await syncNodeState(r);await loadNodeCatalog();await refreshRequests();await refreshPalScripts();await refreshStats()}catch(e){$("#apiLog").textContent=e.message;setNode(false)}};
async function apiFetch(path,payload={},get=false){if(!state.api.url)throw new Error("No node API configured");const opt={method:get?"GET":"POST",headers:{"Content-Type":"application/json"}};if(state.api.token)opt.headers.Authorization="Bearer "+state.api.token;if(!get)opt.body=JSON.stringify(payload);const r=await fetch(state.api.url+"/"+path,opt);if(!r.ok)throw new Error("Node HTTP "+r.status);return r.headers.get("content-type")?.includes("json")?r.json():r.text()}
function setNode(on){state.nodeOnline=on;$("#nodeState").textContent=on?"NODE ONLINE":"NODE OFFLINE";$("#nodeState").classList.toggle("online",on);$("#nodeText").textContent=on?"ONLINE":"OFFLINE";refreshNodeButtons();if(state.mic){$("#ptt").disabled=!on;$("#micLatch").disabled=!on}$("#vtStore").disabled=!on||!state.lastVoiceBlob}
async function syncNodeState(r=null){const s=r||await apiFetch("status",{},true);if(Array.isArray(s.queue)){state.queue=s.queue;store.set("queue",state.queue);renderQueue()}if(s.now){$("#aArtist").textContent=s.now.artist||"Unknown";$("#aTitle").textContent=s.now.title||"Current track"}if(s.mode){state.mode=s.mode;$(".mode").forEach(x=>x.classList.toggle("active",x.dataset.mode===state.mode))}return s}
function refreshNodeButtons(){$$("[data-node],[data-node-range]").forEach(x=>x.disabled=!state.nodeOnline)}
async function nodeAction(path,payload={}){if(!state.nodeOnline){log(path+" blocked: node offline");return}try{await apiFetch(path,payload);log(path+" OK")}catch(e){log(path+" failed: "+e.message);setNode(false)}}
$("[data-node]").forEach(b=>b.onclick=()=>{let payload={};if(b.dataset.node==="crossfade/apply")payload=collectXf();if(b.dataset.node==="dsp/apply")payload={processors:collectDsp()};nodeAction(b.dataset.node,payload)});
async function loadDeck(deck){const item=state.queue[state.selectedQueue];if(!item){log("Select a queue item first");return}if(!item.uri&&item.message_id==null){log("Track is not in the playable cloud catalog yet");return}try{await apiFetch("deck/"+deck+"/load",item);$("#"+deck+"Artist").textContent=item.artist||"Unknown";$("#"+deck+"Title").textContent=item.title||"Loaded";log("Loaded Deck "+deck.toUpperCase()+": "+(item.artist||"")+" - "+(item.title||""))}catch(e){log("Deck load failed: "+e.message)}}
$("#loadA").onclick=()=>loadDeck("a");$("#loadB").onclick=()=>loadDeck("b");
async function loadAux(deck){const item=state.queue[state.selectedQueue];if(!item){log("Select a queue item first");return}if(!item.uri&&item.message_id==null){log("Track is not in the playable cloud catalog yet");return}try{await apiFetch("aux/"+deck+"/load",item);$("#aux"+deck+"Artist").textContent=item.artist||"Unknown";$("#aux"+deck+"Title").textContent=item.title||"Loaded";log("Loaded Aux "+deck+": "+(item.artist||"")+" - "+(item.title||""))}catch(e){log("Aux load failed: "+e.message)}}
$("#aux1Load").onclick=()=>loadAux("1");$("#aux2Load").onclick=()=>loadAux("2");$("#aux3Load").onclick=()=>loadAux("3");
$$("[data-node-range]").forEach(x=>x.onchange=()=>nodeAction(x.dataset.nodeRange,{value:+x.value}));

$("#vaultSync").onclick=async()=>{if(!state.nodeOnline){log("Vault sync requires NODE ONLINE");return}$("#vaultSync").disabled=true;try{const r=await apiFetch("vault/sync",{limit:25000,category:"Telegram"});log("Telegram Vault synced: "+r.count+" tracks");await loadNodeCatalog()}catch(e){log("Vault sync failed: "+e.message)}finally{$("#vaultSync").disabled=false}};

function renderRequests(){
 $("#requestRows").innerHTML=state.requests.map(r=>{const t=r.track||{};return '<tr data-rid="'+esc(r.id)+'" class="'+(state.selectedRequest===r.id?"selected":"")+'"><td>'+esc(t.artist||"")+'</td><td>'+esc(t.title||"")+'</td><td>'+esc(r.requested_by||"")+'</td><td>'+esc(r.status||"")+'</td></tr>'}).join("");
 $("[data-rid]").forEach(row=>row.onclick=()=>{state.selectedRequest=row.dataset.rid;renderRequests()});
}
async function refreshRequests(){if(!state.nodeOnline)return;try{state.requests=await apiFetch("requests",{},true);renderRequests()}catch(e){log("Requests failed: "+e.message)}}
$("#requestRefresh").onclick=refreshRequests;
async function decideRequest(action){if(!state.selectedRequest)return;try{await apiFetch("requests/"+encodeURIComponent(state.selectedRequest)+"/"+action,{});await refreshRequests();await syncNodeState();log("Request "+action)}catch(e){log("Request action failed: "+e.message)}}
$("#requestApprove").onclick=()=>decideRequest("approve");$("#requestReject").onclick=()=>decideRequest("reject");

function drawStats(){const canvas=$("#stats"),ctx=canvas.getContext("2d");ctx.clearRect(0,0,canvas.width,canvas.height);ctx.strokeStyle="#45c3ff";ctx.lineWidth=2;ctx.beginPath();const rows=state.statsSamples;if(!rows.length){ctx.fillStyle="#8fa7b5";ctx.fillText("Waiting for relay statistics...",12,22);return}const max=Math.max(1,...rows.map(x=>x.listeners||0));rows.forEach((row,i)=>{const x=rows.length===1?0:i/(rows.length-1)*(canvas.width-12)+6;const y=canvas.height-8-((row.listeners||0)/max)*(canvas.height-20);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke()}
async function refreshStats(){if(!state.nodeOnline)return;try{const s=await apiFetch("stats",{},true);$("#listeners").textContent=s.listeners??"—";$("#peak").textContent=s.peak??"—";if(s.listeners!=null){state.statsSamples.push({t:Date.now(),listeners:s.listeners});state.statsSamples=state.statsSamples.slice(-120)}drawStats()}catch(e){$("#listeners").textContent="—";$("#peak").textContent="—"}}

$("#logClear").onclick=()=>$("#eventLog").textContent="";
function renderHistory(){$("#historyRows").innerHTML=state.history.slice(-100).reverse().map(x=>'<tr><td>'+esc(x.time)+'</td><td>'+esc(x.artist)+'</td><td>'+esc(x.title)+'</td></tr>').join("")}

drawStats();

restoreXf();restoreDsp();renderQueue();renderEncoders();renderClock();renderEvents();renderFx();renderHistory();refreshNodeButtons();loadLibrary();log("Louder Cloud Studio ready");
setInterval(async()=>{if(!state.nodeOnline)return;try{const s=await apiFetch("status",{},true);setNode(true);if(s.now){$("#aArtist").textContent=s.now.artist||"Unknown";$("#aTitle").textContent=s.now.title||"Current track"}if(Array.isArray(s.encoders)){state.encoders=s.encoders.map(e=>({name:e.name||e.id,codec:e.format||"MP3",bitrate:e.bitrate||320,status:e.status||"unknown"}));renderEncoders()}await refreshStats()}catch(e){setNode(false)}},5000);
setInterval(refreshRequests,15000);