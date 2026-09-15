import {initializeHybrid} from './hybrid-runtime.mjs';
let ready;
self.onmessage=async ({data})=>{
  const {id,query}=data;
  try{
    ready ||= initializeHybrid().catch(error=>{ready=null;throw error;});
    const expand=await ready;
    self.postMessage({id,result:expand(query)});
  }catch(error){self.postMessage({id,error:'Synonym search could not load. Text search remains available.'});}
};
