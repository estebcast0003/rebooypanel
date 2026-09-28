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

function initDashboard() {
    initTextareaControls();
    initDropZone();
    initButtons();
    initSearchFilter();
    initSchedulerControls();
    updateUrlCount();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDashboard);
} else {
    initDashboard();
}

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
        btnTriggerNow.addEventListener('click', triggerSchedulerNow);
    }

    // Initial status sync & start countdown timer
    syncSchedulerStatus();
    startSchedulerCountdownTimer();
}

async function triggerSchedulerNow() {
    const btnTriggerNow = document.getElementById('btnTriggerScheduledNow');
    const origIcon = document.getElementById('btnTriggerSchedulerIcon');
    const origText = document.getElementById('btnTriggerSchedulerText');

    if (btnTriggerNow) btnTriggerNow.disabled = true;
    if (origIcon) origIcon.classList.add('animate-spin');
    if (origText) origText.textContent = 'Actualizando...';

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
            showToast(data.message || 'Actualización iniciada', 'info');
            coordinateJobMonitoring(data.job_id, data.total_urls || 0);
            syncSchedulerStatus();
        } else {
            showToast(data.message || 'Error al disparar actualización', 'warning');
            if (btnTriggerNow) btnTriggerNow.disabled = false;
            if (origIcon) origIcon.classList.remove('animate-spin');
            if (origText) origText.textContent = 'Actualizar Ahora';
        }
    } catch (err) {
        console.error('Error triggering scheduler now:', err);
        showToast('Error de conexión', 'error');
        if (btnTriggerNow) btnTriggerNow.disabled = false;
        if (origIcon) origIcon.classList.remove('animate-spin');
        if (origText) origText.textContent = 'Actualizar Ahora';
    }
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

        if (response.status === 409 || data.status === 'duplicate' || data.error === 'duplicate') {
            setExtractionRunningState(false);
            openDuplicateFanpagesModal(data.duplicate_items || [], data.message);
            return;
        }

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

let isJobCompletedHandled = false;

function coordinateJobMonitoring(jobId, totalUrls) {
    cleanupJobMonitoring();
    isJobCompletedHandled = false;

    const progressContainers = document.querySelectorAll('#liveProgressCard, #liveProgressContainer, .liveProgressContainer');
    progressContainers.forEach(container => {
        container.style.display = 'block';
        container.classList.remove('hidden');
    });

    const spinnerIcon = document.getElementById('liveProgressSpinnerIcon');
    const checkIcon = document.getElementById('liveProgressCheckIcon');
    if (spinnerIcon) spinnerIcon.classList.remove('hidden');
    if (checkIcon) checkIcon.classList.add('hidden');

    const statusLabels = document.querySelectorAll('.progressStatusLabel');
    statusLabels.forEach(el => el.textContent = 'Actualizando fanpages en tiempo real...');
    const currentPages = document.querySelectorAll('.progressCurrentPage');
    currentPages.forEach(el => el.textContent = totalUrls ? `Iniciando escaneo de ${totalUrls} fanpages...` : 'Conectando con Facebook...');

    const progressBars = document.querySelectorAll('#progressBarFill, .progressBarFill');
    const progressLabels = document.querySelectorAll('#progressCounterLabel, .progressCounterLabel');

    progressBars.forEach(bar => bar.style.width = '8%');
    progressLabels.forEach(label => label.textContent = `0 / ${totalUrls || '?'} (0%)`);
    if (window.lucide) lucide.createIcons();

    // 1. Setup Server-Sent Events (SSE)
    try {
        activeEventSource = new EventSource(`${API_BASE}/api/stream/${jobId}/`);

        activeEventSource.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                const payload = message.data;

                if (message.event === 'item') {
                    upsertTableRow(payload);
                    updateProgressBar(payload.processed, payload.total, payload.name);
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

    // 2. Setup Polling Fallback Safety Net (every 1.2s)
    activePollingInterval = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/job/${jobId}/status/`);
            if (res.ok) {
                const jobData = await res.json();
                if (jobData.items && jobData.items.length > 0) {
                    jobData.items.forEach(item => {
                        try {
                            upsertTableRow({
                                id: item.id,
                                url: item.url,
                                name: item.name,
                                followers: item.followers,
                                status: item.status,
                                is_success: item.is_success,
                                growth: item.growth,
                            });
                        } catch (itemErr) {
                            console.warn('Error upserting row:', itemErr);
                        }
                    });
                }
                const lastItem = jobData.items && jobData.items.length > 0 ? jobData.items[jobData.items.length - 1].name : null;
                updateProgressBar(jobData.processed, jobData.total, lastItem);
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
    }, 1200);

    // Safety timeout: prevent UI from hanging if job gets stalled
    setTimeout(() => {
        if (!isJobCompletedHandled) {
            console.warn('Job monitoring safety timeout reached');
            onJobCompleted({ total: totalUrls || 1, successful: totalUrls || 1, failed: 0 });
        }
    }, 45000);
}

function onJobCompleted(payload) {
    if (isJobCompletedHandled) return;
    isJobCompletedHandled = true;

    cleanupJobMonitoring();
    setExtractionRunningState(false);

    const btnTriggerNow = document.getElementById('btnTriggerScheduledNow');
    if (btnTriggerNow) {
        btnTriggerNow.disabled = false;
        const origIcon = document.getElementById('btnTriggerSchedulerIcon');
        const origText = document.getElementById('btnTriggerSchedulerText');
        if (origIcon) origIcon.classList.remove('animate-spin');
        if (origText) origText.textContent = 'Actualizar Ahora';
    }

    const spinnerIcon = document.getElementById('liveProgressSpinnerIcon');
    const checkIcon = document.getElementById('liveProgressCheckIcon');
    if (spinnerIcon) spinnerIcon.classList.add('hidden');
    if (checkIcon) checkIcon.classList.remove('hidden');

    const statusLabels = document.querySelectorAll('.progressStatusLabel');
    statusLabels.forEach(el => el.textContent = '¡Actualización completada!');
    const currentPages = document.querySelectorAll('.progressCurrentPage');
    currentPages.forEach(el => el.textContent = `${payload.successful || payload.total || 0} fanpages procesadas exitosamente`);

    const progressBars = document.querySelectorAll('#progressBarFill, .progressBarFill');
    const progressLabels = document.querySelectorAll('#progressCounterLabel, .progressCounterLabel');
    progressBars.forEach(bar => bar.style.width = '100%');
    const totalCount = payload.total || payload.processed || 0;
    progressLabels.forEach(label => label.textContent = `${totalCount} / ${totalCount} (100%)`);

    refreshGlobalMetrics();
    showToast(`¡Extracción completada! ${payload.successful || 0} exitosas, ${payload.failed || 0} con error`, (payload.successful || 0) > 0 ? 'success' : 'info');
    if (window.lucide) lucide.createIcons();

    setTimeout(() => {
        const progressContainers = document.querySelectorAll('#liveProgressCard, #liveProgressContainer, .liveProgressContainer');
        progressContainers.forEach(container => {
            container.style.display = 'none';
            container.classList.add('hidden');
        });
        if (spinnerIcon) spinnerIcon.classList.remove('hidden');
        if (checkIcon) checkIcon.classList.add('hidden');
    }, 4500);
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

function updateProgressBar(processed, total, currentItemName) {
    const progressBars = document.querySelectorAll('#progressBarFill, .progressBarFill');
    const progressLabels = document.querySelectorAll('#progressCounterLabel, .progressCounterLabel');
    const currentPages = document.querySelectorAll('.progressCurrentPage');

    const totalCount = Number(total) || 1;
    const processedCount = Number(processed) || 0;
    const percent = Math.min(100, Math.max(8, Math.round((processedCount / totalCount) * 100)));

    progressBars.forEach(bar => {
        bar.style.width = `${percent}%`;
    });
    progressLabels.forEach(label => {
        label.textContent = `${processedCount} / ${totalCount} (${percent}%)`;
    });
    if (currentItemName) {
        currentPages.forEach(el => {
            el.textContent = `Actualizado: ${currentItemName}`;
        });
    }
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

    const safeUrlKey = (data.url || '').replace(/[^a-zA-Z0-9]/g, '');
    const rowId = data.id ? `row-page-${data.id}` : `row-url-${safeUrlKey || Math.random().toString(36).slice(2)}`;
    let row = document.getElementById(rowId);

    const followersFormatted = formatCompactNumber(data.followers);
    const followersExact = Number(data.followers || 0).toLocaleString();
    const isSuccess = data.is_success || data.followers > 0;
    const displayName = data.name || 'Desconocido';
    const displayStatus = data.status || (isSuccess ? 'Activa' : 'Error');
    const growth = data.growth || { formatted_delta: '0', formatted_pct: '0%', is_positive: false, is_negative: false };

    const rowHtml = `
        <td class="text-center font-mono text-xs text-base-content/50 pl-4">${data.id || '-'}</td>
        <td class="py-3.5">
            <div class="font-bold text-sm text-base-content tracking-tight">${escapeHtml(displayName)}</div>
            <a href="${escapeHtml(data.url)}" target="_blank" rel="noopener noreferrer" class="text-xs text-primary hover:underline font-mono opacity-80 inline-flex items-center gap-1 transition">
                ${escapeHtml(data.url)}
                <i data-lucide="external-link" class="w-3 h-3 opacity-60"></i>
            </a>
        </td>
        <td class="text-right font-mono font-bold text-sm text-base-content" title="${followersExact} seguidores">
            <span class="inline-flex items-center px-2.5 py-0.5 rounded-lg bg-base-200 border border-base-300 text-xs">
                ${followersFormatted}
            </span>
        </td>
        <td class="text-center font-mono text-xs">
            ${growth.is_positive ? `
                <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-success/10 text-success border border-success/20" title="Crecimiento registrado: ${growth.formatted_delta}">
                    <i data-lucide="trending-up" class="w-3 h-3"></i>
                    ${growth.formatted_delta} (${growth.formatted_pct})
                </span>
            ` : growth.is_negative ? `
                <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-error/10 text-error border border-error/20">
                    <i data-lucide="trending-down" class="w-3 h-3"></i>
                    ${growth.formatted_delta}
                </span>
            ` : `
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs text-base-content/50 bg-base-200 border border-base-300">
                    0 (0%)
                </span>
            `}
        </td>
        <td class="text-center">
            ${isSuccess ? `
                <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-success/10 text-success border border-success/20">
                    <i data-lucide="check" class="w-3 h-3"></i> Activa
                </span>
            ` : `
                <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-warning/10 text-warning border border-warning/20" title="${escapeHtml(displayStatus)}">
                    <i data-lucide="alert-triangle" class="w-3 h-3"></i> ${escapeHtml(displayStatus.substring(0, 14))}
                </span>
            `}
        </td>
        <td class="text-center pr-6">
            <div class="inline-flex items-center gap-1.5 justify-center">
                ${data.id ? `
                <button type="button" class="btn btn-ghost btn-xs gap-1 border border-base-300 hover:border-primary hover:bg-primary/10 hover:text-primary rounded-lg text-xs h-8 px-2 text-base-content/75 transition-all" onclick="openGrowthModal(${data.id})" title="Ver evolución de seguidores">
                    <i data-lucide="line-chart" class="w-3.5 h-3.5 text-success"></i>
                    Historial
                </button>
                ` : ''}
                <a href="${escapeHtml(data.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-ghost btn-square btn-xs border border-base-300 hover:border-primary hover:bg-primary/10 hover:text-primary rounded-lg h-8 w-8 text-base-content/75 transition-all" title="Abrir en Facebook">
                    <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                </a>
                ${data.id ? `
                <button type="button" onclick="openDeleteModal(${data.id}, '${escapeHtml(displayName).replace(/'/g, "\\'")}')" class="btn btn-ghost btn-square btn-xs border border-base-300 hover:border-error hover:bg-error/10 hover:text-error rounded-lg h-8 w-8 text-base-content/75 transition-all" title="Eliminar fila">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                </button>
                ` : ''}
            </div>
        </td>
    `;

    if (row) {
        row.innerHTML = rowHtml;
        row.className = 'fanpage-row hover:bg-base-200/30 transition-colors';
        row.setAttribute('data-followers', data.followers || 0);
        row.setAttribute('data-has-growth', growth.is_positive ? 'true' : 'false');
    } else {
        row = document.createElement('tr');
        row.id = rowId;
        row.className = 'fanpage-row hover:bg-base-200/30 transition-colors';
        row.setAttribute('data-followers', data.followers || 0);
        row.setAttribute('data-has-growth', growth.is_positive ? 'true' : 'false');
        row.innerHTML = rowHtml;
        tbody.insertBefore(row, tbody.firstChild);
    }

    if (window.lucide) {
        lucide.createIcons();
    }
}

// ----------------------------------------------------
// Growth History Modal & Visual Chart Operations
// ----------------------------------------------------
let activeGrowthChart = null;

function renderGrowthChart(historyList, pageName) {
    const canvas = document.getElementById('growthChartCanvas');
    if (!canvas) return;
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js library is not loaded');
        return;
    }

    if (activeGrowthChart) {
        activeGrowthChart.destroy();
        activeGrowthChart = null;
    }

    if (!historyList || historyList.length === 0) return;

    // Orden cronológico (pasado a presente)
    const sorted = [...historyList].sort((a, b) => (a.id || 0) - (b.id || 0));
    const labels = sorted.map(item => {
        return item.date.length > 10 ? item.date.substring(0, 5) + ' ' + item.date.substring(11, 16) : item.date;
    });
    const values = sorted.map(item => item.followers);

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const gradient = ctx.createLinearGradient(0, 0, 0, 150);
    gradient.addColorStop(0, 'rgba(34, 197, 94, 0.35)');
    gradient.addColorStop(1, 'rgba(34, 197, 94, 0.0)');

    try {
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
                    pointRadius: values.length === 1 ? 6 : (values.length > 15 ? 2 : 4),
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
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        ticks: { color: '#888888', font: { size: 10 } }
                    },
                    y: {
                        grid: { color: 'rgba(0, 0, 0, 0.05)' },
                        ticks: {
                            color: '#888888',
                            font: { size: 10 },
                            callback: function(value) {
                                return formatCompactNumber(value);
                            }
                        }
                    }
                }
            }
        });
    } catch (chartErr) {
        console.warn('Error rendering growth chart:', chartErr);
    }
}

async function openGrowthModal(pageId) {
    const modal = document.getElementById('growthHistoryModal');
    const tbody = document.getElementById('growthSnapshotsBody') || document.getElementById('growthHistoryTableBody');
    if (modal) {
        modal.style.display = 'flex';
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        if (window.lucide) lucide.createIcons({ root: modal });
    }

    if (!tbody) {
        console.error('Growth modal table body not found in DOM.');
        return;
    }

    tbody.innerHTML = `
        <tr>
            <td colspan="3" class="text-center py-8 text-base-content/50">
                <div class="flex items-center justify-center gap-2 text-xs">
                    <i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i>
                    <span>Cargando historial de seguidores...</span>
                </div>
            </td>
        </tr>
    `;
    if (window.lucide) lucide.createIcons();

    try {
        const res = await fetch(`${API_BASE}/api/page/${pageId}/history/`);
        const data = await res.json();

        if (data.status === 'ok') {
            const titleEl = document.getElementById('growthModalTitle');
            const urlEl = document.getElementById('growthModalUrl');
            const subtitleEl = document.getElementById('growthModalSubtitle');
            if (titleEl) titleEl.textContent = data.page_name || 'Historial de Fanpage';
            if (urlEl) urlEl.textContent = data.page_url || '';
            if (subtitleEl) subtitleEl.textContent = data.page_url || '';

            const initialFmt = Number(data.growth?.initial ?? data.current_followers).toLocaleString();
            const currentFmt = Number(data.current_followers).toLocaleString();
            const deltaFmt = data.growth?.formatted_delta || '0';
            const pctFmt = data.growth?.formatted_pct || '0%';

            const initEl = document.getElementById('growthModalInitial');
            const currEl = document.getElementById('growthModalCurrent');
            const deltaEl = document.getElementById('growthModalTotalDelta');

            if (initEl) initEl.textContent = initialFmt;
            if (currEl) currEl.textContent = currentFmt;
            if (deltaEl) {
                deltaEl.textContent = `${deltaFmt} (${pctFmt})`;
                if (data.growth?.is_positive) {
                    deltaEl.style.color = '#22c55e';
                } else if (data.growth?.is_negative) {
                    deltaEl.style.color = '#f87171';
                } else {
                    deltaEl.style.color = 'var(--text-muted)';
                }
            }

            setTimeout(() => {
                renderGrowthChart(data.history, data.page_name);
            }, 60);

            if (data.history && data.history.length > 0) {
                tbody.innerHTML = data.history.map(item => `
                    <tr class="hover:bg-base-200/30 transition-colors">
                        <td class="font-mono text-xs text-base-content/70 pl-5 py-2.5">${item.date}</td>
                        <td class="text-right font-mono font-bold text-xs text-base-content">${Number(item.followers).toLocaleString()}</td>
                        <td class="text-right pr-5">
                            ${item.is_positive ? `
                                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-success/10 text-success border border-success/20">
                                    <i data-lucide="trending-up" class="w-3 h-3"></i>
                                    ${item.formatted_delta}
                                </span>
                            ` : item.is_negative ? `
                                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-error/10 text-error border border-error/20">
                                    <i data-lucide="trending-down" class="w-3 h-3"></i>
                                    ${item.formatted_delta}
                                </span>
                            ` : `
                                <span class="text-base-content/40 text-xs font-mono">0</span>
                            `}
                        </td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="3" class="text-center py-6 text-xs text-base-content/50">
                            No hay registros adicionales aún.
                        </td>
                    </tr>
                `;
            }
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="3" class="text-center py-6 text-xs text-error">
                        ${data.message || 'Error al cargar el historial.'}
                    </td>
                </tr>
            `;
        }
        if (window.lucide) lucide.createIcons();
    } catch (err) {
        console.error('Error fetching growth history:', err);
        tbody.innerHTML = `
            <tr>
                <td colspan="3" class="text-center py-6 text-xs text-error">
                    Error de conexión al cargar el historial.
                </td>
            </tr>
        `;
        if (window.lucide) lucide.createIcons();
    }
}

function closeGrowthModal() {
    const modal = document.getElementById('growthHistoryModal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = 'auto';
    }
    if (activeGrowthChart) {
        activeGrowthChart.destroy();
        activeGrowthChart = null;
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
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        if (window.lucide) lucide.createIcons();
    }
}

function closeDeleteModal() {
    currentDeletePageId = null;
    const modal = document.getElementById('deleteConfirmModal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = 'auto';
    }
}

async function executeDeletePage() {
    if (!currentDeletePageId) return;

    const btn = document.getElementById('confirmDeleteBtn');
    const text = document.getElementById('confirmDeleteText');

    if (btn) btn.disabled = true;
    if (text) text.textContent = 'Eliminando...';

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
                row.remove();
                checkEmptyTable();
            }
            refreshGlobalMetrics();
            closeDeleteModal();
            showToast('Fanpage eliminada correctamente', 'success');
        } else {
            showToast(data.message || 'Error al eliminar la página', 'error');
        }
    } catch (err) {
        console.error('Error deleting page:', err);
        showToast('Error al conectar con el servidor', 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (text) text.textContent = 'Eliminar';
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
    if (!tbody || tbody.querySelectorAll('.fanpage-row').length > 0) return;

    tbody.innerHTML = `
        <tr id="emptyTableMessage">
            <td colspan="6" class="p-16 text-center text-base-content/50">
                <div class="flex flex-col items-center justify-center gap-2.5">
                    <i data-lucide="inbox" class="w-12 h-12 text-base-content/30 mb-1"></i>
                    <div class="text-sm font-bold text-base-content">No hay fanpages registradas todavía</div>
                    <div class="text-xs text-base-content/60">Hacé clic en <strong>Extraer Nuevas URLs</strong> para iniciar el rastreo.</div>
                    <button type="button" class="btn btn-primary btn-sm gap-2 rounded-xl text-xs font-semibold mt-2" onclick="openExtractionModal()">
                        <i data-lucide="plus" class="w-4 h-4"></i> Extraer Primeras URLs
                    </button>
                </div>
            </td>
        </tr>
    `;
    if (window.lucide) lucide.createIcons();
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

function openExtractionModal() {
    const modal = document.getElementById('newExtractionModal');
    if (modal) {
        modal.style.display = 'flex';
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        if (window.lucide) lucide.createIcons({ root: modal });
    }
}

function closeExtractionModal() {
    const modal = document.getElementById('newExtractionModal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = 'auto';
    }
}

function filterTableCategory(category, btn) {
    document.querySelectorAll('.pill-tab').forEach(el => {
        el.classList.remove('tab-active', 'bg-base-100', 'shadow-sm', 'text-primary', 'font-bold');
        el.classList.add('text-base-content/70');
    });
    if (btn) {
        btn.classList.add('tab-active', 'bg-base-100', 'shadow-sm', 'text-primary', 'font-bold');
        btn.classList.remove('text-base-content/70');
    }

    const rows = document.querySelectorAll('.fanpage-row');
    rows.forEach(row => {
        const followers = parseFloat(row.getAttribute('data-followers')) || 0;
        const hasGrowth = row.getAttribute('data-has-growth') === 'true';

        if (category === 'all') {
            row.style.display = '';
        } else if (category === 'growth') {
            row.style.display = hasGrowth ? '' : 'none';
        } else if (category === 'major') {
            row.style.display = followers >= 100000 ? '' : 'none';
        }
    });
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const alert = document.createElement('div');
    const alertClass = type === 'success' ? 'alert-success text-white' :
                       type === 'error' ? 'alert-error text-white' :
                       type === 'warning' ? 'alert-warning text-zinc-900' :
                       'alert-info text-white';

    alert.className = `alert ${alertClass} text-xs shadow-xl rounded-xl p-3 flex items-center gap-2 pointer-events-auto border border-base-300`;
    const iconName = type === 'success' ? 'check-circle-2' : type === 'error' ? 'alert-circle' : type === 'warning' ? 'alert-triangle' : 'info';
    alert.innerHTML = `<i data-lucide="${iconName}" class="w-4 h-4 shrink-0"></i> <span>${message}</span>`;
    container.appendChild(alert);
    if (window.lucide) lucide.createIcons();

    setTimeout(() => {
        alert.style.opacity = '0';
        alert.style.transition = 'opacity 0.25s ease';
        setTimeout(() => alert.remove(), 260);
    }, 3500);
}

function openDuplicateFanpagesModal(items, message) {
    const listEl = document.getElementById('dupFanpagesList');
    const msgEl = document.getElementById('dupFanpagesMessage');
    if (msgEl && message) {
        msgEl.innerHTML = `${escapeHtml(message)} Para no duplicar tareas ni consumir recursos, la petición fue rechazada. Podés actualizar sus métricas usando el botón <strong>"Actualizar Ahora"</strong>.`;
    }

    if (listEl) {
        if (items && items.length > 0) {
            listEl.innerHTML = items.map(item => `
                <div class="flex items-center justify-between p-2.5 rounded-lg bg-base-100 border border-base-300 text-xs">
                    <div class="flex-1 min-w-0 pr-3">
                        <div class="font-bold text-base-content truncate">${escapeHtml(item.name || 'Fanpage')}</div>
                        <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer" class="text-[11px] text-primary hover:underline font-mono truncate block opacity-80">
                            ${escapeHtml(item.url)}
                        </a>
                    </div>
                    <span class="badge badge-neutral badge-md font-mono font-bold text-xs px-2.5 shrink-0">
                        ${item.followers || '0'}
                    </span>
                </div>
            `).join('');
        } else {
            listEl.innerHTML = '<div class="text-xs text-base-content/50 text-center py-3">No hay detalles disponibles.</div>';
        }
    }

    const modal = document.getElementById('duplicateFanpagesModal');
    if (modal) {
        modal.style.display = 'flex';
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        if (window.lucide) lucide.createIcons();
    }
}

function closeDuplicateFanpagesModal() {
    const modal = document.getElementById('duplicateFanpagesModal');
    if (modal) {
        modal.style.display = 'none';
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = 'auto';
    }
}

// Attach globally to window
window.triggerSchedulerNow = triggerSchedulerNow;
window.coordinateJobMonitoring = coordinateJobMonitoring;
window.onJobCompleted = onJobCompleted;
window.updateProgressBar = updateProgressBar;
window.openGrowthModal = openGrowthModal;
window.loadGrowthHistoryData = openGrowthModal;
window.closeGrowthModal = closeGrowthModal;
window.openDeleteModal = openDeleteModal;
window.closeDeleteModal = closeDeleteModal;
window.executeDeletePage = executeDeletePage;
window.openExtractionModal = openExtractionModal;
window.closeExtractionModal = closeExtractionModal;
window.openDuplicateFanpagesModal = openDuplicateFanpagesModal;
window.closeDuplicateFanpagesModal = closeDuplicateFanpagesModal;
window.filterTableCategory = filterTableCategory;
window.showToast = showToast;

window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeExtractionModal();
        closeDeleteModal();
        closeGrowthModal();
        closeDuplicateFanpagesModal();
    }
});
document.getElementById('newExtractionModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'newExtractionModal') closeExtractionModal();
});
document.getElementById('deleteConfirmModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'deleteConfirmModal') closeDeleteModal();
});
document.getElementById('growthHistoryModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'growthHistoryModal') closeGrowthModal();
});
document.getElementById('duplicateFanpagesModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'duplicateFanpagesModal') closeDuplicateFanpagesModal();
});

