const session = require('./services/session');
const { createApi } = require('./services/api');
const { getConfig } = require('./config');
App({
  globalData: {},
  onShow() {
    const check = () => {
      if (!session.token(wx)) { session.expire(wx); return; }
      try {
        const env = wx.getAccountInfoSync().miniProgram.envVersion;
        createApi(wx, getConfig(env).apiBaseUrl).me().then(value => { if (value.must_change_password) session.loginPage(wx, true); }).catch(() => {});
      } catch (_) { /* The login page explains missing local domain configuration. */ }
    };
    check(); clearInterval(this.authTimer); this.authTimer = setInterval(check, 10000);
  },
  onHide() { clearInterval(this.authTimer); }
});
