/** Presentation clock. All units are seconds or milliseconds; no financial data. */
export class Clock {
  constructor(durationSeconds) { this.duration=durationSeconds;this.time=0;this.playing=false;this.anchor=0;this.start=0; }
  play(nowMs) { if(this.time>=this.duration)this.time=0;this.anchor=nowMs;this.start=this.time;this.playing=true; }
  pause() { this.playing=false; }
  seek(seconds) { if(!Number.isFinite(seconds))return;this.time=Math.min(this.duration,Math.max(0,seconds));this.pause(); }
  replay(nowMs) { this.time=0;this.play(nowMs); }
  tick(nowMs) { if(this.playing){this.time=Math.min(this.duration,this.start+(nowMs-this.anchor)/1000);if(this.time===this.duration)this.pause();}return this.time; }
}
/** Smooth interpolation is for visual geometry only, never money or rates. */
export const ease = x => { const q=Math.max(0,Math.min(1,x));return q*q*(3-2*q); };
export const phase = (time,start,end) => ease((time-start)/(end-start));
export const mix = (a,b,t) => a+(b-a)*t;
