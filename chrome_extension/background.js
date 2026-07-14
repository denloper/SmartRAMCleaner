const DEFAULT_SETTINGS = {
  enabled: true,
  suspendTime: 10,
  whitelist: ['youtube.com', 'music.youtube.com', 'spotify.com', 'twitch.tv', 'discord.com'],
  dontSuspendPinned: true,
  dontSuspendAudio: true,
  dontSuspendActive: true,
  dontSuspendForms: true
};

let lastAccessedTime = {};
let suspendCount = 0;

// Отслеживаем активные вкладки
chrome.tabs.onActivated.addListener(info => {
  lastAccessedTime[info.tabId] = Date.now();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete') {
    lastAccessedTime[tabId] = Date.now();
  }
});

chrome.tabs.onRemoved.addListener(tabId => {
  delete lastAccessedTime[tabId];
});

// Периодическая проверка каждую минуту
chrome.alarms.create('checkTabs', { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'checkTabs') checkAndSuspend();
});

async function checkAndSuspend() {
  const data = await chrome.storage.local.get(DEFAULT_SETTINGS);
  const settings = { ...DEFAULT_SETTINGS, ...data };
  
  if (!settings.enabled) return;
  
  const tabs = await chrome.tabs.query({});
  const now = Date.now();
  
  for (const tab of tabs) {
    if (tab.discarded) continue;
    if (!tab.url || tab.url.startsWith('chrome')) continue;
    
    // Проверки исключений
    if (tab.active && settings.dontSuspendActive) continue;
    if (tab.pinned && settings.dontSuspendPinned) continue;
    if (tab.audible && settings.dontSuspendAudio) continue;
    
    // Белый список
    try {
      const url = new URL(tab.url);
      if (settings.whitelist.some(domain => url.hostname.includes(domain))) continue;
    } catch(e) { continue; }
    
    // Проверка времени
    const lastAccess = lastAccessedTime[tab.id] || tab.lastAccessed || now;
    const inactiveMinutes = (now - lastAccess) / 1000 / 60;
    
    if (inactiveMinutes > settings.suspendTime) {
      try {
        await chrome.tabs.discard(tab.id);
        suspendCount++;
      } catch(e) {}
    }
  }
}

// Экспорт статистики
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'GET_STATS') {
    sendResponse({ suspendCount });
  } else if (request.type === 'SUSPEND_NOW') {
    chrome.tabs.discard(request.tabId);
    sendResponse({ success: true });
  } else if (request.type === 'SUSPEND_ALL') {
    suspendAll();
    sendResponse({ success: true });
  }
  return true;
});

async function suspendAll() {
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (!tab.discarded && !tab.active) {
      try { await chrome.tabs.discard(tab.id); suspendCount++; } catch(e) {}
    }
  }
}