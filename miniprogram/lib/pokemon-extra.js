function prepareExtra(extra, api) {
  const data = extra || {};
  const statGroups = (data.base_stats || []).map(g => ({ ...g, stats: g.stats.map(s => ({ ...s, width: Math.min(100, s.value / 255 * 100) })) }));
  const groups = (data.movesets || []).map(g => ({ ...g, moves: g.moves.map((move, index) => ({ ...move, rowKey: String(index) })) }));
  const learnGroups = groups.filter(g => g.kind === 'learn');
  const machineGroups = groups.filter(g => g.kind === 'machine');
  const label = g => g.game + ' · ' + g.form + ' · ' + g.method;
  const acquisition = (data.acquisition || []).map((row, index) => ({ ...row, rowKey: String(index) }));
  const shinyPairs = (data.shiny_pairs || []).map(pair => ({ ...pair, normal_url: api.imageUrl(pair.normal), shiny_url: api.imageUrl(pair.shiny) }));
  return {
    statGroups, statLabels: statGroups.map(g => g.label), stats: statGroups[0] || null,
    matchupGroups: data.matchups || [], matchupLabels: (data.matchups || []).map(g => g.label), matchup: (data.matchups || [])[0] || null,
    learnGroups, learnLabels: learnGroups.map(label), learn: learnGroups[0] || null,
    machineGroups, machineLabels: machineGroups.map(label), machine: machineGroups[0] || null,
    acquisition, acquisitionGames: ['全部版本', ...new Set(acquisition.map(r => r.games))], locations: acquisition,
    shinyPairs, shinyLabels: shinyPairs.map(p => p.game + ' · ' + p.form), shiny: shinyPairs[0] || null,
    learnIndex: 0, machineIndex: 0, learnQuery: '', machineQuery: ''
  };
}

function filterMoves(extras, kind, index, query) {
  const group = extras[kind + 'Groups'][index];
  if (!group) return null;
  const q = query.toLowerCase();
  return { ...group, moves: group.moves.filter(m => [m.name, m.type, m.category, m.learn].join(' ').toLowerCase().includes(q)) };
}

module.exports = { prepareExtra, filterMoves };
