const KEY = 'dual-catalog:session:v1';
const listeners = new Set();
let generation = 0, redirected = false;
function read(wxApi) {
  try { const value = wxApi.getStorageSync && wxApi.getStorageSync(KEY); return value && typeof value.access_token === 'string' ? value : null; }
  catch (_) { return null; }
}
function token(wxApi) { return read(wxApi)?.access_token || ''; }
function notify() { generation++; for (const listener of listeners) listener(generation); }
function save(wxApi, value) {
  const previous = token(wxApi);
  if (!value || !value.access_token) throw new Error('登录响应缺少凭证');
  wxApi.setStorageSync(KEY, value); redirected = false;
  if (previous !== value.access_token) notify();
}
function clear(wxApi) { const hadSession=Boolean(read(wxApi)); if (wxApi.removeStorageSync) wxApi.removeStorageSync(KEY); if(hadSession)notify(); return hadSession; }
function loginPage(wxApi, password = false) {
  if (redirected) return;
  redirected = true;
  if (wxApi.reLaunch) wxApi.reLaunch({ url: '/pages/login/index' + (password ? '?mode=password' : '') });
}
function expire(wxApi) { const first=!redirected; loginPage(wxApi); if(!clear(wxApi)&&first)notify(); }
function subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); }
module.exports = { KEY, read, token, save, clear, expire, loginPage, subscribe, generation: () => generation };
