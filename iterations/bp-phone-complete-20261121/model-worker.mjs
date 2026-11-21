/** Run the phone's isolated Python source in the established vendored WASM runtime. */
import {loadPyodide} from './runtime/pyodide.mjs';

const modules = ['model.py', 'quotes.py', 'phone_provider.py', 'phone_ownership.py', 'phone_futures.py',
  'target_reporting.py', 'phone-fixture.json'];
const ready = (async () => {
  const py = await loadPyodide({indexURL:new URL('./runtime/', import.meta.url).href});
  await Promise.all(modules.map(async name => {
    const response = await fetch(new URL('python/'+name, import.meta.url));
    if (!response.ok) throw Error('The calculation file could not be loaded: '+name);
    py.FS.writeFile('/home/pyodide/'+name, new Uint8Array(await response.arrayBuffer()));
  }));
  py.runPython('import json, model, phone_provider');
  return py;
})();

self.onmessage = async ({data:{id, operation, request}}) => {
  try {
    const py = await ready;
    py.globals.set('payload', JSON.stringify(request));
    py.globals.set('route', operation);
    const json = py.runPython("json.dumps((phone_provider.respond if route == 'phone-data' else model.respond)(json.loads(payload)))");
    self.postMessage({id,result:JSON.parse(json)});
  } catch (error) {
    self.postMessage({id,error:String(error)});
  }
};
