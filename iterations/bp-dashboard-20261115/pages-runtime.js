/* Static tester transport only. Financial calculations run unchanged in Python. */
(()=>{
 const base=new URL('.',document.currentScript.src),nativeFetch=window.fetch.bind(window);
 let worker,serial=0;const pending=new Map();
 function engine(){if(worker)return worker;worker=new Worker(new URL('model-worker.mjs',base),{type:'module'});worker.onmessage=({data})=>{const job=pending.get(data.id);if(!job)return;pending.delete(data.id);data.error?job.reject(Error(data.error)):job.resolve(new Response(JSON.stringify(data.result),{headers:{'Content-Type':'application/json'}}));};worker.onerror=e=>{for(const job of pending.values())job.reject(Error(e.message||'The illustration could not start.'));pending.clear();worker.terminate();worker=null;};return worker;}
 window.fetch=(input,init={})=>{
  const url=new URL(input instanceof Request?input.url:String(input),location.href),operation=url.origin===base.origin&&url.pathname.startsWith(base.pathname)?url.pathname.slice(base.pathname.length):null;
  if(operation==='identity')return nativeFetch(new URL('identity.json',base),init);
  if(!['calculate','intro-data','live-intro-data'].includes(operation))return nativeFetch(input,init);
  const signal=init.signal??(input instanceof Request?input.signal:null);
  if(signal?.aborted)return Promise.reject(new DOMException('Aborted','AbortError'));
  return Promise.resolve(init.body??(input instanceof Request?input.text():'{}')).then(body=>new Promise((resolve,reject)=>{
   const id=++serial;const abort=()=>{pending.delete(id);reject(new DOMException('Aborted','AbortError'));};
   pending.set(id,{resolve:r=>{signal?.removeEventListener('abort',abort);resolve(r);},reject:e=>{signal?.removeEventListener('abort',abort);reject(e);}});signal?.addEventListener('abort',abort,{once:true});
   try{engine().postMessage({id,operation,request:JSON.parse(body)});}catch(e){pending.delete(id);signal?.removeEventListener('abort',abort);reject(e);}
  }));
 };
})();
