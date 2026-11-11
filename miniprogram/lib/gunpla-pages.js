const { createApi } = require('../services/api');
const { getConfig } = require('../config');
const session = require('../services/session');
let savedList = null;
session.subscribe(() => { savedList = null; });
const defaults = () => ({ mode: 'grade', grade: '', series: '', sale_type: '1', scale: '', q: '', page: 1, limit: 20 });
function runtime(wxApi) { const env = wxApi.getAccountInfoSync ? wxApi.getAccountInfoSync().miniProgram.envVersion : 'develop'; return createApi(wxApi, getConfig(env).apiBaseUrl); }
function valid(page) { return page.alive && page.generation === session.generation(); }
function initialize(page, wxApi) {
  page.wxApi = wxApi; page.api = runtime(wxApi); page.alive = true; page.generation = session.generation();
  page.stopSession = session.subscribe(() => { page.alive = false; page.pending?.abort(); page.setData({ items: [], detail: null, home: null, loading: false }); });
}
function dispose(page) { page.alive = false; clearTimeout(page.searchTimer); page.pending?.abort(); page.stopSession?.(); }

function createGunplaListPage(wxApi) {
  return {
    data: { query: defaults(), items: [], total: 0, totalPages: 1, loading: true, error: '', brands: ['全部规格'], gradeIndex: 0, scales: ['全部比例'], scaleIndex: 0, sizes: [20, 40, 60, 100], sizeIndex: 0, sales: [], seriesColumns: [[], []], seriesSelection: [0, 0], seriesName: '全部作品' },
    async onLoad() {
      initialize(this, wxApi || wx); this.sequence = 0;
      if (savedList) this.setData({ query: { ...savedList.query } });
      this.setData({ authUsername: session.read(this.wxApi)?.username || '' });
      try {
        const [metadata, home] = await Promise.all([this.api.get('/api/gunpla/filters'), this.api.get('/api/gunpla/home')]);
        if (!valid(this)) return;
        this.metadata = metadata;
        const cover = row => ({ ...row, image_url: this.api.imageUrl(row) });
        this.setData({ brands: ['全部规格', ...metadata.brands.map(r => r.name)], scales: ['全部比例', ...metadata.scales, '非比例 / 未标注'], sales: metadata.sale_types,
          home: { ...home, events: home.events.map(cover), upcoming: home.upcoming.map(g => ({ ...g, items: g.items.map(cover) })) },
          seriesColumns: [['全部年代', ...metadata.series_groups.map(g => g.name)], ['全部作品', ...metadata.series_groups.flatMap(g => g.items).map(r => r.name)]] });
        this.controls(); await this.load(); if (savedList && valid(this)) this.wxApi.pageScrollTo({ scrollTop: savedList.scrollY || 0, duration: 0 });
      } catch (error) { if (valid(this)) this.setData({ loading: false, error: error.message }); }
    },
    onPageScroll(event) { this.scrollY = event.scrollTop; },
    onHide() { if (valid(this)) savedList = { query: { ...this.data.query }, scrollY: this.scrollY || 0 }; },
    onUnload() { this.onHide(); dispose(this); },
    controls() {
      if (!this.metadata) return;
      const query = this.data.query;
      const work = this.metadata.series_groups.flatMap(g => g.items).find(r => r.id === query.series);
      this.setData({ gradeIndex: Math.max(0, this.metadata.brands.findIndex(r => r.id === query.grade) + 1), scaleIndex: query.scale === 'unscaled' ? this.data.scales.length - 1 : Math.max(0, this.data.scales.indexOf(query.scale)), sizeIndex: Math.max(0, this.data.sizes.indexOf(query.limit)), seriesName: work?.name || '全部作品' });
      if (work) {
        const group = this.metadata.series_groups.findIndex(g => g.items.some(r => r.id === work.id));
        this.setData({ seriesSelection: [group + 1, this.metadata.series_groups[group].items.findIndex(r => r.id === work.id) + 1], 'seriesColumns[1]': ['全部作品', ...this.metadata.series_groups[group].items.map(r => r.name)] });
      }
    },
    async load() {
      const sequence = ++this.sequence; this.pending?.abort(); this.setData({ loading: true, error: '' });
      try {
        this.pending = this.api.get('/api/gunpla', this.data.query); const value = await this.pending;
        if (!valid(this) || sequence !== this.sequence) return;
        this.setData({ items: value.items.map(row => ({ ...row, image_url: this.api.imageUrl(row) })), total: value.total, totalPages: value.total_pages, 'query.page': value.page });
      } catch (error) { if (valid(this) && sequence === this.sequence && error.code !== 'ABORTED') this.setData({ error: error.message }); }
      finally { if (valid(this) && sequence === this.sequence) this.setData({ loading: false }); }
    },
    setFilters(patch) {
      const query = { ...this.data.query, ...patch, page: 1 };
      if (patch.mode && patch.mode !== this.data.query.mode) { query.grade = ''; query.series = ''; query.sale_type = patch.mode === 'series' ? '' : '1'; query.scale = ''; }
      if (query.mode === 'series') { query.grade = ''; query.sale_type = ''; } else query.series = '';
      this.setData({ query }); this.controls(); return this.load();
    },
    mode(event) { return this.setFilters({ mode: event.currentTarget.dataset.mode }); },
    grade(event) { const index = Number(event.detail.value); return this.setFilters({ grade: index ? this.metadata.brands[index - 1].id : '' }); },
    sale(event) { return this.setFilters({ sale_type: event.currentTarget.dataset.sale }); },
    scale(event) { const index = Number(event.detail.value); return this.setFilters({ scale: !index ? '' : index === this.data.scales.length - 1 ? 'unscaled' : this.metadata.scales[index - 1] }); },
    size(event) { return this.setFilters({ limit: this.data.sizes[Number(event.detail.value)] }); },
    search(event) { clearTimeout(this.searchTimer); this.searchTimer = setTimeout(() => { if (valid(this)) this.setFilters({ q: event.detail.value.trim() }); }, 280); },
    seriesColumn(event) {
      if (event.detail.column !== 0) return;
      const group = Number(event.detail.value), works = group ? this.metadata.series_groups[group - 1].items : this.metadata.series_groups.flatMap(g => g.items);
      this.setData({ 'seriesColumns[1]': ['全部作品', ...works.map(r => r.name)], seriesSelection: [group, 0] });
    },
    series(event) {
      const [group, index] = event.detail.value, works = group ? this.metadata.series_groups[group - 1].items : this.metadata.series_groups.flatMap(g => g.items);
      this.setData({ seriesSelection: event.detail.value }); return this.setFilters({ series: index ? works[index - 1].id : '' });
    },
    async page(event) { const page = this.data.query.page + Number(event.currentTarget.dataset.delta); if (this.data.loading || page < 1 || page > this.data.totalPages) return; this.setData({ 'query.page': page }); await this.load(); if (valid(this)) this.wxApi.pageScrollTo({ scrollTop: 0, duration: 0 }); },
    reset() { this.setData({ query: defaults() }); this.controls(); return this.load(); },
    open(event) { this.onHide(); this.wxApi.navigateTo({ url: '/pages/gunpla-detail/index?id=' + encodeURIComponent(event.currentTarget.dataset.id) }); },
    async previewEvent(event) { try { const url = await this.api.downloadImage(event.currentTarget.dataset.url); if (valid(this)) this.wxApi.previewImage({ current: url, urls: [url] }); } catch (error) { if (valid(this)) this.setData({ error: error.message }); } },
    changePassword() { session.loginPage(this.wxApi, true); },
    async logout() { try { await this.api.logout(); session.expire(this.wxApi); } catch (error) { if (valid(this)) this.setData({ error: error.message }); } }
  };
}

function createGunplaDetailPage(wxApi) {
  return {
    data: { loading: true, error: '', detail: null, activeImage: null },
    onLoad(options) { initialize(this, wxApi || wx); this.id = options.id; return this.load(); },
    onUnload() { dispose(this); },
    async load() {
      this.setData({ loading: true, error: '' });
      try {
        this.pending = this.api.get('/api/gunpla/products/' + encodeURIComponent(this.id)); const value = await this.pending;
        if (!valid(this)) return;
        const url = value => value ? this.api.imageUrl({ preview_image_url: value }) : null;
        const detail = { ...value, cover: url(value.cover), gallery: value.gallery.map(url), detail_images: value.detail_images.map(url) };
        this.setData({ detail, activeImage: detail.gallery[0] || detail.cover });
      } catch (error) { if (valid(this)) this.setData({ error: error.message }); }
      finally { if (valid(this)) this.setData({ loading: false }); }
    },
    chooseImage(event) { this.setData({ activeImage: event.currentTarget.dataset.url }); },
    async previewImage(event) {
      if (!this.data.detail) return;
      const current = event.currentTarget.dataset.url, urls = [...new Set([...this.data.detail.gallery, ...this.data.detail.detail_images])];
      if (!urls.includes(current)) return;
      try { const originals = await Promise.all(urls.map(url => this.api.downloadImage(url))); if (valid(this)) this.wxApi.previewImage({ current: originals[urls.indexOf(current)], urls: originals }); }
      catch (error) { if (valid(this)) this.setData({ error: error.message }); }
    }
  };
}
module.exports = { createGunplaListPage, createGunplaDetailPage };
