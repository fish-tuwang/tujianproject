const { createApi } = require('../services/api');
const { createCatalogState } = require('./catalog-state');
const { getConfig } = require('../config');
const { prepareExtra, filterMoves } = require('./pokemon-extra');
const cache = new Map();
function runtimeApi(wxApi) { const version = wxApi.getAccountInfoSync ? wxApi.getAccountInfoSync().miniProgram.envVersion : 'develop'; return createApi(wxApi, getConfig(version).apiBaseUrl); }
function createListPage(kind, wxApi) {
  return {
    data: { kind, items: [], filters: {}, loading: false, error: '', hasMore: true, brands: ['全部品牌'], years: ['全部年份'], regions: ['全部地区'], regionKeys: [''], regionIndex: 0, types: ['全部属性', '一般', '火', '水', '电', '草', '冰', '格斗', '毒', '地面', '飞行', '超能力', '虫', '岩石', '幽灵', '龙', '恶', '钢', '妖精'], brandIndex: 0, yearIndex: 0, typeIndex: 0 },
    onLoad() {
      this.alive = true;
      this.wxApi = wxApi || wx;
      this.api = runtimeApi(this.wxApi);
      this.state = createCatalogState({ api: this.api, kind, onChange: value => this.setData({ ...value, regionIndex: Math.max(0, this.data.regionKeys.indexOf(value.filters.region || '')), typeIndex: Math.max(0, this.data.types.indexOf(value.filters.type || '全部属性')), items: value.items.map(item => ({ ...item, image_url: this.api.imageUrl(item), numberLabel: kind === 'pokemon' ? '#' + String(item.dex).padStart(4, '0') : 'No. ' + item.number, title: item.name_display || item.name_original || item.name_zh, subtitle: item.name_en || item.brand || '品牌待整理', symbol: (item.types || ['T'])[0], yearLabel: item.release_year || '年份未知' })) }) });
      if (cache.has(kind)) this.state.restore(cache.get(kind)); else this.state.load(true);
      if (kind === 'tomica') this.api.filters().then(value => this.setData({ brands: ['全部品牌', ...value.brands, '未知品牌'], years: ['全部年份', ...value.years, '未知年份'] })).catch(() => {});
      if (kind === 'pokemon') this.regionsLoaded = this.api.regions().then(value => { if (!this.alive) return; const items = value.items || [], keys = ['', ...items.map(r => r.key)]; this.setData({ regions: ['全部地区', ...items.map(r => r.name + '地区')], regionKeys: keys, regionIndex: Math.max(0, keys.indexOf(this.state.snapshot().filters.region || '')) }); }).catch(() => {});
    },
    onShow() { if (this.state && this.state.snapshot().scrollTop) this.wxApi.pageScrollTo({ scrollTop: this.state.snapshot().scrollTop, duration: 0 }); },
    onHide() { if (this.state) cache.set(kind, this.state.snapshot()); },
    onUnload() { this.alive = false; clearTimeout(this.searchTimer); if (this.state) { cache.set(kind, this.state.snapshot()); this.state.dispose(); } },
    onPageScroll(event) { if (this.state) this.state.setScroll(event.scrollTop); },
    onReachBottom() { return this.state.load(); },
    onPullDownRefresh() { return this.state.load(true).finally(() => this.wxApi.stopPullDownRefresh()); },
    search(event) { clearTimeout(this.searchTimer); const q = event.detail.value; this.searchTimer = setTimeout(() => this.state.setFilters({ ...this.state.snapshot().filters, q }), 300); },
    filterBrand(event) { const index = Number(event.detail.value), label = this.data.brands[index]; this.setData({ brandIndex: index }); return this.state.setFilters({ ...this.state.snapshot().filters, brand: index ? label === '未知品牌' ? 'unknown' : label : null }); },
    filterYear(event) { const index = Number(event.detail.value), label = this.data.years[index]; this.setData({ yearIndex: index }); return this.state.setFilters({ ...this.state.snapshot().filters, year: index ? label === '未知年份' ? 'unknown' : label : null }); },
    filterType(event) { const index = Number(event.detail.value); this.setData({ typeIndex: index }); return this.state.setFilters({ ...this.state.snapshot().filters, type: index ? this.data.types[index] : null }); },
    filterRegion(event) { const index = Number(event.detail.value); this.setData({ regionIndex: index }); return this.state.setFilters({ ...this.state.snapshot().filters, region: this.data.regionKeys[index] || null }); },
    open(event) { this.wxApi.navigateTo({ url: '/pages/' + kind + '-detail/index?id=' + encodeURIComponent(event.currentTarget.dataset.id) }); },
    retry() { return this.state.load(this.state.snapshot().items.length === 0); },
    imageError(event) { const index = event.currentTarget.dataset.index; const field = 'image_url'; this.setData({ ['items[' + index + '].'+field]: null }); }
  };
}
function createDetailPage(kind, wxApi) {
  return {
    data: { kind, detail: null, loading: true, error: '', activeForm: 0, selectedForm: null },
    onLoad(options) { this.wxApi = wxApi || wx; this.api = runtimeApi(this.wxApi); this.id = options.id; return this.load(); },
    async load() { this.setData({ loading: true, error: '' }); try { const detail = await this.api.detail(kind, this.id); detail.title = detail.name_display || detail.name_original || detail.name_zh; detail.image_url = this.api.imageUrl(detail); detail.variants = (detail.variants || []).map(v => ({ ...v, image_url: this.api.imageUrl(v) })); detail.numberLabel = kind === 'pokemon' ? '#' + String(detail.dex).padStart(4, '0') : 'No. ' + detail.number; if (kind === 'pokemon') this.setData({ extras: prepareExtra(detail.extra, this.api) }); this.baseImage = detail.image_url; this.setData({ detail, activeForm: 0, selectedForm: detail.forms && detail.forms[0] || null }); } catch (error) { this.setData({ error: error.message }); } finally { this.setData({ loading: false }); } },
    chooseForm(event) { const index = Number(event.currentTarget.dataset.index), form = this.data.detail.forms[index]; this.setData({ activeForm: index, selectedForm: form, 'detail.image_url': index ? this.api.imageUrl(form) : this.baseImage || null }); },
    evolve(event) { const target = event.currentTarget.dataset.dex; if (event.currentTarget.dataset.available) this.wxApi.navigateTo({ url: '/pages/pokemon-detail/index?id=' + target }); },
    previewImage(event) {
      if (kind !== 'tomica' || !this.data.detail) return;
      const detail = this.data.detail, current = event.currentTarget.dataset.url;
      const urls = [...new Set([detail.image_url, ...(detail.variants || []).map(v => v.image_url)].filter(Boolean))];
      if (urls.includes(current)) this.wxApi.previewImage({ current, urls });
    },
    chooseExtra(event) {
      const key = event.currentTarget.dataset.key, index = Number(event.detail.value), extras = this.data.extras;
      if (key === 'acquisition') { this.setData({ 'extras.locations': index ? extras.acquisition.filter(r => r.games === extras.acquisitionGames[index]) : extras.acquisition }); return; }
      const names = { stats: 'statGroups', matchup: 'matchupGroups', shiny: 'shinyPairs' };
      if (names[key]) { this.setData({ ['extras.' + key]: extras[names[key]][index] }); return; }
      if (key === 'learn' || key === 'machine') this.setData({ ['extras.' + key + 'Index']: index, ['extras.' + key]: filterMoves(extras, key, index, extras[key + 'Query']) });
    },
    searchMoves(event) { const key = event.currentTarget.dataset.key, query = event.detail.value, extras = this.data.extras; this.setData({ ['extras.' + key + 'Query']: query, ['extras.' + key]: filterMoves(extras, key, extras[key + 'Index'], query) }); },
    imageError() { this.setData({ ['detail.image_url']: null }); },
    retry() { return this.load(); }
  };
}
module.exports = { createListPage, createDetailPage };
