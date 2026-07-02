'use strict';

const STORAGE_KEY = 'finance_world_events';

let events = loadEvents();

// ── DOM refs ──────────────────────────────────────────────────────────────────
const form         = document.getElementById('event-form');
const listEl       = document.getElementById('events-list');
const countEl      = document.getElementById('event-count');
const filterCat    = document.getElementById('filter-category');
const filterImpact = document.getElementById('filter-impact');
const filterSearch = document.getElementById('filter-search');

// ── Persistence ───────────────────────────────────────────────────────────────
function loadEvents() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  } catch {
    return [];
  }
}

function saveEvents() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(events));
}

// ── CRUD ──────────────────────────────────────────────────────────────────────
function addEvent(data) {
  events.unshift({ id: Date.now(), ...data });
  saveEvents();
  render();
}

function deleteEvent(id) {
  events = events.filter(e => e.id !== id);
  saveEvents();
  render();
}

// ── Filtering ─────────────────────────────────────────────────────────────────
function getFiltered() {
  const cat    = filterCat.value;
  const impact = filterImpact.value;
  const q      = filterSearch.value.trim().toLowerCase();

  return events.filter(e => {
    if (cat    && e.category !== cat)    return false;
    if (impact && e.impact   !== impact) return false;
    if (q && !e.title.toLowerCase().includes(q) &&
             !(e.region || '').toLowerCase().includes(q) &&
             !(e.notes || '').toLowerCase().includes(q)) return false;
    return true;
  });
}

// ── Render ────────────────────────────────────────────────────────────────────
function render() {
  const filtered = getFiltered();
  countEl.textContent = `${filtered.length} event${filtered.length !== 1 ? 's' : ''}`;

  if (filtered.length === 0) {
    listEl.innerHTML = `
      <div class="empty-state">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945
               M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0
               2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064
               M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p>No events found. Add one above.</p>
      </div>`;
    return;
  }

  listEl.innerHTML = filtered.map(e => `
    <div class="event-card impact-${e.impact}" data-id="${e.id}">
      <div class="event-meta">
        <span class="event-date">${formatDate(e.date)}</span>
        <span class="badge badge-impact-${e.impact}">${e.impact}</span>
        <span class="badge badge-category">${e.category}</span>
      </div>
      <div class="event-body">
        <div class="event-title">${escapeHtml(e.title)}</div>
        <div class="event-region">📍 ${escapeHtml(e.region)}</div>
        ${e.notes ? `<div class="event-notes">${escapeHtml(e.notes)}</div>` : ''}
      </div>
      <div class="event-actions">
        <button class="btn-delete" data-id="${e.id}" title="Remove event">✕</button>
      </div>
    </div>`).join('');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatDate(iso) {
  if (!iso) return '—';
  // Parse YYYY-MM-DD without timezone shift by splitting manually
  const parts = String(iso).split('-');
  if (parts.length === 3) {
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Event Listeners ───────────────────────────────────────────────────────────
form.addEventListener('submit', e => {
  e.preventDefault();
  const fd = new FormData(form);
  addEvent({
    title:    fd.get('title').trim(),
    date:     fd.get('date'),
    region:   fd.get('region').trim() || 'Global',
    category: fd.get('category'),
    impact:   fd.get('impact'),
    notes:    fd.get('notes').trim(),
  });
  form.reset();
  // restore today's date default
  document.getElementById('input-date').value = today();
});

listEl.addEventListener('click', e => {
  const btn = e.target.closest('.btn-delete');
  if (btn) deleteEvent(Number(btn.dataset.id));
});

[filterCat, filterImpact, filterSearch].forEach(el =>
  el.addEventListener('input', render));

function today() {
  return new Date().toISOString().slice(0, 10);
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.getElementById('input-date').value = today();
render();
