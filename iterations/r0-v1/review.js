/* Review navigation only. No animation, financial calculation or product state. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let scenes = [], index = 0;
  const initial = location.hash.match(/^#frame-(\d{2})$/);
  function show(next, announce = true) {
    index = Math.max(0, Math.min(scenes.length - 1, next));
    const s = scenes[index];
    $('chapter').textContent = `${s.id} / 14 · ${s.chapter}`;
    $('frame-title').textContent = s.title;
    $('main-frame').src = `frames/${s.id}.svg`;
    $('mobile-frame').srcset = `frames/${s.id}-mobile.svg`;
    $('main-frame').alt = `${s.learn} ${s.truth}`;
    for (const key of ['learn', 'transition', 'pacing', 'interaction', 'continuity', 'truth']) $(key).textContent = s[key];
    $('counter').textContent = `Keyframe ${s.id}`;
    $('prev').disabled = index === 0;
    $('next').disabled = index === scenes.length - 1;
    document.querySelectorAll('.frame-nav button').forEach((b, i) => b.setAttribute('aria-current', String(i === index)));
    if (announce) {
      history.replaceState(null, '', `#frame-${s.id}`);
      $('announcement').textContent = `Keyframe ${s.id}: ${s.title}`;
    }
  }
  function inspect(i) { show(i); $('review').scrollIntoView(); $('frame-title').focus({preventScroll:true}); }
  fetch('scenes.json').then(r => {if (!r.ok) throw new Error('Scenes unavailable'); return r.json();}).then(data => {
    scenes = data;
    scenes.forEach((s, i) => {
      const button = document.createElement('button');
      button.textContent = s.id; button.type = 'button'; button.setAttribute('aria-label', `Keyframe ${s.id}: ${s.title}`);
      button.addEventListener('click', () => show(i)); $('frame-nav').append(button);
    });
    $('prev').addEventListener('click', () => show(index - 1));
    $('next').addEventListener('click', () => show(index + 1));
    $('end').addEventListener('click', () => show(13));
    document.querySelectorAll('[data-inspect]').forEach(b => b.addEventListener('click', () => inspect(Number(b.dataset.inspect))));
    document.querySelectorAll('[data-beat]').forEach(a => a.addEventListener('click', e => {e.preventDefault(); inspect(Number(a.dataset.beat));}));
    show(initial ? Number(initial[1]) - 1 : 0, false);
    if (initial) $('review').scrollIntoView();
    window.addEventListener('hashchange', () => {
      const target = location.hash.match(/^#frame-(\d{2})$/);
      if (target) { show(Number(target[1]) - 1, false); $('review').scrollIntoView(); }
    });
  }).catch(() => {
    $('learn').textContent = 'The review navigation could not load. Open scenes.json or the individual SVG drawings linked in the evidence section.';
  });
  fetch('review.json').then(r => r.ok ? r.json() : null).then(r => {if(r?.source_commit) $('source-info').textContent = `Source branch: ${r.source_branch}. Artifact commit: ${r.source_commit}.`;}).catch(() => {});
})();
