'use strict';
const address = document.querySelector('#page-address');
address.value = location.origin + '/download';
document.querySelector('#copy-address').addEventListener('click', async () => {
  const status = document.querySelector('#copy-status');
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(address.value);
    } else {
      address.focus(); address.select(); address.setSelectionRange(0, address.value.length);
      if (!document.execCommand('copy')) throw new Error('copy');
    }
    status.textContent = 'اتنسخ! ابعته للجهاز التاني على نفس الشبكة.';
  } catch {
    address.focus(); address.select();
    status.textContent = 'اضغط مطولًا على الرابط وانسخه.';
  }
});
async function loadReleases() {
  try {
    const response = await fetch('/api/releases', {cache: 'no-store'});
    if (!response.ok) throw new Error('metadata');
    const {releases} = await response.json();
    for (const platform of ['android', 'windows']) {
      const release = releases[platform];
      const button = document.querySelector(`#${platform}-download`);
      const meta = document.querySelector(`#${platform}-meta`);
      if (!release.available) {
        meta.textContent = 'النسخة مش موجودة على الكمبيوتر ده';
        continue;
      }
      // Only accept the two fixed, same-origin download endpoints.
      if (release.url !== `/files/${platform}`) throw new Error('download URL');
      button.href = release.url;
      button.download = platform === 'android' ? 'SahlRemote-Android.apk' : 'SahlRemote-Desktop.exe';
      button.setAttribute('aria-disabled', 'false');
      meta.textContent = `v${release.version} · ${(release.size_bytes / 1048576).toFixed(1)} MB · ${platform === 'android' ? 'APK' : 'EXE'}`;
    }
  } catch {
    document.querySelector('#load-error').hidden = false;
  }
}
loadReleases();
