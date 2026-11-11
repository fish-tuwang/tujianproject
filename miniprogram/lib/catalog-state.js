function createCatalogState({ api, kind, onChange = () => {} }) {
  let value = { items: [], filters: {}, cursor: null, loading: false, error: '', hasMore: true, scrollTop: 0 };
  let sequence = 0, request = null;
  const emit = () => onChange({ ...value, items: [...value.items], filters: { ...value.filters } });
  async function load(reset = false) {
    if (value.loading && !reset) return;
    if (!reset && !value.hasMore) return;
    if (reset) { sequence++; if (request && request.abort) request.abort(); value.items = []; value.cursor = null; value.hasMore = true; }
    const current = sequence;
    value.loading = true; value.error = ''; emit();
    try {
      request = api.list(kind, { ...value.filters, limit: 20, cursor: reset ? null : value.cursor });
      const response = await request;
      if (current !== sequence) return;
      const items = [...value.items, ...response.items]; const unique = new Map(items.map(item => [kind === 'pokemon' ? item.dex : item.id, item]));
      value.items = [...unique.values()]; value.cursor = response.next_cursor; value.hasMore = Boolean(response.next_cursor);
    } catch (error) {
      if (current !== sequence || error.code === 'ABORTED') return;
      if (error.status === 409 && !reset) { value.loading = false; return load(true); }
      value.error = error.message || '暂时无法加载';
    } finally { if (current === sequence) { value.loading = false; emit(); } }
  }
  return { load, setFilters(filters) { value.filters = { ...filters }; return load(true); }, setScroll(top) { value.scrollTop = top; }, snapshot() { return { ...value, items: [...value.items], filters: { ...value.filters } }; }, restore(saved) { value = { ...saved, loading: false }; emit(); }, dispose() { sequence++; if (request && request.abort) request.abort(); value.loading = false; } };
}
module.exports = { createCatalogState };
