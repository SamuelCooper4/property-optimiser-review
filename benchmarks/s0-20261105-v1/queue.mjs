// Scheduling only: no financial calculation or ranking.
export class TaskQueue {
 constructor(){this.context=0;this.tasks=new Map();}
 submit(task){
  if(task.context<this.context)return {accepted:false,cancelled:[]};
  const cancelled=[];
  for(const old of this.tasks.values()){
   if(task.context>this.context||(task.priority==='interactive'&&old.priority==='interactive')){
    old.cancelled=true;cancelled.push(old);this.tasks.delete(old.id);
   }
  }
  this.context=task.context;this.tasks.set(task.id,{...task,state:'queued',units:0});
  return {accepted:true,cancelled};
 }
 next(){const all=[...this.tasks.values()].filter(t=>t.state==='queued');
  const task=all.find(t=>t.priority==='interactive')||all[0];if(task)task.state='running';return task;}
 yield(task){if(this.tasks.has(task.id))task.state='queued';}
 complete(id){this.tasks.delete(id);}
 cancel(id){const task=this.tasks.get(id);if(task){task.cancelled=true;this.tasks.delete(id);}return task;}
}
