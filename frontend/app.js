// ═══════════════════════════════════════════════════════════
//  app.js  –  BTS Rental Dashboard  (v2 – clean rebuild)
// ═══════════════════════════════════════════════════════════

// ── Formatters ────────────────────────────────────────────
const fVND = v => (v == null || isNaN(+v)) ? '-'
  : new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(v);
const fNum = v => (v == null || isNaN(+v)) ? '-'
  : new Intl.NumberFormat('vi-VN').format(v);
const fPct = v => (v == null || v === '') ? '-' : `${(+v * 100).toFixed(0)}%`;

// ── Charts ────────────────────────────────────────────────
let cVendor, cRevenue, cStatus;

// ── Toast ─────────────────────────────────────────────────
let _toastTimer;
function toast(msg, err = false) {
  const el = document.getElementById('toast');
  const sp = document.getElementById('toast-msg');
  sp.textContent = msg;
  el.className = 'toast show' + (err ? ' err' : '');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.className = 'toast', 3000);
}

// ── Tab Switch ────────────────────────────────────────────
function switchTab(id) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.currentTarget.classList.add('active');
}

// ── Status Pill ───────────────────────────────────────────
function statusClass(s) {
  if (!s) return 'gray';
  const u = s.toString().toUpperCase().trim();
  if (u === 'ĐÃ TT') return 'green';
  if (u === 'CHƯA TT') return 'red';
  if (u.includes('XỬ LÝ') || u.includes('ĐANG')) return 'warn';
  return 'gray';
}

function mkStatusSel(val, maTram, nhaMang, col) {
  const cur = (val || '').toString().trim();
  const cls = statusClass(cur);
  const opts = ['ĐÃ TT', 'CHƯA TT', 'ĐANG XỬ LÝ', ''];
  if (!opts.includes(cur.toUpperCase()) && cur !== '') opts.unshift(cur);
  return `<select class="sel-status ${cls}"
    data-orig="${escHtml(cur)}"
    onchange="dbUpdate('${escHtml(maTram)}','${escHtml(nhaMang)}','${escHtml(col)}',this.value,this)">
    ${opts.map(o => `<option value="${o}"${o.toUpperCase()===cur.toUpperCase()?' selected':''}>${o||'--'}</option>`).join('')}
  </select>`;
}

function mkPriceEdit(val, maTram, nhaMang, col) {
  const raw = (val != null && val !== '') ? String(val).replace(/[^0-9.-]/g, '') : '';
  const display = fVND(val);
  const id = `ed_${Math.random().toString(36).slice(2)}`;
  return `<span class="editable" onclick="startEdit('${id}','${escHtml(maTram)}','${escHtml(nhaMang)}','${escHtml(col)}','${raw}')">
    <span id="${id}_disp">${display}</span>
    <i class="fa-solid fa-pen edit-icon"></i>
  </span>`;
}

function startEdit(id, maTram, nhaMang, col, raw) {
  const span = document.getElementById(`${id}_disp`);
  if (!span) return;
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'num-input';
  input.value = raw;
  input.dataset.orig = raw;
  input.onblur = () => {
    if (input.value !== input.dataset.orig) dbUpdate(maTram, nhaMang, col, input.value, input);
    else { input.replaceWith(span); }
  };
  input.onkeydown = e => { if (e.key === 'Enter') input.blur(); if (e.key === 'Escape') { input.value = input.dataset.orig; input.blur(); } };
  span.parentElement.replaceChild(input, span);
  input.focus(); input.select();
}

function escHtml(s) { return String(s || '').replace(/'/g, "\\'"); }

// ── DB Update ─────────────────────────────────────────────
async function dbUpdate(maTram, nhaMang, col, newVal, el) {
  const orig = el.getAttribute('data-orig') || el.dataset.orig || '';
  if (String(newVal) === String(orig)) return;
  try {
    const res = await fetch('/api/dashboard/update-rent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ma_tram: maTram, nha_mang: nhaMang, column: col, value: String(newVal) })
    });
    if (res.ok) {
      toast('✓ Đã lưu thành công');
      loadData(true);
    } else {
      const err = await res.json();
      toast('Lỗi: ' + (err.detail || 'Không xác định'), true);
    }
  } catch (e) {
    toast('Lỗi kết nối: ' + e.message, true);
  }
}

// ── Load Data ─────────────────────────────────────────────
async function loadData(silent = false) {
  if (!silent) document.getElementById('lbl-updated').textContent = 'Đang tải...';
  try {
    const res = await fetch('/api/dashboard/rent-data');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const d = await res.json();
    document.getElementById('lbl-updated').textContent = 'Cập nhật: ' + d.last_updated;
    // Lưu toàn bộ dữ liệu gốc cho search
    _lastTT = d.doanh_thu || [];
    _lastTram = d.tong_hop || [];
    renderKPI(d.tong_hop, d.doanh_thu);
    renderCharts(d.tong_hop, d.doanh_thu);
    // Render bảng qua search để giữ filter hiện tại
    applySearch();
    // Hiện số bản ghi
    const cnt = document.getElementById('search-count');
    if (cnt) cnt.innerHTML = `<i class="fa-solid fa-list"></i> ${_lastTT.length} bản ghi`;
  } catch (e) {
    document.getElementById('lbl-updated').textContent = '⚠ Lỗi tải dữ liệu';
    if (!silent) toast('Lỗi tải dữ liệu: ' + e.message, true);
  }
}

// ── KPI ───────────────────────────────────────────────────
function renderKPI(tong_hop, dt) {
  let invest = 0, rent = 0, exp25 = 0, recv25 = 0, recv26 = 0;
  tong_hop.forEach(r => {
    invest += +r['Tổng Đầu Tư'] || 0;
    rent   += +r['Tiền Thuê Đất / Năm'] || 0;
  });
  dt.forEach(r => {
    exp25  += +r['[25] Tổng Đ.Kiến'] || 0;
    recv25 += +r['[K1_25] Tiền Nhận'] || 0;
    recv26 += +r['[K1_26] Tiền Nhận'] || 0;
  });

  // Count payment stats
  let da25 = 0, chua25 = 0;
  dt.forEach(r => {
    const s = (r['[K1_26] Trạng Thái'] || '').toUpperCase().trim();
    if (s === 'ĐÃ TT') da25++;
    else if (s === 'CHƯA TT') chua25++;
  });

  const cards = [
    { label: 'Tổng Số Trạm',       value: fNum(tong_hop.length),   sub: `${dt.length} hợp đồng`,        icon: 'fa-tower-cell',           color: '#6c63ff', bg: 'rgba(108,99,255,.15)' },
    { label: 'Tổng Vốn Đầu Tư',    value: fVND(invest),            sub: 'Đất + Xây dựng',               icon: 'fa-building-columns',     color: '#a78bfa', bg: 'rgba(167,139,250,.15)' },
    { label: 'Thuê Đất / Năm',      value: fVND(rent),              sub: 'Chi phí hàng năm',             icon: 'fa-money-bill-transfer',  color: '#ffa94d', bg: 'rgba(255,169,77,.15)' },
    { label: 'Đã Thu K1/2025',      value: fVND(recv25),            sub: `Dự kiến: ${fVND(exp25)}`,      icon: 'fa-circle-dollar-to-slot', color: '#00d2a0', bg: 'rgba(0,210,160,.15)' },
    { label: 'K1/2026 Đã Thanh Toán', value: `${da25} / ${da25+chua25}`, sub: `Còn ${chua25} chưa TT`,  icon: 'fa-check-double',         color: '#38bdf8', bg: 'rgba(56,189,248,.15)' },
  ];

  document.getElementById('kpi-grid').innerHTML = cards.map(c => `
    <div class="kpi-card">
      <div class="kpi-icon" style="color:${c.color};background:${c.bg}"><i class="fa-solid ${c.icon}"></i></div>
      <div class="kpi-body">
        <div class="label">${c.label}</div>
        <div class="value" style="color:${c.color}">${c.value}</div>
        <div class="sub">${c.sub}</div>
      </div>
    </div>`).join('');
}

// ── Charts ────────────────────────────────────────────────
function renderCharts(tong_hop, dt) {
  // 1. Vendor pie
  const cnt = { MOBI: 0, VIETTEL: 0, VINA: 0, KHAC: 0 };
  dt.forEach(r => {
    const nm = (r['Nhà Mạng'] || '').toUpperCase().trim();
    if (nm.includes('MOBI')) cnt.MOBI++;
    else if (nm.includes('VIETTEL')) cnt.VIETTEL++;
    else if (nm.includes('VINA')) cnt.VINA++;
    else cnt.KHAC++;
  });
  if (cVendor) cVendor.destroy();
  cVendor = new Chart(document.getElementById('cVendor'), {
    type: 'doughnut',
    data: {
      labels: ['MobiFone','Viettel','VinaPhone','Khác'],
      datasets: [{ data: [cnt.MOBI, cnt.VIETTEL, cnt.VINA, cnt.KHAC], backgroundColor: ['#6c63ff','#ff5e57','#00d2a0','#8b91a8'], borderWidth: 0 }]
    },
    options: { maintainAspectRatio: false, cutout: '65%', plugins: { legend: { position: 'bottom', labels: { color: '#8b91a8', font: { size: 11 }, boxWidth: 12, padding: 10 } } } }
  });

  // 2. Revenue by vendor
  const rev = { MOBI: 0, VIETTEL: 0, VINA: 0, KHAC: 0 };
  dt.forEach(r => {
    const nm = (r['Nhà Mạng'] || '').toUpperCase().trim();
    const t = +r['[K1_25] Tiền Nhận'] || 0;
    if (nm.includes('MOBI')) rev.MOBI += t;
    else if (nm.includes('VIETTEL')) rev.VIETTEL += t;
    else if (nm.includes('VINA')) rev.VINA += t;
    else rev.KHAC += t;
  });
  if (cRevenue) cRevenue.destroy();
  cRevenue = new Chart(document.getElementById('cRevenue'), {
    type: 'bar',
    data: {
      labels: ['Mobi','Viettel','Vina','Khác'],
      datasets: [{ data: [rev.MOBI, rev.VIETTEL, rev.VINA, rev.KHAC], backgroundColor: ['#6c63ff','#ff5e57','#00d2a0','#8b91a8'], borderRadius: 6, borderSkipped: false }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#8b91a8' } },
        y: { grid: { color: '#1e2132' }, ticks: { color: '#8b91a8', callback: v => v >= 1e9 ? (v/1e9).toFixed(1)+'T' : v >= 1e6 ? (v/1e6).toFixed(0)+'M' : v } }
      }
    }
  });

  // 3. Payment status stacked
  const ks = [
    { k: '[K1_25] Trạng Thái', l: 'K1/25' },
    { k: '[K2_25] Trạng Thái', l: 'K2/25' },
    { k: '[K3_25] Trạng Thái', l: 'K3/25' },
    { k: '[K4_25] Trạng Thái', l: 'K4/25' },
    { k: '[K1_26] Trạng Thái', l: 'K1/26' },
  ];
  const da = [], chua = [], kl = [];
  ks.forEach(p => {
    let d = 0, c = 0;
    dt.forEach(r => { const s = (r[p.k]||'').toUpperCase().trim(); if(s==='ĐÃ TT')d++; else if(s==='CHƯA TT')c++; });
    da.push(d); chua.push(c); kl.push(p.l);
  });
  if (cStatus) cStatus.destroy();
  cStatus = new Chart(document.getElementById('cStatus'), {
    type: 'bar',
    data: {
      labels: kl,
      datasets: [
        { label: 'Đã TT', data: da, backgroundColor: '#00d2a0', borderRadius: 4, borderSkipped: false },
        { label: 'Chưa TT', data: chua, backgroundColor: '#ff5e57', borderRadius: 4, borderSkipped: false }
      ]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: '#8b91a8', boxWidth: 12, font: { size: 11 } } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: '#8b91a8' } },
        y: { stacked: true, grid: { color: '#1e2132' }, ticks: { color: '#8b91a8' } }
      }
    }
  });
}

// ── Table: Thanh Toán (editable) ──────────────────────────
function renderTT(dt, q = '') {
  document.getElementById('tbody-tt').innerHTML = dt.map((r, i) => {
    const ma = r['Mã Trạm Gốc'] || '';
    const nm = r['Nhà Mạng'] || '';
    const nmCls = nm.toUpperCase().includes('MOBI') ? 'blue' : nm.toUpperCase().includes('VIETTEL') ? 'red' : nm.toUpperCase().includes('VINA') ? 'green' : 'gray';
    return `<tr>
      <td style="color:var(--txt2)">${i+1}</td>
      <td style="font-weight:700;color:#a78bfa">${hl(ma, q)}</td>
      <td style="color:var(--txt2);max-width:160px;overflow:hidden;text-overflow:ellipsis">${hl(r['Tên Trạm']||'-', q)}</td>
      <td><span class="pill pill-${nmCls}">${hl(nm||'-', q)}</span></td>
      <td style="text-align:center">${fPct(r['% Sở Hữu'])}</td>
      <td style="text-align:right">${mkPriceEdit(r['[25] Đơn Giá'], ma, nm, '[25] Đơn Giá')}</td>
      <td style="text-align:center">${mkStatusSel(r['[K1_25] Trạng Thái'], ma, nm, '[K1_25] Trạng Thái')}</td>
      <td style="text-align:center">${mkStatusSel(r['[K2_25] Trạng Thái'], ma, nm, '[K2_25] Trạng Thái')}</td>
      <td style="text-align:center">${mkStatusSel(r['[K3_25] Trạng Thái'], ma, nm, '[K3_25] Trạng Thái')}</td>
      <td style="text-align:center">${mkStatusSel(r['[K4_25] Trạng Thái'], ma, nm, '[K4_25] Trạng Thái')}</td>
      <td style="text-align:right">${mkPriceEdit(r['[26] Đơn Giá'], ma, nm, '[26] Đơn Giá')}</td>
      <td style="text-align:center">${mkStatusSel(r['[K1_26] Trạng Thái'], ma, nm, '[K1_26] Trạng Thái')}</td>
    </tr>`;
  }).join('');
}

// ── Table: Danh Mục Trạm ─────────────────────────────────
function renderTram(tong_hop, q = '') {
  document.getElementById('tbody-tram').innerHTML = tong_hop.map((r, i) => {
    const phi = (r['Trạng Thái Trả Phí'] || '').toString();
    const phiCls = phi.toUpperCase().includes('ĐÃ') ? 'green' : phi.toUpperCase().includes('CHƯA') ? 'red' : 'gray';
    return `<tr>
      <td style="color:var(--txt2)">${i+1}</td>
      <td style="font-weight:700;color:#a78bfa">${hl(r['Mã Trạm Gốc']||'-', q)}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${hl(r['Tên Vị Trí/Kiểu Trạm']||'-', q)}</td>
      <td>${hl(r['Tỉnh']||'-', q)}</td>
      <td style="color:var(--txt2)">${hl(r['Người Quản Lý']||'-', q)}</td>
      <td><span class="pill pill-blue">${r['Mã Mobi']||'-'}</span></td>
      <td><span class="pill pill-red">${r['Mã Viettel']||'-'}</span></td>
      <td><span class="pill pill-green">${r['Mã Vina']||'-'}</span></td>
      <td style="text-align:right;font-weight:600">${fVND(r['Tổng Đầu Tư'])}</td>
      <td style="text-align:right">${fVND(r['Tiền Thuê Đất / Năm'])}</td>
      <td><span class="pill pill-${phiCls}">${phi||'-'}</span></td>
    </tr>`;
  }).join('');
}

// ── Search & Filter ───────────────────────────────────────
let _lastTT = [], _lastTram = [];

function hl(text, q) {
  if (!q) return text;
  const safe = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return String(text).replace(new RegExp(`(${safe})`, 'gi'), '<span class="hl">$1</span>');
}

function applySearch() {
  const q = (document.getElementById('search-input')?.value || '').trim().toLowerCase();
  const vendor = (document.getElementById('filter-vendor')?.value || '').toUpperCase();
  const status = document.getElementById('filter-status')?.value || '';

  // Filter doanh_thu
  const fTT = _lastTT.filter(r => {
    const nm = (r['Nhà Mạng'] || '').toUpperCase();
    if (vendor) {
      if (vendor === 'MOBI' && !nm.includes('MOBI')) return false;
      if (vendor === 'VIETTEL' && !nm.includes('VIETTEL')) return false;
      if (vendor === 'VINA' && !nm.includes('VINA')) return false;
    }
    if (status && (r['[K1_26] Trạng Thái'] || '') !== status) return false;
    if (!q) return true;
    return [r['Mã Trạm Gốc'], r['Tên Trạm'], r['Nhà Mạng'], r['Người Phụ Trách'], r['Người nhận tiền']]
      .some(v => String(v || '').toLowerCase().includes(q));
  });

  // Filter tong_hop
  const fTram = _lastTram.filter(r => {
    const nm = (r['Mã Mobi'] || r['Mã Viettel'] || r['Mã Vina'] || '').toUpperCase();
    if (vendor) {
      if (vendor === 'MOBI' && !r['Mã Mobi']) return false;
      if (vendor === 'VIETTEL' && !r['Mã Viettel']) return false;
      if (vendor === 'VINA' && !r['Mã Vina']) return false;
    }
    if (!q) return true;
    return [r['Mã Trạm Gốc'], r['Tên Vị Trí/Kiểu Trạm'], r['Tỉnh'], r['Người Quản Lý']]
      .some(v => String(v || '').toLowerCase().includes(q));
  });

  renderTT(fTT, q);
  renderTram(fTram, q);

  const total = _lastTT.length;
  const shown = fTT.length;
  const cnt = document.getElementById('search-count');
  if (cnt) {
    cnt.innerHTML = q || vendor || status
      ? `<i class="fa-solid fa-filter"></i> ${shown} / ${total} kết quả`
      : `<i class="fa-solid fa-list"></i> ${total} bản ghi`;
  }
}

async function openQR() {
  const modal = document.getElementById('qr-modal');
  modal.classList.add('open');
  document.getElementById('qr-wrap').innerHTML =
    '<i class="fa-solid fa-spinner fa-spin" style="font-size:2rem;color:var(--accent);display:block;margin:40px auto;text-align:center"></i>';
  document.getElementById('qr-url').textContent = '';

  // Thử lấy ngrok URL ngay, nếu chưa có thì thử lại sau 5 giây
  async function _tryFetch(retry = 0) {
    try {
      const info = await (await fetch('/api/network-info')).json();
      const url = info.url;
      const isNgrok = info.type === 'ngrok';

      document.getElementById('qr-url').innerHTML =
        `<span style="color:${isNgrok ? 'var(--accent2)' : 'var(--warn)'}">
          <i class="fa-solid fa-${isNgrok ? 'globe' : 'wifi'}"></i>
          ${isNgrok ? 'Internet (ngrok)' : 'Mạng LAN nội bộ'}
        </span><br><small style="color:var(--txt2)">${url}</small>`;

      document.getElementById('qr-wrap').innerHTML =
        `<img src="https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(url)}&margin=10"
              class="qr-img" width="240" height="240"
              style="display:block;margin:0 auto;border-radius:12px;padding:10px;background:#fff" />`;

      // Nếu là LAN và ngrok chưa sẵn sàng, thử lại
      if (!isNgrok && retry < 6) {
        setTimeout(() => _tryFetch(retry + 1), 5000);
        document.getElementById('qr-url').insertAdjacentHTML('beforeend',
          `<br><small style="color:var(--txt2)"><i class="fa-solid fa-spinner fa-spin"></i> Đang kết nối ngrok... (${6 - retry} lần thử còn lại)</small>`);
      }
    } catch (e) {
      document.getElementById('qr-wrap').innerHTML =
        `<p style="color:var(--danger);padding:20px;text-align:center">Lỗi: ${e.message}</p>`;
    }
  }
  _tryFetch();
}
function closeQR() { document.getElementById('qr-modal').classList.remove('open'); }
document.getElementById('qr-modal').addEventListener('click', e => { if(e.target===e.currentTarget) closeQR(); });

// ── Init ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => loadData(false));
