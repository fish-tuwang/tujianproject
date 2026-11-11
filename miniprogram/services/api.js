const session = require('./session');
const { loadPrivateImage } = require('./private-images');
function createApi(wxApi, baseUrl) {
  function request(path, params = {}, method = 'GET') {
    let task;
    const token = session.token(wxApi);
    const query = Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '').map(([key, value]) => encodeURIComponent(key) + '=' + encodeURIComponent(value)).join('&');
    const promise = new Promise((resolve, reject) => {
      const header = token ? { Authorization: 'Bearer ' + token } : undefined;
      const options = { url: baseUrl.replace(/\/$/, '') + path + (method === 'GET' && query ? '?' + query : ''), method, timeout: 20000,
        success(response) {
          if (response.statusCode >= 200 && response.statusCode < 300) { resolve(response.data); return; }
          const data = response.data || {};
          if (token === session.token(wxApi)) {
            if (response.statusCode === 401 && path !== '/api/auth/login') session.expire(wxApi);
            if (data.code === 'PASSWORD_CHANGE_REQUIRED') session.loginPage(wxApi, true);
          }
          reject(Object.assign(new Error(data.message || '加载失败'), { code: data.code, status: response.statusCode }));
        },
        fail(error) { reject(Object.assign(new Error('连接失败，请稍后重试'), { code: /abort/.test(error.errMsg || '') ? 'ABORTED' : 'NETWORK_ERROR' })); }
      };
      if (header) options.header = header;
      if (method === 'POST') { options.data = params; options.header = { ...header, 'Content-Type': 'application/json', 'X-Catalog-Client': 'miniprogram' }; }
      task = wxApi.request(options);
    });
    promise.abort = () => task && task.abort();
    return promise;
  }
  const get = (path, params) => request(path, params);
  return { get, imageUrl: item => item.image_url || (item.preview_image_url ? baseUrl.replace(/\/$/, '') + item.preview_image_url : null), list: (kind, params) => get('/api/' + kind, params), detail: (kind, id) => get('/api/' + kind + '/' + encodeURIComponent(id)), filters: () => get('/api/tomica/filters'), regions: () => get('/api/pokemon/regions'),
    login: (username, password) => request('/api/auth/login', { username, password }, 'POST'), me: () => get('/api/auth/me'),
    changePassword: (current_password, new_password) => request('/api/auth/password', { current_password, new_password }, 'POST'),
    logout: () => request('/api/auth/logout', {}, 'POST'), downloadImage: url => loadPrivateImage(wxApi, baseUrl, url) };
}
module.exports = { createApi };
