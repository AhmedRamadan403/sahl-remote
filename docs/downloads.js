"use strict";
const address = document.querySelector('#page-address');
address.value = location.href.split('#')[0].split('?')[0];
document.querySelector('#copy-address').addEventListener('click', async () => {
  const status = document.querySelector('#copy-status');
  try {
    await navigator.clipboard.writeText(address.value);
    status.textContent = 'اتنسخ! ابعته للجهاز اللي عايز تحمّل عليه.';
  } catch {
    address.focus(); address.select();
    status.textContent = 'انسخ الرابط المحدد وابعته للجهاز التاني.';
  }
});
async function loadReleases() {
  try {
    const response = await fetch('./releases.json', {cache:'no-store'});
    if (!response.ok) throw new Error('metadata');
    const data = await response.json();
    address.value = data.site_url;
    for (const platform of ['android','windows']) {
      const release = data.releases[platform];
      const url = new URL(release.url);
      if (url.protocol !== 'https:' || url.hostname !== 'github.com' || !url.pathname.includes('/releases/download/')) throw new Error('release URL');
      const button = document.querySelector(`#${platform}-download`);
      button.href = url.href;
      button.setAttribute('aria-disabled','false');
      document.querySelector(`#${platform}-meta`).textContent = `v${release.version} · ${(release.size_bytes/1048576).toFixed(1)} MB · ${platform==='android'?'APK':'EXE'}`;
    }
  } catch { document.querySelector('#load-error').hidden = false; }
}
loadReleases();
