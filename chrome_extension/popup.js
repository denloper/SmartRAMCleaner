document.addEventListener('DOMContentLoaded', async () => {
  const data = await chrome.storage.local.get(['enabled']);
  document.getElementById('enabledToggle').checked = data.enabled !== false;
  
  chrome.runtime.sendMessage({ type: 'GET_STATS' }, response => {
    document.getElementById('statsCount').textContent = response?.suspendCount || 0;
  });
  
  document.getElementById('enabledToggle').addEventListener('change', async (e) => {
    await chrome.storage.local.set({ enabled: e.target.checked });
  });
  
  document.getElementById('suspendAllBtn').addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'SUSPEND_ALL' });
    setTimeout(() => window.close(), 500);
  });
  
  document.getElementById('settingsBtn').addEventListener('click', () => {
    chrome.runtime.openOptionsPage();
  });
});