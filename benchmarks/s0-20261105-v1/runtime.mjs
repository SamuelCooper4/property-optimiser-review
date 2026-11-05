// One worker. A cancelled promise is different from a cancelled computation receipt.
let epoch=0;
export class Cancelled extends Error {}
export class Runtime {
 constructor(trace){this.epoch=++epoch;this.serial=0;this.jobs=new Map();this.trace=trace;this.worker=new Worker(new URL('./worker.mjs',import.meta.url),{type:'module'});
  this.ready=new Promise((resolve,reject)=>{this.resolveReady=resolve;this.rejectReady=reject;});
  this.worker.onmessage=({data})=>this.receive(data);
  this.worker.onerror=event=>{event.preventDefault();this.trace({type:'worker_fault',error:event.message,at:performance.now(),epoch:this.epoch});
   for(const job of this.jobs.values())job.reject(Error('worker fault'));this.jobs.clear();this.rejectReady(Error(event.message));this.crashResolve?.();};
 }
 receive(data){this.trace({...data,observedAt:performance.now(),epoch:this.epoch});
  if(data.type==='ready'){this.readyInfo=data;this.resolveReady(data);return;}
  if(data.type==='boot_failure'){this.rejectReady(Error(data.error));return;}
  const job=this.jobs.get(data.id);if(!job)return;
  if(data.type==='result'){this.jobs.delete(data.id);job.resolve({...data,elapsedMs:performance.now()-job.started});}
  if(data.type==='cancelled'){this.jobs.delete(data.id);job.reject(new Cancelled(data.reason));}
  if(data.type==='failure'){this.jobs.delete(data.id);job.reject(Error(data.error));}
 }
 submit(request,context,priority='interactive'){
  const id=this.epoch+':'+(++this.serial),started=performance.now();
  const promise=new Promise((resolve,reject)=>{this.jobs.set(id,{resolve,reject,started});
   this.worker.postMessage({type:'submit',task:{id,context,priority,request}});});
  return {id,promise};
 }
 cancel(id){this.trace({type:'cancel_requested',id,at:performance.now()});this.worker.postMessage({type:'cancel',id});}
 crash(){return new Promise(resolve=>{this.crashResolve=resolve;this.worker.postMessage({type:'crash'});});}
 close(){this.worker.terminate();for(const job of this.jobs.values())job.reject(new Cancelled('worker terminated'));this.jobs.clear();}
}
