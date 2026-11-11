const session = require('./session');
const cached = new Map(), queue = [];
let active = 0;
const stale = () => Object.assign(new Error('登录状态已变化'), { code: 'STALE_SESSION' });
session.subscribe(() => { cached.clear(); for (const entry of queue.splice(0)) entry.reject(stale()); });
function pump() {
  while (active < 3 && queue.length) {
    const entry = queue.shift();
    if (entry.generation !== session.generation()) { entry.reject(stale()); continue; }
    active++;
    entry.run().then(entry.resolve, entry.reject).finally(() => { active--; pump(); });
  }
}
function loadPrivateImage(wxApi, baseUrl, url) {
  if (!url) return Promise.resolve(null);
  const base = baseUrl.replace(/\/$/, ''), absolute = url.startsWith('/') && !url.startsWith('//') ? base + url : url;
  if (!absolute.startsWith(base + '/')) return Promise.resolve(url);
  const token = session.token(wxApi), generation = session.generation();
  if (!token) { session.expire(wxApi); return Promise.reject(Object.assign(new Error('请先登录'), { code: 'AUTH_REQUIRED' })); }
  const key = generation + ':' + absolute;
  if (cached.has(key)) return cached.get(key);
  const promise = new Promise((resolve, reject) => {
    queue.push({ generation, resolve, reject, run: () => new Promise((done, fail) => {
      wxApi.downloadFile({ url: absolute, header: { Authorization: 'Bearer ' + token }, timeout: 30000,
        success(response) {
          if (generation !== session.generation() || token !== session.token(wxApi)) { fail(stale()); return; }
          if (response.statusCode === 401) { session.expire(wxApi); fail(Object.assign(new Error('请重新登录'), { code: 'AUTH_REQUIRED' })); return; }
          if (response.statusCode !== 200 || !response.tempFilePath) { fail(new Error('原图暂时无法加载')); return; }
          done(response.tempFilePath);
        }, fail() { fail(new Error('原图连接失败')); }
      });
    }) });
    pump();
  });
  cached.set(key, promise);
  promise.catch(() => { if (cached.get(key) === promise) cached.delete(key); });
  if (cached.size > 200) cached.delete(cached.keys().next().value);
  return promise;
}
module.exports = { loadPrivateImage };
