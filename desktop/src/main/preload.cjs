/* The only road between the panel and the main process.
 *
 * The renderer gets a handful of named calls and a state subscription — no Node, no file system, and
 * never the API key. Everything it draws arrives already worked out by shulgo-core in the main process.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('shulgo', {
    getState: () => ipcRenderer.invoke('shulgo:getState'),
    onState: (callback) => {
        const listener = (_event, state) => callback(state);
        ipcRenderer.on('shulgo:state', listener);

        return () => ipcRenderer.removeListener('shulgo:state', listener);
    },

    refresh: () => ipcRenderer.invoke('shulgo:refresh'),
    set: (changes) => ipcRenderer.invoke('shulgo:set', changes),
    openExternal: (url) => ipcRenderer.invoke('shulgo:openExternal', url),
    openSettings: () => ipcRenderer.invoke('shulgo:openSettings'),
    hidePanel: () => ipcRenderer.invoke('shulgo:hidePanel'),
    quit: () => ipcRenderer.invoke('shulgo:quit'),
    reportNetwork: (online) => ipcRenderer.invoke('shulgo:network', online),

    searchPlaces: (text) => ipcRenderer.invoke('shulgo:searchPlaces', text),
    setPlace: (match) => ipcRenderer.invoke('shulgo:setPlace', match),
    settleTimezone: () => ipcRenderer.invoke('shulgo:settleTimezone'),
    setKey: (key, options) => ipcRenderer.invoke('shulgo:setKey', key, options),
});
