const promptInput = document.getElementById('prompt');
const output = document.getElementById('output');
const runBtn = document.getElementById('runBtn');
const clearBtn = document.getElementById('clearBtn');
const saveBtn = document.getElementById('saveBtn');
const copyBtn = document.getElementById('copyBtn');
const exportMdBtn = document.getElementById('exportMdBtn');
const statusEl = document.getElementById('status');
const tempSlider = document.getElementById('tempSlider');
const tempValue = document.getElementById('tempValue');
const regionSelect = document.getElementById('regionSelect');
const modelSelect = document.getElementById('modelSelect');
const pipelineBtn = document.getElementById('pipelineBtn');
const pipelineStatus = document.getElementById('pipelineStatus');
const pipelineProgress = document.getElementById('pipelineProgress');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const cfgProviderSelect = document.getElementById('cfgProviderSelect');
const cfgModelSelect = document.getElementById('cfgModelSelect');
const cfgApiKey = document.getElementById('cfgApiKey');
const apiKeyField = document.getElementById('apiKeyField');
const applyConfigBtn = document.getElementById('applyConfigBtn');

let apiToken = '';
let lastResponse = '';
let isStreaming = false;
let availableModels = [];

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${apiToken}`
  };
}

async function fetchToken() {
  try {
    const res = await fetch('/api/token');
    const data = await res.json();
    apiToken = data.token || '';
  } catch (e) {
    apiToken = '';
  }
}

async function checkStatus() {
  try {
    const res = await fetch('/api/ollama/status');
    const data = await res.json();
    if (data.ollama_available) {
      statusEl.textContent = `Ollama activo · ${data.model}`;
      statusEl.className = 'status-badge ok';
    } else {
      statusEl.textContent = 'Ollama no responde';
      statusEl.className = 'status-badge error';
    }
  } catch {
    statusEl.textContent = 'Sin conexion';
    statusEl.className = 'status-badge error';
  }
}

async function loadModels() {
  try {
    const res = await fetch('/api/models', { headers: authHeaders() });
    const data = await res.json();
    availableModels = data.models || [];
    const currentModel = data.current_model || '';

    modelSelect.innerHTML = '<option value="">Por defecto</option>';
    cfgModelSelect.innerHTML = '';

    availableModels.forEach(m => {
      const name = typeof m === 'string' ? m : m.name || m.model || '';
      const opt1 = document.createElement('option');
      opt1.value = name;
      opt1.textContent = name;
      if (name === currentModel) opt1.selected = true;
      modelSelect.appendChild(opt1);

      const opt2 = document.createElement('option');
      opt2.value = name;
      opt2.textContent = name;
      if (name === currentModel) opt2.selected = true;
      cfgModelSelect.appendChild(opt2);
    });

    if (availableModels.length === 0) {
      cfgModelSelect.innerHTML = '<option value="">Sin modelos disponibles</option>';
    }

    const countEl = document.getElementById('cfgModelsCount');
    if (countEl) countEl.textContent = availableModels.length;
  } catch {
    modelSelect.innerHTML = '<option value="">Error al cargar</option>';
    cfgModelSelect.innerHTML = '<option value="">Error al cargar</option>';
  }
}

modelSelect.addEventListener('change', async () => {
  const model = modelSelect.value;
  if (!model) return;
  try {
    await fetch('/api/config', {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify({ model })
    });
  } catch {}
});

function renderMarkdown(text) {
  if (typeof marked !== 'undefined') {
    output.innerHTML = marked.parse(text);
  } else {
    output.textContent = text;
  }
}

async function runAnalysis() {
  if (isStreaming) return;
  const prompt = promptInput.value.trim();
  if (!prompt) {
    output.textContent = 'Escribe una pregunta o solicitud para iniciar.';
    return;
  }
  runBtn.disabled = true;
  isStreaming = true;
  output.innerHTML = '';
  lastResponse = '';

  const region = regionSelect.value;
  const systemPrompt = region
    ? `Eres un analista de inteligencia estrategica especializado en ${region}. Responde en espanol con rigor, claridad y contexto geopolitico. Aplica metodologia PMESII-PT.`
    : 'Eres un analista de inteligencia estrategica. Responde en espanol con rigor, claridad y contexto geopolitico. Aplica metodologia PMESII-PT.';

  try {
    const res = await fetch('/api/analyze/stream', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        prompt,
        temperature: parseFloat(tempSlider.value),
        max_tokens: 2000,
        system: systemPrompt,
        model: modelSelect.value || undefined
      })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      output.textContent = `Error: ${errData.error || res.statusText}`;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const payload = line.slice(6);
          if (payload === '[DONE]') continue;
          try {
            const parsed = JSON.parse(payload);
            if (parsed.token) {
              lastResponse += parsed.token;
              renderMarkdown(lastResponse);
            } else if (parsed.chunk) {
              lastResponse += parsed.chunk;
              renderMarkdown(lastResponse);
            } else if (parsed.error) {
              lastResponse += `\n\nError: ${parsed.error}`;
              renderMarkdown(lastResponse);
            }
          } catch {}
        }
      }
    }

    if (!lastResponse) {
      output.textContent = 'No se recibio respuesta del modelo.';
    }
  } catch (error) {
    output.textContent = `Error de conexion: ${error.message}`;
  } finally {
    runBtn.disabled = false;
    isStreaming = false;
  }
}

async function saveToHistory() {
  const prompt = promptInput.value.trim();
  if (!prompt || !lastResponse) return;
  try {
    await fetch('/api/history', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        prompt,
        response: lastResponse,
        region: regionSelect.value,
        model: modelSelect.value
      })
    });
    saveBtn.textContent = 'Guardado';
    setTimeout(() => { saveBtn.textContent = 'Guardar en historial'; }, 2000);
  } catch {
    saveBtn.textContent = 'Error al guardar';
    setTimeout(() => { saveBtn.textContent = 'Guardar en historial'; }, 2000);
  }
}

async function renderHistory() {
  const list = document.getElementById('historyList');
  list.innerHTML = '<p class="empty-state">Cargando historial...</p>';
  try {
    const res = await fetch('/api/history', { headers: authHeaders() });
    const data = await res.json();
    const items = data.history || data.items || data || [];

    if (!Array.isArray(items) || items.length === 0) {
      list.innerHTML = '<p class="empty-state">No hay analisis guardados.</p>';
      return;
    }

    list.innerHTML = items.map((item, i) => {
      const id = item.id || i;
      const date = item.date || item.created_at || '';
      const dateStr = date ? new Date(date).toLocaleString('es-ES') : '';
      const model = item.model || '';
      const region = item.region || '';
      const meta = [dateStr, model, region].filter(Boolean).join(' · ');
      const promptText = (item.prompt || '').substring(0, 120);
      const preview = (item.response || '').substring(0, 150);
      return `
        <div class="history-item" data-id="${id}">
          <div class="history-item-content" onclick="loadHistoryItem('${id}')">
            <div class="h-date">${meta}</div>
            <div class="h-prompt">${promptText}${(item.prompt || '').length > 120 ? '...' : ''}</div>
            <div class="h-preview">${preview}...</div>
          </div>
          <button class="btn-delete" onclick="deleteHistoryItem('${id}', event)" title="Eliminar" aria-label="Eliminar analisis">
            &#x2716;
          </button>
        </div>
      `;
    }).join('');
  } catch {
    list.innerHTML = '<p class="empty-state">Error al cargar el historial.</p>';
  }
}

window.loadHistoryItem = async function(id) {
  try {
    const res = await fetch('/api/history', { headers: authHeaders() });
    const data = await res.json();
    const items = data.history || data.items || data || [];
    const item = items.find(h => (h.id || '').toString() === id.toString());
    if (!item) return;
    promptInput.value = item.prompt || '';
    lastResponse = item.response || '';
    renderMarkdown(lastResponse);
    document.querySelector('[data-section="analysis"]').click();
  } catch {}
};

window.deleteHistoryItem = async function(id, event) {
  event.stopPropagation();
  try {
    const res = await fetch(`/api/history/${id}`, {
      method: 'DELETE',
      headers: authHeaders()
    });
    if (res.ok) {
      renderHistory();
    }
  } catch {}
};

async function launchPipeline() {
  pipelineBtn.disabled = true;
  pipelineStatus.textContent = 'Iniciando pipeline...';
  pipelineProgress.style.display = 'block';
  progressBar.style.width = '0%';
  progressText.textContent = 'Preparando...';

  const days = document.getElementById('daysSelect').value;
  const classification = document.getElementById('classSelect').value;

  try {
    const res = await fetch(`/api/pipeline/stream?days=${days}&classification=${classification}`, {
      headers: authHeaders()
    });

    if (!res.ok) {
      pipelineStatus.textContent = `Error: ${res.statusText}`;
      pipelineProgress.style.display = 'none';
      pipelineBtn.disabled = false;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let reportFile = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const payload = line.slice(6);
          if (payload === '[DONE]') continue;
          try {
            const parsed = JSON.parse(payload);
            if (parsed.country) {
              progressText.textContent = `Procesando: ${parsed.country}`;
            }
            if (parsed.progress !== undefined) {
              const pct = Math.round(parsed.progress);
              progressBar.style.width = `${pct}%`;
              progressBar.setAttribute('aria-valuenow', pct);
            }
            if (parsed.completed !== undefined && parsed.total !== undefined) {
              progressText.textContent = `${parsed.completed}/${parsed.total} paises completados` +
                (parsed.country ? ` · Actual: ${parsed.country}` : '');
            }
            if (parsed.status) {
              pipelineStatus.textContent = parsed.status;
            }
            if (parsed.report) {
              reportFile = parsed.report;
            }
            if (parsed.error) {
              pipelineStatus.textContent = `Error: ${parsed.error}`;
            }
          } catch {}
        }
      }
    }

    if (reportFile) {
      pipelineStatus.innerHTML = `Pipeline completado. <a href="/api/reports/${encodeURIComponent(reportFile)}" class="report-link" download>Descargar reporte</a>`;
    } else {
      pipelineStatus.textContent = pipelineStatus.textContent || 'Pipeline finalizado.';
    }
  } catch (error) {
    pipelineStatus.textContent = `Error de conexion: ${error.message}`;
  } finally {
    pipelineBtn.disabled = false;
  }
}

async function loadReports() {
  const list = document.getElementById('reportsList');
  list.innerHTML = '<p class="empty-state">Cargando reportes...</p>';
  try {
    const res = await fetch('/api/reports', { headers: authHeaders() });
    const data = await res.json();
    const reports = data.reports || data.files || data || [];

    if (!Array.isArray(reports) || reports.length === 0) {
      list.innerHTML = '<p class="empty-state">No hay reportes generados.</p>';
      return;
    }

    list.innerHTML = reports.map(r => {
      const name = typeof r === 'string' ? r : (r.filename || r.name || '');
      const date = r.date || r.created_at || '';
      const size = r.size || '';
      const dateStr = date ? new Date(date).toLocaleString('es-ES') : '';
      const sizeStr = size ? formatSize(size) : '';
      const meta = [dateStr, sizeStr].filter(Boolean).join(' · ');
      return `
        <div class="report-item">
          <div class="report-info">
            <div class="report-name">${name}</div>
            ${meta ? `<div class="report-meta">${meta}</div>` : ''}
          </div>
          <a href="/api/reports/${encodeURIComponent(name)}" class="btn-secondary btn-download" download aria-label="Descargar ${name}">Descargar</a>
        </div>
      `;
    }).join('');
  } catch {
    list.innerHTML = '<p class="empty-state">Error al cargar los reportes.</p>';
  }
}

function formatSize(bytes) {
  if (typeof bytes !== 'number') return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

cfgProviderSelect.addEventListener('change', () => {
  apiKeyField.style.display = cfgProviderSelect.value === 'openai' ? 'flex' : 'none';
});

applyConfigBtn.addEventListener('click', async () => {
  applyConfigBtn.disabled = true;
  applyConfigBtn.textContent = 'Aplicando...';
  const config = {
    provider: cfgProviderSelect.value,
    model: cfgModelSelect.value
  };
  if (cfgProviderSelect.value === 'openai' && cfgApiKey.value.trim()) {
    config.api_key = cfgApiKey.value.trim();
  }
  try {
    const res = await fetch('/api/config', {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify(config)
    });
    if (res.ok) {
      applyConfigBtn.textContent = 'Aplicado';
      loadConfig();
      loadModels();
    } else {
      applyConfigBtn.textContent = 'Error';
    }
  } catch {
    applyConfigBtn.textContent = 'Error';
  }
  setTimeout(() => {
    applyConfigBtn.textContent = 'Aplicar cambios';
    applyConfigBtn.disabled = false;
  }, 2000);
});

function exportMarkdown() {
  if (!lastResponse) return;
  const blob = new Blob([lastResponse], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `analisis_${new Date().toISOString().slice(0, 10)}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

function copyToClipboard() {
  if (!lastResponse) return;
  navigator.clipboard.writeText(lastResponse);
}

document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', (e) => {
    e.preventDefault();
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    item.classList.add('active');
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    const sectionId = `section-${item.dataset.section}`;
    document.getElementById(sectionId)?.classList.add('active');
    if (item.dataset.section === 'history') renderHistory();
    if (item.dataset.section === 'config') loadConfig();
    if (item.dataset.section === 'reports') loadReports();
  });
});

async function loadConfig() {
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    document.getElementById('cfgProvider').textContent = data.provider || '-';
    document.getElementById('cfgModel').textContent = data.model || '-';
    document.getElementById('cfgUrl').textContent = data.ollama_url || 'http://localhost:11434';
    document.getElementById('cfgToken').textContent = apiToken ? apiToken.substring(0, 12) + '...' : 'No disponible';

    if (data.provider) {
      cfgProviderSelect.value = data.provider;
      apiKeyField.style.display = data.provider === 'openai' ? 'flex' : 'none';
    }
  } catch {
    document.getElementById('cfgProvider').textContent = 'Error';
  }
}

tempSlider.addEventListener('input', () => {
  tempValue.textContent = tempSlider.value;
});

runBtn.addEventListener('click', runAnalysis);
clearBtn.addEventListener('click', () => {
  promptInput.value = '';
  output.innerHTML = 'Esperando entrada...';
  lastResponse = '';
});
saveBtn.addEventListener('click', saveToHistory);
copyBtn.addEventListener('click', copyToClipboard);
exportMdBtn.addEventListener('click', exportMarkdown);
pipelineBtn.addEventListener('click', launchPipeline);

promptInput.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    runAnalysis();
  }
});

fetchToken().then(() => {
  checkStatus();
  loadModels();
});
