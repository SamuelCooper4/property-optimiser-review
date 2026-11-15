"""Transport adapter to the preserved live introduction's unchanged provider."""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import sys

SOURCE = Path(__file__).parent / 'evidence/target-layout/reference/live-intro-source/public'

def _load(name: str):
    spec=spec_from_file_location(name,SOURCE/(name+'.py'))
    module=module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

_load('scenario')
_original=_load('illustration')

def respond(request: dict) -> dict:
    """Delegate without changing the published example's values or storyboard."""
    return _original.respond(request)
