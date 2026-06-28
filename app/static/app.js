// Hydrate initial Lucide icons
lucide.createIcons();

let jobsCache = [];
let lastDownloadUrl = null;

// Dropzone logic
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('cv_file');
const fileInfo = document.getElementById('fileInfo');
const fileName = document.getElementById('fileName');
const fileError = document.getElementById('fileError');
const redownloadBtn = document.getElementById('redownloadBtn');

dropzone.addEventListener('click', () => fileInput.click());

dropzone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    fileInput.click();
  }
});

dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropzone.classList.add('dragover');
});

['dragleave', 'dragend'].forEach(type => {
  dropzone.addEventListener(type, () => {
    dropzone.classList.remove('dragover');
  });
});

dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    updateFileInfo();
  }
});

fileInput.addEventListener('change', updateFileInfo);

function updateFileInfo() {
  fileError.classList.add('hidden');
  fileError.textContent = '';

  if (fileInput.files.length) {
    const file = fileInput.files[0];
    
    // Validação Client-Side
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      fileError.textContent = 'Por favor, selecione um arquivo PDF válido.';
      fileError.classList.remove('hidden');
      fileInput.value = '';
      fileInfo.style.display = 'none';
      dropzone.style.borderColor = 'var(--error)';
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      fileError.textContent = 'O arquivo excede o limite máximo de 10MB.';
      fileError.classList.remove('hidden');
      fileInput.value = '';
      fileInfo.style.display = 'none';
      dropzone.style.borderColor = 'var(--error)';
      return;
    }

    fileName.textContent = file.name;
    fileInfo.style.display = 'inline-flex';
    dropzone.style.borderColor = 'var(--cta)';
    lucide.createIcons();
  } else {
    fileInfo.style.display = 'none';
    dropzone.style.borderColor = '';
  }
}

async function loadJobs() {
  const select = document.getElementById('job_id');
  const jobError = document.getElementById('jobError');
  
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) throw new Error('Erro ao carregar vagas');
    jobsCache = await res.json();
    select.innerHTML = '';

    jobsCache.forEach(job => {
      const option = document.createElement('option');
      option.value = job.id;
      option.textContent = `${job.titulo} (${job.categoria || 'Geral'})`;
      select.appendChild(option);
    });

    if (jobsCache.length) {
      document.getElementById('descricao_customizada').value = jobsCache[0].descricao;
    }

    select.addEventListener('change', () => {
      const selected = jobsCache.find(j => j.id === select.value);
      document.getElementById('descricao_customizada').value = selected?.descricao || '';
    });
  } catch (err) {
    jobError.classList.remove('hidden');
    select.innerHTML = '<option value="">(Personalizada)</option>';
  }
}

function setStatus(message, type = 'idle') {
  const status = document.getElementById('status');
  
  let iconName = 'info';
  if (type === 'loading') iconName = 'loader';
  if (type === 'success') iconName = 'check-circle';
  if (type === 'error') iconName = 'x-circle';

  status.className = `status-bar ${type}`;
  status.innerHTML = `<i data-lucide="${iconName}" style="width: 16px; height: 16px; flex-shrink: 0;"></i> <span>${message}</span>`;
  lucide.createIcons();
}

function setPills(text, type) {
  const statusPill = document.getElementById('statusPill');
  const resultPill = document.getElementById('resultPill');
  
  statusPill.className = `status-pill ${type}`;
  resultPill.className = `status-pill ${type}`;
  
  let iconName = 'clock';
  if (type === 'success') iconName = 'check';
  if (type === 'warning') iconName = 'alert-circle';
  if (type === 'error') iconName = 'alert-triangle';

  statusPill.innerHTML = `<i data-lucide="${iconName}" style="width: 12px; height: 12px;"></i> <span id="statusPillText">${text}</span>`;
  resultPill.innerHTML = `<i data-lucide="${iconName}" style="width: 12px; height: 12px;"></i> <span id="resultPillText">${text}</span>`;
  lucide.createIcons();
}

// Anti-XSS Markdown Parser
function escapeHTML(str) {
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}

function renderMarkdown(text) {
  if (!text) return '';
  const cleanText = escapeHTML(text);
  
  let html = cleanText
    .replace(/\r/g, '')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .split('\n')
    .map(line => {
      line = line.trim();
      if (line.startsWith('#')) {
        const level = (line.match(/^#+/) || ['#'])[0].length;
        const content = line.replace(/^#+\s*/, '');
        return `<h${level + 1}>${content}</h${level + 1}>`;
      }
      if (line.startsWith('-') || line.startsWith('*')) {
        const content = line.replace(/^[-*]\s*/, '');
        return `<li>${content}</li>`;
      }
      if (line.startsWith('&gt;') || line.startsWith('>')) {
        const content = line.replace(/^(&gt;|>)\s*/, '');
        return `<blockquote>${content}</blockquote>`;
      }
      if (line === '') return '';
      return `<p>${line}</p>`;
    })
    .join('\n');
  
  html = html.replace(/(<li>.*?<\/li>)+/gs, (match) => `<ul>${match}</ul>`);
  return html;
}

function setResult(score, headline, detail, pillType = 'neutral') {
  const scoreNum = document.getElementById('scoreNumber');
  const scoreCircle = document.getElementById('scoreProgress');
  const radius = 75;
  const circumference = 2 * Math.PI * radius;
  
  scoreNum.textContent = score !== null ? score : '--';
  document.getElementById('resultHeadline').textContent = headline || 'Envie o currículo para iniciar a análise.';
  document.getElementById('resultDetail').textContent = detail || 'O relatório em PDF será baixado automaticamente ao final do processamento.';
  
  if (score !== null && !isNaN(score)) {
    const val = parseFloat(score);
    const offset = circumference - (val / 100) * circumference;
    scoreCircle.style.strokeDashoffset = offset;
  } else {
    scoreCircle.style.strokeDashoffset = circumference;
  }

  setPills(
    pillType === 'success' ? 'Concluído' : pillType === 'warning' ? 'Atenção' : pillType === 'error' ? 'Falha' : 'Aguardando',
    pillType
  );
}

function setMetrics({ tech = '--', senior = '--', nlp = '--', friction = '--' } = {}) {
  document.getElementById('metricTech').textContent = tech;
  document.getElementById('metricSenior').textContent = senior;
  document.getElementById('metricNlp').textContent = nlp;
  document.getElementById('metricFriction').textContent = friction;
}

function setAuditText(text) {
  const container = document.getElementById('auditText');
  if (!text) {
    container.textContent = 'Aguardando o processamento do currículo para exibir o parecer executivo, análise de riscos e gaps técnicos.';
  } else {
    container.innerHTML = renderMarkdown(text);
  }
}

function showOverlay(show) {
  document.getElementById('overlay').classList.toggle('hidden', !show);
}

function updateProgress(step, percent, text) {
  document.getElementById('progressBar').style.width = `${percent}%`;
  document.getElementById('progressStepText').textContent = `Etapa ${step}/4: ${text}`;
}

redownloadBtn.addEventListener('click', () => {
  if (lastDownloadUrl) {
    const a = document.createElement('a');
    a.href = lastDownloadUrl;
    a.download = 'diagnostico_ats.pdf';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
});

document.getElementById('atsForm').addEventListener('submit', async (e) => {
  e.preventDefault();

  if (fileInput.files.length === 0 || !fileInput.files[0].name.toLowerCase().endsWith('.pdf')) {
    fileError.textContent = 'Por favor, selecione um arquivo PDF válido.';
    fileError.classList.remove('hidden');
    return;
  }

  const submitBtn = document.getElementById('submitBtn');
  const formData = new FormData(e.target);

  submitBtn.disabled = true;
  submitBtn.classList.add('loading');
  redownloadBtn.classList.add('hidden');
  showOverlay(true);
  setStatus('Processando análise em background...', 'loading');
  setResult(null, 'Processando a solicitação.', 'O sistema está executando a análise neural.', 'neutral');
  setAuditText(null);
  updateProgress(1, 25, 'Extração de texto do PDF');

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      let detail = 'Erro ao processar análise.';
      try {
        const err = await res.json();
        detail = err.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    const initData = await res.json();
    const statusUrl = initData.status_url;

    // Polling loop
    let attempts = 0;
    let successData = null;

    while (attempts < 60) {
      await new Promise(r => setTimeout(r, 2000));
      attempts++;

      if (attempts === 2) {
        updateProgress(2, 50, 'Otimização do currículo e modelagem de similaridade semântica');
      } else if (attempts === 5) {
        updateProgress(3, 75, 'Auditoria neural avançada com modelos DeepSeek');
      }

      const pollRes = await fetch(statusUrl);
      if (!pollRes.ok) throw new Error('Erro ao consultar status da análise.');
      const pollData = await pollRes.json();

      if (pollData.status === 'success') {
        successData = pollData;
        updateProgress(4, 100, 'Concluído');
        break;
      } else if (pollData.status === 'error') {
        throw new Error(pollData.detail || 'Falha na execução do pipeline neural.');
      }
    }

    if (!successData) {
      throw new Error('Tempo limite de processamento excedido.');
    }

    const data = successData;
    lastDownloadUrl = data.download_url;
    redownloadBtn.classList.remove('hidden');

    setStatus(data.detail, 'success');
    setResult(
      data.score_final.toFixed(1),
      data.headline,
      `Vaga: ${data.vaga_alvo}`,
      'success'
    );

    setMetrics({
      tech: `${data.s_tech}/100`,
      senior: `${data.s_senior}/100`,
      nlp: `${data.s_nlp}%`,
      friction: `-${data.penalidade}`,
    });

    if (data.analise_texto) {
      setAuditText(data.analise_texto);
    } else {
      setAuditText('Diagnóstico neural concluído. Veja os detalhes e a recomendação no PDF do relatório executivo.');
    }

    const pdfRes = await fetch(data.download_url);
    if (!pdfRes.ok) throw new Error('Análise concluída, mas não foi possível baixar o PDF.');

    const blob = await pdfRes.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'diagnostico_ats.pdf';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    setStatus(err.message || 'Falha inesperada no processamento.', 'error');
    setResult('--', 'Falha na análise.', err.message || 'Não foi possível gerar o relatório.', 'error');
    setAuditText('Ocorreu um erro no processamento do seu PDF. Detalhes: ' + (err.message || 'Erro de comunicação com o servidor neural.'));
  } finally {
    submitBtn.disabled = false;
    submitBtn.classList.remove('loading');
    showOverlay(false);
  }
});

loadJobs();
