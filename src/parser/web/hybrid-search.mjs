let worker,serial=0;
const pending=new Map();
export function expandQuery(query){
  if(!worker){
    worker=new Worker(new URL('./hybrid-worker.mjs',import.meta.url),{type:'module'});
    worker.onmessage=({data})=>{const request=pending.get(data.id);if(!request)return;pending.delete(data.id);clearTimeout(request.timer);data.error?request.reject(Error(data.error)):request.resolve(data.result);};
    worker.onerror=()=>{for(const r of pending.values()){clearTimeout(r.timer);r.reject(Error('Synonym search unavailable'));}pending.clear();worker.terminate();worker=null;};
  }
  return new Promise((resolve,reject)=>{const id=++serial,timer=setTimeout(()=>{pending.delete(id);reject(Error('Synonym search timed out'));},60000);pending.set(id,{resolve,reject,timer});worker.postMessage({id,query});});
}

export function fuseResults(query,lexical,index,expansion,chapter='',status=''){
  const eligible=new Map(index.filter(r=>(!chapter||r[1]===chapter)&&(!status||r[3]===status)).map(r=>[r[0],r]));
  const raw=query.trim().toLowerCase(),terms=[...new Set(raw.match(/[a-z0-9]+/g)||[])];
  const concept=new Map(),reasons=new Map();
  for(const match of expansion.matches||[]){
    const id=match.statute_citation.replace(/^ORS\s+/i,'');if(!eligible.has(id))continue;
    const text=`${match.canonical_term} ${match.layperson_synonym}`.toLowerCase();
    const score=terms.filter(t=>t.length>=3&&text.includes(t)).length+(text.includes(raw)?4:0);
    if(score>(concept.get(id)||-1)){concept.set(id,score);reasons.set(id,match.canonical_term);}
  }
  const ranked=[...concept].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],'en',{numeric:true}));
  const scores=new Map();
  lexical.forEach((row,i)=>{if(eligible.has(row[0]))scores.set(row[0],1/(60+i+1));});
  ranked.forEach(([id],i)=>scores.set(id,(scores.get(id)||0)+0.8/(60+i+1)));
  const exact=raw.replace(/^ors\s+/,'');if(eligible.has(exact))scores.set(exact,10);
  return {rows:[...scores].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],'en',{numeric:true})).map(([id])=>eligible.get(id)),reasons};
}
