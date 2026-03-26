// Download file and report path back to popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  // Download with any URL (data URI, blob, etc.) and report path
  if (msg.action === 'download') {
    chrome.downloads.download({
      url: msg.url,
      filename: msg.filename,
      saveAs: false
    }, (downloadId) => {
      if (chrome.runtime.lastError) {
        sendResponse({ error: chrome.runtime.lastError.message });
        return;
      }

      const listener = (delta) => {
        if (delta.id === downloadId && delta.state) {
          if (delta.state.current === 'complete') {
            chrome.downloads.onChanged.removeListener(listener);
            chrome.downloads.search({ id: downloadId }, (results) => {
              if (results && results[0]) {
                chrome.runtime.sendMessage({
                  action: 'downloadComplete',
                  path: results[0].filename
                });
              }
            });
          } else if (delta.state.current === 'interrupted') {
            chrome.downloads.onChanged.removeListener(listener);
            chrome.runtime.sendMessage({
              action: 'downloadFailed',
              error: 'Download interrupted'
            });
          }
        }
      };
      chrome.downloads.onChanged.addListener(listener);
      sendResponse({ downloadId });
    });
    return true;
  }

  // Cleanup old subtitle files (>7 days)
  if (msg.action === 'cleanup') {
    const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
    chrome.downloads.search({
      filenameRegex: '.*\\.json$',
      endedBefore: weekAgo
    }, (results) => {
      let removed = 0;
      if (results) {
        for (const item of results) {
          if (item.filename && item.filename.includes('_subs') || item.filename.includes('_ru') || item.filename.includes('_en')) {
            chrome.downloads.removeFile(item.id, () => {
              if (!chrome.runtime.lastError) {
                chrome.downloads.erase({ id: item.id });
                removed++;
              }
            });
          }
        }
      }
      sendResponse({ removed, total: results ? results.length : 0 });
    });
    return true;
  }
});
