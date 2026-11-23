// Public FatFish v1.18.2 send view, MIT, Vegra85/fatfish-bot.
VIEWS.send = async main => {
  main.innerHTML = `<h1>代发消息</h1><p class="sub">用她的号发一句话 / 一条语音 / 一张表情包（不受频率限制）</p>
    <div class="cols"><div class="card">
      <div class="row" style="margin-bottom:10px"><label><input type="radio" name="sc" value="group" checked> 群</label><label><input type="radio" name="sc" value="private"> 私聊</label>
        <select id="tgt" style="flex:1;min-width:200px"></select></div>
      <div class="row" style="margin-bottom:10px"><span class="small muted">或者直接填号：</span><input type="text" id="tgt2" placeholder="群号 / QQ 号" style="width:160px"></div>
      <textarea id="txt" rows="4" placeholder="要说的话（可以只发表情包）"></textarea>
      <div class="row" style="margin:10px 0"><label class="row"><span class="sw"><input type="checkbox" id="asvoice"><span></span></span>用语音发</label>
        <select id="emo"><option value="">自动语气</option>${["开心", "撒娇", "难过", "生气", "惊讶", "平静", "困"].map(x => `<option>${x}</option>`).join("")}</select>
        <label class="row"><span class="sw"><input type="checkbox" id="remember" checked><span></span></span>记进她的聊天记录</label></div>
      <div class="row"><span id="picked" class="muted small">没选表情包</span><span class="spacer"></span><button class="btn primary" id="go">发送</button></div>
      <h2 style="margin-top:16px">这个聊天最近说了什么</h2><div class="chat" id="ctx"><div class="muted">选个群或者人</div></div>
    </div><div class="card"><div class="row" style="margin-bottom:8px"><h2 style="margin:0">挑表情包</h2><span class="spacer"></span><input type="text" id="sq" placeholder="搜：开心 / 饿 / 拿捏…" style="width:180px"></div><div class="stk list" id="sg"></div></div></div>`;
  const P = await api("/api/people"); let picked = "";
  const fill = () => {
    const sc = document.querySelector("[name=sc]:checked").value;
    const opts = sc === "group" ? P.groups.map(g => [g.id, (g.name || "群") + " · " + g.id]) : P.friends.map(f => [f.id, (f.name || "QQ") + " · " + f.id]);
    $("#tgt").innerHTML = opts.map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join("") || "<option value=''>（没有）</option>";
    loadCtx();
  };
  const target = () => ($("#tgt2").value.trim() || $("#tgt").value);
  const loadCtx = async () => {
    const sc = document.querySelector("[name=sc]:checked").value, t = target(); if (!t) return;
    const r = await api(`/api/memory/detail?key=${sc}_${t}&n=15`);
    $("#ctx").innerHTML = r.ok ? r.data.history.map(h => `<div class="${h.role === "assistant" ? "me" : ""}"><span class="muted small">${hm(h.ts)}</span> <b>${esc(h.role === "assistant" ? "她" : h.name)}</b>：${esc(h.text)}</div>`).join("") : '<div class="muted">这个聊天还没有记录</div>';
    $("#ctx").scrollTop = 1e6;
  };
  document.querySelectorAll("[name=sc]").forEach(x => x.onchange = fill);
  $("#tgt").onchange = loadCtx; $("#tgt2").onchange = loadCtx;
  fill();
  const S = await stickers();
  const showStk = () => {
    const q = $("#sq").value.trim();
    const list = S.filter(s => !s.off && (!q || (s.name + s.emo + s.scene + s.text).includes(q))).slice(0, 80);
    $("#sg").innerHTML = list.map(s => `<div class="s ${s.name === picked ? "pick" : ""}" data-n="${esc(s.name)}" title="${esc(s.scene)}"><img loading="lazy" src="/sticker?f=${encodeURIComponent(s.file)}"><div class="n">${esc(s.name)}</div><div class="e">${esc(s.emo)}</div></div>`).join("") || '<div class="empty">没搜到</div>';
  };
  $("#sq").oninput = showStk; showStk();
  $("#sg").onclick = e => { const el = e.target.closest(".s"); if (!el) return; picked = picked === el.dataset.n ? "" : el.dataset.n; $("#picked").textContent = picked ? "表情包：" + picked : "没选表情包"; showStk(); };
  $("#go").onclick = async () => {
    const body = {scene: document.querySelector("[name=sc]:checked").value, target: target(), text: $("#txt").value, sticker: picked,
      voice: $("#asvoice").checked, emo: $("#emo").value, remember: $("#remember").checked};
    if (!body.target) { toast("选一个发给谁", true); return; }
    $("#go").setAttribute("disabled", ""); const r = await api("/api/send", body); $("#go").removeAttribute("disabled");
    toast(r.ok ? "发出去了" + (r.error ? "（" + r.error + "）" : "") : (r.error || "没发出去"), !r.ok);
    if (r.ok) { $("#txt").value = ""; picked = ""; $("#picked").textContent = "没选表情包"; showStk(); setTimeout(loadCtx, 800); }
  };
};
VIEWS.stickers = async main => {
  STK = null; const S = await stickers();
  const emos = [...new Set(S.map(s => s.emo).filter(Boolean))];
  main.innerHTML = `<h1>表情包</h1><p class="sub">一共 ${S.length} 张（关掉的 ${S.filter(s => s.off).length} 张）。点一下开关 关掉的她就不会发了（马上生效）</p>
    <div class="card"><div class="row" style="margin-bottom:10px"><input type="text" id="q" placeholder="搜名字 / 场景 / 图上的字" style="width:240px"><select id="emo"><option value="">全部情绪</option>${emos.map(e => `<option>${esc(e)}</option>`).join("")}</select>
    <select id="st"><option value="">全部</option><option value="on">开着的</option><option value="off">关掉的</option></select><span class="spacer"></span><span class="small muted" id="cnt"></span></div><div class="stk" id="g"></div></div>`;
  const draw = () => {
    const q = $("#q").value.trim(), em = $("#emo").value, st = $("#st").value;
    const L = S.filter(s => (!q || (s.name + s.scene + s.text).includes(q)) && (!em || s.emo === em) && (!st || (st === "off") === s.off));
    $("#cnt").textContent = `${L.length} 张` + (L.length > 200 ? "（只显示前 200 张 搜一下更快）" : "");
    $("#g").innerHTML = L.slice(0, 200).map(s => `<div class="s ${s.off ? "off" : ""}" data-n="${esc(s.name)}" title="${esc(s.scene)}${s.note ? "\n⚠ " + esc(s.note) : ""}"><img loading="lazy" src="/sticker?f=${encodeURIComponent(s.file)}"><div class="n">${esc(s.name)}</div><div class="e">${esc(s.emo)}${s.off ? " · 关" : ""}</div></div>`).join("") || '<div class="empty">没有</div>';
  };
  ["q", "emo", "st"].forEach(id => $("#" + id).oninput = draw); draw();
  $("#g").onclick = async e => {
    const el = e.target.closest(".s"); if (!el) return; const s = S.find(x => x.name === el.dataset.n);
    const r = await api("/api/stickers/toggle", {name: s.name, off: !s.off}); if (r.ok) { s.off = !s.off; draw(); toast(s.off ? `关掉了「${s.name}」` : `打开了「${s.name}」`); } else toast("没改成", true);
  };
};