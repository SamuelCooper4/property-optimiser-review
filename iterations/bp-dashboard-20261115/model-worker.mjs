import {loadPyodide} from './runtime/pyodide.mjs';
const ready=(async()=>{
 const py=await loadPyodide({indexURL:new URL('./runtime/',import.meta.url).href});
 const sources=await(await fetch(new URL('python-sources.json',import.meta.url))).json();
 await Promise.all(sources.map(async name=>{const r=await fetch(new URL('python/'+name,import.meta.url));if(!r.ok)throw Error('Illustrative module unavailable: '+name);const path='/home/pyodide/'+name;py.FS.mkdirTree(path.slice(0,path.lastIndexOf('/property-optimiser-review/iterations/bp-dashboard-20261115/')));py.FS.writeFile(path,await r.text());}));
 py.runPython('import json, model, intro_provider, live_reference');return py;
})();
self.onmessage=async({data:{id,operation,request}})=>{
 try{const py=await ready;py.globals.set('request_json',JSON.stringify(request));py.globals.set('operation_name',operation);
 const result=JSON.parse(py.runPython("json.dumps((intro_provider.respond if operation_name == 'intro-data' else live_reference.respond if operation_name == 'live-intro-data' else model.respond)(json.loads(request_json)))"));self.postMessage({id,result});
 }catch(error){self.postMessage({id,error:String(error)});}
};
