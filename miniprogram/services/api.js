function createApi(wxApi, baseUrl) {
  function get(path, params = {}) {
    let task;
    const query = Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '').map(([key, value]) => encodeURIComponent(key) + '=' + encodeURIComponent(value)).join('&');
    const promise = new Promise((resolve, reject) => {
      task = wxApi.request({ url: baseUrl.replace(/\/$/, '') + path + (query ? '?' + query : ''), method: 'GET', timeout: 20000,
        success(response) { if (response.statusCode >= 200 && response.statusCode < 300) resolve(response.data); else reject(Object.assign(new Error(response.data.message || '加载失败'), { code: response.data.code, status: response.statusCode })); },
        fail(error) { reject(Object.assign(new Error('连接失败，请稍后重试'), { code: /abort/.test(error.errMsg || '') ? 'ABORTED' : 'NETWORK_ERROR' })); }
      });
    });
    promise.abort = () => task && task.abort();
    return promise;
  }
  return { get, imageUrl: item => item.image_url || (item.preview_image_url ? baseUrl.replace(/\/$/, '') + item.preview_image_url : null), list: (kind, params) => get('/api/' + kind, params), detail: (kind, id) => get('/api/' + kind + '/' + encodeURIComponent(id)), filters: () => get('/api/tomica/filters'), regions: () => get('/api/pokemon/regions') };
}
module.exports = { createApi };
