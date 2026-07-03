(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const statusEl = $('#status-bar');

  function setStatus(msg, cls) {
    statusEl.textContent = msg;
    statusEl.className = 'status-bar ' + (cls || '');
  }

  function fmtPct(v) {
    if (v == null || Number.isNaN(v)) return '—';
    const sign = v >= 0 ? '+' : '';
    return sign + v.toFixed(2) + '%';
  }

  function pctClass(v) {
    if (v == null) return '';
    return v >= 0 ? 'positive' : 'negative';
  }

  function renderKPIs(kpis) {
    const grid = $('#kpi-grid');
    if (!kpis) return;
    const items = [
      {
        label: 'Consumer Strength',
        value: (kpis.strength_label || '—'),
        delta: 'Score ' + (kpis.consumer_strength_score ?? '—').toFixed(2),
      },
      {
        label: 'Sales Momentum Index',
        value: (kpis.sales_momentum_index ?? 0).toFixed(2),
        delta: kpis.sales_momentum_index >= 0.55 ? 'Accelerating' : 'Softening',
        deltaClass: kpis.sales_momentum_index >= 0.55 ? 'positive' : 'negative',
      },
      {
        label: 'Retail Breadth (20d)',
        value: (kpis.retail_breadth_pct ?? 0).toFixed(0) + '%',
        delta: 'Tickers positive',
      },
      {
        label: 'Discretionary Premium',
        value: fmtPct(kpis.discretionary_premium_pct),
        delta: 'XLY vs XLP spread',
        deltaClass: pctClass(kpis.discretionary_premium_pct),
      },
    ];
    grid.innerHTML = items.map(function (k) {
      return (
        '<div class="kpi-card">' +
        '<div class="label">' + k.label + '</div>' +
        '<div class="value">' + k.value + '</div>' +
        '<div class="delta ' + (k.deltaClass || '') + '">' + k.delta + '</div>' +
        '</div>'
      );
    }).join('');
  }

  function renderCategories(categories) {
    const el = $('#category-bars');
    if (!categories || !categories.length) {
      el.innerHTML = '<p style="color:#718096">No category data</p>';
      return;
    }
    const maxAbs = Math.max.apply(null, categories.map(function (c) {
      return Math.abs(c.avg_return_20d_pct || 0);
    }).concat([1]));
    el.innerHTML = categories.map(function (c) {
      const pct = c.avg_return_20d_pct || 0;
      const width = Math.min(100, (Math.abs(pct) / maxAbs) * 100);
      const neg = pct < 0 ? ' negative' : '';
      return (
        '<div class="bar-row">' +
        '<span class="bar-label">' + c.label + '</span>' +
        '<div class="bar-track"><div class="bar-fill' + neg + '" style="width:' + width + '%"></div></div>' +
        '<span class="bar-value ' + pctClass(pct) + '">' + fmtPct(pct) + '</span>' +
        '</div>'
      );
    }).join('');
  }

  function renderSparkline(trend) {
    if (!trend || !trend.length) return '<span style="color:#718096">—</span>';
    return (
      '<div class="sparkline">' +
      trend.map(function (v, i) {
        const h = Math.max(4, Math.round(v * 24));
        const cls = i > 0 && v >= trend[i - 1] ? 'up' : 'down';
        return '<div class="spark-bar ' + cls + '" style="height:' + h + 'px"></div>';
      }).join('') +
      '</div>'
    );
  }

  function renderTable(retailers) {
    const tbody = $('#retail-tbody');
    if (!retailers || !retailers.length) {
      tbody.innerHTML = '<tr><td colspan="6">No data</td></tr>';
      return;
    }
    tbody.innerHTML = retailers.map(function (r) {
      return (
        '<tr>' +
        '<td><strong>' + r.symbol + '</strong></td>' +
        '<td>' + (r.name || '') + '</td>' +
        '<td>' + (r.category_label || r.category || '') + '</td>' +
        '<td class="' + pctClass(r.return_1d_pct) + '">' + fmtPct(r.return_1d_pct) + '</td>' +
        '<td class="' + pctClass(r.return_20d_pct) + '">' + fmtPct(r.return_20d_pct) + '</td>' +
        '<td>' + (r.momentum_score != null ? r.momentum_score.toFixed(2) : '—') + '</td>' +
        '<td>' + renderSparkline(r.trend_20d) + '</td>' +
        '</tr>'
      );
    }).join('');
  }

  function renderComparison(retailers) {
    const el = $('#comparison-panel');
    const xly = (retailers || []).find(function (r) { return r.symbol === 'XLY'; });
    const xlp = (retailers || []).find(function (r) { return r.symbol === 'XLP'; });
    if (!xly && !xlp) {
      el.innerHTML = '<p style="color:#718096">ETF data unavailable</p>';
      return;
    }
    function card(sym, r) {
      if (!r) return '';
      return (
        '<div class="comparison-card">' +
        '<div class="sym">' + sym + ' — ' + (r.name || '') + '</div>' +
        '<div class="pct ' + pctClass(r.return_20d_pct) + '">' + fmtPct(r.return_20d_pct) + '</div>' +
        '<div style="font-size:0.75rem;color:#718096;margin-top:0.25rem">20-day return</div>' +
        '</div>'
      );
    }
    el.innerHTML = '<div class="comparison-row">' + card('XLY', xly) + card('XLP', xlp) + '</div>';
  }

  function renderSignals(signals) {
    const el = $('#signals-list');
    if (!signals || !signals.length) {
      el.innerHTML = '<li>No signals</li>';
      return;
    }
    el.innerHTML = signals.map(function (s) {
      return (
        '<li>' +
        '<span class="bias bias-' + (s.bias || 'NEUTRAL') + '">' + (s.bias || 'NEUTRAL') + '</span>' +
        '<strong>' + (s.sector || '') + '</strong> — ' + (s.reason || '') +
        '</li>'
      );
    }).join('');
  }

  function applyData(data) {
    renderKPIs(data.kpis);
    renderCategories(data.categories);
    renderTable(data.retailers);
    renderComparison(data.retailers);
    renderSignals(data.signals || data.market_signals);
    if (data.summary) {
      $('#summary-text').textContent = data.summary;
    }
    if (data.updated_at) {
      setStatus('Dashboard loaded — ' + new Date(data.updated_at).toLocaleString(), 'loaded');
    } else {
      setStatus('Dashboard data loaded', 'loaded');
    }
  }

  function loadFromObject(obj) {
    const feed = obj.kpis ? obj : {
      kpis: obj.metrics || obj.kpis,
      categories: obj.categories,
      retailers: obj.retailers,
      signals: obj.market_signals || obj.signals,
      summary: (obj.meta && obj.meta.expert_summary) || obj.summary,
      updated_at: (obj.meta && obj.meta.analyzed_at) || obj.updated_at,
    };
    applyData(feed);
  }

  async function tryFetchDefault() {
    try {
      const resp = await fetch('output/sales_dashboard_data.json');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      loadFromObject(data);
    } catch (e) {
      setStatus(
        'Run run.bat sales-analytics -o output/sales_analytics.json then refresh, or Import JSON.',
        'error'
      );
    }
  }

  $('#btn-refresh').addEventListener('click', tryFetchDefault);

  $('#btn-import').addEventListener('click', function () {
    $('#import-input').click();
  });

  $('#import-input').addEventListener('change', function (ev) {
    const file = ev.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function (e) {
      try {
        loadFromObject(JSON.parse(e.target.result));
      } catch (err) {
        setStatus('Invalid JSON file', 'error');
      }
    };
    reader.readAsText(file);
    ev.target.value = '';
  });

  tryFetchDefault();
})();