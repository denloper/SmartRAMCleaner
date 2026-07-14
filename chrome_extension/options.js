document.addEventListener('DOMContentLoaded', async () => {
  const data = await chrome.storage.local.get({
    suspendTime: 10,
    whitelist: ['youtube.com', 'music.youtube.com', 'spotify.com', 'twitch.tv', 'discord.com'],
    dontSuspendPinned: true,
    dontSuspendAudio: true,
    dontSuspendActive: true
  });
  
  document.getElementById('suspendTime').value = data.suspendTime;
  document.getElementById('whitelist').value = data.whitelist.join('\n');
  document.getElementById('dontSuspendPinned').checked = data.dontSuspendPinned;
  document.getElementById('dontSuspendAudio').checked = data.dontSuspendAudio;
  document.getElementById('dontSuspendActive').checked = data.dontSuspendActive;
  
  document.getElementById('saveBtn').addEventListener('click', async () => {
    const settings = {
      suspendTime: parseInt(document.getElementById('suspendTime').value) || 10,
      whitelist: document.getElementById('whitelist').value.split('\n').map(s => s.trim()).filter(s => s),
      dontSuspendPinned: document.getElementById('dontSuspendPinned').checked,
      dontSuspendAudio: document.getElementById('dontSuspendAudio').checked,
      dontSuspendActive: document.getElementById('dontSuspendActive').checked
    };
    
    await chrome.storage.local.set(settings);
    document.getElementById('status').textContent = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').textContent = '', 2000);
  });
});