"""Small UI adaptations applied to public HTML without modifying upstream files."""


def enhance_sticker_ui(html):
    # Selection must retain the actual img nodes. Rebuilding a no-store image grid
    # makes mobile browsers decode/download all pictures again on every tap.
    sync = '$("#sg").querySelectorAll(".s").forEach(card => card.classList.toggle("pick", card.dataset.n === picked));'
    html = html.replace(
        '$("#picked").textContent = picked ? "表情包：" + picked : "没选表情包"; showStk();',
        '$("#picked").textContent = picked ? "表情包：" + picked : "没选表情包"; ' + sync)
    html = html.replace(
        '$("#picked").textContent = "没选表情包"; showStk(); setTimeout(loadCtx, 800);',
        '$("#picked").textContent = "没选表情包"; ' + sync + ' setTimeout(loadCtx, 800);')
    old = '''    const r = await api("/api/stickers/toggle", {name: s.name, off: !s.off}); if (r.ok) { s.off = !s.off; draw(); toast(s.off ? `关掉了「${s.name}」` : `打开了「${s.name}」`); } else toast("没改成", true);'''
    new = '''    if (el.dataset.pending) return;
    el.dataset.pending = "1";
    try {
      const r = await api("/api/stickers/toggle", {name: s.name, off: !s.off});
      if (r.ok) {
        s.off = !s.off; el.classList.toggle("off", s.off);
        el.querySelector(".e").textContent = s.emo + (s.off ? " · 关" : "");
        const q = $("#q").value.trim(), em = $("#emo").value, st = $("#st").value;
        if (st && (st === "off") !== s.off) el.remove();
        const count = S.filter(x => (!q || (x.name + x.scene + x.text).includes(q)) && (!em || x.emo === em) && (!st || (st === "off") === x.off)).length;
        $("#cnt").textContent = `${count} 张` + (count > 200 ? "（只显示前 200 张 搜一下更快）" : "");
        toast(s.off ? `关掉了「${s.name}」` : `打开了「${s.name}」`);
      } else toast(r.error || "没改成", true);
    } catch (error) { toast("没改成，请稍后重试", true); }
    finally { delete el.dataset.pending; }'''
    html=html.replace(old,new)
    html=html.replace('const st = s => s.ok === true ?', 'const st = (s,ready=false) => s.ok === true ?')
    html=html.replace("'<span class=\"badge good\">能用</span>' : s.ok === false ? '<span class=\"badge bad\">用不了</span>'", "'<span class=\"badge good\">'+(ready?'已就绪':'本次通过')+'</span>' : s.ok === false ? '<span class=\"badge bad\">'+(ready?'暂不可用':'本次未通过')+'</span>'")
    html=html.replace(": st(x)}<span class=\"muted\">", ": st(x,true)}<span class=\"muted\">")
    return html
