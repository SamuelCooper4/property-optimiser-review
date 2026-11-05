import {Runtime,Cancelled} from './runtime.mjs';
const $=id=>document.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
const paint=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
const base={price:'450000',savings:'150000',reserve:'10000',deposit:'123456.78',monthly:'2000',
 term_months:420,horizon_months:360,view_month:360,investment_return:'.05',deals:[[420,'.04']]};
let current={...base},context=1,revision=0,accepted=0,runtime,manual=null,runToken=0,busy=false,lastSnapshot=null,displayed=null;
const evidence={schema:'s0-device-evidence-v2',synthetic:true,startedUTC:new Date().toISOString(),
 observations:'DOM + double-rAF, not optical presentation proof',events:[],runs:[],errors:[],visibility:[],firstStartup:null,
 memory:{totalNative:'unsupported in this page',crossOriginIsolated,wasm:'sampled committed linear heap capacity',js:'performance.memory when available; snapshot, not native peak'},
 environment:{userAgent:navigator.userAgent,viewport:[innerWidth,innerHeight],devicePixelRatio,
 hardwareConcurrency:navigator.hardwareConcurrency??null,deviceMemoryGiB:navigator.deviceMemory??null}};
const trace=event=>{evidence.events.push(event);};
const status=text=>{$('status').textContent=text;};
const stampMetadata=()=>{evidence.device={physicalPixel9ProXL:$('physical').checked,androidOverride:$('android').value,
 chromeOverride:$('chrome').value,thermal:$('thermal').value,power:$('power').value,visibleObservation:$('visible').value,observation:$('observation').value};};
const metrics=()=>({inputs:[],updates:[],releases:[],started:performance.now(),context,mismatches:0});
let activeMetrics=metrics();
const geometry=value=>value===null?0:Math.max(0,Math.min(600,Number(value)/450000*600)); // drawing only
function render(response,jobRevision,jobContext){
 const r=response.result,row=response.display,month=r.view?.month??r.horizon_months;
 if(!r.target)throw Error('No selected financial row: '+r.status);
 const state=r.view; // select and scrub both request the displayed month explicitly
 const expected={deposit:r.deposit,position:state.position,debt:state.debt};
 for(const name of ['deposit','position','debt']){
  $(name==='deposit'?'deposit-value':name).textContent=row[name];
  $(name+'-graphic').textContent=name+': '+row[name];
  $(name+'-bar').setAttribute('width',String(geometry(expected[name])));
 }
 for(const el of document.querySelectorAll('[data-financial]')){
  el.dataset.snapshot=response.snapshot;el.dataset.context=String(jobContext);el.dataset.deposit=r.deposit;
 }
 $('view-month').textContent=String(month);$('pending').textContent='Complete figures for deposit £'+row.deposit+', month '+month+
  (r.first_gap_month!==null?'. Known funding gap at month '+r.first_gap_month+'; excluded from ranking.':'');
 $('exact').textContent=JSON.stringify({snapshot:response.snapshot,deposit:r.deposit,month,position:state.position,debt:state.debt,
  firstGap:r.first_gap_month,rankEligible:r.rank_eligible},null,2);lastSnapshot=response;
 return ()=>['deposit','position','debt'].every(name=>
  $(name==='deposit'?'deposit-value':name).textContent===row[name]&&$(name+'-graphic').textContent===name+': '+row[name]
  &&$(name+'-bar').getAttribute('width')===String(geometry(expected[name])))
  &&[...document.querySelectorAll('[data-financial]')].every(el=>el.dataset.snapshot===response.snapshot&&el.dataset.context===String(jobContext)&&el.dataset.deposit===r.deposit)
  &&$('view-month').textContent===String(month);
}
async function input(kind,value,source='automated',trusted=false,pointerType=null){
 if(kind==='deposit'){current.deposit=value;$('deposit').value=value;}else{current.view_month=Number(value);$('month').value=value;}
 const at=performance.now(),rev=++revision,ctx=context,record=activeMetrics;
 const sample={revision:rev,context:ctx,kind,value,at,source,trusted,pointerType};record.inputs.push(sample);
 requestAnimationFrame(()=>sample.handleMs=performance.now()-at);
 $('pending').textContent='Requested deposit £'+current.deposit+', month '+current.view_month+'; previous complete figures remain labelled.';
 const instance=runtime,job=instance.submit({operation:'scrub',case:{...current}},ctx);
 sample.jobId=job.id;
 try{
  const message=await job.promise;
  if(rev!==revision||ctx!==context||instance!==runtime){trace({type:'obsolete_result_rejected',id:job.id,at:performance.now()});return;}
  const check=render(message.response,rev,ctx);accepted=rev;
  displayed={check,response:message.response,revision:rev,context:ctx,at,record,jobId:job.id,observed:false};
  await paint();
  // Observe the complete state actually present at this frame, not an older response
  // which was legitimately superseded while two frames elapsed. Count each snapshot once.
  const shown=displayed;if(shown.observed)return;shown.observed=true;
  const matching=shown.check();if(!matching)shown.record.mismatches++;
  shown.record.updates.push({at:performance.now(),revision:shown.revision,context:shown.context,matching,
   latest:shown.revision===revision&&shown.context===context,inputAgeMs:performance.now()-shown.at,
   snapshot:shown.response.snapshot,jobId:shown.jobId,deposit:shown.response.result.deposit,
   position:shown.response.result.view.position,debt:shown.response.result.view.debt});
 }catch(error){if(!(error instanceof Cancelled)){evidence.errors.push(String(error));status('Calculation error: '+error);}}
}
async function settle(){const start=performance.now();while(accepted!==revision){if(performance.now()-start>30000)throw Error('Selection settle timeout');await sleep(5);}await paint();return performance.now()-start;}
function summarise(record,end,settleMs){
 const coherent=record.updates.filter(x=>x.matching&&x.at<=end),fresh=coherent.filter(x=>x.latest);
 const gaps=list=>{const times=[record.started,...list.map(x=>x.at),end];return Math.max(...times.slice(1).map((t,i)=>t-times[i]));};
 return {...record,end,settleMs,seconds:(end-record.started)/1000,freshHz:fresh.length/((end-record.started)/1000),freshCount:fresh.length,
  longestFreshGapMs:gaps(fresh),coherentHz:coherent.length/((end-record.started)/1000),longestCoherentGapMs:gaps(coherent),
  memoryJS:performance.memory?{used:performance.memory.usedJSHeapSize,total:performance.memory.totalJSHeapSize}:null};
}
const depositString=i=>{const pennies=12300000+(i*37)%16000;return Math.floor(pennies/100)+'.'+String(pennies%100).padStart(2,'0');};
async function drag(milliseconds=30000,kind='deposit'){
 activeMetrics=metrics();const record=activeMetrics,start=performance.now(),token=runToken;let i=0;
 while(performance.now()-start<milliseconds&&token===runToken){input(kind,kind==='deposit'?depositString(i++):String((i++*7)%421));await sleep(16);}
 const end=performance.now(),settleMs=await settle();return summarise(record,end,settleMs);
}
const heavyRequest=()=>({operation:'search',case:{...base,monthly:'100000',horizon_months:720,view_month:720},
 choices:Array.from({length:256},(_,i)=>[String(112500+i),720]),deals:Array.from({length:24},()=>[30,'.04'])});
async function unitSeen(id){const start=performance.now();while(!evidence.events.some(e=>e.type==='unit'&&e.id===id)){if(performance.now()-start>30000)throw Error('No heavy progress');await sleep(5);}}
function updateSummary(){stampMetadata();$('summary').textContent=JSON.stringify({build:evidence.build?.buildId,device:evidence.device,
 completed:evidence.runs.map(r=>({name:r.name,freshHz:r.freshHz,longestGapMs:r.longestFreshGapMs,settleMs:r.settleMs,mismatches:r.mismatches})),
 errors:evidence.errors,visibilityChanges:evidence.visibility.length,manualRequired:!evidence.runs.some(r=>r.name==='real-touch-deposit'),
 memoryLimitations:evidence.memory},null,2);}
async function automated({cold=30,warm=100,dragMs=30000}={}){
 if(busy)throw Error('Already running');busy=true;const token=++runToken;stampMetadata();$('run').disabled=true;$('stop').disabled=false;
 const check=()=>{if(token!==runToken)throw new Cancelled('test stopped');};let wake;
 try{
  try{wake=await navigator.wakeLock?.request('screen');}catch{trace({type:'wake_lock_unavailable'});}
  const coldSamples=[];runtime.close();
  for(let i=0;i<cold;i++){check();status(`Fresh Python worker ${i+1}/${cold} (network cache may be warm)`);const begin=performance.now();runtime=new Runtime(trace);const info=await runtime.ready;
   const result=await runtime.submit({operation:'select',case:base},++context).promise;
   coldSamples.push({ms:performance.now()-begin,initialiseMs:info.initialiseMs,memory:info.memory,python:info.python,snapshot:result.response.snapshot});
   if(i<cold-1){runtime.close();await sleep(30);}}
  evidence.runs.push({name:'fresh-worker-start',samples:coldSamples,networkCache:'not cleared; first page navigation recorded separately'});
  current={...base};++context;
  for(const operation of ['select','scrub','search','scenario']){
   const samples=[];for(let i=0;i<warm;i++){check();status(`Warm ${operation}: ${i+1}/${warm}`);
    const request={operation:operation==='scenario'?'search':operation,case:{...base,deposit:depositString(i),view_month:operation==='scrub'?(i*7)%421:360},
     ...(operation==='scenario'?{deals:[[24,'.04'],[60,'.05'],[636,'.04']]}:{})};
    const message=await runtime.submit(request,context,['search','scenario'].includes(operation)?'background':'interactive').promise;
    samples.push({ms:message.elapsedMs,snapshot:message.response.snapshot,bytes:new TextEncoder().encode(JSON.stringify(message.response)).length,memory:message.memory});
   }evidence.runs.push({name:'warm-'+operation,samples});
  }
  check();status('30-second uncached automated deposit dragging');evidence.runs.push({name:'automated-drag',...await drag(dragMs)});
  check();status('Dragging while a larger admitted synthetic search runs');let repeat=true,activeHeavy;
  const background=(async()=>{while(repeat){activeHeavy=runtime.submit(heavyRequest(),context,'background');try{await activeHeavy.promise;}catch(error){if(!(error instanceof Cancelled))throw error;}}})();
  const underLoad=await drag(dragMs);repeat=false;if(activeHeavy)runtime.cancel(activeHeavy.id);await background;
  evidence.runs.push({name:'drag-during-heavy-work',...underLoad});
  check();status('Repeated assumption changes and stale-result rejection');const changes=[];
  for(let i=0;i<12;i++){++context;current={...base,investment_return:i%2?'.04':'.05'};
   const heavy=runtime.submit(heavyRequest(),context,'background');heavy.promise.catch(()=>{});input('deposit',depositString(i));changes.push({context,heavy:heavy.id});await sleep(40);}
  ++context;current={...base};await input('deposit',base.deposit);await settle();evidence.runs.push({name:'repeated-context-changes',changes,finalContext:context,finalSnapshot:lastSnapshot.snapshot});
  check();status('Abandoning a heavy analysis and verifying actual work stops');const abandoned=runtime.submit(heavyRequest(),context,'background');abandoned.promise.catch(()=>{});
  await unitSeen(abandoned.id);const cancelAt=performance.now();runtime.cancel(abandoned.id);await abandoned.promise.catch(()=>{});await sleep(100);
  const ack=evidence.events.find(e=>e.type==='cancelled'&&e.id===abandoned.id);
  const after=evidence.events.filter(e=>e.type==='unit'&&e.id===abandoned.id&&e.observedAt>ack.observedAt);
  evidence.runs.push({name:'abandon-analysis',jobId:abandoned.id,cancelAckMs:ack.observedAt-cancelAt,unitsAtStop:ack.units,unitsAfterAck:after.length,memory:ack.memory});
  check();status('Deliberate worker failure, restart and exact context recovery');const before=lastSnapshot,begin=performance.now();await runtime.crash();runtime.close();runtime=new Runtime(trace);await runtime.ready;++context;
  await input('deposit',current.deposit);await settle();evidence.runs.push({name:'worker-recovery',ms:performance.now()-begin,sameFinancialResult:JSON.stringify(before.result)===JSON.stringify(lastSnapshot.result),restoredSnapshot:lastSnapshot.snapshot});
  status('Automated checks finished. Please do the two real-touch checks below, then export.');
 }catch(error){evidence.runs.push({name:'automatic-run-stopped',reason:String(error)});status('Checks stopped: '+error);if(!(error instanceof Cancelled))evidence.errors.push(String(error));}
 finally{busy=false;$('run').disabled=false;$('stop').disabled=true;$('progress').value=1;await wake?.release();updateSummary();}
 return evidence;
}
let pointer=null;
for(const kind of ['deposit','month']){
 const control=$(kind);control.addEventListener('pointerdown',event=>{pointer=event.pointerType;});
 control.addEventListener('input',event=>input(kind==='deposit'?'deposit':'scrub',event.target.value,'real-input',event.isTrusted,pointer));
 control.addEventListener('pointerup',async event=>{const at=performance.now(),record=activeMetrics;const ms=await settle();record.releases.push({at,settleMs:ms,pointerType:event.pointerType,trusted:event.isTrusted});pointer=null;});
}
async function startManual(kind){if(busy)return;manual=kind;activeMetrics=metrics();$('touch-end').disabled=false;status('Move the '+kind+' slider continuously for about 20 seconds, then release and press Finish.');}
$('touch-deposit').onclick=()=>startManual('deposit');$('touch-scrub').onclick=()=>startManual('scrub');
$('touch-end').onclick=async()=>{const end=performance.now(),ms=await settle();evidence.runs.push({name:'real-touch-'+manual,...summarise(activeMetrics,end,ms)});manual=null;$('touch-end').disabled=true;status('Touch check saved. Export after both checks.');updateSummary();};
$('renewal').onclick=async()=>{if(busy)return;++context;current={...current,deals:[[24,'.04'],[60,'.05'],[336,'.04']]};const start=performance.now();await input('deposit',current.deposit,'renewal-button',true);await settle();evidence.runs.push({name:'real-renewal',ms:performance.now()-start,snapshot:lastSnapshot.snapshot});updateSummary();};
$('run').onclick=()=>automated();$('stop').onclick=()=>{++runToken;for(const id of runtime.jobs.keys())runtime.cancel(id);input('deposit',current.deposit,'stop-recovery');};
function exportText(){stampMetadata();evidence.exportedUTC=new Date().toISOString();return JSON.stringify(evidence,null,2);}
$('export').onclick=()=>{const url=URL.createObjectURL(new Blob([exportText()],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='s0-pixel-synthetic-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(exportText());status('Synthetic results copied. Paste them into the S0 chat.');}catch{status('Clipboard unavailable; use Download results.');}};
document.addEventListener('visibilitychange',()=>evidence.visibility.push({state:document.visibilityState,at:performance.now()}));
async function initialise(){const start=performance.now();evidence.build=await (await fetch('./build.json',{cache:'no-store'})).json();
 $('identity').textContent='Build '+evidence.build.buildId+' · source '+evidence.build.sourceCommit;
 try{evidence.environment.userAgentData=await navigator.userAgentData?.getHighEntropyValues(['platformVersion','fullVersionList','model']);}catch{evidence.environment.userAgentData=null;}
 runtime=new Runtime(trace);const info=await runtime.ready;await input('deposit',current.deposit);await settle();
 evidence.firstStartup={ms:performance.now()-start,worker:info,navigation:performance.getEntriesByType('navigation').map(x=>x.toJSON()),
  resourceScope:'first page view; browser/network cache state not independently proven'};
 for(const id of ['run','renewal','touch-deposit','touch-scrub','export','copy'])$(id).disabled=false;status('Ready. Confirm your test conditions, then run the checks.');}
window.s0={evidence,automated,drag,input,settle,get runtime(){return runtime;},get snapshot(){return lastSnapshot;},ready:initialise()};
window.s0.ready.catch(error=>{evidence.errors.push(String(error));status('Unable to start: '+error);$('export').disabled=false;});
