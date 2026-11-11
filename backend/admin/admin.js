'use strict';
let token = '';
const $ = id => document.getElementById(id);
async function adminRequest(path, options = {}) {
  const response = await fetch('/api/admin' + path, { ...options, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token } });
  const value = await response.json();
  if (!response.ok) { if (response.status === 401) token = ''; throw new Error(value.message || '请求失败'); }
  return value;
}
function renderRows(target, values, retry = false) {
  const root = $(target); root.replaceChildren();
  if (!values.length) { root.textContent = '暂无记录'; return; }
  for (const value of values) {
    const div = document.createElement('div'); div.className = 'row';
    const label = document.createElement('div'); label.textContent = JSON.stringify(value, null, 2); div.append(label);
    if (retry && ['failed', 'partial', 'limited'].includes(value.status)) {
      const button = document.createElement('button'); button.textContent = '重试失败页面'; button.onclick = () => perform(button, () => retryRun(value.id)); div.append(button);
    }
    root.append(div);
  }
}
async function loadRuns() { renderRows('runs', (await adminRequest('/runs')).items, true); }
async function loadIssues() { renderRows('issues', (await adminRequest('/issues')).items); }
async function enqueueSync() { await adminRequest('/sync', { method: 'POST', body: JSON.stringify({ source: $('source').value, mode: $('mode').value }) }); await loadRuns(); }
async function retryRun(id) { await adminRequest('/runs/' + encodeURIComponent(id) + '/retry', { method: 'POST' }); await loadRuns(); }
async function saveOverride() {
  let value = $('value').value; try { value = JSON.parse(value); } catch (_) { /* 普通文本保持字符串 */ }
  const result = await adminRequest('/overrides', { method: 'PATCH', body: JSON.stringify({ kind: $('kind').value, entity_key: $('entity').value, field: $('field').value, value }) });
  $('result').textContent = JSON.stringify(result, null, 2);
}
async function perform(button, operation) { button.disabled = true; $('message').textContent = ''; try { await operation(); $('message').textContent = '操作完成'; } catch (error) { $('message').textContent = error.message; } finally { button.disabled = false; } }
$('connect').onclick = () => { token = $('token').value; $('token').value = ''; perform($('connect'), async () => { await loadRuns(); await loadIssues(); }); };
$('sync').onclick = () => perform($('sync'), enqueueSync);
$('save').onclick = () => perform($('save'), saveOverride);
