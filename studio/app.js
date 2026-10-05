const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
const store={get:(k,d)=>{try{const v=localStorage.getItem("lcs:"+k);return v?JSON.parse(v):d}catch{return d}},set:(k,v)=>localStorage.setItem("lcs:"+k,JSON.stringify(v))};
const state={mode:store.get("mode","auto"),queue:store.get("queue",[]),clock:store.get("clock",[]),events:store.get("events",[]),encoders:store.get("encoders",[{name:"YesStreaming Primary",codec:"MP3",bitrate:320,status:"Unknown"}]),history:store.get("history",[]),xf:store.get("xf",{}),dsp:store.get("dsp",{}),api:store.get("api",{url:"",token:""}),library:[],category:"All",selectedQueue:-1,mic:null,micCtx:null,micProcessor:null,micSending:false,voiceWs:null,recorder:null,chunks:[],lastVoiceBlob:null,palStop:false,nodeOnline:false};
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

async function saveQueue(){store.set("queue",state.queue);renderQueue();if(state.nodeOnline&&state.queue.every(x=>x.uri)){try{await apiFetch("queue/set",state.queue)}catch(e){log("Queue sync failed: "+e.message)}}}
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
function wsUrl(){if(!state.api.url)return"";const base=state.api.url.replace(/^http:/,"ws:").replace(/^https:/,"wss:");return base+"/ws/voice"+(state.api.token?"?token="+encodeURIComponent(state.api.token):"")}
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

function collectXf(){return {enable:$("#xfEnable").checked,ms:+$("#xfMs").value,fadeIn:+$("#xfIn").value,fadeOut:+$("#xfOut").value,overlapDb:+$("#xfOverlap").value,gapKiller:$("#gapKiller").checked,silenceDb:+$("#silenceDb").value,silenceMs:+$("#silenceMs").value,respectCue:$("#respectCue").checked,jingles:$("#xfJingles").checked}}
$("#xfSave").onclick=()=>{state.xf=collectXf();store.set("xf",state.xf);log("Crossfade rules saved")};
function restoreXf(){const x=state.xf;if(!Object.keys(x).length)return;$("#xfEnable").checked=x.enable;$("#xfMs").value=x.ms;$("#xfIn").value=x.fadeIn;$("#xfOut").value=x.fadeOut;$("#xfOverlap").value=x.overlapDb;$("#gapKiller").checked=x.gapKiller;$("#silenceDb").value=x.silenceDb;$("#silenceMs").value=x.silenceMs;$("#respectCue").checked=x.respectCue;$("#xfJingles").checked=x.jingles}

function collectDsp(){return $$(".processor").map(p=>({name:p.querySelector("h3").textContent,on:p.querySelector('input[type="checkbox"]').checked,values:[...p.querySelectorAll('input[type="range"]')].map(x=>+x.value)}))}
$("#pipelineSave").onclick=()=>{state.dsp=collectDsp();store.set("dsp",state.dsp);log("DSP preset saved")};
function restoreDsp(){if(!Array.isArray(state.dsp))return;$$(".processor").forEach((p,i)=>{const d=state.dsp[i];if(!d)return;p.querySelector('input[type="checkbox"]').checked=d.on;[...p.querySelectorAll('input[type="range"]')].forEach((x,j)=>x.value=d.values[j]??x.value)})}

function palLines(){return $("#palEditor").value.split(/\r?\n/).map(x=>x.trim()).filter(x=>x&&!x.startsWith("#"))}
function validatePal(){const bad=[];palLines().forEach((l,i)=>{if(!/^(LOG\s+".*"|MODE\s+(AUTO|QUEUE|MANUAL|RECOVERY)|QUEUE\s+CATEGORY\s+".*"\s+\d+|WAIT\s+\d+)$/i.test(l))bad.push("Line "+(i+1)+": "+l)});$("#palLog").textContent=bad.length?bad.join("\n"):"Valid.";return !bad.length}
async function runPal(){if(!validatePal())return;state.palStop=false;$("#palLog").textContent="Running...\n";for(const line of palLines()){if(state.palStop)break;let m;if((m=line.match(/^LOG\s+"(.*)"$/i)))$("#palLog").textContent+=m[1]+"\n";else if((m=line.match(/^MODE\s+(AUTO|QUEUE|MANUAL|RECOVERY)$/i))){state.mode=m[1].toLowerCase();store.set("mode",state.mode);$("#palLog").textContent+="Mode "+m[1]+"\n"}else if((m=line.match(/^QUEUE\s+CATEGORY\s+"(.*)"\s+(\d+)$/i))){const pool=state.library.filter(x=>x.category.toLowerCase()===m[1].toLowerCase());for(let i=0;i<+m[2]&&pool.length;i++)state.queue.push(pool[Math.floor(Math.random()*pool.length)]);saveQueue();$("#palLog").textContent+="Queued "+m[2]+" from "+m[1]+"\n"}else if((m=line.match(/^WAIT\s+(\d+)$/i)))await new Promise(r=>setTimeout(r,+m[1]*1000))}$("#palLog").textContent+=state.palStop?"Stopped.":"Done."}
$("#palValidate").onclick=validatePal;$("#palRun").onclick=async()=>{if(!validatePal())return;if(state.nodeOnline){try{const r=await apiFetch("pal/run",{script:$("#palEditor").value});$("#palLog").textContent=(r.log||[]).join("\n")||"Done.";log("PAL executed on node")}catch(e){$("#palLog").textContent=e.message}}else runPal()};$("#palStop").onclick=()=>state.palStop=true;

$("#apiUrl").value=state.api.url||"";$("#apiToken").value=state.api.token||"";
$("#apiSave").onclick=()=>{state.api={url:$("#apiUrl").value.trim().replace(/\/$/,""),token:$("#apiToken").value};store.set("api",state.api);log("Node API settings saved");refreshNodeButtons()};
$("#apiTest").onclick=async()=>{state.api={url:$("#apiUrl").value.trim().replace(/\/$/,""),token:$("#apiToken").value};try{const r=await apiFetch("status",{},true);state.nodeOnline=!!r;$("#apiLog").textContent=JSON.stringify(r,null,2);setNode(true);await syncNodeState(r)}catch(e){$("#apiLog").textContent=e.message;setNode(false)}};
async function apiFetch(path,payload={},get=false){if(!state.api.url)throw new Error("No node API configured");const opt={method:get?"GET":"POST",headers:{"Content-Type":"application/json"}};if(state.api.token)opt.headers.Authorization="Bearer "+state.api.token;if(!get)opt.body=JSON.stringify(payload);const r=await fetch(state.api.url+"/"+path,opt);if(!r.ok)throw new Error("Node HTTP "+r.status);return r.headers.get("content-type")?.includes("json")?r.json():r.text()}
function setNode(on){state.nodeOnline=on;$("#nodeState").textContent=on?"NODE ONLINE":"NODE OFFLINE";$("#nodeState").classList.toggle("online",on);$("#nodeText").textContent=on?"ONLINE":"OFFLINE";refreshNodeButtons();if(state.mic){$("#ptt").disabled=!on;$("#micLatch").disabled=!on}$("#vtStore").disabled=!on||!state.lastVoiceBlob}
async function syncNodeState(r=null){const s=r||await apiFetch("status",{},true);if(Array.isArray(s.queue)&&s.queue.length){state.queue=s.queue;store.set("queue",state.queue);renderQueue()}if(s.now){$("#aArtist").textContent=s.now.artist||"Unknown";$("#aTitle").textContent=s.now.title||"Current track"}if(s.mode){state.mode=s.mode;$(".mode").forEach(x=>x.classList.toggle("active",x.dataset.mode===state.mode))}return s}
function refreshNodeButtons(){$$("[data-node],[data-node-range]").forEach(x=>x.disabled=!state.nodeOnline)}
async function nodeAction(path,payload={}){if(!state.nodeOnline){log(path+" blocked: node offline");return}try{await apiFetch(path,payload);log(path+" OK")}catch(e){log(path+" failed: "+e.message);setNode(false)}}
$("[data-node]").forEach(b=>b.onclick=()=>{let payload={};if(b.dataset.node==="crossfade/apply")payload=collectXf();if(b.dataset.node==="dsp/apply")payload={processors:collectDsp()};nodeAction(b.dataset.node,payload)});
async function loadDeck(deck){const item=state.queue[state.selectedQueue];if(!item){log("Select a queue item first");return}if(!item.uri){log("Track has no cloud play URI yet");return}try{await apiFetch("deck/"+deck+"/load",{uri:item.uri});$("#"+deck+"Artist").textContent=item.artist||"Unknown";$("#"+deck+"Title").textContent=item.title||"Loaded";log("Loaded Deck "+deck.toUpperCase()+": "+(item.artist||"")+" - "+(item.title||""))}catch(e){log("Deck load failed: "+e.message)}}
$("#loadA").onclick=()=>loadDeck("a");$("#loadB").onclick=()=>loadDeck("b");
$$("[data-node-range]").forEach(x=>x.onchange=()=>nodeAction(x.dataset.nodeRange,{value:+x.value}));

$("#logClear").onclick=()=>$("#eventLog").textContent="";
function renderHistory(){$("#historyRows").innerHTML=state.history.slice(-100).reverse().map(x=>'<tr><td>'+esc(x.time)+'</td><td>'+esc(x.artist)+'</td><td>'+esc(x.title)+'</td></tr>').join("")}

function drawStats(){const c=$("#stats"),ctx=c.getContext("2d");ctx.clearRect(0,0,c.width,c.height);ctx.strokeStyle="#45c3ff";ctx.beginPath();for(let x=0;x<c.width;x+=25){const y=95+Math.sin(x/60)*30+(Math.random()*8);x?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.stroke()}drawStats();

restoreXf();restoreDsp();renderQueue();renderEncoders();renderClock();renderEvents();renderFx();renderHistory();refreshNodeButtons();loadLibrary();log("Louder Cloud Studio ready");
setInterval(async()=>{if(!state.nodeOnline)return;try{const s=await apiFetch("status",{},true);setNode(true);if(s.now){$("#aArtist").textContent=s.now.artist||"Unknown";$("#aTitle").textContent=s.now.title||"Current track"}if(Array.isArray(s.encoders)){$("#encoderRows").querySelectorAll("tr").forEach(()=>{});state.encoders=s.encoders.map(e=>({name:e.name||e.id,codec:e.format||"MP3",bitrate:e.bitrate||320,status:e.status||"unknown"}));renderEncoders()}}catch(e){setNode(false)}},5000);