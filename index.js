const WEBHOOK_URL = 'https://n8n-n8n.ppnoc4.easypanel.host/webhook/b433705d-ac26-4c0a-a4f5-4a945a31efb9';
const SQL_WEBHOOK_URL = 'https://n8n-n8n.ppnoc4.easypanel.host/webhook/f77ba4cd-67ca-4ab4-8c00-be8a38152f6e';

const USER = JSON.parse(localStorage.getItem('havi_user')) || {
  user_id: 'TEST_01',
  nombre: 'User',
  edad: 25,
  ingreso_mensual_mxn: 35000,
  score_buro: 720,
  antiguedad_dias: 5,
  num_productos_activos: 1,
  es_hey_pro: 1,
  nomina_domiciliada: 0,
  recibe_remesas: 0,
  ocupacion: 'Empleado',
  nivel_educativo: 'Universidad',
  canal_apertura: 'app',
  classificationString: '',
};

window.USER_ID = USER.user_id;
window.CLASSIFICATION_STRING = USER.classificationString || '';

// Se genera una sola vez por sesión de chat
const SESSION_ID = Math.floor(1000000000 + Math.random() * 9000000000).toString();

const messagesEl = document.getElementById('messages');
const msgInput = document.getElementById('msgInput');
const sendBtn = document.getElementById('sendBtn');

function appendMessage(text, sender) {
  const div = document.createElement('div');
  div.classList.add('message', sender === 'bot' ? 'havi' : 'user');
  const bubble = document.createElement('div');
  bubble.classList.add('bubble');
  bubble.textContent = text;
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ───────────── Gráficas dinámicas ─────────────
const HAVI_CHART_PALETTE = ['#4D96FF', '#FF5E5E', '#FFD93D', '#b8b0e8', '#22c55e', '#FF9F40', '#2563eb'];
const HAVI_CHART_TYPES = ['bar', 'line', 'area', 'pie', 'doughnut'];

const SAMPLE_LABEL_SETS = [
  ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun'],
  ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
  ['S1', 'S2', 'S3', 'S4'],
  ['Comida', 'Transporte', 'Ocio', 'Servicios', 'Ahorro'],
  ['Nómina', 'Tarjeta', 'Crédito', 'Inversión'],
];

const SAMPLE_TITLES = [
  'Gastos por categoría',
  'Ingresos mensuales',
  'Distribución de ahorro',
  'Movimientos recientes',
  'Tendencia semanal',
  'Resumen financiero',
];

function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

function generateRandomChartConfig() {
  const type = pick(HAVI_CHART_TYPES);
  const labels = pick(SAMPLE_LABEL_SETS).slice();
  const data = labels.map(() => Math.floor(Math.random() * 90) + 10);
  return { type, title: pick(SAMPLE_TITLES), labels, datasets: [{ label: '', data }] };
}

// Convierte un valor a número (acepta strings con comas)
function toNumber(v) {
  if (v === null || v === undefined || v === '') return 0;
  const n = parseFloat(String(v).replace(/,/g, ''));
  return isNaN(n) ? 0 : n;
}

function applyOperation(matchingRows, valueCol, op) {
  if (op === 'count') return matchingRows.length;
  const values = matchingRows.map(r => toNumber(r[valueCol])).filter(v => !isNaN(v));
  if (!values.length) return 0;
  switch (op) {
    case 'sum': return values.reduce((a, b) => a + b, 0);
    case 'avg': return Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 100) / 100;
    case 'max': return Math.max(...values);
    case 'min': return Math.min(...values);
    default:    return values.reduce((a, b) => a + b, 0);
  }
}

// Normaliza varios formatos a: { type, title, labels, datasets:[{label,data}] }
// Soporta:
//  · Formato Reporteador → cfg = { type, mode, x, y[], group, operation, value, title }, rows = [...]
//  · Directo simple      → cfg = { type, title, labels, data }
//  · Directo con rows    → cfg = { type, rows, x, y, title }
// Devuelve null si la config está vacía / inválida o si rows está vacío.
function normalizeChartConfig(cfg, rowsParam) {
  if (!cfg || typeof cfg !== 'object') return null;

  const type  = cfg.type || 'bar';
  const title = cfg.title || '';

  if (Array.isArray(cfg.labels) && Array.isArray(cfg.data) && cfg.labels.length) {
    return { type, title, labels: cfg.labels, datasets: [{ label: cfg.label || '', data: cfg.data }] };
  }

  const rows = Array.isArray(rowsParam) ? rowsParam : (Array.isArray(cfg.rows) ? cfg.rows : null);
  if (!rows || !rows.length) return null;

  const mode = (cfg.mode || 'direct').toLowerCase();

  if (mode === 'grouped' && cfg.x && cfg.group) {
    const xCol   = cfg.x;
    const gCol   = cfg.group;
    const op     = cfg.operation || 'count';
    const valCol = op !== 'count' ? cfg.value : null;

    const labels      = [...new Set(rows.map(r => String(r[xCol] ?? '')))];
    const groupValues = [...new Set(rows.map(r => String(r[gCol] ?? '')))];

    const datasets = groupValues.map(gv => ({
      label: gv,
      data: labels.map(lv => {
        const matching = rows.filter(r =>
          String(r[xCol] ?? '') === lv && String(r[gCol] ?? '') === gv
        );
        return applyOperation(matching, valCol, op);
      })
    }));
    return { type, title, labels, datasets };
  }

  // Modo directo: x + y[]
  const xCol  = cfg.x;
  const yCols = Array.isArray(cfg.y) ? cfg.y : (cfg.y ? [cfg.y] : null);
  if (!xCol || !yCols || !yCols.length) return null;

  const labels   = rows.map(r => String(r[xCol] ?? ''));
  const datasets = yCols.map(col => ({
    label: String(col).replace(/_/g, ' '),
    data:  rows.map(r => toNumber(r[col])),
  }));
  return { type, title, labels, datasets };
}

// Extrae rows. Busca en orden: response_rows, response_data, datos, response_query (solo si NO es SQL).
function extractRows(data) {
  if (!data) return null;
  const candidates = [data.response_rows, data.response_data, data.rows, data.datos, data.response_query];
  for (const raw of candidates) {
    if (raw === undefined || raw === null || raw === '') continue;
    if (Array.isArray(raw)) return raw;
    if (typeof raw === 'string') {
      // Si parece SQL crudo (empieza con SELECT/WITH/etc.), saltar
      if (/^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)\b/i.test(raw)) continue;
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed;
        const r = parsed.Resultado ?? parsed.resultado ?? parsed.rows ?? null;
        if (Array.isArray(r)) return r;
      } catch (_) { /* probar siguiente candidato */ }
    }
    if (typeof raw === 'object') {
      const r = raw.Resultado ?? raw.resultado ?? raw.rows ?? null;
      if (Array.isArray(r)) return r;
    }
  }
  return null;
}

// Acepta el chart como objeto o string JSON.
function parseChartCfg(raw) {
  if (!raw) return null;
  if (typeof raw === 'object') return raw;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch (_) { return null; }
  }
  return null;
}

function hexToRgba(hex, a) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

function buildEchartsOption({ type, labels, datasets }) {
  const isPolar = type === 'pie' || type === 'doughnut' || type === 'polarArea';
  const base = {
    color: HAVI_CHART_PALETTE,
    backgroundColor: 'transparent',
    animationDuration: 900,
    animationEasing: 'cubicOut',
    textStyle: { color: '#cfcfd6', fontSize: 11 },
    tooltip: {
      backgroundColor: 'rgba(20,20,28,0.95)',
      borderColor: 'rgba(77,150,255,0.4)',
      borderWidth: 1,
      textStyle: { color: '#fff', fontSize: 12 },
      padding: [6, 10],
    },
  };

  const showLegend = datasets.length > 1;
  const legend = showLegend ? {
    data: datasets.map(d => d.label),
    bottom: 0,
    type: 'scroll',
    textStyle: { color: '#9a9aa3', fontSize: 10 },
    itemWidth: 10, itemHeight: 8,
  } : undefined;

  if (isPolar) {
    const ds = datasets[0] || { data: [] };
    return {
      ...base,
      tooltip: { ...base.tooltip, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie',
        radius: type === 'doughnut' ? ['48%', '72%'] : '70%',
        center: ['50%', '52%'],
        roseType: type === 'polarArea' ? 'area' : undefined,
        data: labels.map((l, i) => ({ name: l, value: ds.data[i] ?? 0 })),
        label: { color: '#cfcfd6', fontSize: 10 },
        labelLine: { lineStyle: { color: '#3a3a44' } },
        itemStyle: { borderColor: '#14141b', borderWidth: 2 },
        emphasis: { itemStyle: { shadowBlur: 14, shadowColor: 'rgba(77,150,255,0.5)' } },
        animationType: 'expansion',
      }],
    };
  }

  if (type === 'barH') {
    return {
      ...base,
      tooltip: { ...base.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend,
      grid: { left: 4, right: 12, top: 14, bottom: showLegend ? 28 : 4, containLabel: true },
      xAxis: {
        type: 'value',
        axisLine: { show: false }, axisTick: { show: false },
        splitLine: { lineStyle: { color: '#1f1f24' } },
        axisLabel: { color: '#9a9aa3', fontSize: 10 },
      },
      yAxis: {
        type: 'category',
        data: labels,
        axisLine: { lineStyle: { color: '#2a2a30' } },
        axisTick: { show: false },
        axisLabel: { color: '#9a9aa3', fontSize: 10 },
      },
      series: datasets.map((ds, i) => ({
        name: ds.label,
        type: 'bar',
        data: ds.data,
        itemStyle: { color: HAVI_CHART_PALETTE[i % HAVI_CHART_PALETTE.length], borderRadius: [0, 6, 6, 0] },
      })),
    };
  }

  const isLine = type === 'line' || type === 'area';
  return {
    ...base,
    tooltip: { ...base.tooltip, trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: 'rgba(77,150,255,0.4)' } } },
    legend,
    grid: { left: 4, right: 12, top: 14, bottom: showLegend ? 28 : 4, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: '#2a2a30' } },
      axisTick: { show: false },
      axisLabel: { color: '#9a9aa3', fontSize: 10, rotate: labels.length > 8 ? 30 : 0 },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#1f1f24' } },
      axisLabel: { color: '#9a9aa3', fontSize: 10 },
    },
    series: datasets.map((ds, i) => {
      const color = HAVI_CHART_PALETTE[i % HAVI_CHART_PALETTE.length];
      return {
        name: ds.label,
        type: isLine ? 'line' : 'bar',
        data: ds.data,
        smooth: isLine ? 0.4 : undefined,
        symbol: isLine ? 'circle' : undefined,
        symbolSize: isLine ? 6 : undefined,
        lineStyle: isLine ? { width: 2.5, color } : undefined,
        itemStyle: isLine
          ? { color, borderColor: '#0a0a0e', borderWidth: 2 }
          : {
              color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                colorStops: [{ offset: 0, color }, { offset: 1, color: hexToRgba(color, 0.55) }] },
              borderRadius: [6, 6, 0, 0],
            },
        areaStyle: type === 'area' ? {
          color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: hexToRgba(color, 0.55) }, { offset: 1, color: hexToRgba(color, 0) }] },
        } : undefined,
        barWidth: type === 'bar' ? (datasets.length > 1 ? undefined : '52%') : undefined,
        animationDelay: (idx) => idx * 60 + i * 40,
      };
    }),
  };
}

// Crea la burbuja con loader y devuelve helpers para inyectar el chart o un mensaje de error.
function appendChartShell(title) {
  const div = document.createElement('div');
  div.classList.add('message', 'havi', 'chart-message');

  const wrapper = document.createElement('div');
  wrapper.classList.add('chart-wrapper');

  if (title) {
    const titleEl = document.createElement('div');
    titleEl.classList.add('chart-title-mini');
    titleEl.textContent = title;
    wrapper.appendChild(titleEl);
  }

  const loading = document.createElement('div');
  loading.classList.add('chart-loading');
  loading.innerHTML = `
    <div class="chart-loading-bars">
      <span></span><span></span><span></span><span></span><span></span>
    </div>
    <div class="chart-loading-text">Consultando datos</div>
  `;
  wrapper.appendChild(loading);

  div.appendChild(wrapper);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  requestAnimationFrame(() => wrapper.classList.add('show'));

  return {
    renderChart(config) {
      loading.remove();
      const canvas = document.createElement('div');
      canvas.classList.add('chart-canvas');
      wrapper.appendChild(canvas);
      const chart = echarts.init(canvas);
      chart.setOption(buildEchartsOption(config));
      window.addEventListener('resize', () => chart.resize());
      messagesEl.scrollTop = messagesEl.scrollHeight;
    },
    renderEmpty(text) {
      loading.remove();
      const empty = document.createElement('div');
      empty.classList.add('chart-empty');
      empty.innerHTML = `
        <div class="chart-empty-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="9"/>
            <line x1="8" y1="12" x2="16" y2="12"/>
          </svg>
        </div>
        <div class="chart-empty-text">${text || 'No hay datos para mostrar'}</div>
      `;
      wrapper.appendChild(empty);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    },
  };
}

async function fetchRowsFromSql(sqlQuery) {
  console.log('[chart] POST SQL webhook:', sqlQuery);
  const res = await fetch(SQL_WEBHOOK_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql_query: sqlQuery }),
  });
  if (!res.ok) throw new Error('SQL webhook HTTP ' + res.status);
  const data = await res.json();
  console.log('[chart] SQL webhook response:', data);
  if (Array.isArray(data)) {
    if (data[0]?.json) return data.map(i => i.json); // n8n a veces envuelve en {json:{...}}
    return data;
  }
  if (Array.isArray(data?.rows)) return data.rows;
  if (Array.isArray(data?.Resultado)) return data.Resultado;
  if (Array.isArray(data?.data)) return data.data;
  // Si llega un solo objeto-fila, envolverlo en array
  if (data && typeof data === 'object' && Object.keys(data).length) return [data];
  return [];
}

async function appendChartFromAgent(chartCfg, sqlQuery) {
  console.log('[chart] appendChartFromAgent', { chartCfg, sqlQuery });
  if (typeof echarts === 'undefined') {
    console.error('[chart] echarts no está cargado');
    return;
  }
  const cfg = parseChartCfg(chartCfg);
  console.log('[chart] parsed config:', cfg);
  if (!cfg) {
    console.warn('[chart] no se pudo parsear chartConfig');
    return;
  }

  const shell = appendChartShell(cfg.title || '');

  if (!sqlQuery) {
    console.warn('[chart] sin sqlQuery → no hay datos');
    shell.renderEmpty('No hay datos para mostrar');
    return;
  }

  try {
    const rows = await fetchRowsFromSql(sqlQuery);
    console.log('[chart] rows recibidas:', rows?.length, rows);
    if (!rows || !rows.length) {
      shell.renderEmpty('No hay datos para mostrar');
      return;
    }
    const config = normalizeChartConfig(cfg, rows);
    console.log('[chart] config normalizada:', config);
    if (!config) {
      shell.renderEmpty('No hay datos para mostrar');
      return;
    }
    shell.renderChart(config);
  } catch (err) {
    console.error('[chart] error:', err);
    shell.renderEmpty('No hay datos para mostrar');
  }
}

function appendTyping() {
  const div = document.createElement('div');
  div.classList.add('message', 'havi');
  div.id = 'typing';
  const bubble = document.createElement('div');
  bubble.classList.add('bubble', 'typing-bubble');
  bubble.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('typing');
  if (el) el.remove();
}

async function sendMessage() {
  const text = msgInput.value.trim();
  if (!text) return;

  appendMessage(text, 'user');
  msgInput.value = '';
  sendBtn.disabled = true;
  appendTyping();

  try {
    const res = await fetch(WEBHOOK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: SESSION_ID,
        mensaje: text,
        user_id: window.USER_ID,
        nombre: USER.nombre,
        classificationString: window.CLASSIFICATION_STRING,
      }),
    });

    let data = await res.json();
    console.log('[chat] respuesta webhook chat:', data);
    // El webhook puede devolver un array con un solo objeto: [{...}]. Desempaquetar.
    if (Array.isArray(data)) data = data[0] ?? {};
    console.log('[chat] data desempaquetada:', data);
    removeTyping();

    const reply = data.response_message ?? data.mensaje ?? data.output ?? data.message ?? data.text ?? data.response ?? '';
    if (reply) appendMessage(reply, 'bot');

    // Si el agente pide gráfica, consultar el segundo webhook con el SQL para obtener filas
    const chartCfg = data.response_chart ?? data.chartConfig;
    const sqlQuery = data.response_query ?? '';
    if (chartCfg) {
      appendChartFromAgent(chartCfg, sqlQuery);
    }
  } catch (err) {
    removeTyping();
    appendMessage('No pude conectarme con HAVI. Intenta de nuevo.', 'bot');
  } finally {
    sendBtn.disabled = false;
    msgInput.focus();
  }
}

sendBtn.addEventListener('click', sendMessage);
msgInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMessage();
});

appendMessage('¡Hola! Soy HAVI, tu asistente financiero. ¿En qué te puedo ayudar hoy?', 'bot');