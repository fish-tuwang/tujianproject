const { createApi } = require('../../services/api');
const { getConfig } = require('../../config');
const session = require('../../services/session');
Page({
  data: { passwordMode: false, username: '', password: '', currentPassword: '', newPassword: '', confirmation: '', loading: false, error: '' },
  onLoad(options) {
    const env = wx.getAccountInfoSync ? wx.getAccountInfoSync().miniProgram.envVersion : 'develop';
    try { this.api = createApi(wx, getConfig(env).apiBaseUrl); }
    catch (error) { this.setData({ error: error.message }); return; }
    const profile = session.read(wx);
    this.setData({ passwordMode: options.mode === 'password' || Boolean(profile?.must_change_password), username: profile?.username || '' });
    if (profile && !this.data.passwordMode) this.api.me().then(value => { if (value.must_change_password) this.setData({ passwordMode: true }); else wx.switchTab({ url: '/pages/tomica-list/index' }); }).catch(() => {});
  },
  input(event) { this.setData({ [event.currentTarget.dataset.key]: event.detail.value }); },
  async submit() {
    if (this.data.loading || !this.api) return;
    if (this.data.passwordMode && (this.data.newPassword.length < 15 || this.data.newPassword.length > 128 || this.data.newPassword !== this.data.confirmation)) { this.setData({ error: '新密码须为15–128个字符，且两次输入一致' }); return; }
    this.setData({ loading: true, error: '' });
    try {
      const value = this.data.passwordMode ? await this.api.changePassword(this.data.currentPassword, this.data.newPassword) : await this.api.login(this.data.username.trim(), this.data.password);
      session.save(wx, value); this.setData({ password: '', currentPassword: '', newPassword: '', confirmation: '' });
      if (value.must_change_password) this.setData({ passwordMode: true });
      else wx.switchTab({ url: '/pages/tomica-list/index' });
    } catch (error) { this.setData({ error: error.message }); }
    finally { this.setData({ loading: false }); }
  },
  async logout() { try { await this.api.logout(); session.clear(wx); this.setData({ passwordMode: false, username: '', password: '', error: '' }); } catch (error) { this.setData({ error: error.message }); } }
});
