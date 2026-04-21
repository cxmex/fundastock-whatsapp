"""Inline CSS and JS for the dashboard. No external dependencies except Chart.js CDN."""

DASHBOARD_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0b141a; --bg2: #202c33; --bg3: #1a262d; --bg4: #2a3942;
  --fg: #e9edef; --fg2: #8696a0; --accent: #00a884; --accent2: #00c49a;
  --user: #005c4b; --link: #53bdeb;
  --red: #e74c3c; --orange: #f39c12; --blue: #3498db; --green: #27ae60;
}
html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: var(--bg); color: var(--fg); font-size: 14px; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Layout */
.app { display: flex; flex-direction: column; height: 100vh; }
.topbar { background: var(--bg3); padding: 10px 16px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--bg4); flex-shrink: 0; }
.topbar h1 { font-size: 16px; font-weight: 600; flex: 1; }
.topbar .tabs { display: flex; gap: 4px; }
.topbar .tab { padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; background: var(--bg4); border: none; color: var(--fg2); }
.topbar .tab.active { background: var(--accent); color: #fff; }
.topbar .tab:hover { background: var(--bg2); }
.topbar .tab.active:hover { background: var(--accent2); }
.main { display: flex; flex: 1; overflow: hidden; }

/* Sidebar */
.sidebar { width: 320px; background: var(--bg3); border-right: 1px solid var(--bg4); display: flex; flex-direction: column; flex-shrink: 0; }
.sidebar .filters { padding: 10px; display: flex; flex-direction: column; gap: 6px; border-bottom: 1px solid var(--bg4); }
.sidebar .filters input, .sidebar .filters select { background: var(--bg4); border: 1px solid transparent; color: var(--fg); padding: 6px 8px; border-radius: 4px; font-size: 12px; width: 100%; }
.sidebar .filters .row { display: flex; gap: 6px; }
.sidebar .filters .row > * { flex: 1; }
.sidebar .filters .checks { display: flex; gap: 8px; flex-wrap: wrap; }
.sidebar .filters label { font-size: 11px; color: var(--fg2); display: flex; align-items: center; gap: 3px; cursor: pointer; }
.convlist { flex: 1; overflow-y: auto; }
.convitem { padding: 10px 12px; border-bottom: 1px solid var(--bg4); cursor: pointer; }
.convitem:hover { background: var(--bg2); }
.convitem.active { background: var(--bg4); border-left: 3px solid var(--accent); }
.convitem .phone { font-weight: 600; font-size: 13px; }
.convitem .meta { font-size: 11px; color: var(--fg2); margin-top: 2px; display: flex; gap: 6px; align-items: center; }
.badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }
.badge.retail { background: var(--blue); color: #fff; }
.badge.wholesale { background: var(--orange); color: #000; }
.badge.unknown { background: var(--bg4); color: var(--fg2); }
.badge.greeting, .badge.qualifying { background: var(--fg2); color: var(--bg); }
.badge.product_selection { background: var(--blue); color: #fff; }
.badge.closing { background: var(--accent); color: #fff; }
.badge.post_sale, .badge.completed { background: var(--green); color: #fff; }
.badge.escalated { background: var(--red); color: #fff; }
.badge.paid { background: var(--green); color: #fff; }
.badge.pending { background: var(--orange); color: #000; }
.badge.payment_claimed { background: var(--blue); color: #fff; }
.loadmore { text-align: center; padding: 10px; }
.loadmore button { background: var(--bg4); color: var(--fg2); border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 12px; }

/* Content */
.content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.content .empty { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--fg2); font-size: 15px; }
.convheader { padding: 12px 16px; background: var(--bg3); border-bottom: 1px solid var(--bg4); flex-shrink: 0; }
.convheader .phone-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.convheader .phone-row .num { font-size: 16px; font-weight: 600; }
.convheader .details { font-size: 12px; color: var(--fg2); display: flex; gap: 12px; flex-wrap: wrap; }
.convheader .actions { display: flex; gap: 6px; margin-top: 8px; }
.btn { background: var(--accent); color: #fff; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.btn:hover { background: var(--accent2); }
.btn.danger { background: var(--red); }
.btn.secondary { background: var(--bg4); color: var(--fg2); }
.btn.small { padding: 4px 10px; font-size: 11px; }

/* Transcript */
.transcript { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 4px; }
.t-msg { max-width: 70%; padding: 8px 12px; border-radius: 8px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; position: relative; }
.t-msg.user { background: var(--user); align-self: flex-end; }
.t-msg.assistant { background: var(--bg2); align-self: flex-start; }
.t-msg .ts { font-size: 10px; color: var(--fg2); margin-top: 4px; }
.t-msg.tool { background: var(--bg3); align-self: flex-start; font-size: 12px; color: var(--fg2); border: 1px dashed var(--bg4); max-width: 80%; }
.t-msg.tool .tool-name { color: var(--accent); font-weight: 600; }
.t-msg.tool .tool-result { cursor: pointer; }
.t-msg.tool .tool-result-full { display: none; margin-top: 6px; font-size: 11px; white-space: pre-wrap; max-height: 200px; overflow-y: auto; background: var(--bg); padding: 6px; border-radius: 4px; }
.t-msg.tool .tool-result-full.open { display: block; }
.stage-divider { text-align: center; color: var(--fg2); font-size: 11px; padding: 8px 0; }
.stage-divider span { background: var(--bg); padding: 0 8px; }
.t-msg .ann-dot { position: absolute; top: 4px; right: 4px; width: 8px; height: 8px; border-radius: 50%; background: var(--red); cursor: pointer; }
.t-msg.selected { outline: 2px solid var(--accent); }

/* Annotation panel */
.annpanel { background: var(--bg3); border-top: 1px solid var(--bg4); padding: 12px 16px; flex-shrink: 0; }
.annpanel .quicktags { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
.annpanel .quicktags button { padding: 4px 10px; border-radius: 4px; border: 1px solid var(--bg4); background: var(--bg2); color: var(--fg); cursor: pointer; font-size: 12px; }
.annpanel .quicktags button:hover, .annpanel .quicktags button.active { border-color: var(--accent); background: var(--bg4); }
.annpanel .fields { display: flex; gap: 8px; margin-bottom: 8px; }
.annpanel .fields select { background: var(--bg4); color: var(--fg); border: 1px solid transparent; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
.annpanel textarea { width: 100%; background: var(--bg4); color: var(--fg); border: 1px solid transparent; padding: 6px 8px; border-radius: 4px; font-size: 12px; resize: vertical; min-height: 36px; }
.annpanel .ann-row { display: flex; gap: 8px; margin-bottom: 6px; }
.annpanel .ann-row textarea { flex: 1; }
.annpanel .existing { margin-top: 8px; max-height: 120px; overflow-y: auto; }
.annpanel .existing .ann-item { font-size: 11px; color: var(--fg2); padding: 4px 0; border-bottom: 1px solid var(--bg4); }
.annpanel .existing .ann-item .cat { font-weight: 600; }

/* Send as human */
.sendbar { display: flex; gap: 8px; padding: 8px 16px; background: var(--bg3); border-top: 1px solid var(--bg4); }
.sendbar input { flex: 1; background: var(--bg4); border: none; color: var(--fg); padding: 8px; border-radius: 6px; font-size: 13px; }

/* Metrics */
.metrics { padding: 20px; overflow-y: auto; }
.metrics h2 { font-size: 15px; margin-bottom: 12px; color: var(--accent); }
.funnel { display: flex; gap: 4px; margin-bottom: 24px; flex-wrap: wrap; }
.funnel .step { background: var(--bg2); padding: 12px 16px; border-radius: 8px; text-align: center; min-width: 110px; }
.funnel .step .num { font-size: 24px; font-weight: 700; }
.funnel .step .label { font-size: 11px; color: var(--fg2); margin-top: 2px; }
.funnel .arrow { display: flex; align-items: center; color: var(--fg2); font-size: 12px; flex-direction: column; justify-content: center; }
.segment-cols { display: flex; gap: 16px; margin-bottom: 24px; }
.segment-cols .col { flex: 1; background: var(--bg2); padding: 16px; border-radius: 8px; }
.segment-cols .col h3 { font-size: 13px; margin-bottom: 8px; }
.campaign-table { width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 12px; }
.campaign-table th { text-align: left; padding: 8px; background: var(--bg3); color: var(--fg2); cursor: pointer; user-select: none; }
.campaign-table th:hover { color: var(--fg); }
.campaign-table td { padding: 8px; border-bottom: 1px solid var(--bg4); }
.campaign-table tr.good { background: rgba(39,174,96,0.1); }
.campaign-table tr.bad { background: rgba(231,76,60,0.1); }
.chart-container { background: var(--bg2); padding: 16px; border-radius: 8px; margin-bottom: 24px; max-height: 300px; }
.heatmap { display: grid; grid-template-columns: 40px repeat(24, 1fr); gap: 2px; font-size: 10px; margin-bottom: 24px; }
.heatmap .cell { padding: 4px; text-align: center; border-radius: 2px; min-height: 20px; }
.heatmap .header { color: var(--fg2); font-weight: 600; }
.dropoff-chart { display: flex; gap: 4px; align-items: flex-end; height: 120px; margin-bottom: 24px; }
.dropoff-chart .bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
.dropoff-chart .bar { background: var(--accent); border-radius: 3px 3px 0 0; width: 100%; max-width: 60px; }
.dropoff-chart .bar-label { font-size: 10px; color: var(--fg2); margin-top: 4px; text-align: center; }
.dropoff-chart .bar-count { font-size: 11px; font-weight: 600; margin-bottom: 2px; }

/* Reports */
.reports { padding: 20px; overflow-y: auto; }
.report-card { background: var(--bg2); padding: 16px; border-radius: 8px; margin-bottom: 16px; }
.report-card h3 { font-size: 14px; margin-bottom: 8px; }
.report-card .md { font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.report-card .md h2 { font-size: 14px; color: var(--accent); margin: 12px 0 6px; }
.report-card .md h3 { font-size: 13px; color: var(--fg); }

/* Ad Spend */
.adspend { padding: 20px; overflow-y: auto; }
.adspend table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 16px; }
.adspend th { text-align: left; padding: 8px; background: var(--bg3); color: var(--fg2); }
.adspend td { padding: 8px; border-bottom: 1px solid var(--bg4); }
.adspend input, .adspend select { background: var(--bg4); border: 1px solid transparent; color: var(--fg); padding: 4px 8px; border-radius: 4px; font-size: 12px; }
.addrow { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }

/* Login */
.login-page { display: flex; align-items: center; justify-content: center; height: 100vh; }
.login-box { background: var(--bg2); padding: 32px; border-radius: 12px; width: 300px; text-align: center; }
.login-box h2 { margin-bottom: 16px; }
.login-box input { width: 100%; padding: 10px; background: var(--bg4); border: none; color: var(--fg); border-radius: 6px; font-size: 14px; margin-bottom: 12px; }
.login-box button { width: 100%; }
.login-box .error { color: var(--red); font-size: 12px; margin-bottom: 8px; }

/* Keyboard shortcut help */
.kbd-help { position: fixed; bottom: 12px; right: 12px; background: var(--bg2); padding: 8px 12px; border-radius: 6px; font-size: 11px; color: var(--fg2); z-index: 100; display: none; }
.kbd-help.show { display: block; }
.kbd-help kbd { background: var(--bg4); padding: 1px 5px; border-radius: 3px; font-family: monospace; }

/* Mobile */
@media (max-width: 768px) {
  .sidebar { width: 100%; border-right: none; border-bottom: 1px solid var(--bg4); max-height: 40vh; }
  .main { flex-direction: column; }
  .main.conv-open .sidebar { display: none; }
  .main.conv-open .content { display: flex; }
  .content .back-btn { display: block !important; }
  .convheader .details { flex-direction: column; gap: 4px; }
  .funnel { flex-direction: column; }
  .funnel .arrow { flex-direction: row; }
  .segment-cols { flex-direction: column; }
}
@media (min-width: 769px) {
  .content .back-btn { display: none !important; }
}
"""

DASHBOARD_JS = """
let state = {
  view: 'conversations',
  conversations: [],
  selectedPhone: null,
  transcript: [],
  annotations: [],
  filters: { date_from: '', date_to: '', lead_type: 'all', stage: 'all', campaign: 'all', escalated: false, takeover: false, annotated: false, search: '' },
  offset: 0,
  totalConvos: 0,
  selectedTurnId: null,
  annCategory: null,
};

// ── API helpers ──
async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: 'same-origin', ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) }
  });
  if (res.status === 401 || res.redirected) { window.location = '/admin/login'; return null; }
  return res.json();
}

// ── Init ──
async function init() {
  setDefaultDates();
  await loadCampaigns();
  await loadConversations();
  bindKeys();
  bindFilters();
}

function setDefaultDates() {
  const now = new Date();
  const from = new Date(now - 7*86400000);
  document.getElementById('f-from').value = from.toISOString().slice(0,10);
  document.getElementById('f-to').value = now.toISOString().slice(0,10);
  state.filters.date_from = document.getElementById('f-from').value;
  state.filters.date_to = document.getElementById('f-to').value;
}

function bindFilters() {
  document.querySelectorAll('.filters input, .filters select').forEach(el => {
    el.addEventListener('change', () => { state.offset = 0; loadConversations(); });
  });
  let searchTimer;
  document.getElementById('f-search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.offset = 0; loadConversations(); }, 400);
  });
}

function gatherFilters() {
  state.filters.date_from = document.getElementById('f-from').value;
  state.filters.date_to = document.getElementById('f-to').value;
  state.filters.lead_type = document.getElementById('f-type').value;
  state.filters.stage = document.getElementById('f-stage').value;
  state.filters.campaign = document.getElementById('f-campaign').value;
  state.filters.escalated = document.getElementById('f-escalated').checked;
  state.filters.takeover = document.getElementById('f-takeover').checked;
  state.filters.annotated = document.getElementById('f-annotated').checked;
  state.filters.search = document.getElementById('f-search').value;
}

// ── Load conversations ──
async function loadCampaigns() {
  const data = await api('/admin/api/campaigns');
  if (!data) return;
  const sel = document.getElementById('f-campaign');
  sel.innerHTML = '<option value="all">All campaigns</option>';
  data.forEach(c => { sel.innerHTML += '<option value="'+esc(c)+'">'+esc(c)+'</option>'; });
}

async function loadConversations(append = false) {
  gatherFilters();
  const f = state.filters;
  const params = new URLSearchParams({
    offset: append ? state.offset : 0,
    limit: 50,
    ...(f.date_from && {date_from: f.date_from}),
    ...(f.date_to && {date_to: f.date_to}),
    ...(f.lead_type !== 'all' && {lead_type: f.lead_type}),
    ...(f.stage !== 'all' && {stage: f.stage}),
    ...(f.campaign !== 'all' && {campaign_id: f.campaign}),
    ...(f.escalated && {escalated: '1'}),
    ...(f.takeover && {takeover: '1'}),
    ...(f.annotated && {annotated: '1'}),
    ...(f.search && {search: f.search}),
  });
  const data = await api('/admin/api/conversations?' + params);
  if (!data) return;

  if (!append) { state.conversations = []; state.offset = 0; }
  state.conversations.push(...data.rows);
  state.totalConvos = data.total;
  state.offset = state.conversations.length;
  renderConvList();
}

function loadMore() { loadConversations(true); }

// ── Render conversation list ──
function renderConvList() {
  const el = document.getElementById('convlist');
  el.innerHTML = state.conversations.map(c => {
    const last4 = c.phone_number.slice(-4);
    const ago = timeAgo(c.last_message_at);
    const orders = (c._orders || []);
    const orderBadge = orders.length ? orders.map(o =>
      '<span class="badge '+esc(o.payment_status)+'">'+esc(o.payment_status)+'</span>'
    ).join(' ') : '';
    const active = c.phone_number === state.selectedPhone ? ' active' : '';
    return '<div class="convitem'+active+'" onclick="selectConv(\''+esc(c.phone_number)+'\')" title="'+esc(c.phone_number)+'">'+
      '<div class="phone">...'+esc(last4)+' '+
      '<span class="badge '+esc(c.lead_type)+'">'+esc(c.lead_type)+'</span> '+
      '<span class="badge '+esc(c.stage)+'">'+esc(c.stage)+'</span>'+
      (c.human_takeover ? ' <span class="badge escalated">HT</span>' : '')+
      '</div>'+
      '<div class="meta">'+esc(ago)+' '+orderBadge+
      (c.lead_source ? ' <span style="color:var(--fg2)">'+esc(c.lead_source)+'</span>' : '')+
      '</div></div>';
  }).join('');

  const lm = document.getElementById('loadmore');
  lm.style.display = state.conversations.length < state.totalConvos ? 'block' : 'none';
}

// ── Select and load transcript ──
async function selectConv(phone) {
  state.selectedPhone = phone;
  renderConvList();
  document.querySelector('.main').classList.add('conv-open');

  const [conv, transcript, annotations, orders] = await Promise.all([
    api('/admin/api/conversation/' + phone),
    api('/admin/api/transcript/' + phone),
    api('/admin/api/annotations/' + phone),
    api('/admin/api/orders/' + phone),
  ]);

  state.transcript = transcript || [];
  state.annotations = annotations || [];
  renderConvHeader(conv, orders || []);
  renderTranscript();
  renderAnnotations();
  showSendBar(conv);
}

function goBack() {
  state.selectedPhone = null;
  document.querySelector('.main').classList.remove('conv-open');
  document.getElementById('conv-content').innerHTML = '<div class="empty">Select a conversation</div>';
}

function renderConvHeader(conv, orders) {
  if (!conv) return;
  const el = document.getElementById('conv-header');
  const waLink = 'https://wa.me/' + conv.phone_number;
  el.innerHTML =
    '<div class="phone-row">'+
    '<button class="btn small secondary back-btn" onclick="goBack()">&larr; Back</button>'+
    '<span class="num">'+esc(conv.phone_number)+'</span>'+
    '<a href="'+esc(waLink)+'" target="_blank" style="font-size:12px">Abrir WhatsApp</a>'+
    '</div>'+
    '<div class="details">'+
    (conv.lead_source ? '<span>'+esc(conv.lead_source)+'</span>' : '')+
    (conv.campaign_id ? '<span>Camp: '+esc(conv.campaign_id)+'</span>' : '')+
    (conv.ad_headline ? '<span>"'+esc(conv.ad_headline)+'"</span>' : '')+
    '<span class="badge '+esc(conv.lead_type)+'">'+esc(conv.lead_type)+'</span>'+
    '<span class="badge '+esc(conv.stage)+'">'+esc(conv.stage)+'</span>'+
    '</div>'+
    (orders.length ? '<div class="details" style="margin-top:4px">'+orders.map(o =>
      'Order #'+o.id+' <span class="badge '+esc(o.payment_status)+'">'+esc(o.payment_status)+'</span> $'+(Number(o.total)||0).toFixed(2)
    ).join(' | ')+'</div>' : '')+
    '<div class="actions">'+
    (conv.human_takeover ?
      '<button class="btn small" onclick="releaseConv(\''+esc(conv.phone_number)+'\')">Release to Bot</button>' :
      '<button class="btn small danger" onclick="takeoverConv(\''+esc(conv.phone_number)+'\')">Take Over</button>')+
    '<button class="btn small secondary" onclick="markCompleted(\''+esc(conv.phone_number)+'\')">Mark Completed</button>'+
    '</div>';
}

function renderTranscript() {
  const el = document.getElementById('transcript');
  let html = '';
  let lastStage = null;
  const annTurnIds = new Set((state.annotations || []).map(a => a.turn_id).filter(Boolean));

  state.transcript.forEach(t => {
    // Stage divider
    if (t.stage_at_turn && t.stage_at_turn !== lastStage && lastStage !== null) {
      html += '<div class="stage-divider"><span>── '+esc(lastStage)+' → '+esc(t.stage_at_turn)+' ──</span></div>';
    }
    if (t.stage_at_turn) lastStage = t.stage_at_turn;

    const sel = t.id === state.selectedTurnId ? ' selected' : '';
    const annDot = annTurnIds.has(t.id) ? '<div class="ann-dot" title="Has annotation"></div>' : '';

    if (t.role === 'tool') {
      const tn = t.tool_name || '';
      const ta = t.tool_args ? JSON.stringify(t.tool_args) : '';
      const tr = t.tool_result ? JSON.stringify(t.tool_result, null, 2) : '';
      const summary = tr.length > 80 ? tr.slice(0, 80) + '...' : tr;
      html += '<div class="t-msg tool'+sel+'" data-turn-id="'+t.id+'" onclick="selectTurn('+t.id+')">'+
        annDot+
        (ta ? '<span class="tool-name">&#128295; '+esc(tn)+'</span>('+esc(ta.slice(0,200))+')<br>' : '')+
        (tr ? '<span class="tool-result" onclick="toggleResult(event, this)">&#8627; '+esc(summary)+'</span>'+
        '<div class="tool-result-full"><pre>'+esc(tr)+'</pre></div>' : '')+
        '<div class="ts">'+timeAgo(t.created_at)+'</div></div>';
    } else {
      const cls = t.role === 'user' ? 'user' : 'assistant';
      html += '<div class="t-msg '+cls+sel+'" data-turn-id="'+t.id+'" onclick="selectTurn('+t.id+')">'+
        annDot+esc(t.content || '')+'<div class="ts">'+timeAgo(t.created_at)+'</div></div>';
    }
  });

  el.innerHTML = html || '<div style="padding:20px;color:var(--fg2)">No turns recorded</div>';
  el.scrollTop = el.scrollHeight;
}

function toggleResult(e, el) {
  e.stopPropagation();
  el.nextElementSibling.classList.toggle('open');
}

function selectTurn(turnId) {
  state.selectedTurnId = state.selectedTurnId === turnId ? null : turnId;
  document.querySelectorAll('.t-msg').forEach(m => {
    m.classList.toggle('selected', Number(m.dataset.turnId) === state.selectedTurnId);
  });
}

// ── Annotations ──
function renderAnnotations() {
  const el = document.getElementById('ann-existing');
  if (!state.annotations || !state.annotations.length) {
    el.innerHTML = '<div style="color:var(--fg2);font-size:11px">No annotations yet</div>';
    return;
  }
  el.innerHTML = state.annotations.map(a =>
    '<div class="ann-item"><span class="cat">'+esc(a.category)+'</span>'+
    (a.severity ? ' ['+esc(a.severity)+']' : '')+
    (a.note ? ' — '+esc(a.note) : '')+
    ' <span style="color:var(--fg2)">'+timeAgo(a.created_at)+'</span></div>'
  ).join('');
}

function setAnnCategory(cat) {
  state.annCategory = cat;
  document.querySelectorAll('.quicktags button').forEach(b => {
    b.classList.toggle('active', b.dataset.cat === cat);
  });
}

async function saveAnnotation() {
  if (!state.annCategory || !state.selectedPhone) return;
  const data = {
    phone_number: state.selectedPhone,
    turn_id: state.selectedTurnId,
    category: state.annCategory,
    severity: document.getElementById('ann-severity').value || null,
    note: document.getElementById('ann-note').value || null,
    suggested_prompt_change: document.getElementById('ann-prompt').value || null,
  };
  await api('/admin/api/annotations', { method: 'POST', body: JSON.stringify(data) });
  document.getElementById('ann-note').value = '';
  document.getElementById('ann-prompt').value = '';
  state.annCategory = null;
  document.querySelectorAll('.quicktags button').forEach(b => b.classList.remove('active'));
  const anns = await api('/admin/api/annotations/' + state.selectedPhone);
  state.annotations = anns || [];
  renderAnnotations();
  renderTranscript();
}

// ── Actions ──
async function takeoverConv(phone) {
  await api('/admin/takeover/' + phone, { method: 'POST' });
  selectConv(phone);
}
async function releaseConv(phone) {
  await api('/admin/release/' + phone, { method: 'POST' });
  selectConv(phone);
}
async function markCompleted(phone) {
  await api('/admin/api/update-stage/' + phone, { method: 'POST', body: JSON.stringify({stage: 'completed'}) });
  selectConv(phone);
}
async function sendAsHuman(phone) {
  const inp = document.getElementById('human-msg');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  await api('/admin/api/send-message/' + phone, { method: 'POST', body: JSON.stringify({text}) });
  setTimeout(() => selectConv(phone), 500);
}

function showSendBar(conv) {
  const bar = document.getElementById('sendbar');
  bar.style.display = conv && conv.human_takeover ? 'flex' : 'none';
}

// ── View switching ──
function switchView(view) {
  state.view = view;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === view));
  document.getElementById('view-convos').style.display = view === 'conversations' ? 'flex' : 'none';
  document.getElementById('view-metrics').style.display = view === 'metrics' ? 'block' : 'none';
  document.getElementById('view-reports').style.display = view === 'reports' ? 'block' : 'none';
  document.getElementById('view-adspend').style.display = view === 'adspend' ? 'block' : 'none';
  if (view === 'metrics') loadMetrics();
  if (view === 'reports') loadReports();
  if (view === 'adspend') loadAdSpend();
}

// ── Metrics ──
async function loadMetrics() {
  const [funnel, campaigns, dropoff, runaway, trend, heatmap, annCounts, recentAnns] = await Promise.all([
    api('/admin/api/funnel'),
    api('/admin/api/campaign-table'),
    api('/admin/api/dropoff'),
    api('/admin/api/runaway'),
    api('/admin/api/daily-trend'),
    api('/admin/api/heatmap'),
    api('/admin/api/annotation-counts'),
    api('/admin/api/recent-annotations'),
  ]);
  renderMetrics(funnel, campaigns, dropoff, runaway, trend, heatmap, annCounts, recentAnns);
}

function renderMetrics(funnel, campaigns, dropoff, runaway, trend, heatmap, annCounts, recentAnns) {
  const el = document.getElementById('view-metrics');
  const t = funnel?.total || {};
  const r = funnel?.retail || {};
  const w = funnel?.wholesale || {};

  const pct = (a, b) => b > 0 ? (a/b*100).toFixed(1)+'%' : '-';
  const fmtMoney = n => '$' + (Number(n)||0).toLocaleString('es-MX', {minimumFractionDigits:2, maximumFractionDigits:2});

  let html = '<h2>30-Day Funnel</h2>';
  html += '<div class="funnel">';
  const steps = [
    {n: t.conversations||0, l: 'Convos'},
    {n: t.qualified||0, l: 'Qualified', p: pct(t.qualified, t.conversations)},
    {n: t.orders||0, l: 'Orders', p: pct(t.orders, t.qualified)},
    {n: t.claimed||0, l: 'Claimed', p: pct(t.claimed, t.orders)},
    {n: t.paid||0, l: 'Paid', p: pct(t.paid, t.claimed)},
  ];
  steps.forEach((s, i) => {
    if (i > 0) html += '<div class="arrow">'+esc(s.p)+'<br>→</div>';
    html += '<div class="step"><div class="num">'+s.n+'</div><div class="label">'+s.l+'</div></div>';
  });
  html += '<div class="step"><div class="num">'+fmtMoney(t.revenue)+'</div><div class="label">Revenue</div></div>';
  html += '</div>';

  // Segment breakdown
  html += '<h2>Segment Breakdown</h2><div class="segment-cols">';
  [{lbl:'Retail', d:r}, {lbl:'Wholesale', d:w}].forEach(({lbl, d}) => {
    html += '<div class="col"><h3>'+lbl+'</h3>'+
      '<div>Convos: '+d.conversations+' → Qualified: '+d.qualified+' ('+pct(d.qualified,d.conversations)+')</div>'+
      '<div>Orders: '+d.orders+' → Paid: '+d.paid+'</div>'+
      '<div>Revenue: '+fmtMoney(d.revenue)+'</div></div>';
  });
  html += '</div>';

  // Campaign table
  html += '<h2>Campaign Performance</h2>';
  if (campaigns && campaigns.length) {
    html += '<table class="campaign-table"><thead><tr>'+
      '<th>Campaign</th><th>Ad Headline</th><th>Convos</th><th>Qual%</th><th>Paid%</th><th>Avg Order</th><th>Revenue</th><th>Spend</th><th>ROAS</th>'+
      '</tr></thead><tbody>';
    campaigns.forEach(c => {
      const cls = c.roas >= 2 ? ' class="good"' : (c.roas > 0 && c.roas < 1 ? ' class="bad"' : '');
      html += '<tr'+cls+'><td>'+esc(c.campaign_id)+'</td><td>'+esc(c.ad_headline||'').slice(0,40)+'</td>'+
        '<td>'+c.convos+'</td><td>'+pct(c.qualified,c.convos)+'</td><td>'+pct(c.paid,c.orders||1)+'</td>'+
        '<td>'+fmtMoney(c.avg_order)+'</td><td>'+fmtMoney(c.revenue)+'</td><td>'+fmtMoney(c.spend)+'</td>'+
        '<td><b>'+(c.roas||0).toFixed(2)+'x</b></td></tr>';
    });
    html += '</tbody></table>';
  }

  // Dropoff histogram
  html += '<h2>Drop-off by Stage (silent >24h)</h2><div class="dropoff-chart">';
  if (dropoff) {
    const maxVal = Math.max(1, ...Object.values(dropoff));
    Object.entries(dropoff).sort((a,b) => b[1]-a[1]).forEach(([stage, count]) => {
      const h = Math.max(4, (count/maxVal)*100);
      html += '<div class="bar-wrap"><div class="bar-count">'+count+'</div><div class="bar" style="height:'+h+'%"></div><div class="bar-label">'+esc(stage)+'</div></div>';
    });
  }
  html += '</div>';

  // Runaway conversations
  html += '<h2>Top Runaway Conversations (no close)</h2>';
  if (runaway && runaway.length) {
    html += '<table class="campaign-table"><thead><tr><th>Phone</th><th>Type</th><th>Stage</th><th>Turns</th><th>Last</th></tr></thead><tbody>';
    runaway.forEach(c => {
      html += '<tr style="cursor:pointer" onclick="switchView(\'conversations\');selectConv(\''+esc(c.phone_number)+'\')">'+
        '<td>...'+esc(c.phone_number.slice(-4))+'</td><td>'+esc(c.lead_type||'')+'</td>'+
        '<td><span class="badge '+esc(c.stage)+'">'+esc(c.stage)+'</span></td>'+
        '<td>'+(c._turn_count||0)+'</td><td>'+timeAgo(c.last_message_at)+'</td></tr>';
    });
    html += '</tbody></table>';
  }

  // Daily trend chart
  html += '<h2>Daily Trend (30 days)</h2><div class="chart-container"><canvas id="trendChart"></canvas></div>';

  // Heatmap
  html += '<h2>Conversation Start Heatmap (Hour x Day)</h2><div class="heatmap">';
  const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  html += '<div class="cell header"></div>';
  for (let h=0; h<24; h++) html += '<div class="cell header">'+h+'</div>';
  if (heatmap) {
    const maxH = Math.max(1, ...heatmap.map(h=>h.count));
    days.forEach((d, di) => {
      html += '<div class="cell header">'+d+'</div>';
      for (let h=0; h<24; h++) {
        const item = heatmap.find(x => x.dow===di && x.hour===h) || {count:0};
        const intensity = item.count / maxH;
        const bg = intensity > 0 ? 'rgba(0,168,132,'+Math.max(0.1,intensity).toFixed(2)+')' : 'var(--bg2)';
        html += '<div class="cell" style="background:'+bg+'" title="'+d+' '+h+':00 = '+item.count+'">'+
          (item.count>0?item.count:'')+'</div>';
      }
    });
  }
  html += '</div>';

  // Annotation analytics
  html += '<h2>Annotation Counts (30 days)</h2>';
  if (annCounts && annCounts.length) {
    html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">';
    annCounts.forEach(a => {
      html += '<div class="step"><div class="num">'+a.count+'</div><div class="label">'+esc(a.category)+'</div></div>';
    });
    html += '</div>';
  }
  if (recentAnns && recentAnns.length) {
    html += '<h3 style="font-size:13px;margin-bottom:8px">Recent Annotations</h3>';
    recentAnns.forEach(a => {
      html += '<div style="font-size:12px;color:var(--fg2);padding:4px 0;border-bottom:1px solid var(--bg4);cursor:pointer" onclick="switchView(\'conversations\');selectConv(\''+esc(a.phone_number)+'\')">'+
        '<span class="badge '+esc(a.category)+'">'+esc(a.category)+'</span> '+
        esc((a.note||'').slice(0,80))+' <span>...'+esc(a.phone_number.slice(-4))+'</span> '+timeAgo(a.created_at)+
        '</div>';
    });
  }

  el.innerHTML = html;

  // Render Chart.js trend
  if (trend && trend.length && typeof Chart !== 'undefined') {
    setTimeout(() => {
      const ctx = document.getElementById('trendChart');
      if (!ctx) return;
      new Chart(ctx, {
        type: 'line',
        data: {
          labels: trend.map(d => d.date.slice(5)),
          datasets: [
            { label: 'Conversations', data: trend.map(d => d.conversations), borderColor: '#00a884', tension: 0.3, fill: false },
            { label: 'Orders', data: trend.map(d => d.orders), borderColor: '#3498db', tension: 0.3, fill: false },
            { label: 'Paid', data: trend.map(d => d.paid), borderColor: '#27ae60', tension: 0.3, fill: false },
          ]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: '#8696a0' } } },
          scales: { x: { ticks: { color: '#8696a0' } }, y: { ticks: { color: '#8696a0' }, beginAtZero: true } } }
      });
    }, 100);
  }
}

// ── Reports ──
async function loadReports() {
  const reports = await api('/admin/api/reports');
  const el = document.getElementById('view-reports');
  if (!reports || !reports.length) { el.innerHTML = '<h2>Daily Reports</h2><p style="color:var(--fg2)">No reports yet. Run /admin/tasks/daily-review to generate.</p>'; return; }
  el.innerHTML = '<h2>Daily Reports</h2>' + reports.map(r =>
    '<div class="report-card"><h3>'+esc(r.date)+' ('+r.conversations_reviewed+' conversations)</h3>'+
    '<div class="md">'+simpleMarkdown(r.report_markdown||'')+'</div>'+
    (r.source_phone_numbers ? '<div style="margin-top:8px;font-size:11px;color:var(--fg2)">Source conversations: '+
      r.source_phone_numbers.map(p => '<a href="#" onclick="switchView(\'conversations\');selectConv(\''+esc(p)+'\');return false">...'+esc(p.slice(-4))+'</a>').join(', ')+
    '</div>' : '')+
    '</div>'
  ).join('');
}

// ── Ad Spend ──
async function loadAdSpend() {
  const [rows, campaigns] = await Promise.all([
    api('/admin/api/ad-spend'),
    api('/admin/api/campaigns'),
  ]);
  const el = document.getElementById('view-adspend');
  let html = '<h2>Ad Spend</h2>';
  html += '<div class="addrow">'+
    '<input type="date" id="as-date" />'+
    '<select id="as-campaign"><option value="">Campaign</option>'+(campaigns||[]).map(c=>'<option>'+esc(c)+'</option>').join('')+'</select>'+
    '<input type="number" id="as-amount" placeholder="Spend MXN" step="0.01" />'+
    '<input type="text" id="as-notes" placeholder="Notes" />'+
    '<button class="btn small" onclick="addSpend()">Add</button>'+
    '</div>';
  html += '<table><thead><tr><th>Date</th><th>Campaign</th><th>Spend MXN</th><th>Notes</th><th></th></tr></thead><tbody>';
  (rows||[]).forEach(r => {
    html += '<tr><td>'+esc(r.date)+'</td><td>'+esc(r.campaign_id)+'</td><td>$'+(Number(r.spend_mxn)||0).toFixed(2)+'</td><td>'+esc(r.notes||'')+'</td>'+
      '<td><button class="btn small danger" onclick="deleteSpend('+r.id+')">Del</button></td></tr>';
  });
  html += '</tbody></table>';
  el.innerHTML = html;
}

async function addSpend() {
  const data = {
    date: document.getElementById('as-date').value,
    campaign_id: document.getElementById('as-campaign').value,
    spend_mxn: parseFloat(document.getElementById('as-amount').value) || 0,
    notes: document.getElementById('as-notes').value,
  };
  if (!data.date || !data.campaign_id) return alert('Date and campaign required');
  await api('/admin/api/ad-spend', { method: 'POST', body: JSON.stringify(data) });
  loadAdSpend();
}

async function deleteSpend(id) {
  if (!confirm('Delete?')) return;
  await api('/admin/api/ad-spend/' + id, { method: 'DELETE' });
  loadAdSpend();
}

// ── Export ──
function exportCSV(type) {
  const f = state.filters;
  const params = new URLSearchParams({ from: f.date_from, to: f.date_to });
  if (type === 'turns' && state.selectedPhone) params.set('phone_number', state.selectedPhone);
  window.open('/admin/export/' + type + '.csv?' + params, '_blank');
}

// ── Keyboard shortcuts ──
function bindKeys() {
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
    if (state.view !== 'conversations') return;
    const convos = state.conversations;
    const idx = convos.findIndex(c => c.phone_number === state.selectedPhone);
    if (e.key === 'j' && idx < convos.length - 1) { selectConv(convos[idx+1].phone_number); e.preventDefault(); }
    if (e.key === 'k' && idx > 0) { selectConv(convos[idx-1].phone_number); e.preventDefault(); }
    if (e.key === '1') setAnnCategory('bad_response');
    if (e.key === '2') setAnnCategory('missed_upsell');
    if (e.key === '3') setAnnCategory('good_close');
    if (e.key === '4') setAnnCategory('prompt_gap');
    if (e.key === '5') setAnnCategory('tool_failure');
    if (e.key === '6') setAnnCategory('other');
    if (e.key === 't') { if (state.selectedPhone) takeoverConv(state.selectedPhone); }
    if (e.key === '?') document.getElementById('kbd-help').classList.toggle('show');
  });
}

// ── Helpers ──
function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

function timeAgo(ts) {
  if (!ts) return '';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + 'm';
  if (diff < 86400) return Math.floor(diff/3600) + 'h';
  return Math.floor(diff/86400) + 'd';
}

function simpleMarkdown(md) {
  return md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>')
    .replace(/^- (.+)$/gm, '&bull; $1<br>')
    .replace(/^(\\d+)\\. (.+)$/gm, '$1. $2<br>')
    .replace(/\\n/g, '<br>');
}

// ── Start ──
document.addEventListener('DOMContentLoaded', init);
"""
