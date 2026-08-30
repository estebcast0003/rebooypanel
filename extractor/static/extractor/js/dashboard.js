/**
 * Facebook Fan Extractor Dashboard Client Script
 * Handles real-time SSE streaming, Polling Fallback, Auto-Refresh Scheduler,
 * Drag & Drop, Auto-save cache, and Table DOM manipulation.
 */

const API_BASE = window.EXTRACTOR_API_BASE || '/extractor';

let activeEventSource = null;
let activePollingInterval = null;
let saveCacheTimeout = null;
let schedulerCountdownInterval = null;
let schedulerRemainingSeconds = 0;

document.addEventListener('DOMContentLoaded', () => {
    initTextareaControls();
    initDropZone();
    initButtons();
    initSearchFilter();
    initSchedulerControls();
    updateUrlCount();
});

// ----------------------------------------------------
// CSRF Token Helper
// ----------------------------------------------------
function getCsrfToken() {
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input) return input.value;
    const cookieValue = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1];
    return cookieValue || '';
}

// ----------------------------------------------------
// Auto-Refresh Scheduler Controls
// ----------------------------------------------------
function initSchedulerControls() {
    const toggle = document.getElementById('schedulerToggle');
    const intervalSelect = document.getElementById('schedulerIntervalSelect');
    const btnTriggerNow = document.getElementById('btnTriggerScheduledNow');

    if (toggle) {
        toggle.addEventListener('change', () => {
            saveSchedulerConfig();
        });
    }

    if (intervalSelect) {
        intervalSelect.addEventListener('change', () => {
            saveSchedulerConfig();
        });
    }

    if (btnTriggerNow) {
        btnTriggerNow.addEventListener('click', async () => {
            btnTriggerNow.disabled = true;
            try {
                const res = await fetch(`${API_BASE}/api/scheduler/trigger/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                    }
                });
                const data = await res.json();
                if (data.status === 'ok' && data.job_id) {
                    showToast(data.message, 'info');
                    coordinateJobMonitoring(data.job_id, 0);
                    syncSchedulerStatus();
                } else {
                    showToast(data.message || 'Error al disparar actualización', 'warning');
                }
            } catch (err) {
                console.error('Error triggering scheduler now:', err);
                showToast('Error de conexión', 'error');
            } finally {
                btnTriggerNow.disabled = false;
            }
        });
    }

    // Initial status sync & start countdown timer
    syncSchedulerStatus();
    startSchedulerCountdownTimer();
}

async function saveSchedulerConfig() {
    const toggle = document.getElementById('schedulerToggle');
    const intervalSelect = document.getElementById('schedulerIntervalSelect');

    const enabled = toggle?.checked || false;
    const intervalMinutes = parseInt(intervalSelect?.value || '60', 10);

    try {
        const res = await fetch(`${API_BASE}/api/scheduler/update/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({
                enabled: enabled,
                interval_minutes: intervalMinutes,
            })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(data.message, 'success');
            updateSchedulerUI(data.scheduler);
        } else {
            showToast(data.message || 'Error al guardar programador', 'error');
        }
    } catch (err) {
        console.error('Error saving scheduler config:', err);
        showToast('Error al conectar con el servidor', 'error');
    }
}

async function syncSchedulerStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/scheduler/status/`);
        if (res.ok) {
            const data = await res.json();
            if (data.scheduler) {
                updateSchedulerUI(data.scheduler);
            }
        }
    } catch (err) {
        console.warn('Could not sync scheduler status:', err);
    }
}

function updateSchedulerUI(sched) {
    const toggle = document.getElementById('schedulerToggle');
    const intervalSelect = document.getElementById('schedulerIntervalSelect');
    const countdownEl = document.getElementById('schedulerCountdown');
    const track = document.getElementById('schedulerToggleTrack');
    const thumb = document.getElementById('schedulerToggleThumb');
    const statusIcon = document.getElementById('schedulerStatusIcon');

    if (toggle) toggle.checked = !!sched.enabled;
    if (track) track.style.background = sched.enabled ? '#3b82f6' : 'rgba(255,255,255,0.15)';
    if (thumb) thumb.style.left = sched.enabled ? '20px' : '2px';
    if (statusIcon) {
        if (sched.enabled) {
            statusIcon.style.color = '#3b82f6';
        } else {
            statusIcon.style.color = '#94a3b8';
        }
    }

    if (intervalSelect && sched.interval_minutes) {
        intervalSelect.value = String(sched.interval_minutes);
    }

    schedulerRemainingSeconds = sched.remaining_seconds || 0;

    if (!sched.enabled) {
        if (countdownEl) countdownEl.textContent = 'Pausado';
    } else {
        renderCountdownText();
    }
}

function startSchedulerCountdownTimer() {
    clearInterval(schedulerCountdownInterval);
    schedulerCountdownInterval = setInterval(() => {
        const toggle = document.getElementById('schedulerToggle');
        if (!toggle || !toggle.checked) {
            const countdownEl = document.getElementById('schedulerCountdown');
            if (countdownEl) countdownEl.textContent = 'Pausado';
            return;
        }

        if (schedulerRemainingSeconds > 0) {
            schedulerRemainingSeconds--;
            renderCountdownText();
        } else {
            // Check if scheduler triggered
            syncSchedulerStatus();
        }
    }, 1000);
}

function renderCountdownText() {
    const countdownEl = document.getElementById('schedulerCountdown');
    if (!countdownEl) return;

    if (schedulerRemainingSeconds <= 0) {
        countdownEl.textContent = 'En ejecución...';
        return;
    }

    const hours = Math.floor(schedulerRemainingSeconds / 3600);
    const minutes = Math.floor((schedulerRemainingSeconds % 3600) / 60);
    const seconds = schedulerRemainingSeconds % 60;

    if (hours > 0) {
        countdownEl.textContent = `${hours}h ${minutes.toString().padStart(2, '0')}m`;
    } else {
        countdownEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')} min`;
    }
}

// ----------------------------------------------------
// Textarea & Cache Persistence
// ----------------------------------------------------
function initTextareaControls() {
    const textarea = document.getElementById('urlsTextarea');
    if (!textarea) return;

    textarea.addEventListener('input', () => {
        updateUrlCount();
        scheduleCacheSave(textarea.value);
    });
}

function updateUrlCount() {
    const textarea = document.getElementById('urlsTextarea');
    const badge = document.getElementById('urlCountBadge');
    if (!textarea || !badge) return;

    const lines = textarea.value.split('\n').filter(line => line.trim().length > 0);
    badge.textContent = `${lines.length} ${lines.length === 1 ? 'URL' : 'URLs'}`;
}

function scheduleCacheSave(text) {
    clearTimeout(saveCacheTimeout);
    const indicator = document.getElementById('cacheSaveIndicator');

    saveCacheTimeout = setTimeout(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/save-cache/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify({ urls: text })
            });
            if (res.ok && indicator) {
                indicator.style.opacity = '1';
                setTimeout(() => { indicator.style.opacity = '0'; }, 1500);
            }
        } catch (err) {
            console.error('Error saving urls cache:', err);
        }
    }, 800);
}

// ----------------------------------------------------
// Drag & Drop / File Input
// ----------------------------------------------------
function initDropZone() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const textarea = document.getElementById('urlsTextarea');

    if (!dropZone || !fileInput || !textarea) return;

    dropZone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) readFile(file);
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.add('border-blue-500', 'bg-blue-500/10');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropZone.classList.remove('border-blue-500', 'bg-blue-500/10');
        });
    });

    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const file = dt.files[0];
        if (file) readFile(file);
    });

    function readFile(file) {
        if (!file.name.endsWith('.txt')) {
            showToast('Por favor seleccioná un archivo de texto (.txt)', 'error');
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            textarea.value = e.target.result;
            updateUrlCount();
            scheduleCacheSave(textarea.value);
            showToast(`Archivo "${file.name}" cargado correctamente`, 'success');
        };
        reader.readAsText(file);
    }
}

// ----------------------------------------------------
// Action Buttons
// ----------------------------------------------------
function initButtons() {
    const btnStart = document.getElementById('btnStartExtraction');
    const btnCopy = document.getElementById('btnCopyUrls');
    const btnClear = document.getElementById('btnClearUrls');
    const textarea = document.getElementById('urlsTextarea');

    if (btnStart) {
        btnStart.addEventListener('click', startExtraction);
    }

    if (btnCopy && textarea) {
        btnCopy.addEventListener('click', async () => {
            if (!textarea.value.trim()) {
                showToast('No hay URLs para copiar', 'info');
                return;
            }
            try {
                await navigator.clipboard.writeText(textarea.value);
                showToast('URLs copiadas al portapapeles', 'success');
            } catch {
                showToast('Error al copiar al portapapeles', 'error');
            }
        });
    }

    if (btnClear && textarea) {
        btnClear.addEventListener('click', () => {
            if (textarea.value.trim()) {
                textarea.value = '';
                updateUrlCount();
                scheduleCacheSave('');
                showToast('Formulario vaciado', 'info');
            }
        });
    }
}

// ----------------------------------------------------
// Start Extraction & Real-Time Coordination (SSE + Polling)
// ----------------------------------------------------
async function startExtraction() {
    const textarea = document.getElementById('urlsTextarea');
    const urlsText = textarea?.value.trim() || '';

    if (!urlsText) {
        showToast('Pegá o cargá al menos una URL de Facebook para iniciar', 'error');
        return;
    }

    // Cerrar el modal inmediatamente para volver al Dashboard
    if (typeof closeExtractionModal === 'function') {
        closeExtractionModal();
    }

    setExtractionRunningState(true);

    try {
        const response = await fetch(`${API_BASE}/api/extract/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ urls: urlsText }),
        });

        const data = await response.json();

        if (!response.ok || data.status !== 'ok') {
            showToast(data.message || 'Error al iniciar la extracción', 'error');
            setExtractionRunningState(false);
            return;
        }

        showToast(`Extracción iniciada para ${data.total_urls} URLs`, 'info');
        coordinateJobMonitoring(data.job_id, data.total_urls);

    } catch (err) {
        console.error('Error starting extraction:', err);
        showToast('Error de conexión con el servidor', 'error');
        setExtractionRunningState(false);
    }
}

function coordinateJobMonitoring(jobId, totalUrls) {
    cleanupJobMonitoring();

    const progressContainers = document.querySelectorAll('#liveProgressContainer, .liveProgressContainer');
    progressContainers.forEach(container => {
        container.style.display = 'block';
        container.classList.remove('hidden');
    });

    const progressBars = document.querySelectorAll('#progressBarFill, .progressBarFill');
    const progressLabels = document.querySelectorAll('#progressCounterLabel, .progressCounterLabel');

    progressBars.forEach(bar => bar.style.width = '0%');
    progressLabels.forEach(label => label.textContent = `0 / ${totalUrls || '?'} (0%)`);

    // 1. Setup Server-Sent Events (SSE)
    try {
        activeEventSource = new EventSource(`${API_BASE}/api/stream/${jobId}/`);

        activeEventSource.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                const payload = message.data;

                if (message.event === 'item') {
                    upsertTableRow(payload);
                    updateProgressBar(payload.processed, payload.total);
                    refreshGlobalMetrics();
                } else if (message.event === 'completed') {
                    onJobCompleted(payload);
                }
            } catch (e) {
                console.error('Error parsing SSE payload:', e);
            }
        };

        activeEventSource.onerror = () => {
            // If SSE fails or drops, polling takes over seamlessly
            if (activeEventSource) {
                activeEventSource.close();
                activeEventSource = null;
            }
        };
    } catch (e) {
        console.warn('SSE not supported or connection error, using polling fallback', e);
    }

    // 2. Setup Polling Fallback Safety Net (every 1.5s)
    activePollingInterval = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/job/${jobId}/status/`);
            if (res.ok) {
                const jobData = await res.json();
                if (jobData.items && jobData.items.length > 0) {
                    jobData.items.forEach(item => upsertTableRow({
                        id: item.id,
                        url: item.url,
                        name: item.name,
                        followers: item.followers,
                        status: item.status,
                        is_success: item.is_success,
                    }));
                }
                updateProgressBar(jobData.processed, jobData.total);
                refreshGlobalMetrics();

                if (jobData.status === 'COMPLETED' || jobData.status === 'FAILED') {
                    onJobCompleted({
                        total: jobData.total,
                        processed: jobData.processed,
                        successful: jobData.successful,
                        failed: jobData.failed,
                    });
                }
            }
        } catch (pollErr) {
            console.error('Error polling job status:', pollErr);
        }
    }, 1500);
}

function onJobCompleted(payload) {
    cleanupJobMonitoring();
    setExtractionRunningState(false);
    updateProgressBar(payload.total, payload.total);
    refreshGlobalMetrics();
    showToast(`¡Extracción completada! ${payload.successful} exitosas, ${payload.failed} con error`, payload.successful > 0 ? 'success' : 'info');

    setTimeout(() => {
        const progressContainers = document.querySelectorAll('#liveProgressContainer, .liveProgressContainer');
        progressContainers.forEach(container => {
            container.style.display = 'none';
        });
    }, 3500);
}

function cleanupJobMonitoring() {
    if (activeEventSource) {
        activeEventSource.close();
        activeEventSource = null;
    }
    if (activePollingInterval) {
        clearInterval(activePollingInterval);
        activePollingInterval = null;
    }
}

function setExtractionRunningState(isRunning) {
    const btnStart = document.getElementById('btnStartExtraction');
    const btnStartText = document.getElementById('btnStartText');
    const btnStartIcon = document.getElementById('btnStartIcon');
    const engineText = document.getElementById('engineStatusText');
    const enginePulse = document.getElementById('enginePulseDot');

    if (isRunning) {
        if (btnStart) btnStart.disabled = true;
        if (btnStartText) btnStartText.textContent = 'Extrayendo...';
        if (btnStartIcon) {
            btnStartIcon.setAttribute('data-lucide', 'loader-2');
            btnStartIcon.classList.add('animate-spin');
        }
        if (engineText) engineText.textContent = 'Extrayendo';
        if (enginePulse) enginePulse.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-ping';
    } else {
        if (btnStart) btnStart.disabled = false;
        if (btnStartText) btnStartText.textContent = 'Iniciar Extracción';
        if (btnStartIcon) {
            btnStartIcon.setAttribute('data-lucide', 'play');
            btnStartIcon.classList.remove('animate-spin');
        }
        if (engineText) engineText.textContent = 'En espera';
        if (enginePulse) enginePulse.className = 'w-2 h-2 rounded-full bg-zinc-500';
    }
    lucide.createIcons();
}

function updateProgressBar(processed, total) {
    const progressBars = document.querySelectorAll('#progressBarFill, .progressBarFill');
    const progressLabels = document.querySelectorAll('#progressCounterLabel, .progressCounterLabel');
    if (!total || total <= 0) return;

    const percent = Math.min(100, Math.round((processed / total) * 100));
    progressBars.forEach(bar => bar.style.width = `${percent}%`);
    progressLabels.forEach(label => label.textContent = `${processed} / ${total} (${percent}%)`);
}

function formatCompactNumber(num) {
    const n = Number(num);
    if (isNaN(n) || n === 0) return '0';
    if (n < 1000) return String(Math.round(n));
    if (n < 1000000) {
        const val = (n / 1000).toFixed(1);
        return val.endsWith('.0') ? `${parseInt(val, 10)}K` : `${val}K`;
    }
    if (n < 1000000000) {
        const val = (n / 1000000).toFixed(1);
        return val.endsWith('.0') ? `${parseInt(val, 10)}M` : `${val}M`;
    }
    const val = (n / 1000000000).toFixed(1);
    return val.endsWith('.0') ? `${parseInt(val, 10)}B` : `${val}B`;
}

// ----------------------------------------------------
// Table DOM Operations
// ----------------------------------------------------
function upsertTableRow(data) {
    const tbody = document.getElementById('pagesTableBody');
    if (!tbody) return;

    const emptyMsg = document.getElementById('emptyTableMessage');
    if (emptyMsg) emptyMsg.remove();

    const rowId = data.id ? `row-page-${data.id}` : `row-url-${btoa(data.url).replace(/=/g, '')}`;
    let row = document.getElementById(rowId);

    const followersFormatted = formatCompactNumber(data.followers);
    const followersExact = Number(data.followers || 0).toLocaleString();
    const isSuccess = data.is_success || data.followers > 0;
    const displayName = data.name || 'Desconocido';
    const displayStatus = data.status || (isSuccess ? 'Éxito' : 'Error');
    const growth = data.growth || { formatted_delta: '0', formatted_pct: '0%', is_positive: false, is_negative: false };

    const rowHtml = `
        <td style="text-align:center; font-family:monospace; color:var(--text-muted);">${data.id || '-'}</td>
        <td>
            <div style="font-weight:600; color:var(--text-primary); font-size:0.9rem;">${escapeHtml(displayName)}</div>
            <a href="${escapeHtml(data.url)}" target="_blank" rel="noopener noreferrer" style="font-size:0.76rem; color:var(--text-muted); font-family:monospace; text-decoration:none;" onmouseover="this.style.color='#ef4444'" onmouseout="this.style.color='var(--text-muted)'">
                ${escapeHtml(data.url)}
            </a>
        </td>
        <td style="text-align:right;">
            <span class="badge-active" title="${followersExact} seguidores" style="font-family:monospace; font-weight:700; font-size:0.88rem; background:rgba(34,197,94,0.12); padding:4px 10px; border-radius:6px; border:1px solid rgba(34,197,94,0.25); cursor:help;">
                ${followersFormatted}
            </span>
        </td>
        <td style="text-align:center;">
            ${growth.is_positive ? `
                <span class="growth-badge-up" title="Crecimiento registrado: ${growth.formatted_delta}">
                    <i data-lucide="trending-up" style="width:12px; height:12px;"></i>
                    ${growth.formatted_delta} (${growth.formatted_pct})
                </span>
            ` : growth.is_negative ? `
                <span style="background:rgba(239,68,68,0.12); color:#f87171; border:1px solid rgba(239,68,68,0.25); padding:3px 8px; border-radius:6px; font-size:0.75rem; font-weight:600; display:inline-flex; align-items:center; gap:4px; font-family:monospace;">
                    <i data-lucide="trending-down" style="width:12px; height:12px;"></i>
                    ${growth.formatted_delta}
                </span>
            ` : `
                <span class="growth-badge-neutral" title="Sin variación registrada">
                    <i data-lucide="minus" style="width:12px; height:12px;"></i>
                    0 (0%)
                </span>
            `}
        </td>
        <td style="text-align:center;">
            ${isSuccess ? `
                <span class="badge-active" style="font-size:0.75rem; padding:4px 10px; border-radius:999px; background:rgba(34,197,94,0.1); border:1px solid rgba(34,197,94,0.2);">
                    <i data-lucide="check" style="width:12px; height:12px;"></i> Éxito
                </span>
            ` : `
                <span class="badge-inactive" style="font-size:0.75rem; padding:4px 10px; border-radius:999px; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.2); color:#f87171;" title="${escapeHtml(displayStatus)}">
                    <i data-lucide="alert-triangle" style="width:12px; height:12px;"></i> ${escapeHtml(displayStatus.substring(0, 18))}
                </span>
            `}
        </td>
        <td style="text-align:center;">
            <div style="display:flex; align-items:center; justify-content:center; gap:6px;">
                ${data.id ? `
                <button type="button" class="btn-ghost" style="padding:4px 8px; font-size:0.72rem;" onclick="openGrowthModal(${data.id})" title="Ver evolución de seguidores">
                    <i data-lucide="line-chart" style="width:13px; height:13px; color:#22c55e;"></i>
                    Historial
                </button>
                ` : ''}
                <a href="${escapeHtml(data.url)}" target="_blank" rel="noopener noreferrer" class="action-btn action-btn-edit" title="Abrir en Facebook">
                    <i data-lucide="external-link"></i>
                </a>
                ${data.id ? `
                <button type="button" onclick="openDeleteModal(${data.id}, '${escapeHtml(displayName).replace(/'/g, "\\'")}')" class="action-btn action-btn-delete" title="Eliminar fila">
                    <i data-lucide="trash-2"></i>
                </button>
                ` : ''}
            </div>
        </td>
    `;

    if (row) {
        row.innerHTML = rowHtml;
    } else {
        row = document.createElement('tr');
        row.id = rowId;
        row.innerHTML = rowHtml;
        tbody.insertBefore(row, tbody.firstChild);
    }

    lucide.createIcons({ root: row });
}

// ----------------------------------------------------
// Growth History Modal & Visual Chart Operations
// ----------------------------------------------------
let activeGrowthChart = null;

function renderGrowthChart(historyList, pageName) {
    const canvas = document.getElementById('growthChartCanvas');
    if (!canvas || typeof Chart === 'undefined') return;

    if (activeGrowthChart) {
        activeGrowthChart.destroy();
        activeGrowthChart = null;
    }

    if (!historyList || historyList.length === 0) return;

    const chronological = [...historyList].reverse();
    const labels = chronological.map(item => {
        return item.date.length > 10 ? item.date.substring(0, 5) + ' ' + item.date.substring(11, 16) : item.date;
    });
    const values = chronological.map(item => item.followers);

    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, 150);
    gradient.addColorStop(0, 'rgba(34, 197, 94, 0.35)');
    gradient.addColorStop(1, 'rgba(34, 197, 94, 0.0)');

    activeGrowthChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Seguidores',
                data: values,
                borderColor: '#22c55e',
                backgroundColor: gradient,
                fill: true,
                tension: 0.35,
                borderWidth: 2,
                pointRadius: values.length > 15 ? 2 : 4,
                pointBackgroundColor: '#22c55e',
                pointHoverRadius: 6,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    titleColor: '#e2e8f0',
                    bodyColor: '#4ade80',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
                    padding: 10,
                    displayColors: false,
                    callbacks: {
                        label: function(context) {
                            return `${Number(context.raw).toLocaleString()} seguidores`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#64748b', font: { size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: {
                        color: '#64748b',
                        font: { size: 10 },
                        callback: function(value) {
                            return formatCompactNumber(value);
                        }
                    }
                }
            }
        }
    });
}

async function openGrowthModal(pageId) {
    const modal = document.getElementById('growthHistoryModal');
    const tbody = document.getElementById('growthSnapshotsBody');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        lucide.createIcons({ root: modal });
    }

    if (!tbody) return;
    tbody.innerHTML = `
        <tr>
            <td colspan="3" style="text-align:center; padding:30px; color:var(--text-muted);">
                <div style="display:flex; align-items:center; justify-content:center; gap:8px;">
                    <i data-lucide="loader-2" class="animate-spin" style="width:16px; height:16px;"></i>
                    <span>Cargando historial de seguidores...</span>
                </div>
            </td>
        </tr>
    `;
    lucide.createIcons({ root: tbody });

    try {
        const res = await fetch(`${API_BASE}/api/page/${pageId}/history/`);
        const data = await res.json();

        if (data.status === 'ok') {
            const titleEl = document.getElementById('growthModalTitle');
            const urlEl = document.getElementById('growthModalUrl');
            if (titleEl) titleEl.textContent = data.page_name || 'Historial de Fanpage';
            if (urlEl) urlEl.textContent = data.page_url || '';

            const initialFmt = Number(data.growth?.initial || data.current_followers).toLocaleString();
            const currentFmt = Number(data.current_followers).toLocaleString();
            const deltaFmt = data.growth?.formatted_delta || '0';
            const pctFmt = data.growth?.formatted_pct || '0%';

            const initEl = document.getElementById('growthModalInitial');
            const currEl = document.getElementById('growthModalCurrent');
            const deltaEl = document.getElementById('growthModalTotalDelta');

            if (initEl) initEl.textContent = initialFmt;
            if (currEl) currEl.textContent = currentFmt;
            if (deltaEl) deltaEl.textContent = `${deltaFmt} (${pctFmt})`;

            renderGrowthChart(data.history, data.page_name);

            if (data.history && data.history.length > 0) {
                tbody.innerHTML = data.history.map(item => `
                    <tr>
                        <td style="font-family:monospace; font-size:0.82rem; color:var(--text-muted);">${item.date}</td>
                        <td style="text-align:right; font-family:monospace; font-weight:700; color:var(--text-primary);">
                            ${Number(item.followers).toLocaleString()}
                        </td>
                        <td style="text-align:right;">
                            ${item.is_positive ? `
                                <span class="growth-badge-up">
                                    <i data-lucide="trending-up" style="width:11px; height:11px;"></i>
                                    ${item.formatted_delta}
                                </span>
                            ` : item.is_negative ? `
                                <span style="background:rgba(239,68,68,0.12); color:#f87171; border:1px solid rgba(239,68,68,0.25); padding:3px 8px; border-radius:6px; font-size:0.75rem; font-weight:600; display:inline-flex; align-items:center; gap:4px; font-family:monospace;">
                                    <i data-lucide="trending-down" style="width:11px; height:11px;"></i>
                                    ${item.formatted_delta}
                                </span>
                            ` : `
                                <span class="growth-badge-neutral">
                                    <i data-lucide="minus" style="width:11px; height:11px;"></i>
                                    0
                                </span>
                            `}
                        </td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="3" style="text-align:center; padding:24px; color:var(--text-muted);">
                            No hay registros adicionales aún.
                        </td>
                    </tr>
                `;
            }
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="3" style="text-align:center; padding:24px; color:#f87171;">
                        Error al cargar el historial.
                    </td>
                </tr>
            `;
        }
        lucide.createIcons({ root: modal });
    } catch (err) {
        console.error('Error fetching growth history:', err);
        tbody.innerHTML = `
            <tr>
                <td colspan="3" style="text-align:center; padding:24px; color:#f87171;">
                    Error de conexión al cargar el historial.
                </td>
            </tr>
        `;
        lucide.createIcons({ root: tbody });
    }
}

function closeGrowthModal() {
    const modal = document.getElementById('growthHistoryModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

// ----------------------------------------------------
// Modal-Driven Glassmorphism Deletions (No Native Alerts)
// ----------------------------------------------------
let currentDeletePageId = null;

function openDeleteModal(pageId, pageName) {
    currentDeletePageId = pageId;
    const targetLabel = document.getElementById('deleteModalTargetText');
    if (targetLabel) {
        targetLabel.textContent = pageName || `Fanpage #${pageId}`;
    }
    const modal = document.getElementById('deleteConfirmModal');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        lucide.createIcons({ root: modal });
    }
}

function closeDeleteModal() {
    currentDeletePageId = null;
    const modal = document.getElementById('deleteConfirmModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

async function executeDeletePage() {
    if (!currentDeletePageId) return;

    const btn = document.getElementById('confirmDeleteBtn');
    const text = document.getElementById('confirmDeleteText');
    const icon = document.getElementById('confirmDeleteIcon');

    if (btn) btn.disabled = true;
    if (text) text.textContent = 'Eliminando...';
    if (icon) {
        icon.setAttribute('data-lucide', 'loader-2');
        icon.classList.add('animate-spin');
        lucide.createIcons({ root: btn });
    }

    try {
        const res = await fetch(`${API_BASE}/api/page/${currentDeletePageId}/delete/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            }
        });
        const data = await res.json();
        if (data.status === 'ok') {
            const row = document.getElementById(`row-page-${currentDeletePageId}`);
            if (row) {
                row.style.transition = 'all 0.25s ease';
                row.style.opacity = '0';
                row.style.transform = 'scale(0.95)';
                setTimeout(() => {
                    row.remove();
                    checkEmptyTable();
                }, 250);
            }
            updateMetrics(data.total_pages, data.total_followers);
            closeDeleteModal();
            showToast('Fanpage eliminada correctamente', 'info');
        } else {
            showToast(data.message || 'Error al eliminar la página', 'error');
        }
    } catch (err) {
        console.error('Error deleting page:', err);
        showToast('Error al conectar con el servidor', 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (text) text.textContent = 'Eliminar';
        if (icon) {
            icon.setAttribute('data-lucide', 'trash-2');
            icon.classList.remove('animate-spin');
            lucide.createIcons({ root: btn });
        }
    }
}

function openClearAllModal() {
    const modal = document.getElementById('clearAllConfirmModal');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        lucide.createIcons({ root: modal });
    }
}

function closeClearAllModal() {
    const modal = document.getElementById('clearAllConfirmModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

async function executeClearAllPages() {
    const btn = document.getElementById('confirmClearAllBtn');
    const text = document.getElementById('confirmClearAllText');
    const icon = document.getElementById('confirmClearAllIcon');

    if (btn) btn.disabled = true;
    if (text) text.textContent = 'Limpiando...';
    if (icon) {
        icon.setAttribute('data-lucide', 'loader-2');
        icon.classList.add('animate-spin');
        lucide.createIcons({ root: btn });
    }

    try {
        const res = await fetch(`${API_BASE}/api/pages/clear/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            }
        });
        const data = await res.json();
        if (data.status === 'ok') {
            const tbody = document.getElementById('pagesTableBody');
            if (tbody) tbody.innerHTML = '';
            checkEmptyTable();
            updateMetrics(0, 0);
            closeClearAllModal();
            showToast('Todos los registros fueron eliminados', 'success');
        } else {
            showToast(data.message || 'Error al limpiar los registros', 'error');
        }
    } catch (err) {
        console.error('Error clearing pages:', err);
        showToast('Error al conectar con el servidor', 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (text) text.textContent = 'Limpiar Todo';
        if (icon) {
            icon.setAttribute('data-lucide', 'trash');
            icon.classList.remove('animate-spin');
            lucide.createIcons({ root: btn });
        }
    }
}

function deletePage(pageId) {
    openDeleteModal(pageId);
}

function clearAllPages() {
    openClearAllModal();
}

function checkEmptyTable() {
    const tbody = document.getElementById('pagesTableBody');
    if (!tbody || tbody.children.length > 0) return;

    tbody.innerHTML = `
        <tr id="emptyTableMessage">
            <td colspan="5" style="padding:56px 20px; text-align:center; color:var(--text-muted);">
                <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px;">
                    <i data-lucide="inbox" style="width:42px; height:42px; stroke-width:1; color:var(--text-muted);"></i>
                    <div style="font-size:0.95rem; font-weight:500;">No hay fanpages registradas todavía</div>
                    <div style="font-size:0.8rem; color:var(--text-secondary);">Hacé clic en <strong>Extraer Nuevas URLs</strong> para comenzar el escaneo</div>
                </div>
            </td>
        </tr>
    `;
    lucide.createIcons();
}

async function refreshGlobalMetrics() {
    try {
        const res = await fetch(`${API_BASE}/api/stats/`);
        if (res.ok) {
            const data = await res.json();
            updateMetrics(data);
        }
    } catch (e) {
        console.error('Error fetching fresh stats:', e);
    }
}

function updateMetrics(data) {
    if (!data) return;
    const metricPages = document.getElementById('metricTotalPages');
    const metricFollowers = document.getElementById('metricTotalFollowers');
    const metricNetGrowth = document.getElementById('metricNetGrowth');
    const metricGrowthPct = document.getElementById('metricGrowthPct');
    const metricAvgFollowers = document.getElementById('metricAvgFollowers');
    const metricGrowingCount = document.getElementById('metricGrowingCount');
    const tableBadge = document.getElementById('tableCountBadge');

    if (metricPages) metricPages.textContent = Number(data.total_pages || 0).toLocaleString();
    if (metricFollowers) metricFollowers.textContent = data.formatted_total_followers || formatCompactNumber(data.total_followers || 0);
    if (metricNetGrowth) metricNetGrowth.textContent = data.formatted_net_growth || '0';
    if (metricGrowthPct) metricGrowthPct.textContent = `(${data.formatted_growth_percentage || '0%'})`;
    if (metricAvgFollowers) metricAvgFollowers.textContent = data.formatted_avg_followers || '0';
    if (metricGrowingCount) metricGrowingCount.textContent = `${data.growing_pages_count || 0} en subida`;
    if (tableBadge) tableBadge.textContent = Number(data.total_pages || 0).toLocaleString();
}

// ----------------------------------------------------
// Search & Filter
// ----------------------------------------------------
function initSearchFilter() {
    const searchInput = document.getElementById('tableSearchInput');
    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase().trim();
        const rows = document.querySelectorAll('#pagesTableBody tr[id^="row-page-"], #pagesTableBody tr[id^="row-url-"]');

        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(term) ? '' : 'none';
        });
    });
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ----------------------------------------------------
// Alerts & Webhooks Modal
// ----------------------------------------------------
async function openAlertsModal() {
    const modal = document.getElementById('alertsConfigModal');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        lucide.createIcons({ root: modal });
    }
    await loadAlertsConfig();
}

function closeAlertsModal() {
    const modal = document.getElementById('alertsConfigModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

async function loadAlertsConfig() {
    try {
        const res = await fetch(`${API_BASE}/api/alerts/config/`);
        if (res.ok) {
            const data = await res.json();
            const input = document.getElementById('alertWebhookUrlInput');
            const checkbox = document.getElementById('alertsEnabledCheckbox');
            if (input) input.value = data.webhook_url || '';
            if (checkbox) checkbox.checked = data.enabled !== false;
        }
    } catch (e) {
        console.error('Error loading alerts config:', e);
    }
}

async function saveAlertsConfig() {
    const input = document.getElementById('alertWebhookUrlInput');
    const checkbox = document.getElementById('alertsEnabledCheckbox');
    const btn = document.getElementById('btnSaveAlertsConfig');

    const webhookUrl = input ? input.value.trim() : '';
    const enabled = checkbox ? checkbox.checked : true;

    if (btn) btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/alerts/save/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({
                webhook_url: webhookUrl,
                enabled: enabled,
            })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('Configuración de alertas guardada exitosamente', 'success');
            closeAlertsModal();
        } else {
            showToast(data.message || 'Error al guardar configuración', 'error');
        }
    } catch (err) {
        console.error('Error saving alerts config:', err);
        showToast('Error de conexión con el servidor', 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function testWebhookAlert() {
    const input = document.getElementById('alertWebhookUrlInput');
    const btn = document.getElementById('btnTestWebhookAlert');
    const text = document.getElementById('btnTestWebhookText');
    const icon = document.getElementById('btnTestWebhookIcon');

    const webhookUrl = input ? input.value.trim() : '';
    if (!webhookUrl) {
        showToast('Ingresá una URL de webhook antes de probar', 'warning');
        return;
    }

    if (btn) btn.disabled = true;
    if (text) text.textContent = 'Enviando...';
    if (icon) {
        icon.setAttribute('data-lucide', 'loader-2');
        icon.classList.add('animate-spin');
        lucide.createIcons({ root: btn });
    }

    try {
        const res = await fetch(`${API_BASE}/api/alerts/test/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ webhook_url: webhookUrl })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast('¡Notificación de prueba enviada con éxito!', 'success');
        } else {
            showToast(data.message || 'Error al enviar prueba', 'error');
        }
    } catch (err) {
        console.error('Error testing webhook:', err);
        showToast('Error de conexión al enviar prueba', 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (text) text.textContent = 'Probar Webhook';
        if (icon) {
            icon.setAttribute('data-lucide', 'send');
            icon.classList.remove('animate-spin');
            lucide.createIcons({ root: btn });
        }
    }
}
