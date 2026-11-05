import {TaskQueue} from './queue.mjs';
const started=performance.now(),queue=new TaskQueue();let py,pumping=false;
const yieldTask=()=>new Promise(resolve=>setTimeout(resolve,0));
const hash=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
const wasmBytes=()=>py?._module?.HEAP8?.buffer?.byteLength??null;
const memory=()=>({wasmCommittedBytes:wasmBytes(),scope:'WASM linear heap capacity, not total process memory',pythonJobs:py?.runPython('bridge.job_count()')??null});
async function boot(){
 const build=await (await fetch('./build.json',{cache:'no-store'})).json();
 const {loadPyodide}=await import('./runtime/pyodide.mjs');
 py=await loadPyodide({indexURL:new URL('./runtime/',location.href).href});
 for(const file of ['lab.py','benchmark_bridge.py']){
  const bytes=await (await fetch('./'+file,{cache:'no-store'})).arrayBuffer();
  if(await hash(bytes)!==build.files[file])throw Error('Source digest mismatch: '+file);
  py.FS.writeFile(file,new Uint8Array(bytes));
 }
 py.runPython('import benchmark_bridge as bridge, sys');
 postMessage({type:'ready',initialiseMs:performance.now()-started,buildId:build.buildId,
  python:py.runPython('sys.version'),memory:memory()});
}
function cancel(task,reason){if(!task)return;py.globals.set('job_id',String(task.id));py.runPython('bridge.discard(job_id)');
 postMessage({type:'cancelled',id:task.id,context:task.context,units:task.units,reason,at:performance.now(),memory:memory()});}
async function pump(){
 if(pumping||!py)return;pumping=true;
 try{
  let task;
  while((task=queue.next())){
   const begin=performance.now();
   try{
    py.globals.set('job_id',String(task.id));py.globals.set('request_json',JSON.stringify(task.request));
    let response;
    if(task.priority==='background'){
     if(!task.begun){task.total=py.runPython('bridge.begin(job_id, request_json)');task.begun=true;}
     response=JSON.parse(py.runPython('bridge.step(job_id)'));task.units=response.units;
    }else{response=JSON.parse(py.runPython('bridge.calculate(request_json)'));response.complete=true;task.units=1;}
    const elapsed=performance.now()-begin;
    postMessage({type:'unit',id:task.id,context:task.context,units:task.units,total:task.total??1,ms:elapsed,memory:memory()});
    if(response.complete){queue.complete(task.id);postMessage({type:'result',id:task.id,context:task.context,response,memory:memory()});}
    else queue.yield(task);
   }catch(error){queue.complete(task.id);py.globals.set('job_id',String(task.id));py.runPython('bridge.discard(job_id)');postMessage({type:'failure',id:task.id,error:String(error)});}
   await yieldTask();
  }
 }finally{pumping=false;}
}
onmessage=({data})=>{
 if(data.type==='crash'){throw Error('Deliberate synthetic recovery probe');}
 if(data.type==='cancel'){cancel(queue.cancel(data.id),'abandoned');return;}
 if(data.type==='submit'){
  const status=queue.submit(data.task);status.cancelled.forEach(t=>cancel(t,'superseded'));
  if(!status.accepted)postMessage({type:'cancelled',id:data.task.id,reason:'stale_context',units:0});
  pump();
 }
};
boot().catch(error=>postMessage({type:'boot_failure',error:String(error)}));
