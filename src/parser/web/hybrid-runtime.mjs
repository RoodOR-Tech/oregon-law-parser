// Executes the upstream Python function. There is no JavaScript port of its SQL.
export async function initializeHybrid({rootURL,readBytes,runtimePath}={}) {
  rootURL ||= new URL('./',import.meta.url);
  const runtimeURL=new URL('hybrid/runtime/',rootURL);
  readBytes ||= async url=>{const response=await fetch(url);if(!response.ok)throw Error('Synonym data unavailable');return new Uint8Array(await response.arrayBuffer());};
  const {loadPyodide}=await import(new URL('pyodide.mjs',runtimeURL).href);
  const py=await loadPyodide({indexURL:runtimePath||runtimeURL.href});
  await py.loadPackage('sqlalchemy');
  const [code,database]=await Promise.all([readBytes(new URL('hybrid/build_synonym_db.py',rootURL)),readBytes(new URL('hybrid/synonyms.sqlite3',rootURL))]);
  py.FS.writeFile('/build_synonym_db.py',code);
  py.FS.writeFile('/synonyms.sqlite3',database);
  py.runPython(`
import json, sys
sys.path.insert(0, '/')
from build_synonym_db import get_engine, get_session_factory, expand_user_query
_synonym_engine = get_engine('sqlite:////synonyms.sqlite3')
_synonym_sessions = get_session_factory(_synonym_engine)
def _expand_explorer_query(query):
    with _synonym_sessions() as session:
        return json.dumps(expand_user_query(query, session), ensure_ascii=False)
`);
  const expand=py.globals.get('_expand_explorer_query');
  return query=>{
    if(typeof query!=='string'||query.length>300)throw Error('Search must be at most 300 characters');
    if(!/[a-z0-9]/i.test(query))return {matches:[],ors_citations:[],matched_canonical_terms:[],alternative_phrases:[]};
    return JSON.parse(expand(query));
  };
}
