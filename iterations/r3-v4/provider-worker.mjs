import {loadPyodide} from './runtime/pyodide.mjs';
const ready=(async()=>{
 const py=await loadPyodide({indexURL:new URL('./runtime/',import.meta.url).href});
 for(const name of ['facts.json','illustration.py']){
  const response=await fetch(new URL(name,import.meta.url));if(!response.ok)throw Error(`Cannot load ${name}`);
  py.FS.writeFile(`/home/pyodide/${name}`,await response.text());
 }
 py.runPython('import json\nfrom illustration import respond');return py;
})();
onmessage=async({data:{id,request}})=>{
 try{const py=await ready;py.globals.set('request_json',JSON.stringify(request));
  const result=JSON.parse(py.runPython('json.dumps(respond(json.loads(request_json)))'));postMessage({id,result});
 }catch(error){postMessage({id,error:String(error)});}
};
