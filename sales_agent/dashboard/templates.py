"""HTML templates for the dashboard."""

from sales_agent.dashboard.static import DASHBOARD_CSS, DASHBOARD_JS


def login_page(error: str = ""):
    err_html = f'<div class="error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login — Fundastock</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, sans-serif; background: #0b141a; color: #e9edef; }}
.login-page {{ display: flex; align-items: center; justify-content: center; height: 100vh; }}
.login-box {{ background: #202c33; padding: 32px; border-radius: 12px; width: 300px; text-align: center; }}
.login-box h2 {{ margin-bottom: 16px; }}
.login-box input {{ width: 100%; padding: 10px; background: #2a3942; border: none; color: #e9edef; border-radius: 6px; font-size: 14px; margin-bottom: 12px; }}
.login-box button {{ width: 100%; background: #00a884; color: #fff; border: none; padding: 10px; border-radius: 6px; cursor: pointer; font-size: 14px; }}
.login-box button:hover {{ background: #00c49a; }}
.login-box .error {{ color: #e74c3c; font-size: 12px; margin-bottom: 8px; }}
</style></head><body>
<div class="login-page"><div class="login-box">
<h2>Fundastock Admin</h2>
{err_html}
<form method="POST" action="/admin/login">
<input type="password" name="password" placeholder="Password" autofocus />
<button type="submit">Login</button>
</form></div></div></body></html>"""


def dashboard_page():
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fundastock Admin Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>{DASHBOARD_CSS}</style>
</head><body>
<div class="app">
  <div class="topbar">
    <h1>Fundastock Admin</h1>
    <div class="tabs">
      <button class="tab active" data-view="conversations" onclick="switchView('conversations')">Conversations</button>
      <button class="tab" data-view="metrics" onclick="switchView('metrics')">Metrics</button>
      <button class="tab" data-view="reports" onclick="switchView('reports')">Reports</button>
      <button class="tab" data-view="adspend" onclick="switchView('adspend')">Ad Spend</button>
    </div>
    <div style="display:flex;gap:6px">
      <button class="btn small secondary" onclick="exportCSV('conversations')">CSV</button>
      <a href="/admin/logout" class="btn small secondary" style="text-decoration:none">Logout</a>
      <a href="/test" class="btn small secondary" style="text-decoration:none">Test</a>
    </div>
  </div>

  <!-- Conversations View -->
  <div id="view-convos" class="main">
    <div class="sidebar">
      <div class="filters">
        <input type="text" id="f-search" placeholder="Search conversations..." />
        <div class="row">
          <input type="date" id="f-from" />
          <input type="date" id="f-to" />
        </div>
        <div class="row">
          <select id="f-type">
            <option value="all">All types</option>
            <option value="retail">Retail</option>
            <option value="wholesale">Wholesale</option>
            <option value="unknown">Unknown</option>
          </select>
          <select id="f-stage">
            <option value="all">All stages</option>
            <option value="greeting">Greeting</option>
            <option value="qualifying">Qualifying</option>
            <option value="product_selection">Product Sel.</option>
            <option value="closing">Closing</option>
            <option value="post_sale">Post Sale</option>
            <option value="escalated">Escalated</option>
            <option value="completed">Completed</option>
          </select>
        </div>
        <select id="f-campaign"><option value="all">All campaigns</option></select>
        <div class="checks">
          <label><input type="checkbox" id="f-escalated" /> Escalated</label>
          <label><input type="checkbox" id="f-takeover" /> Human takeover</label>
          <label><input type="checkbox" id="f-annotated" /> With annotations</label>
        </div>
      </div>
      <div class="convlist" id="convlist"></div>
      <div class="loadmore" id="loadmore" style="display:none">
        <button onclick="loadMore()">Load more...</button>
      </div>
    </div>

    <div class="content" id="conv-content">
      <div class="convheader" id="conv-header" style="display:none"></div>
      <div class="transcript" id="transcript"></div>
      <div class="sendbar" id="sendbar" style="display:none">
        <input id="human-msg" placeholder="Send as human..." onkeydown="if(event.key==='Enter')sendAsHuman('{{}}')" />
        <button class="btn small" onclick="sendAsHuman(state.selectedPhone)">Send</button>
      </div>
      <div class="annpanel" id="annpanel" style="display:none">
        <div class="quicktags">
          <button data-cat="bad_response" onclick="setAnnCategory('bad_response')">&#128683; Bad response</button>
          <button data-cat="missed_upsell" onclick="setAnnCategory('missed_upsell')">&#128184; Missed upsell</button>
          <button data-cat="good_close" onclick="setAnnCategory('good_close')">&#9989; Good close</button>
          <button data-cat="prompt_gap" onclick="setAnnCategory('prompt_gap')">&#10067; Prompt gap</button>
          <button data-cat="tool_failure" onclick="setAnnCategory('tool_failure')">&#128295; Tool failure</button>
          <button data-cat="other" onclick="setAnnCategory('other')">&#8505;&#65039; Other</button>
        </div>
        <div class="fields">
          <select id="ann-severity">
            <option value="">Severity</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
          <button class="btn small" onclick="saveAnnotation()">Save</button>
        </div>
        <div class="ann-row"><textarea id="ann-note" placeholder="Note — what went wrong?" rows="1"></textarea></div>
        <div class="ann-row"><textarea id="ann-prompt" placeholder="Suggested prompt change..." rows="1"></textarea></div>
        <div class="existing" id="ann-existing"></div>
      </div>
      <div class="empty" id="empty-state">Select a conversation from the list</div>
    </div>
  </div>

  <!-- Metrics View -->
  <div id="view-metrics" class="metrics" style="display:none"></div>

  <!-- Reports View -->
  <div id="view-reports" class="reports" style="display:none"></div>

  <!-- Ad Spend View -->
  <div id="view-adspend" class="adspend" style="display:none"></div>
</div>

<div class="kbd-help" id="kbd-help">
  <b>Keyboard shortcuts</b><br>
  <kbd>j</kbd>/<kbd>k</kbd> next/prev conversation<br>
  <kbd>1</kbd>-<kbd>6</kbd> quick annotation tag<br>
  <kbd>t</kbd> toggle takeover<br>
  <kbd>?</kbd> toggle this help
</div>

<script>
{DASHBOARD_JS}

// Show/hide panels on conversation select
const origSelect = selectConv;
selectConv = async function(phone) {{
  await origSelect(phone);
  document.getElementById('conv-header').style.display = 'block';
  document.getElementById('annpanel').style.display = 'block';
  document.getElementById('empty-state').style.display = 'none';
}};
const origBack = goBack;
goBack = function() {{
  origBack();
  document.getElementById('conv-header').style.display = 'none';
  document.getElementById('annpanel').style.display = 'none';
  document.getElementById('sendbar').style.display = 'none';
  document.getElementById('empty-state').style.display = 'flex';
}};
</script>
</body></html>"""
