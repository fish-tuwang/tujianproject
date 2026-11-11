const { getConfig } = require('../../config');
const { loadPrivateImage } = require('../../services/private-images');
const session = require('../../services/session');
Component({
  options: { styleIsolation: 'apply-shared' },
  properties: { src: { type: String, value: '', observer: 'load' }, mode: { type: String, value: 'aspectFit' } },
  data: { localSrc: '' },
  lifetimes: {
    attached() { this.alive = true; this.sequence = 0; this.unsubscribe = session.subscribe(() => this.load()); this.load(); },
    detached() { this.alive = false; this.sequence++; if (this.unsubscribe) this.unsubscribe(); }
  },
  methods: {
    async load() {
      if (!this.alive) return;
      const sequence = ++this.sequence, src = this.properties.src;
      this.setData({ localSrc: '' }); if (!src) return;
      try {
        const env = wx.getAccountInfoSync ? wx.getAccountInfoSync().miniProgram.envVersion : 'develop';
        const localSrc = await loadPrivateImage(wx, getConfig(env).apiBaseUrl, src);
        if (this.alive && sequence === this.sequence) this.setData({ localSrc });
      } catch (error) { if (this.alive && sequence === this.sequence && error.code !== 'STALE_SESSION' && error.code !== 'AUTH_REQUIRED') this.triggerEvent('error'); }
    },
    imageError() { this.triggerEvent('error'); }
  }
});
