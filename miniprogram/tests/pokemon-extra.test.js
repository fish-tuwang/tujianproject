const test = require('node:test');
const assert = require('node:assert/strict');
const { prepareExtra, filterMoves } = require('../lib/pokemon-extra');

test('extra detail maps original shiny image URLs and preserves game groups', () => {
  const data = prepareExtra({
    base_stats: [{ label: '通常形态', stats: [{ name: 'HP', value: 45 }] }],
    movesets: [{ game: '朱／紫', kind: 'learn', form: '通常', method: '升级', moves: [{ name: '火花', type: '火', learn: '1' }, { name: '摇尾巴', type: '一般', learn: '4' }] }, { game: 'Z-A', kind: 'machine', moves: [{ name: '剧毒', learn: '学习器007' }] }],
    shiny_pairs: [{ form: '阿罗拉', game: 'HOME', normal: { preview_image_url: '/normal' }, shiny: { preview_image_url: '/shiny' } }]
  }, { imageUrl: value => value.preview_image_url });
  assert.equal(data.shiny.normal_url, '/normal');
  assert.equal(data.shiny.shiny_url, '/shiny');
  assert.equal(data.learnGroups.length, 1);
  assert.equal(data.machineGroups.length, 1);
  assert.deepEqual(filterMoves(data, 'learn', 0, '火').moves.map(m => m.name), ['火花']);
  assert.equal(data.learnGroups[0].moves.length, 2);
  assert.ok(data.stats.stats[0].width > 0);
});

test('missing extra data stays empty', () => {
  const data = prepareExtra(null, { imageUrl() { throw Error('unexpected'); } });
  assert.equal(data.stats, null);
  assert.equal(data.shiny, null);
  assert.deepEqual(data.acquisitionGames, ['全部版本']);
});
