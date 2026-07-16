(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const statusEl = $('#status-bar');

  const HORIZON_LABELS = {
    '1m': '1 Minute',
    '1h': '1 Hour',
    '24h': '24 Hour',
    '1wk': '1 Week',
    '1mo': '1 Month',
    '1yr': '1 Year',
  };

  const INTRADAY = new Set(['1m', '1h']);

  let activeHorizon = '24h';
  let latestData = null;

  function setStatus(msg, cls) {
    statusEl.textContent = msg;
    statusEl.className = 'status-bar ' + (cls || '');
  }

  function fmtPct(v) {
    if (v == null || Number.isNaN(v)) return '—';
    const sign = v >= 0 ? '+' : '';
    return sign + Number(v).toFixed(2) + '%';
  }

  function pctClass(v) {
    if (v == null || Number.isNaN(v)) return '';
    return v >= 0 ? 'positive' : 'negative';
  }

  function horizonOrder(data) {
    const meta = (data && data.meta) || {};
    if (Array.isArray(meta.horizons) && meta.horizons.length) {
      return meta.horizons.filter((h) => HORIZON_LABELS[h]);
    }
    return Object.keys(HORIZON_LABELS);
  }

  function renderKPIs(data) {
    const grid = $('#kpi-grid');
    const meta = (data && data.meta) || {};
    const fusion = meta.fusion || {};
    const regime = fusion.regime || {};
    const balance = fusion.account_balance || {};
    const items = [
      {
        label: 'Tickers scored',
        value: meta.tickers_scored != null ? String(meta.tickers_scored) : '—',
        delta: (meta.source_files || []).length + ' agent reports',
      },
      {
        label: 'Market regime',
        value: regime.label || '—',
        delta: regime.posture || '',
      },
      {
        label: 'Risk-on score',
        value: regime.risk_on_score != null ? Number(regime.risk_on_score).toFixed(2) : '—',
        delta: 'Fusion posture input',
      },
      {
        label: 'Account growth',
        value: balance.growth_pct != null ? fmtPct(balance.growth_pct) : '—',
        delta: balance.trend ? String(balance.trend) : 'Portfolio benchmark',
        deltaClass: pctClass(balance.growth_pct),
      },
    ];
    grid.innerHTML = items.map(function (k) {
      return (
        '<div class="kpi-card">' +
        '<div class="label">' + k.label + '</div>' +
        '<div class="value">' + k.value + '</div>' +
        '<div class="delta ' + (k.deltaClass || '') + '">' + (k.delta || '') + '</div>' +
        '</div>'
      );
    }).join('');
  }

  function renderSummary(data) {
    const meta = (data && data.meta) || {};
    const fusion = meta.fusion || {};
    const regime = fusion.regime || {};
    const bits = [];
    if (meta.analyzed_at) {
      bits.push('Updated ' + meta.analyzed_at.replace('T', ' ').replace('+00:00', ' UTC'));
    }
    if (regime.summary) {
      bits.push(regime.summary);
    }
    const recs = data.recommendations || [];
    if (recs.length) {
      bits.push(recs[0]);
    }
    $('#summary-text').textContent = bits.join(' · ');
  }

  function renderHorizonNav(data) {
    const nav = $('#horizon-nav');
    const preds = (data && data.predictions) || {};
    const order = horizonOrder(data);
    if (!order.includes(activeHorizon)) {
      activeHorizon = order.find((h) => Array.isArray(preds[h]) && preds[h].length) || order[0] || '24h';
    }
    nav.innerHTML = order.map(function (h) {
      const rows = preds[h] || [];
      const count = rows.length;
      const cls = [
        h === activeHorizon ? 'active' : '',
        INTRADAY.has(h) ? 'intraday' : '',
      ].filter(Boolean).join(' ');
      return (
        '<button type="button" class="' + cls + '" data-horizon="' + h + '">' +
        HORIZON_LABELS[h] + ' (' + count + ')' +
        '</button>'
      );
    }).join('');
    nav.querySelectorAll('button[data-horizon]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        activeHorizon = btn.getAttribute('data-horizon');
        renderHorizonNav(latestData);
        renderTable(latestData);
      });
    });
  }

  function renderTable(data) {
    const preds = (data && data.predictions) || {};
    const rows = preds[activeHorizon] || [];
    const label = HORIZON_LABELS[activeHorizon] || activeHorizon;
    $('#table-title').textContent = 'Top movers — ' + label;
    const tbody = $('#predictions-tbody');
    if (!rows.length) {
      tbody.innerHTML =
        '<tr><td colspan="8" class="muted">No predictions for this horizon yet. Run Full Pipeline.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(function (row) {
      const ret = row.predicted_return_pct;
      const sources = (row.sources || []).join(', ');
      const price = row.price_at_prediction != null ? '$' + Number(row.price_at_prediction).toFixed(2) : '—';
      const conf = row.confidence != null ? (Number(row.confidence) * 100).toFixed(0) + '%' : '—';
      return (
        '<tr>' +
        '<td>#' + (row.rank != null ? row.rank : '—') + '</td>' +
        '<td><strong>' + (row.symbol || '—') + '</strong></td>' +
        '<td class="' + pctClass(ret) + '">' + fmtPct(ret) + '</td>' +
        '<td>' + (row.predicted_direction || '—') + '</td>' +
        '<td>' + conf + '</td>' +
        '<td>' + price + '</td>' +
        '<td class="sources">' + (sources || '—') + '</td>' +
        '<td class="rationale muted">' + (row.rationale || '—') + '</td>' +
        '</tr>'
      );
    }).join('');
  }

  function applyData(data) {
    latestData = data;
    renderKPIs(data);
    renderSummary(data);
    renderHorizonNav(data);
    renderTable(data);
    const meta = (data && data.meta) || {};
    setStatus(
      'Loaded ' + (meta.tickers_scored || 0) + ' tickers across ' + horizonOrder(data).length + ' horizons.',
      'ok'
    );
  }

  function loadFromObject(data) {
    if (!data || !data.predictions) {
      setStatus('JSON is missing a predictions block.', 'error');
      return;
    }
    applyData(data);
  }

  async function tryFetchDefault() {
    try {
      const resp = await fetch('output/market_predictions.json');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      loadFromObject(data);
    } catch (e) {
      setStatus(
        'Run Full Pipeline to refresh output/market_predictions.json, or Import JSON.',
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