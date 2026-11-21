/* Review gallery: load only videos actually deployed. No unverified review claims. */
(() => {
  const section = document.getElementById('la-ugc-showcase');
  if (!section) return;
  section.querySelectorAll('.la-ugc-media').forEach(media => {
    const video = media.querySelector('video');
    if (!video) return;
    const src = video.dataset.src || '';
    const poster = media.querySelector('.la-ugc-poster');
    const placeholder = media.querySelector('.la-ugc-placeholder');
    const pending = () => {
      media.classList.add('la-ugc-pending');
      if (placeholder) placeholder.hidden = false;
      if (poster) poster.hidden = false;
      video.hidden = true;
    };
    if (!src) { pending(); return; }
    // Skip loading large media until it's clear the file exists.
    fetch(src, {method:'HEAD', cache:'no-store'}).then(response => {
      const type = response.headers.get('content-type') || '';
      if (!response.ok || !(type.includes('video/') || type.includes('application/octet-stream'))) throw new Error('Missing video');
      const source = document.createElement('source');
      source.src = src; source.type = 'video/mp4';
      video.appendChild(source);
      if (placeholder) placeholder.hidden = true;
      if (poster) poster.hidden = true;
      video.hidden = false;
      video.load();
    }).catch(pending);
    video.addEventListener('error', pending, {once:true});
  });
})();
