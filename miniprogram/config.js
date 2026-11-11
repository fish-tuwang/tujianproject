const config = { develop: { apiBaseUrl: 'http://127.0.0.1:8092' }, trial: { apiBaseUrl: '' }, release: { apiBaseUrl: '' } };
function getConfig(envVersion = 'develop') { const value = config[envVersion]; if (!value || !value.apiBaseUrl) throw new Error('请配置接口域名'); return value; }
module.exports = { getConfig };
