const FALLBACK_WORKFLOW_STEPS = [
    { id: 'setup', label: 'Project Setup', states: ['SETUP_REQUIRED'] },
    { id: 'vision', label: 'Vision', states: ['VISION_INTERVIEW', 'VISION_REVIEW', 'VISION_PERSISTENCE'] },
    { id: 'backlog', label: 'Backlog', states: ['BACKLOG_INTERVIEW', 'BACKLOG_REVIEW', 'BACKLOG_PERSISTENCE'] },
    { id: 'roadmap', label: 'Roadmap', states: ['ROADMAP_INTERVIEW', 'ROADMAP_REVIEW', 'ROADMAP_PERSISTENCE'] },
    { id: 'story', label: 'Stories', states: ['STORY_INTERVIEW', 'STORY_REVIEW', 'STORY_PERSISTENCE'] },
    {
        id: 'sprint',
        label: 'Sprint',
        states: [
            'SPRINT_SETUP',
            'SPRINT_DRAFT',
            'SPRINT_PERSISTENCE',
            'SPRINT_VIEW',
            'SPRINT_LIST',
            'SPRINT_UPDATE_STORY',
            'SPRINT_MODIFY',
            'SPRINT_COMPLETE',
        ],
    },
];

const STEP_ICONS = {
    setup: 'settings',
    vision: 'visibility',
    backlog: 'format_list_bulleted',
    roadmap: 'timeline',
    story: 'description',
    sprint: 'bolt',
};

const PHASE_ORDER = ['setup', 'vision', 'backlog', 'roadmap', 'story', 'sprint'];
const NEXT_PHASE = {
    setup: 'vision',
    vision: 'backlog',
    backlog: 'roadmap',
    roadmap: 'story',
    story: 'sprint',
    sprint: null,
};

const PHASE_TERMINAL_STATES = {
    setup: ['VISION_INTERVIEW', 'VISION_REVIEW', 'VISION_PERSISTENCE', 'BACKLOG_INTERVIEW', 'BACKLOG_REVIEW', 'BACKLOG_PERSISTENCE', 'ROADMAP_INTERVIEW', 'ROADMAP_REVIEW', 'ROADMAP_PERSISTENCE', 'STORY_INTERVIEW', 'STORY_REVIEW', 'STORY_PERSISTENCE', 'SPRINT_SETUP', 'SPRINT_DRAFT', 'SPRINT_PERSISTENCE', 'SPRINT_COMPLETE'],
    vision: ['VISION_PERSISTENCE'],
    backlog: ['BACKLOG_PERSISTENCE'],
    roadmap: ['ROADMAP_PERSISTENCE'],
    story: ['STORY_PERSISTENCE'],
    sprint: ['SPRINT_PERSISTENCE', 'SPRINT_COMPLETE'],
};

let dashboardConfig = null;
let selectedProjectId = null;
let activeFsmState = 'SETUP_REQUIRED';
let activePhaseId = 'setup';
let viewPhaseId = 'setup';
let currentProjectState = { setup_status: 'failed', setup_error: null };

let latestVisionIsComplete = false;
let visionAttemptCount = 0;

let latestBacklogIsComplete = false;
let backlogAttemptCount = 0;

let latestRoadmapIsComplete = false;
let roadmapAttemptCount = 0;

// Story Phase State
let storyRequirements = []; // Array of { requirement, status, attempt_count }
let activeStoryReq = null;
let activeStoryAttemptCount = 0;
let activeStoryIsComplete = false;

// Variables to hold raw JSON data for the copy feature
let currentVisionArtifactJSON = null;
let currentBacklogArtifactJSON = null;
let currentRoadmapArtifactJSON = null;
let currentStoryArtifactJSON = null;
let currentSprintArtifactJSON = null;
let currentSprintInputContextJSON = null;

let latestSprintIsComplete = false;
let sprintAttemptCount = 0;
let sprintCandidates = [];
let selectedSprintStoryIds = new Set();

const SPRINT_VELOCITY_LIMITS = {
    Low: 3,
    Medium: 5,
    High: 7,
};

window.addEventListener('DOMContentLoaded', async () => {
    // 1. Get Project ID from URL
    const urlParams = new URLSearchParams(window.location.search);
    const idParam = urlParams.get('id');

    if (!idParam) {
        alert("No project ID found in URL. Returning to dashboard.");
        window.location.href = '/dashboard';
        return;
    }
    selectedProjectId = parseInt(idParam, 10);

    // 2. Fetch config & set initial state
    await fetchDashboardConfig();
    document.getElementById('setup-panel').classList.remove('hidden');

    setPhaseState('SETUP_REQUIRED', 'setup');

    // 3. Load initial project data & state
    await loadInitialProjectMetadata();
    await fetchProjectFSMState(selectedProjectId);
    await loadVisionHistory();
    await loadBacklogHistory();
    await loadRoadmapHistory();
    await loadStoryRequirements();
    attachSprintInputListeners();
    await loadSprintHistory();
});

async function fetchDashboardConfig() {
    try {
        const response = await fetch('/api/dashboard/config');
        const data = await response.json();
        dashboardConfig = data?.status === 'success' ? data.data : null;
    } catch (error) {
        console.error('Error fetching dashboard config:', error);
        dashboardConfig = null;
    }
}

async function loadInitialProjectMetadata() {
    try {
        const response = await fetch('/api/projects');
        const data = await response.json();
        if (data.status === 'success') {
            const project = data.data.find(p => p.id === selectedProjectId);
            const title = document.getElementById('project-page-title');
            const nameInput = document.getElementById('setup-project-name');
            if (project) {
                if (title) title.innerText = project.name;
                if (nameInput) nameInput.value = project.name;
            } else {
                if (title) title.innerText = `Project ${selectedProjectId}`;
                if (nameInput) nameInput.value = `Project ${selectedProjectId}`;
            }
        }
    } catch (e) {
        console.error("Failed to load generic metadata");
    }
}


function getWorkflowSteps() {
    const configSteps = dashboardConfig?.workflow_steps;
    if (Array.isArray(configSteps) && configSteps.length > 0) {
        return configSteps;
    }
    return FALLBACK_WORKFLOW_STEPS;
}

function normalizeStateKey(value) {
    if (typeof value !== 'string') return 'SETUP_REQUIRED';
    const normalized = value.trim().toUpperCase();
    return normalized || 'SETUP_REQUIRED';
}

function getPhaseIdForState(stateKey) {
    const step = getWorkflowSteps().find((item) => Array.isArray(item.states) && item.states.includes(stateKey));
    return step ? step.id : 'setup';
}

function phaseIndex(phaseId) {
    return PHASE_ORDER.indexOf(phaseId);
}

function capitalizePhase(phaseId) {
    if (phaseId === 'story') return 'Stories';
    return phaseId.charAt(0).toUpperCase() + phaseId.slice(1);
}

function updateRetryButton() {
    const retryBtn = document.getElementById('btn-retry-setup');
    if (!retryBtn) return;

    if (currentProjectState.setup_status === 'failed') {
        retryBtn.classList.remove('hidden');
    } else {
        retryBtn.classList.add('hidden');
    }
}

function updateSetupStatusBanner() {
    const banner = document.getElementById('setup-status-banner');
    if (!banner) return;

    banner.classList.remove('hidden');
    if (currentProjectState.setup_status === 'passed') {
        banner.className = 'text-sm rounded-lg border px-4 py-3 border-emerald-200 bg-emerald-50 text-emerald-700';
        banner.innerText = 'Setup passed. Specification linked and authority compiled.';
        return;
    }

    banner.className = 'text-sm rounded-lg border px-4 py-3 border-amber-200 bg-amber-50 text-amber-700';
    banner.innerText = currentProjectState.setup_error || 'Setup is required before Vision.';
}

function setPhaseState(fsmState, desiredViewPhase = null) {
    activeFsmState = normalizeStateKey(fsmState);
    activePhaseId = getPhaseIdForState(activeFsmState);
    viewPhaseId = desiredViewPhase || activePhaseId;

    updateStepperUI(activeFsmState);
    renderPhaseSection();
    updateNextButton();
}

function renderPhaseSection() {
    PHASE_ORDER.forEach((phaseId) => {
        const section = document.getElementById(`phase-section-${phaseId}`);
        if (!section) return;
        if (phaseId === viewPhaseId) section.classList.remove('hidden');
        else section.classList.add('hidden');
    });
}

function isPhaseReady(phaseId) {
    if (phaseId === 'setup') {
        return currentProjectState.setup_status === 'passed' && activeFsmState !== 'SETUP_REQUIRED';
    }

    const activeIndex = phaseIndex(activePhaseId);
    const targetIndex = phaseIndex(phaseId);
    if (activeIndex > targetIndex) {
        return true;
    }

    return (PHASE_TERMINAL_STATES[phaseId] || []).includes(activeFsmState);
}

function getNextButtonModel() {
    const targetPhase = NEXT_PHASE[viewPhaseId] || null;
    if (!targetPhase) {
        return {
            label: 'Workflow Complete',
            enabled: false,
            hint: 'You reached the final phase.',
        };
    }

    const currentReady = isPhaseReady(viewPhaseId);
    if (!currentReady) {
        if (viewPhaseId === 'setup') {
            return {
                label: `Next: ${capitalizePhase(targetPhase)}`,
                enabled: false,
                hint: 'Setup must pass (valid file path + compiled authority).',
            };
        }
        const required = (PHASE_TERMINAL_STATES[viewPhaseId] || []).join(', ');
        return {
            label: `Next: ${capitalizePhase(targetPhase)}`,
            enabled: false,
            hint: required ? `Current phase must reach ${required}.` : 'Current phase is not ready yet.',
        };
    }

    return {
        label: `Next: ${capitalizePhase(targetPhase)}`,
        enabled: true,
        hint: `Navigate to ${capitalizePhase(targetPhase)} section.`,
    };
}

function updateNextButton() {
    const button = document.getElementById('btn-next-phase');
    const hint = document.getElementById('next-phase-hint');
    if (!button || !hint) return;

    const model = getNextButtonModel();
    // Inner text and HTML must be cleanly inserted with icon
    button.innerHTML = `${model.label} <span class="material-symbols-outlined text-sm">arrow_forward</span>`;
    button.disabled = !model.enabled;
    hint.innerText = model.hint;

    button.className = model.enabled
        ? 'inline-flex items-center gap-2 px-6 py-2.5 rounded-lg bg-primary hover:bg-primary/90 text-white font-bold transition-all shadow-sm'
        : 'inline-flex items-center gap-2 px-6 py-2.5 rounded-lg bg-primary/40 text-white font-bold cursor-not-allowed transition-all shadow-sm';
}

function handleNextPhase() {
    const model = getNextButtonModel();
    if (!model.enabled) return;

    const target = NEXT_PHASE[viewPhaseId];
    if (!target) return;

    viewPhaseId = target;
    renderPhaseSection();
    updateNextButton();

    // Auto-trigger logic
    if (viewPhaseId === 'backlog' && backlogAttemptCount === 0) {
        generateBacklogDraft();
    } else if (viewPhaseId === 'roadmap' && roadmapAttemptCount === 0) {
        generateRoadmapDraft();
    } else if (viewPhaseId === 'story') {
        loadStoryRequirements();
    } else if (viewPhaseId === 'sprint') {
        loadSprintCandidates();
    }
}

async function fetchProjectFSMState(projectId) {
    try {
        const response = await fetch(`/api/projects/${projectId}/state`);
        const data = await response.json();

        if (data.status !== 'success') throw new Error('Failed to load state');

        const state = data.data || {};
        currentProjectState = {
            setup_status: state.setup_status || 'failed',
            setup_error: state.setup_error || null,
        };

        const stateKey = normalizeStateKey(state.fsm_state);
        const mappedPhaseId = getPhaseIdForState(stateKey);

        const specInput = document.getElementById('setup-spec-path');
        if (specInput) {
            specInput.value = state.setup_spec_file_path || '';
            // Only unlock edits if setup completely failed
            specInput.readOnly = currentProjectState.setup_status !== 'failed';
            if (!specInput.readOnly) {
                specInput.classList.remove('bg-white', 'dark:bg-slate-900', 'cursor-not-allowed', 'border-slate-300', 'dark:border-slate-600');
                specInput.classList.add('bg-amber-50', 'dark:bg-amber-900/40', 'border-amber-400');
            } else {
                specInput.classList.add('bg-white', 'dark:bg-slate-900', 'cursor-not-allowed', 'border-slate-300', 'dark:border-slate-600');
                specInput.classList.remove('bg-amber-50', 'dark:bg-amber-900/40', 'border-amber-400');
            }
        }

        if (currentProjectState.setup_status === 'failed') {
            setPhaseState('SETUP_REQUIRED', 'setup');
        } else {
            setPhaseState(stateKey, mappedPhaseId);
            // Trigger auto-run if the page loaded directly onto these phases without history
            setTimeout(() => {
                if (viewPhaseId === 'backlog' && backlogAttemptCount === 0) {
                    generateBacklogDraft();
                } else if (viewPhaseId === 'roadmap' && roadmapAttemptCount === 0) {
                    generateRoadmapDraft();
                } else if (viewPhaseId === 'sprint') {
                    loadSprintCandidates();
                }
            }, 500);
        }

        updateSetupStatusBanner();
        updateRetryButton();
        updateNextButton();
    } catch (error) {
        console.error('Error fetching project state:', error);
        currentProjectState = { setup_status: 'failed', setup_error: 'Failed to load state.' };
        setPhaseState('SETUP_REQUIRED', 'setup');
        updateSetupStatusBanner();
    }
}

async function retryProjectSetup() {
    if (!selectedProjectId) return;

    const specInput = document.getElementById('setup-spec-path');
    const specFilePath = specInput?.value?.trim() || '';

    if (!specFilePath) {
        alert('Please provide a specification file path.');
        return;
    }

    const btn = document.getElementById('btn-retry-setup');
    const original = btn?.innerHTML;
    if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">refresh</span> Retrying...';
        btn.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/setup/retry`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ spec_file_path: specFilePath }),
        });

        const data = await response.json();
        if (data.status === 'success') {
            await fetchProjectFSMState(selectedProjectId);
            await loadVisionHistory();
        } else {
            alert(data.detail || 'Setup retry failed.');
        }
    } catch (error) {
        console.error('Setup retry error:', error);
        alert('Network error while retrying setup.');
    } finally {
        if (btn) {
            btn.innerHTML = original || '<span class="material-symbols-outlined text-sm">refresh</span> Try Setup Again';
            btn.disabled = false;
        }
    }
}

function updateStepperUI(fsmState) {
    const stateKey = normalizeStateKey(fsmState);
    const steps = getWorkflowSteps();
    const activeStepId = getPhaseIdForState(stateKey);
    let activeIndex = Math.max(0, steps.findIndex((step) => step.id === activeStepId));

    // If the active phase's FSM state is explicitly its terminal/persistence state,
    // the UI should mark it as Completed and move the Active badge to the next phase.
    if ((PHASE_TERMINAL_STATES[activeStepId] || []).includes(stateKey)) {
        activeIndex++;
    }

    steps.forEach((step, index) => {
        const stepEls = document.querySelectorAll(`[data-step-id="${step.id}"]`);
        if (stepEls.length === 0) return;

        stepEls.forEach((stepEl) => {
            const iconContainer = stepEl.querySelector('[data-role="icon"]');
            const labelSpan = stepEl.querySelector('[data-role="label"]');
            const statusSpan = stepEl.querySelector('[data-role="status"]');
            if (!iconContainer || !labelSpan || !statusSpan) return;

            if (index < activeIndex) {
                stepEl.removeAttribute('aria-current');
                iconContainer.className = 'w-10 h-10 rounded-full bg-emerald-500 text-white flex items-center justify-center ring-4 ring-white dark:ring-background-dark shadow-md transition-all';
                iconContainer.innerHTML = '<span class="material-symbols-outlined text-xl">check</span>';
                labelSpan.className = 'text-xs font-bold text-emerald-600 dark:text-emerald-400 transition-colors';
                statusSpan.className = 'text-[10px] text-emerald-500 uppercase font-black transition-colors';
                statusSpan.innerText = 'Completed';
                return;
            }

            if (index === activeIndex) {
                stepEl.setAttribute('aria-current', 'step');
                const icon = STEP_ICONS[step.id] || 'play_circle';
                iconContainer.className = 'w-10 h-10 rounded-full bg-primary text-white flex items-center justify-center ring-4 ring-white dark:ring-background-dark shadow-md transition-all';
                iconContainer.innerHTML = `<span class="material-symbols-outlined text-xl">${icon}</span>`;
                labelSpan.className = 'text-xs font-bold text-primary transition-colors';
                statusSpan.className = 'text-[10px] text-primary/80 uppercase font-black transition-colors';
                statusSpan.innerText = 'Active';
                return;
            }

            stepEl.removeAttribute('aria-current');
            iconContainer.className = 'w-10 h-10 rounded-full bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400 flex items-center justify-center ring-4 ring-white dark:ring-background-dark transition-all';
            iconContainer.innerHTML = '<span class="material-symbols-outlined text-xl">lock</span>';
            labelSpan.className = 'text-xs font-medium text-slate-500 transition-colors';
            statusSpan.className = 'text-[10px] text-slate-400 uppercase font-black transition-colors';
            statusSpan.innerText = 'Locked';
        });
    });
}

function renderVisionArtifactHtml(artifact) {
    if (!artifact) return '<div class="text-xs text-slate-500">No vision run yet.</div>';

    const uc = artifact.updated_components || {};
    const stmt = artifact.product_vision_statement || 'No statement drafted.';
    const isComplete = Boolean(artifact.is_complete);
    const questions = Array.isArray(artifact.clarifying_questions) ? artifact.clarifying_questions : [];

    const statusColor = isComplete ? 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-900/30 dark:border-emerald-800' : 'text-rose-700 bg-rose-50 border-rose-200 dark:text-rose-400 dark:bg-rose-900/30 dark:border-rose-800';
    const statusIcon = isComplete ? 'check_circle' : 'error';
    const statusText = isComplete ? 'Complete' : 'Incomplete - Needs Refinement';

    let html = `
        <div class="space-y-5">
            <!-- Status Pill -->
            <div class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border ${statusColor} text-xs font-bold">
                <span class="material-symbols-outlined text-[14px]">${statusIcon}</span>
                ${statusText}
            </div>

            <!-- Vision Statement -->
            <div class="space-y-1.5 border-l-2 border-primary/40 pl-3">
                <h6 class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Vision Statement drafted</h6>
                <div class="text-sm text-slate-800 dark:text-slate-200 leading-relaxed italic">
                    "${stmt}"
                </div>
            </div>

            <!-- Clarifying Questions -->
            ${!isComplete && questions.length > 0 ? `
            <div class="space-y-2">
                <h6 class="text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-500 flex items-center gap-1"><span class="material-symbols-outlined text-[14px]">help</span> Missing Context / Questions</h6>
                <ul class="text-xs text-slate-700 dark:text-slate-300 space-y-1.5 list-disc list-inside bg-amber-50 dark:bg-amber-900/20 p-3 rounded-lg border border-amber-200 dark:border-amber-800">
                    ${questions.map(q => `<li>${q}</li>`).join('')}
                </ul>
            </div>
            ` : ''}

            <!-- Granular Components -->
            <div class="space-y-3 pt-2 border-t border-slate-100 dark:border-slate-800">
                <h6 class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Components Dictionary</h6>
                <div class="grid grid-cols-1 gap-2.5">
    `;

    const labels = {
        project_name: 'Project Name',
        target_user: 'Target User',
        problem: 'Problem',
        product_category: 'Category',
        key_benefit: 'Key Benefit',
        competitors: 'Competitors',
        differentiator: 'Differentiator'
    };

    for (const [key, label] of Object.entries(labels)) {
        const val = uc[key];
        const isSet = val && val !== 'null' && val !== '/UNKNOWN' && String(val).trim() !== '';
        const badgeColor = isSet ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-400' : 'bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-400';
        const badgeIcon = isSet ? 'check' : 'close';
        const displayVal = isSet ? val : 'Not defined yet...';

        html += `
            <div class="flex items-start gap-2.5 text-xs">
                <div class="mt-0.5 shrink-0 w-4 h-4 rounded-full flex items-center justify-center ${badgeColor}">
                    <span class="material-symbols-outlined text-[10px] font-bold">${badgeIcon}</span>
                </div>
                <div class="flex-1">
                    <span class="font-bold text-slate-600 dark:text-slate-400">${label}:</span> 
                    <span class="${isSet ? 'text-slate-800 dark:text-slate-200 font-medium' : 'text-slate-400 italic'}">${displayVal}</span>
                </div>
            </div>
        `;
    }

    html += `
                </div>
            </div>
        </div>
    `;

    return html;
}

function renderVisionAttemptPanels(inputContext, outputArtifact) {
    const inputEl = document.getElementById('vision-input-context');
    const outputEl = document.getElementById('vision-output-artifact');
    const copyBtn = document.getElementById('btn-copy-vision-output');

    if (inputEl) {
        inputEl.innerText = inputContext ? JSON.stringify(inputContext, null, 2) : 'No vision run yet.';
    }

    if (outputEl) {
        outputEl.innerHTML = renderVisionArtifactHtml(outputArtifact);
    }
    
    currentVisionArtifactJSON = outputArtifact || null;
    if (copyBtn) {
        if (currentVisionArtifactJSON) {
            copyBtn.classList.remove('hidden');
        } else {
            copyBtn.classList.add('hidden');
        }
    }
}

function renderVisionHistory(items) {
    const container = document.getElementById('vision-history-list');
    if (!container) return;

    container.innerHTML = '';

    if (!items || items.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500">No attempts yet.</p>';
        return;
    }

    const reversed = [...items].reverse();
    reversed.forEach((item, index) => {
        const stamp = item.created_at || '-';
        const state = item.is_complete ? 'Complete' : 'Needs input';
        const color = item.is_complete ? 'text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 ring-emerald-200' : 'text-amber-600 bg-amber-50 dark:bg-amber-900/30 ring-amber-200';
        const trigger = item.trigger === 'auto_setup_transition' ? 'Auto setup' : 'Manual refine';

        const row = document.createElement('div');
        row.className = 'border border-slate-200 dark:border-slate-700 rounded-lg p-3 bg-slate-50 dark:bg-slate-800/60 transition-transform';
        row.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-xs font-extrabold text-slate-700 dark:text-slate-300">Attempt ${items.length - index}</span>
                <span class="text-[10px] uppercase ${color} px-2 py-0.5 rounded-full ring-1 ring-inset font-bold">${state}</span>
            </div>
            <p class="text-[11px] font-semibold text-slate-500 mt-2">Trigger: <span class="text-slate-700 dark:text-slate-300 font-bold">${trigger}</span></p>
            <p class="text-[10px] text-slate-400 mt-1">${stamp}</p>
        `;
        container.appendChild(row);
    });
}

function updateVisionSaveButton() {
    const button = document.getElementById('btn-save-vision');
    const hint = document.getElementById('vision-save-hint');
    if (!button || !hint) return;

    const canSave = Boolean(selectedProjectId) && latestVisionIsComplete;
    button.disabled = !canSave;
    button.className = canSave
        ? 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition-all shadow-sm'
        : 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-primary/40 text-white font-bold cursor-not-allowed transition-all';

    hint.innerText = canSave
        ? 'Vision is complete. Proceed to save and advance to Backlog.'
        : 'Save is disabled until latest Vision output has is_complete=true.';
}

async function loadVisionHistory() {
    if (!selectedProjectId) {
        visionAttemptCount = 0;
        latestVisionIsComplete = false;
        renderVisionHistory([]);
        return;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/vision/history`);
        const data = await response.json();
        if (data.status !== 'success') {
            renderVisionHistory([]);
            return;
        }

        const items = Array.isArray(data.data?.items) ? data.data.items : [];
        visionAttemptCount = items.length;
        renderVisionHistory(items);

        if (items.length > 0) {
            const latest = items[items.length - 1];
            latestVisionIsComplete = Boolean(latest.is_complete);
            renderVisionAttemptPanels(latest.input_context || null, latest.output_artifact || null);
        } else {
            latestVisionIsComplete = false;
            renderVisionAttemptPanels(null, null);
        }

        updateVisionSaveButton();
    } catch (error) {
        console.error('Failed to load vision history:', error);
        visionAttemptCount = 0;
        latestVisionIsComplete = false;
        renderVisionHistory([]);
    }
}

async function generateVisionDraft() {
    if (!selectedProjectId) {
        alert('Select a project first.');
        return;
    }

    const input = document.getElementById('vision-user-input');
    const userInput = input?.value?.trim() || '';
    if (!userInput && visionAttemptCount === 0) {
        await loadVisionHistory();
    }
    if (visionAttemptCount > 0 && !userInput) {
        alert('Please provide feedback to refine Vision.');
        return;
    }

    const button = document.getElementById('btn-generate-vision');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">cycle</span> Running...';
        button.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/vision/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_input: userInput }),
        });

        if (response.status >= 400) {
            const errorBody = await response.json();
            throw new Error(errorBody.detail || 'Vision generation failed');
        }

        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error('Vision generation failed');
        }

        latestVisionIsComplete = Boolean(data.data?.is_complete);
        renderVisionAttemptPanels(data.data?.input_context || null, data.data?.output_artifact || null);
        setPhaseState(data.data?.fsm_state || 'VISION_INTERVIEW', 'vision');

        await loadVisionHistory();
    } catch (error) {
        console.error(error);
        alert(error.message || 'Vision generation failed.');
    } finally {
        if (button) {
            button.innerHTML = original || '<span class="material-symbols-outlined text-sm">cycle</span> Generate / Refine';
            button.disabled = false;
        }
        updateVisionSaveButton();
    }
}

async function saveVisionDraft() {
    if (!selectedProjectId) {
        alert('Select a project first.');
        return;
    }

    const button = document.getElementById('btn-save-vision');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm">save</span> Saving...';
        button.disabled = true;
    }

    let success = false;
    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/vision/save`, {
            method: 'POST',
        });

        if (response.status === 409) {
            const body = await response.json();
            throw new Error(body.detail || 'Vision is not complete yet.');
        }
        if (response.status >= 400) {
            throw new Error('Failed to save vision.');
        }

        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error('Failed to save vision.');
        }

        setPhaseState('VISION_PERSISTENCE', 'vision');
        latestVisionIsComplete = true;
        success = true;

        await fetchProjectFSMState(selectedProjectId);

        if (button) {
            button.innerHTML = '<span class="material-symbols-outlined text-sm">check_circle</span> Saved Successfully!';
            button.className = 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-500 text-white font-bold transition-all shadow-md scale-105 ring-2 ring-emerald-200';
            setTimeout(() => {
                updateVisionSaveButton();
            }, 3000);
        }

        const nextBtn = document.getElementById('btn-next-phase');
        if (nextBtn) {
            nextBtn.classList.add('ring-4', 'ring-primary/40', 'scale-105');
            setTimeout(() => {
                nextBtn.classList.remove('ring-4', 'ring-primary/40', 'scale-105');
            }, 3000);
        }

    } catch (error) {
        console.error(error);
        alert(error.message || 'Failed to save vision.');
    } finally {
        if (!success) {
            if (button) button.innerHTML = original || '<span class="material-symbols-outlined text-sm">save</span> Save Vision';
            updateVisionSaveButton();
        }
    }
}

// --- BACKLOG LOGIC ---

function renderBacklogArtifactHtml(artifact) {
    if (!artifact) return '<div class="text-[11px] text-slate-500 text-center mt-10">No backlog generated yet.</div>';

    const items = Array.isArray(artifact.backlog_items) ? artifact.backlog_items : [];
    const isComplete = Boolean(artifact.is_complete);
    const questions = Array.isArray(artifact.clarifying_questions) ? artifact.clarifying_questions : [];

    const statusColor = isComplete ? 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-900/30 dark:border-emerald-800' : 'text-rose-700 bg-rose-50 border-rose-200 dark:text-rose-400 dark:bg-rose-900/30 dark:border-rose-800';
    const statusIcon = isComplete ? 'check_circle' : 'error';
    const statusText = isComplete ? 'Complete' : 'Incomplete - Needs Refinement';

    let html = `
        <div class="space-y-5">
            <!-- Status Pill -->
            <div class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border ${statusColor} text-xs font-bold">
                <span class="material-symbols-outlined text-[14px]">${statusIcon}</span>
                ${statusText}
            </div>

            <!-- Clarifying Questions -->
            ${!isComplete && questions.length > 0 ? `
            <div class="space-y-2">
                <h6 class="text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-500 flex items-center gap-1"><span class="material-symbols-outlined text-[14px]">help</span> Missing Context / Questions</h6>
                <ul class="text-xs text-slate-700 dark:text-slate-300 space-y-1.5 list-disc list-inside bg-amber-50 dark:bg-amber-900/20 p-3 rounded-lg border border-amber-200 dark:border-amber-800">
                    ${questions.map(q => `<li>${q}</li>`).join('')}
                </ul>
            </div>
            ` : ''}

            <!-- Items list -->
            <div class="space-y-3 pt-2">
                <h6 class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Prioritized Items (${items.length})</h6>
                <div class="space-y-3">
    `;

    if (items.length === 0) {
        html += `<div class="text-[11px] italic text-slate-400">No items available.</div>`;
    }

    items.forEach((item) => {
        let sizeColor = 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';
        if (item.estimated_effort === 'S') sizeColor = 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-400';
        if (item.estimated_effort === 'M') sizeColor = 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-400';
        if (item.estimated_effort === 'L') sizeColor = 'bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-400';
        if (item.estimated_effort === 'XL') sizeColor = 'bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-400';

        html += `
            <div class="border border-slate-200 dark:border-slate-700 rounded-lg p-3 bg-white dark:bg-slate-800 overflow-hidden relative">
                <div class="absolute left-0 top-0 bottom-0 w-1 bg-slate-300 dark:bg-slate-600"></div>
                <div class="flex items-start justify-between gap-3 ml-2">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-[10px] font-black bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400 px-1.5 py-0.5 rounded">#${item.priority || '?'}</span>
                            <span class="text-[10px] font-bold uppercase text-indigo-500 dark:text-indigo-400">${item.value_driver || 'Unknown'}</span>
                        </div>
                        <h4 class="text-sm font-bold text-slate-800 dark:text-slate-200">${item.requirement || 'Untitled'}</h4>
                        <p class="text-[11px] text-slate-500 dark:text-slate-400 mt-1.5 leading-relaxed">${item.justification || ''}</p>
                    </div>
                    <div class="shrink-0 text-center">
                        <div class="text-[10px] uppercase font-bold text-slate-400 mb-0.5">Size</div>
                        <div class="px-2 py-1 rounded text-xs font-black ${sizeColor}">${item.estimated_effort || '?'}</div>
                    </div>
                </div>
            </div>
        `;
    });

    html += `
                </div>
            </div>
        </div>
    `;

    return html;
}

function renderBacklogAttemptPanels(inputContext, outputArtifact) {
    const inputEl = document.getElementById('backlog-input-context');
    const outputEl = document.getElementById('backlog-output-artifact');
    const copyBtn = document.getElementById('btn-copy-backlog-output');

    if (inputEl) {
        inputEl.innerText = inputContext ? JSON.stringify(inputContext, null, 2) : 'No backlog run yet.';
    }

    if (outputEl) {
        outputEl.innerHTML = renderBacklogArtifactHtml(outputArtifact);
    }
    
    currentBacklogArtifactJSON = outputArtifact || null;
    if (copyBtn) {
        if (currentBacklogArtifactJSON) {
            copyBtn.classList.remove('hidden');
        } else {
            copyBtn.classList.add('hidden');
        }
    }
}

function renderBacklogHistory(items) {
    const container = document.getElementById('backlog-history-list');
    if (!container) return;

    container.innerHTML = '';

    if (!items || items.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500">No attempts yet.</p>';
        return;
    }

    const reversed = [...items].reverse();
    reversed.forEach((item, index) => {
        const stamp = item.created_at || '-';
        const state = item.is_complete ? 'Complete' : 'Needs input';
        const color = item.is_complete ? 'text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 ring-emerald-200' : 'text-amber-600 bg-amber-50 dark:bg-amber-900/30 ring-amber-200';
        const trigger = item.trigger === 'auto_transition' ? 'Auto setup' : 'Manual refine';

        const row = document.createElement('div');
        row.className = 'border border-slate-200 dark:border-slate-700 rounded-lg p-3 bg-slate-50 dark:bg-slate-800/60 transition-transform';
        row.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-xs font-extrabold text-slate-700 dark:text-slate-300">Attempt ${items.length - index}</span>
                <span class="text-[10px] uppercase ${color} px-2 py-0.5 rounded-full ring-1 ring-inset font-bold">${state}</span>
            </div>
            <p class="text-[11px] font-semibold text-slate-500 mt-2">Trigger: <span class="text-slate-700 dark:text-slate-300 font-bold">${trigger}</span></p>
            <p class="text-[10px] text-slate-400 mt-1">${stamp}</p>
        `;
        container.appendChild(row);
    });
}

function updateBacklogSaveButton() {
    const button = document.getElementById('btn-save-backlog');
    const hint = document.getElementById('backlog-save-hint');
    if (!button || !hint) return;

    const canSave = Boolean(selectedProjectId) && latestBacklogIsComplete;
    button.disabled = !canSave;
    button.className = canSave
        ? 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition-all shadow-sm'
        : 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-primary/40 text-white font-bold cursor-not-allowed transition-all';

    hint.innerText = canSave
        ? 'Backlog is complete. Proceed to save and advance to Roadmap.'
        : 'Save is disabled until latest Backlog output has is_complete=true.';
}

async function loadBacklogHistory() {
    if (!selectedProjectId) {
        backlogAttemptCount = 0;
        latestBacklogIsComplete = false;
        renderBacklogHistory([]);
        return;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/backlog/history`);
        const data = await response.json();
        if (data.status !== 'success') {
            renderBacklogHistory([]);
            return;
        }

        const items = Array.isArray(data.data?.items) ? data.data.items : [];
        backlogAttemptCount = items.length;
        renderBacklogHistory(items);

        if (items.length > 0) {
            const latest = items[items.length - 1];
            latestBacklogIsComplete = Boolean(latest.is_complete);
            renderBacklogAttemptPanels(latest.input_context || null, latest.output_artifact || null);
        } else {
            latestBacklogIsComplete = false;
            renderBacklogAttemptPanels(null, null);
        }

        updateBacklogSaveButton();
    } catch (error) {
        console.error('Failed to load backlog history:', error);
        backlogAttemptCount = 0;
        latestBacklogIsComplete = false;
        renderBacklogHistory([]);
    }
}

async function generateBacklogDraft() {
    if (!selectedProjectId) {
        alert('Select a project first.');
        return;
    }

    const input = document.getElementById('backlog-user-input');
    const userInput = input?.value?.trim() || '';
    if (backlogAttemptCount > 0 && !userInput) {
        alert('Please provide feedback to refine Backlog.');
        return;
    }

    const button = document.getElementById('btn-generate-backlog');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">cycle</span> Running...';
        button.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/backlog/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_input: userInput }),
        });

        if (response.status >= 400) {
            const errorBody = await response.json();
            throw new Error(errorBody.detail || 'Backlog generation failed');
        }

        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error('Backlog generation failed');
        }

        latestBacklogIsComplete = Boolean(data.data?.is_complete);
        renderBacklogAttemptPanels(data.data?.input_context || null, data.data?.output_artifact || null);
        setPhaseState(data.data?.fsm_state || 'BACKLOG_INTERVIEW', 'backlog');

        await loadBacklogHistory();
    } catch (error) {
        console.error(error);
        alert(error.message || 'Backlog generation failed.');
    } finally {
        if (button) {
            button.innerHTML = original || '<span class="material-symbols-outlined text-sm">cycle</span> Generate / Refine';
            button.disabled = false;
        }
        updateBacklogSaveButton();
    }
}

async function saveBacklogDraft() {
    if (!selectedProjectId) {
        alert('Select a project first.');
        return;
    }

    const button = document.getElementById('btn-save-backlog');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm">save</span> Saving...';
        button.disabled = true;
    }

    let success = false;
    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/backlog/save`, {
            method: 'POST',
        });

        if (response.status === 409) {
            const body = await response.json();
            throw new Error(body.detail || 'Backlog is not complete yet.');
        }
        if (response.status >= 400) {
            throw new Error('Failed to save backlog.');
        }

        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error('Failed to save backlog.');
        }

        setPhaseState('BACKLOG_PERSISTENCE', 'backlog');
        latestBacklogIsComplete = true;
        success = true;

        await fetchProjectFSMState(selectedProjectId);

        if (button) {
            button.innerHTML = '<span class="material-symbols-outlined text-sm">check_circle</span> Saved Successfully!';
            button.className = 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-500 text-white font-bold transition-all shadow-md scale-105 ring-2 ring-emerald-200';
            setTimeout(() => {
                updateBacklogSaveButton();
            }, 3000);
        }

        const nextBtn = document.getElementById('btn-next-phase');
        if (nextBtn) {
            nextBtn.classList.add('ring-4', 'ring-primary/40', 'scale-105');
            setTimeout(() => {
                nextBtn.classList.remove('ring-4', 'ring-primary/40', 'scale-105');
            }, 3000);
        }

    } catch (error) {
        console.error(error);
        alert(error.message || 'Failed to save backlog.');
    } finally {
        if (!success) {
            if (button) button.innerHTML = original || '<span class="material-symbols-outlined text-sm">save</span> Save Backlog';
            updateBacklogSaveButton();
        }
    }
}


// --- ROADMAP LOGIC ---

function renderRoadmapArtifactHtml(artifact) {
    if (!artifact) return '<div class="text-[11px] text-slate-500 text-center mt-10">No roadmap generated yet.</div>';

    const items = Array.isArray(artifact.roadmap_releases) ? artifact.roadmap_releases : [];
    const isComplete = Boolean(artifact.is_complete);
    const questions = Array.isArray(artifact.clarifying_questions) ? artifact.clarifying_questions : [];

    const statusColor = isComplete ? 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-900/30 dark:border-emerald-800' : 'text-rose-700 bg-rose-50 border-rose-200 dark:text-rose-400 dark:bg-rose-900/30 dark:border-rose-800';
    const statusIcon = isComplete ? 'check_circle' : 'error';
    const statusText = isComplete ? 'Complete' : 'Incomplete - Needs Refinement';

    let html = `
        <div class="space-y-5">
            <!-- Status Pill -->
            <div class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border ${statusColor} text-xs font-bold">
                <span class="material-symbols-outlined text-[14px]">${statusIcon}</span>
                ${statusText}
            </div>

            <!-- Roadmap Summary -->
            <div class="space-y-1.5 border-l-2 border-purple-400/40 pl-3">
                <h6 class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Roadmap Overview</h6>
                <div class="text-sm text-slate-800 dark:text-slate-200 leading-relaxed italic">
                    "${artifact.roadmap_summary || 'No summary provided.'}"
                </div>
            </div>

            <!-- Clarifying Questions -->
            ${!isComplete && questions.length > 0 ? `
            <div class="space-y-2">
                <h6 class="text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-500 flex items-center gap-1"><span class="material-symbols-outlined text-[14px]">help</span> Missing Context / Questions</h6>
                <ul class="text-xs text-slate-700 dark:text-slate-300 space-y-1.5 list-disc list-inside bg-amber-50 dark:bg-amber-900/20 p-3 rounded-lg border border-amber-200 dark:border-amber-800">
                    ${questions.map(q => `<li>${q}</li>`).join('')}
                </ul>
            </div>
            ` : ''}

            <!-- Items list -->
            <div class="space-y-3 pt-2">
                <h6 class="text-[10px] font-bold uppercase tracking-wider text-slate-500">Releases & Milestones (${items.length})</h6>
                <div class="space-y-4">
    `;

    if (items.length === 0) {
        html += `<div class="text-[11px] italic text-slate-400">No releases available.</div>`;
    }

    items.forEach((item, index) => {
        const assignedCount = Array.isArray(item.items) ? item.items.length : 0;

        html += `
            <div class="border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 overflow-hidden relative shadow-sm">
                <div class="bg-slate-50 dark:bg-slate-800/80 px-4 py-3 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center">
                    <div class="flex items-center gap-2">
                        <span class="text-[10px] font-black bg-purple-100 text-purple-600 dark:bg-purple-900/40 dark:text-purple-400 px-2 py-0.5 rounded-full uppercase">Release ${index + 1}</span>
                        <h4 class="text-sm font-bold text-slate-800 dark:text-slate-200">${item.release_name || 'Untitled Release'}</h4>
                    </div>
                </div>
                <div class="p-4 space-y-3">
                    <div>
                        <div class="text-[10px] uppercase font-bold text-slate-400 mb-0.5">Focus Area</div>
                        <p class="text-[11px] text-slate-700 dark:text-slate-300 font-medium">${item.focus_area || 'None specified'}</p>
                    </div>
                    <div>
                        <div class="text-[10px] uppercase font-bold text-slate-400 mb-0.5">Theme</div>
                        <p class="text-[11px] text-slate-700 dark:text-slate-300 font-medium">${item.theme || 'None specified'}</p>
                    </div>
                    <div>
                        <div class="text-[10px] uppercase font-bold text-slate-400 mb-0.5">Reasoning</div>
                        <p class="text-[11px] text-slate-700 dark:text-slate-300 font-medium">${item.reasoning || 'None specified'}</p>
                    </div>
                    
                    <div class="pt-2">
                        <div class="flex items-center gap-2 mb-2">
                            <span class="text-[10px] uppercase font-bold text-slate-400">Assigned Backlog Items</span>
                            <span class="bg-slate-100 text-slate-500 text-[9px] font-black px-1.5 py-0.5 rounded-full">${assignedCount}</span>
                        </div>
                        <ul class="text-[11px] text-slate-600 dark:text-slate-400 list-disc list-inside space-y-1">
                            ${(item.items || []).map(bItem => `<li><span class="font-medium text-slate-700 dark:text-slate-300">${bItem}</span></li>`).join('')}
                        </ul>
                    </div>
                </div>
            </div>
        `;
    });

    html += `
                </div>
            </div>
        </div>
    `;

    return html;
}

function renderRoadmapAttemptPanels(inputContext, outputArtifact) {
    const inputEl = document.getElementById('roadmap-input-context');
    const outputEl = document.getElementById('roadmap-output-artifact');
    const copyBtn = document.getElementById('btn-copy-roadmap-output');

    if (inputEl) {
        inputEl.innerText = inputContext ? JSON.stringify(inputContext, null, 2) : 'No roadmap run yet.';
    }

    if (outputEl) {
        outputEl.innerHTML = renderRoadmapArtifactHtml(outputArtifact);
    }
    
    currentRoadmapArtifactJSON = outputArtifact || null;
    if (copyBtn) {
        if (currentRoadmapArtifactJSON) {
            copyBtn.classList.remove('hidden');
        } else {
            copyBtn.classList.add('hidden');
        }
    }
}

function renderRoadmapHistory(items) {
    const container = document.getElementById('roadmap-history-list');
    if (!container) return;

    container.innerHTML = '';

    if (!items || items.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500">No attempts yet.</p>';
        return;
    }

    const reversed = [...items].reverse();
    reversed.forEach((item, index) => {
        const stamp = item.created_at || '-';
        const state = item.is_complete ? 'Complete' : 'Needs input';
        const color = item.is_complete ? 'text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 ring-emerald-200' : 'text-amber-600 bg-amber-50 dark:bg-amber-900/30 ring-amber-200';
        const trigger = item.trigger === 'auto_transition' ? 'Auto setup' : 'Manual refine';

        const row = document.createElement('div');
        row.className = 'border border-slate-200 dark:border-slate-700 rounded-lg p-3 bg-slate-50 dark:bg-slate-800/60 transition-transform';
        row.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-xs font-extrabold text-slate-700 dark:text-slate-300">Attempt ${items.length - index}</span>
                <span class="text-[10px] uppercase ${color} px-2 py-0.5 rounded-full ring-1 ring-inset font-bold">${state}</span>
            </div>
            <p class="text-[11px] font-semibold text-slate-500 mt-2">Trigger: <span class="text-slate-700 dark:text-slate-300 font-bold">${trigger}</span></p>
            <p class="text-[10px] text-slate-400 mt-1">${stamp}</p>
        `;
        container.appendChild(row);
    });
}

function updateRoadmapSaveButton() {
    const button = document.getElementById('btn-save-roadmap');
    const hint = document.getElementById('roadmap-save-hint');
    if (!button || !hint) return;

    const canSave = Boolean(selectedProjectId) && latestRoadmapIsComplete;
    button.disabled = !canSave;
    button.className = canSave
        ? 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition-all shadow-sm'
        : 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-primary/40 text-white font-bold cursor-not-allowed transition-all';

    hint.innerText = canSave
        ? 'Roadmap is complete. Proceed to save and advance to Stories.'
        : 'Save is disabled until latest Roadmap output has is_complete=true.';
}

async function loadRoadmapHistory() {
    if (!selectedProjectId) {
        roadmapAttemptCount = 0;
        latestRoadmapIsComplete = false;
        renderRoadmapHistory([]);
        return;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/roadmap/history`);
        const data = await response.json();
        if (data.status !== 'success') {
            renderRoadmapHistory([]);
            return;
        }

        const items = Array.isArray(data.data?.items) ? data.data.items : [];
        roadmapAttemptCount = items.length;
        renderRoadmapHistory(items);

        if (items.length > 0) {
            const latest = items[items.length - 1];
            latestRoadmapIsComplete = Boolean(latest.is_complete);
            renderRoadmapAttemptPanels(latest.input_context || null, latest.output_artifact || null);
        } else {
            latestRoadmapIsComplete = false;
            renderRoadmapAttemptPanels(null, null);
        }

        updateRoadmapSaveButton();
    } catch (error) {
        console.error('Failed to load roadmap history:', error);
        roadmapAttemptCount = 0;
        latestRoadmapIsComplete = false;
        renderRoadmapHistory([]);
    }
}

async function generateRoadmapDraft() {
    if (!selectedProjectId) {
        alert('Select a project first.');
        return;
    }

    const input = document.getElementById('roadmap-user-input');
    const userInput = input?.value?.trim() || '';
    if (roadmapAttemptCount > 0 && !userInput) {
        alert('Please provide feedback to refine the Roadmap.');
        return;
    }

    const button = document.getElementById('btn-generate-roadmap');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">cycle</span> Running...';
        button.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/roadmap/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_input: userInput }),
        });

        if (response.status >= 400) {
            const errorBody = await response.json();
            throw new Error(errorBody.detail || 'Roadmap generation failed');
        }

        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error('Roadmap generation failed');
        }

        latestRoadmapIsComplete = Boolean(data.data?.is_complete);
        renderRoadmapAttemptPanels(data.data?.input_context || null, data.data?.output_artifact || null);
        setPhaseState(data.data?.fsm_state || 'ROADMAP_INTERVIEW', 'roadmap');

        await loadRoadmapHistory();
    } catch (error) {
        console.error(error);
        alert(error.message || 'Roadmap generation failed.');
    } finally {
        if (button) {
            button.innerHTML = original || '<span class="material-symbols-outlined text-sm">cycle</span> Generate / Refine';
            button.disabled = false;
        }
        updateRoadmapSaveButton();
    }
}

async function saveRoadmapDraft() {
    if (!selectedProjectId) {
        alert('Select a project first.');
        return;
    }

    const button = document.getElementById('btn-save-roadmap');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm">save</span> Saving...';
        button.disabled = true;
    }

    let success = false;
    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/roadmap/save`, {
            method: 'POST',
        });

        if (response.status === 409) {
            const body = await response.json();
            throw new Error(body.detail || 'Roadmap is not complete yet.');
        }
        if (response.status >= 400) {
            throw new Error('Failed to save roadmap.');
        }

        const data = await response.json();
        if (data.status !== 'success') {
            throw new Error('Failed to save roadmap.');
        }

        setPhaseState('ROADMAP_PERSISTENCE', 'roadmap');
        latestRoadmapIsComplete = true;
        success = true;

        await fetchProjectFSMState(selectedProjectId);

        if (button) {
            button.innerHTML = '<span class="material-symbols-outlined text-sm">check_circle</span> Saved Successfully!';
            button.className = 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-500 text-white font-bold transition-all shadow-md scale-105 ring-2 ring-emerald-200';
            setTimeout(() => {
                updateRoadmapSaveButton();
            }, 3000);
        }

        const nextBtn = document.getElementById('btn-next-phase');
        if (nextBtn) {
            nextBtn.classList.add('ring-4', 'ring-primary/40', 'scale-105');
            setTimeout(() => {
                nextBtn.classList.remove('ring-4', 'ring-primary/40', 'scale-105');
            }, 3000);
        }

    } catch (error) {
        console.error(error);
        alert(error.message || 'Failed to save roadmap.');
    } finally {
        if (!success) {
            if (button) button.innerHTML = original || '<span class="material-symbols-outlined text-sm">save</span> Save Roadmap';
            updateRoadmapSaveButton();
        }
    }
}

// ==========================================
// STORY PHASE LOGIC
// ==========================================

let storyGroups = []; // Array of grouped milestone objects

async function loadStoryRequirements() {
    if (!selectedProjectId) return;

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/story/pending`);
        const data = await response.json();

        if (data.status === 'success') {
            storyGroups = data.data.grouped_items || [];

            // Build old flat list used for 'All done' checking
            storyRequirements = [];
            storyGroups.forEach(g => {
                storyRequirements.push(...g.requirements);
            });

            renderStoryRequirementsList();
            updateCompleteStoryPhaseButton();
            await loadSprintCandidates();

            // Auto-select first if none selected
            if (!activeStoryReq && storyRequirements.length > 0) {
                const target = storyRequirements.find(r => r.status !== 'Saved') || storyRequirements[0];
                selectStoryRequirement(target.requirement);
            }
        }
    } catch (e) {
        console.error("Failed to load story requirements:", e);
    }
}

function renderStoryRequirementsList() {
    const container = document.getElementById('story-req-list');
    if (!container) return;

    container.innerHTML = '';
    if (storyGroups.length === 0) {
        container.innerHTML = '<div class="text-[11px] text-slate-500 text-center italic py-4">No requirements found.</div>';
        return;
    }

    storyGroups.forEach((group, index) => {
        // Milestone Header
        const header = document.createElement('div');
        header.className = 'mt-4 mb-2 first:mt-0';
        header.innerHTML = `
            <div class="flex items-center gap-1.5 px-1">
                <span class="material-symbols-outlined text-[14px] text-slate-400">flag</span>
                <h4 class="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wide">Milestone ${index + 1}</h4>
            </div>
            ${group.theme ? `<p class="text-[10px] text-slate-500 px-1 mt-0.5 ml-5 italic border-l-2 border-slate-200">${group.theme}</p>` : ''}
        `;
        container.appendChild(header);

        // Milestone Items Container
        const itemsContainer = document.createElement('div');
        itemsContainer.className = 'space-y-1.5 ml-2 border-l-2 border-slate-100 dark:border-slate-800 pl-3';

        group.requirements.forEach(req => {
            let statusColor = 'bg-slate-200 dark:bg-slate-700'; // Default: Pending
            let statusIcon = 'circle';

            if (req.status === 'Saved') {
                statusColor = 'bg-emerald-500';
                statusIcon = 'check_circle';
            } else if (req.status === 'Attempted') {
                statusColor = 'bg-amber-500';
                statusIcon = 'hourglass_bottom';
            }

            const isSelected = activeStoryReq === req.requirement;
            const selectedClasses = isSelected
                ? 'border-orange-500 bg-orange-50 dark:bg-orange-900/30 shadow-sm'
                : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/60 hover:border-orange-300 dark:hover:border-orange-700 cursor-pointer';

            const row = document.createElement('div');
            row.className = `p-2.5 rounded-lg border transition-all ${selectedClasses}`;
            row.onclick = () => {
                if (!isSelected) selectStoryRequirement(req.requirement);
            };

            row.innerHTML = `
                <div class="flex items-start gap-2">
                    <div class="mt-0.5 rounded-full ${statusColor} w-3 h-3 flex-shrink-0 flex items-center justify-center">
                        <span class="material-symbols-outlined text-[8px] text-white font-bold">${statusIcon}</span>
                    </div>
                    <div class="flex-1 min-w-0">
                        <p class="text-[11px] font-bold text-slate-800 dark:text-slate-200 truncate" title="${req.requirement.replace(/"/g, '&quot;')}">${req.requirement}</p>
                        <div class="flex items-center justify-between mt-1">
                            <span class="text-[9px] text-slate-500">${req.status}</span>
                            <span class="text-[9px] font-bold px-1.5 py-0 bg-slate-100 dark:bg-slate-700 text-slate-500 rounded">${req.attempt_count} runs</span>
                        </div>
                    </div>
                </div>
            `;
            itemsContainer.appendChild(row);
        });

        container.appendChild(itemsContainer);
    });
}

async function selectStoryRequirement(reqName) {
    activeStoryReq = reqName;
    renderStoryRequirementsList(); // update active styling

    // Toggle UI panels
    document.getElementById('story-detail-placeholder').classList.add('opacity-0', 'pointer-events-none');
    document.getElementById('story-detail-active').classList.remove('opacity-0', 'pointer-events-none');

    document.getElementById('story-active-req-title').innerText = reqName;

    // Clear input
    const input = document.getElementById('story-user-input');
    if (input) input.value = '';

    // Load history for specific req
    await loadStoryHistory(reqName);
}

async function loadStoryHistory(reqName) {
    if (!reqName || !selectedProjectId) return;

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/story/history?parent_requirement=${encodeURIComponent(reqName)}`);
        const data = await response.json();

        if (data.status === 'success') {
            const items = Array.isArray(data.data?.items) ? data.data.items : [];
            activeStoryAttemptCount = items.length;
            renderStoryHistory(items);

            if (items.length > 0) {
                const latest = items[items.length - 1];
                activeStoryIsComplete = Boolean(latest.is_complete);
                renderStoryAttemptPanels(latest.input_context || null, latest.output_artifact || null);
            } else {
                activeStoryIsComplete = false;
                renderStoryAttemptPanels(null, null);
            }
            updateStorySaveButton();
        }
    } catch (e) {
        console.error("Failed to load story history:", e);
    }
}

function renderStoryHistory(items) {
    const container = document.getElementById('story-history-list');
    if (!container) return;

    container.innerHTML = '';
    if (!items || items.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500">No attempts yet.</p>';
        return;
    }

    const reversed = [...items].reverse();
    reversed.forEach((item, index) => {
        const stamp = item.created_at || '-';
        const state = item.is_complete ? 'Complete' : 'Needs input';
        const color = item.is_complete ? 'text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 ring-emerald-200' : 'text-amber-600 bg-amber-50 dark:bg-amber-900/30 ring-amber-200';

        const row = document.createElement('div');
        row.className = 'border border-slate-200 dark:border-slate-700 rounded-lg p-3 bg-slate-50 dark:bg-slate-800/60 transition-transform';
        row.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-xs font-extrabold text-slate-700 dark:text-slate-300">Attempt ${items.length - index}</span>
                <span class="text-[10px] uppercase ${color} px-2 py-0.5 rounded-full ring-1 ring-inset font-bold">${state}</span>
            </div>
            <p class="text-[10px] text-slate-400 mt-2">${stamp}</p>
        `;
        container.appendChild(row);
    });
}

function renderStoryAttemptPanels(inputContext, outputArtifact) {
    const inputCanvas = document.getElementById('story-input-context');
    const outputCanvas = document.getElementById('story-output-artifact');
    const copyBtn = document.getElementById('btn-copy-story-output');

    if (!inputCanvas || !outputCanvas) return;

    if (!inputContext) {
        inputCanvas.innerText = "No input context available for this attempt.";
    } else {
        inputCanvas.innerText = JSON.stringify(inputContext, null, 2);
    }

    if (!outputArtifact) {
        outputCanvas.innerHTML = `
            <div class="text-xs text-slate-500 flex flex-col items-center justify-center h-full gap-3 opacity-60">
                <span class="material-symbols-outlined text-4xl">receipt_long</span>
                <p>No stories generated yet.</p>
            </div>
        `;
        return;
    }

    outputCanvas.innerHTML = renderStoryArtifactHtml(outputArtifact);
    
    currentStoryArtifactJSON = outputArtifact || null;
    if (copyBtn) {
        if (currentStoryArtifactJSON) {
            copyBtn.classList.remove('hidden');
        } else {
            copyBtn.classList.add('hidden');
        }
    }
}

function renderStoryArtifactHtml(artifact) {
    let html = '';

    if (artifact.error) {
        html += `
            <div class="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 p-4 rounded-lg mb-4">
                <div class="flex items-center gap-2 text-red-700 dark:text-red-400 font-bold mb-2">
                    <span class="material-symbols-outlined">error</span> Generation Failed
                </div>
                <p class="text-[11px] font-mono text-red-600 dark:text-red-300 whitespace-pre-wrap">${artifact.message || 'Unknown error'}</p>
        `;
        if (artifact.raw_output) {
            // Escape HTML just in case
            const safeRaw = artifact.raw_output.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            html += `
                <div class="mt-4 border-t border-red-200 dark:border-red-800/50 pt-3">
                    <p class="text-[10px] font-bold text-red-700 dark:text-red-400 mb-1 uppercase tracking-wide">Raw Agent Output:</p>
                    <pre class="text-[10px] font-mono text-red-600 dark:text-red-300 bg-white/50 dark:bg-black/20 p-2 rounded overflow-x-auto whitespace-pre-wrap">${safeRaw}</pre>
                </div>
            `;
        }
        html += `</div>`;
    } else if (!artifact.is_complete && artifact.clarifying_questions?.length > 0) {
        html += `
            <div class="bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 p-4 rounded-lg mb-4">
                <div class="flex items-center gap-2 text-amber-700 dark:text-amber-400 font-bold mb-2">
                    <span class="material-symbols-outlined">help</span> Agent Needs Clarification
                </div>
                <ul class="text-[11px] text-amber-800 dark:text-amber-300 list-disc list-inside space-y-1">
                    ${artifact.clarifying_questions.map(q => `<li>${q}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    const stories = Array.isArray(artifact.user_stories) ? artifact.user_stories : [];
    if (stories.length === 0 && !artifact.error) {
        html += `<p class="text-xs text-slate-500 italic">No stories generated.</p>`;
        return html;
    }

    html += `<div class="space-y-4">`;
    stories.forEach((story, index) => {
        let investBadge = '';
        if (story.invest_score === 'High') {
            investBadge = '<span class="px-2 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400 text-[9px] font-black uppercase">INVEST: High</span>';
        } else if (story.invest_score === 'Medium') {
            investBadge = '<span class="px-2 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 text-[9px] font-black uppercase">INVEST: Medium</span>';
        } else {
            investBadge = '<span class="px-2 py-0.5 rounded bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 text-[9px] font-black uppercase">INVEST: Low</span>';
        }

        html += `
            <div class="border border-slate-200 dark:border-slate-700 rounded-lg p-4 bg-white dark:bg-slate-800/60 shadow-sm relative pt-6">
                <span class="absolute top-0 right-0 rounded-bl-lg rounded-tr-lg bg-slate-100 dark:bg-slate-700 text-slate-500 text-[9px] font-black px-2 py-1">STORY ${index + 1}</span>
                
                <div class="flex gap-2 items-start justify-between mb-3 border-b border-slate-100 dark:border-slate-700 pb-3">
                    <h4 class="font-bold text-sm text-slate-800 dark:text-slate-200">${story.story_title}</h4>
                    <div class="flex items-center gap-1.5 flex-wrap justify-end">
                        ${story.estimated_effort ? `<span class="px-2 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400 text-[9px] font-black uppercase">Effort: ${story.estimated_effort}</span>` : ''}
                        ${investBadge}
                    </div>
                </div>
                
                <div class="bg-indigo-50/50 dark:bg-indigo-900/10 p-3 rounded-lg border border-indigo-100 dark:border-indigo-800/30 mb-4">
                    <p class="text-[12px] font-mono text-indigo-900 dark:text-indigo-300 leading-relaxed italic border-l-2 border-indigo-300 dark:border-indigo-600 pl-3">${story.statement}</p>
                </div>
                
                <div>
                    <h5 class="text-[10px] uppercase font-bold text-slate-400 mb-2">Acceptance Criteria</h5>
                    <ul class="text-[11px] text-slate-700 dark:text-slate-300 space-y-1.5 list-disc pl-4">
                        ${(story.acceptance_criteria || []).map(ac => `<li>${ac}</li>`).join('')}
                    </ul>
                </div>
                
                ${(story.produced_artifacts && story.produced_artifacts.length > 0) ? `
                <div class="mt-4 border-t border-slate-100 dark:border-slate-700 pt-3 flex items-start gap-2">
                    <span class="material-symbols-outlined text-[14px] text-indigo-400 mt-0.5 select-none text-transparent bg-clip-text">inventory_2</span>
                    <div>
                        <h5 class="text-[9px] uppercase font-bold text-slate-500 mb-1.5">Produced Artifacts</h5>
                        <div class="flex flex-wrap gap-1.5">
                            ${story.produced_artifacts.map(a => `<span class="px-2 py-0.5 bg-slate-100 dark:bg-slate-700/50 text-slate-700 dark:text-slate-300 text-[10px] rounded border border-slate-200 dark:border-slate-600 shadow-sm font-mono tracking-tight">${a}</span>`).join('')}
                        </div>
                    </div>
                </div>
                ` : ''}
                
                ${story.decomposition_warning ? `
                <div class="mt-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50 rounded-lg">
                    <h5 class="text-[9px] uppercase font-bold text-red-500 mb-1 flex items-center gap-1"><span class="material-symbols-outlined text-[12px]">warning</span> Decomposition Warning</h5>
                    <p class="text-[10px] text-red-700 dark:text-red-400">${story.decomposition_warning}</p>
                </div>
                ` : ''}
            </div>
        `;
    });
    html += `</div>`;

    // Add Copy Raw JSON button
    const rawJsonStr = JSON.stringify(artifact, null, 2);
    const escapedJson = rawJsonStr.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');

    html += `
        <div class="mt-6 flex justify-end border-t border-slate-200 dark:border-slate-700 pt-4">
            <button onclick="navigator.clipboard.writeText(decodeURIComponent('${encodeURIComponent(rawJsonStr)}')).then(() => { const b=this; const o=b.innerHTML; b.innerHTML='<span class=\\'material-symbols-outlined text-sm\\'>check</span> Copied!'; setTimeout(()=>b.innerHTML=o, 2000); })" 
                    class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 text-[11px] font-bold transition-colors">
                <span class="material-symbols-outlined text-[14px]">content_copy</span>
                Copy Raw JSON
            </button>
        </div>
    `;

    return html;
}

function updateStorySaveButton() {
    const button = document.getElementById('btn-save-story');
    const deleteBtn = document.getElementById('btn-delete-story');
    const hint = document.getElementById('story-save-hint');
    if (!button || !hint) return;

    const canSave = Boolean(selectedProjectId) && activeStoryReq && activeStoryIsComplete;
    button.disabled = !canSave;

    // Check if it's already saved to change text
    const reqObj = storyRequirements.find(r => r.requirement === activeStoryReq);
    const isSaved = reqObj?.status === 'Saved';

    // Toggle delete button
    if (deleteBtn) {
        if (activeStoryAttemptCount > 0 || isSaved) {
            deleteBtn.classList.remove('hidden');
        } else {
            deleteBtn.classList.add('hidden');
        }
    }

    button.className = canSave
        ? 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition-all shadow-sm'
        : 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-primary/40 text-white font-bold cursor-not-allowed transition-all';

    if (isSaved) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm">check</span> Saved';
        hint.innerText = 'Stories for this requirement are already saved. You can generate again to overwrite.';
    } else {
        button.innerHTML = '<span class="material-symbols-outlined text-sm">save</span> Save Stories';
        hint.innerText = canSave
            ? 'Output is complete. Proceed to save.'
            : 'Save disabled until latest output has is_complete=true.';
    }
}

function updateCompleteStoryPhaseButton() {
    const btn = document.getElementById('btn-complete-story-phase');
    if (!btn) return;

    // Allow completion if at least one requirement has stories saved
    const anySaved = storyRequirements.length > 0 && storyRequirements.some(r => r.status === 'Saved');

    btn.disabled = !anySaved;
    btn.className = anySaved
        ? 'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition-all shadow-md animate-pulse-once ring-2 ring-emerald-300'
        : 'inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-slate-200 text-slate-400 dark:bg-slate-800 dark:text-slate-600 font-bold cursor-not-allowed transition-all';
}

async function generateStoryDraft() {
    if (!selectedProjectId || !activeStoryReq) return;

    const input = document.getElementById('story-user-input');
    const userInput = input?.value?.trim() || '';

    if (activeStoryAttemptCount > 0 && !userInput) {
        alert('Please provide feedback to refine the generated stories.');
        return;
    }

    const button = document.getElementById('btn-generate-story');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">cycle</span> Running...';
        button.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/story/generate?parent_requirement=${encodeURIComponent(activeStoryReq)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_input: userInput }),
        });

        if (response.status >= 400) {
            const errorBody = await response.json();
            throw new Error(errorBody.detail || 'Generation failed');
        }

        const data = await response.json();
        if (data.status !== 'success') throw new Error('Generation failed');

        // reload data
        await loadStoryRequirements();
        await loadStoryHistory(activeStoryReq);

    } catch (error) {
        console.error(error);
        alert(error.message || 'Generation failed.');
    } finally {
        if (button) {
            button.innerHTML = original || '<span class="material-symbols-outlined text-sm">cycle</span> Generate / Refine';
            button.disabled = false;
        }
    }
}

async function saveStoryDraft() {
    if (!selectedProjectId || !activeStoryReq) return;

    const button = document.getElementById('btn-save-story');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">save</span> Saving...';
        button.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/story/save?parent_requirement=${encodeURIComponent(activeStoryReq)}`, {
            method: 'POST',
        });

        if (response.status >= 400) {
            const body = await response.json();
            throw new Error(body.detail || 'Failed to save stories.');
        }

        const data = await response.json();
        if (data.status !== 'success') throw new Error('Failed to save stories.');

        // Success effect
        if (button) {
            button.innerHTML = '<span class="material-symbols-outlined text-sm">check_circle</span> Saved!';
            button.className = 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-500 text-white font-bold transition-all shadow-md scale-105 ring-2 ring-emerald-200';
            setTimeout(() => { updateStorySaveButton(); }, 2000);
        }

        // Reload lists to update status dot
        await loadStoryRequirements();

    } catch (error) {
        console.error(error);
        alert(error.message || 'Failed to save stories.');
        if (button) {
            button.innerHTML = original;
            button.disabled = false;
        }
    }
}

async function deleteStoryDraft() {
    if (!selectedProjectId || !activeStoryReq) return;

    if (!confirm(`Are you sure you want to delete all stories and history for "${activeStoryReq}"? This cannot be undone.`)) {
        return;
    }

    const button = document.getElementById('btn-delete-story');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">delete</span> Deleting...';
        button.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/story?parent_requirement=${encodeURIComponent(activeStoryReq)}`, {
            method: 'DELETE',
        });

        if (response.status >= 400) {
            const body = await response.json();
            throw new Error(body.detail || 'Failed to delete stories.');
        }

        const data = await response.json();
        if (data.status !== 'success') throw new Error('Failed to delete stories.');

        // Success - clear active UI state
        const input = document.getElementById('story-user-input');
        if (input) input.value = '';

        // Reload data from backend
        await loadStoryRequirements();

        // This will reset attempt count and re-render the empty panels
        await loadStoryHistory(activeStoryReq);

    } catch (error) {
        console.error(error);
        alert(error.message || 'Failed to delete stories.');
    } finally {
        if (button) {
            button.innerHTML = original;
            button.disabled = false;
        }
    }
}

async function completeStoryPhase() {
    if (!selectedProjectId) return;

    const btn = document.getElementById('btn-complete-story-phase');
    const original = btn?.innerHTML;
    if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">flag</span> Processing...';
        btn.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/story/complete_phase`, { method: 'POST' });
        if (response.status >= 400) {
            const body = await response.json();
            throw new Error(body.detail || 'Failed to complete phase.');
        }

        if (btn) {
            btn.innerHTML = original || '<span class="material-symbols-outlined text-sm">flag</span> Complete Refining Phase';
            btn.disabled = false;
        }

        await fetchProjectFSMState(selectedProjectId);
        await loadSprintCandidates();

    } catch (e) {
        alert(e.message || "Failed to complete phase.");
    } finally {
        if (btn) {
            btn.innerHTML = original || '<span class="material-symbols-outlined text-sm">flag</span> Complete Refining Phase';
            btn.disabled = false;
        }
        updateCompleteStoryPhaseButton();
    }
}

// ==========================================
// SPRINT PHASE LOGIC
// ==========================================

function attachSprintInputListeners() {
    const velocityInput = document.getElementById('sprint-velocity');
    const maxPointsInput = document.getElementById('sprint-max-story-points');
    const teamNameInput = document.getElementById('sprint-team-name');
    const startDateInput = document.getElementById('sprint-start-date');

    velocityInput?.addEventListener('change', updateSprintCapacityWarning);
    maxPointsInput?.addEventListener('input', updateSprintCapacityWarning);
    teamNameInput?.addEventListener('input', updateSprintSaveButton);
    startDateInput?.addEventListener('change', updateSprintSaveButton);

    initializeSprintSaveForm();
}

function getTodayLocalDateValue() {
    const now = new Date();
    const timezoneOffsetMs = now.getTimezoneOffset() * 60 * 1000;
    return new Date(now.getTime() - timezoneOffsetMs).toISOString().slice(0, 10);
}

function initializeSprintSaveForm() {
    const startDateInput = document.getElementById('sprint-start-date');
    if (startDateInput && !startDateInput.value) {
        startDateInput.value = getTodayLocalDateValue();
    }
}

function clearSprintSelection() {
    selectedSprintStoryIds = new Set();
    renderSprintCandidates();
    updateSprintCapacityWarning();
}

function getSelectedSprintCandidates() {
    return sprintCandidates.filter(candidate => selectedSprintStoryIds.has(candidate.story_id));
}

function updateSprintSelectionSummary() {
    const summary = document.getElementById('sprint-selection-summary');
    if (!summary) return;

    if (sprintCandidates.length === 0) {
        summary.innerText = 'No sprint-eligible stories are available yet.';
        return;
    }

    const selected = getSelectedSprintCandidates();
    if (selected.length === 0) {
        summary.innerText = `${sprintCandidates.length} eligible stories available. Leave all unchecked to let the planner choose from the full candidate pool.`;
        return;
    }

    const estimatedPoints = selected
        .map(item => Number.isFinite(item.story_points) ? item.story_points : null)
        .filter(value => value !== null);
    const pointsText = estimatedPoints.length === selected.length
        ? `${estimatedPoints.reduce((sum, value) => sum + value, 0)} estimated points`
        : 'partial point estimates';

    summary.innerText = `${selected.length} stories manually selected (${pointsText}).`;
}

function renderSprintCandidates() {
    const container = document.getElementById('sprint-candidate-list');
    if (!container) return;

    container.innerHTML = '';
    if (!sprintCandidates || sprintCandidates.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500">No refined TO_DO stories are available for sprint planning yet.</p>';
        updateSprintSelectionSummary();
        updateSprintCapacityWarning();
        return;
    }

    sprintCandidates.forEach((story) => {
        const checked = selectedSprintStoryIds.has(story.story_id);
        const points = Number.isFinite(story.story_points) ? `${story.story_points} pts` : 'Unestimated';
        const persona = story.persona ? `Persona: ${story.persona}` : 'Persona not set';
        const origin = story.story_origin ? `Origin: ${story.story_origin}` : 'Origin unknown';

        const row = document.createElement('label');
        row.className = 'flex cursor-pointer items-start gap-3 rounded-lg border border-slate-200 bg-white p-3 transition-colors hover:border-teal-300 dark:border-slate-700 dark:bg-slate-800/60 dark:hover:border-teal-700';
        row.innerHTML = `
            <input type="checkbox" class="mt-0.5 rounded border-slate-300 text-teal-600 focus:ring-teal-500" ${checked ? 'checked' : ''}>
            <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-3">
                    <p class="text-sm font-bold text-slate-800 dark:text-slate-200">${story.story_title}</p>
                    <span class="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-black uppercase text-slate-600 dark:bg-slate-700 dark:text-slate-300">#${story.priority}</span>
                </div>
                <div class="mt-1 flex flex-wrap gap-2 text-[10px] text-slate-500">
                    <span>${points}</span>
                    <span>${persona}</span>
                    <span>${origin}</span>
                </div>
            </div>
        `;

        const checkbox = row.querySelector('input[type="checkbox"]');
        checkbox?.addEventListener('change', (event) => {
            if (event.target.checked) {
                selectedSprintStoryIds.add(story.story_id);
            } else {
                selectedSprintStoryIds.delete(story.story_id);
            }
            updateSprintSelectionSummary();
            updateSprintCapacityWarning();
        });

        container.appendChild(row);
    });

    updateSprintSelectionSummary();
    updateSprintCapacityWarning();
}

function updateSprintCapacityWarning() {
    const warning = document.getElementById('sprint-capacity-warning');
    if (!warning) return;

    const selected = getSelectedSprintCandidates();
    if (selected.length === 0) {
        warning.classList.add('hidden');
        warning.innerHTML = '';
        return;
    }

    const velocity = document.getElementById('sprint-velocity')?.value || 'Medium';
    const maxStoryPointsText = document.getElementById('sprint-max-story-points')?.value?.trim() || '';
    const maxStoryPoints = maxStoryPointsText ? parseInt(maxStoryPointsText, 10) : null;
    const messages = [];

    const storyLimit = SPRINT_VELOCITY_LIMITS[velocity] || SPRINT_VELOCITY_LIMITS.Medium;
    if (selected.length > storyLimit) {
        messages.push(`Capacity Overload: ${selected.length} manually selected stories exceed the ${velocity} heuristic limit of ${storyLimit}.`);
    }

    const allSelectedHavePoints = selected.every(item => Number.isFinite(item.story_points));
    if (maxStoryPoints && allSelectedHavePoints) {
        const totalPoints = selected.reduce((sum, item) => sum + item.story_points, 0);
        if (totalPoints > maxStoryPoints) {
            messages.push(`Capacity Overload: ${totalPoints} selected story points exceed the optional cap of ${maxStoryPoints}.`);
        }
    }

    if (messages.length === 0) {
        warning.classList.add('hidden');
        warning.innerHTML = '';
        return;
    }

    warning.classList.remove('hidden');
    warning.innerHTML = messages.join(' ');
}

async function loadSprintCandidates() {
    if (!selectedProjectId) return;
    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/sprint/candidates`);
        const data = await response.json();
        if (data.status !== 'success') throw new Error('Failed to load sprint candidates');

        const items = Array.isArray(data.data?.items) ? data.data.items : [];
        const validIds = new Set(items.map(item => item.story_id));
        selectedSprintStoryIds = new Set(
            Array.from(selectedSprintStoryIds).filter(storyId => validIds.has(storyId))
        );
        sprintCandidates = items;
        renderSprintCandidates();
    } catch (e) {
        console.error('Failed to load sprint candidates:', e);
        sprintCandidates = [];
        selectedSprintStoryIds = new Set();
        renderSprintCandidates();
    }
}

async function loadSprintHistory() {
    if (!selectedProjectId) return;
    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/sprint/history`);
        const data = await response.json();
        if (data.status !== 'success') throw new Error('Failed to load history');

        const items = Array.isArray(data.data?.items) ? data.data.items : [];
        sprintAttemptCount = items.length;
        renderSprintHistory(items);

        if (items.length > 0) {
            const latest = items[items.length - 1];
            latestSprintIsComplete = Boolean(latest.is_complete);
            renderSprintAttemptPanels(latest.input_context || null, latest.output_artifact || null);
        } else {
            latestSprintIsComplete = false;
            renderSprintAttemptPanels(null, null);
        }

        updateSprintSaveButton();
    } catch (e) {
        console.error('Failed to load sprint history:', e);
    }
}

async function generateSprintDraft() {
    if (!selectedProjectId) return;

    const userInput = document.getElementById('sprint-user-input')?.value?.trim() || '';
    const velocityInput = document.getElementById('sprint-velocity')?.value || 'Medium';
    const durationInput = document.getElementById('sprint-duration')?.value || 14;
    const maxPointsInput = document.getElementById('sprint-max-story-points')?.value?.trim() || '';
    const decomposeInput = document.getElementById('sprint-decompose')?.checked ?? true;
    const selectedStoryIds = Array.from(selectedSprintStoryIds);

    const button = document.getElementById('btn-generate-sprint');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">cycle</span> Running...';
        button.disabled = true;
    }

    try {
        const payload = {
            user_input: userInput,
            team_velocity_assumption: velocityInput,
            sprint_duration_days: parseInt(durationInput, 10),
            max_story_points: maxPointsInput ? parseInt(maxPointsInput, 10) : null,
            include_task_decomposition: decomposeInput
        };
        if (selectedStoryIds.length > 0) {
            payload.selected_story_ids = selectedStoryIds;
        }

        const response = await fetch(`/api/projects/${selectedProjectId}/sprint/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (response.status >= 400) {
            const errorBody = await response.json();
            throw new Error(errorBody.detail || 'Sprint generation failed');
        }

        const data = await response.json();
        if (data.status !== 'success') throw new Error('Sprint generation failed');

        latestSprintIsComplete = Boolean(data.data?.is_complete);
        renderSprintAttemptPanels(data.data?.input_context || null, data.data?.output_artifact || null);
        setPhaseState(data.data?.fsm_state || 'SPRINT_SETUP', 'sprint');

        await loadSprintHistory();
    } catch (error) {
        console.error(error);
        const message = error?.message || 'Sprint generation failed.';
        alert(message);
    } finally {
        if (button) {
            button.innerHTML = original || '<span class="material-symbols-outlined text-sm">cycle</span> Plan Sprint';
            button.disabled = false;
        }
        updateSprintSaveButton();
    }
}

async function saveSprintDraft() {
    if (!selectedProjectId) return;

    const teamNameInput = document.getElementById('sprint-team-name');
    const startDateInput = document.getElementById('sprint-start-date');
    const teamName = teamNameInput?.value?.trim() || '';
    const sprintStartDate = startDateInput?.value || '';

    if (!teamName) {
        alert('Team name is required before saving the sprint.');
        teamNameInput?.focus();
        updateSprintSaveButton();
        return;
    }

    if (!sprintStartDate) {
        alert('Sprint start date is required before saving the sprint.');
        startDateInput?.focus();
        updateSprintSaveButton();
        return;
    }

    const button = document.getElementById('btn-save-sprint');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">save</span> Saving...';
        button.disabled = true;
    }

    let success = false;
    try {
        const response = await fetch(`/api/projects/${selectedProjectId}/sprint/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                team_name: teamName,
                sprint_start_date: sprintStartDate,
            }),
        });

        if (response.status >= 400) {
            const body = await response.json().catch(() => null);
            const detail = Array.isArray(body?.detail)
                ? body.detail.map(item => item?.msg || 'Validation error').join('; ')
                : body?.detail;
            throw new Error(detail || 'Failed to save sprint.');
        }

        const data = await response.json();
        if (data.status !== 'success') throw new Error('Failed to save sprint.');

        setPhaseState('SPRINT_PERSISTENCE', 'sprint');
        latestSprintIsComplete = true;
        if (teamNameInput) teamNameInput.disabled = true;
        if (startDateInput) startDateInput.disabled = true;
        success = true;

        await fetchProjectFSMState(selectedProjectId);

        if (button) {
            button.innerHTML = '<span class="material-symbols-outlined text-sm">check_circle</span> Saved Successfully!';
            button.className = 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-500 text-white font-bold transition-all shadow-md scale-105 ring-2 ring-emerald-200';
            setTimeout(() => { updateSprintSaveButton(); }, 3000);
        }

    } catch (error) {
        console.error(error);
        alert(error.message || 'Failed to save sprint plan.');
    } finally {
        if (!success) {
            if (button) button.innerHTML = original;
            updateSprintSaveButton();
        }
    }
}

function renderSprintHistory(items) {
    const container = document.getElementById('sprint-history-list');
    if (!container) return;

    container.innerHTML = '';
    if (!items || items.length === 0) {
        container.innerHTML = '<p class="text-xs text-slate-500">No attempts yet.</p>';
        return;
    }

    const reversed = [...items].reverse();
    reversed.forEach((item, index) => {
        const stamp = item.created_at || '-';
        const state = item.is_complete ? 'Complete' : 'Needs input';
        const color = item.is_complete ? 'text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 ring-emerald-200' : 'text-amber-600 bg-amber-50 dark:bg-amber-900/30 ring-amber-200';

        const row = document.createElement('div');
        row.className = 'border border-slate-200 dark:border-slate-700 rounded-lg p-3 bg-slate-50 dark:bg-slate-800/60 transition-transform';
        row.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-xs font-extrabold text-slate-700 dark:text-slate-300">Attempt ${items.length - index}</span>
                <span class="text-[10px] uppercase ${color} px-2 py-0.5 rounded-full ring-1 ring-inset font-bold">${state}</span>
            </div>
            <p class="text-[10px] text-slate-400 mt-2">${stamp}</p>
        `;
        container.appendChild(row);
    });
}

function renderSprintAttemptPanels(inputContext, outputArtifact) {
    const inputCanvas = document.getElementById('sprint-input-context');
    const outputCanvas = document.getElementById('sprint-output-artifact');
    const copyBtn = document.getElementById('btn-copy-sprint-output');

    currentSprintInputContextJSON = inputContext || null;
    if (inputCanvas) {
        inputCanvas.innerText = inputContext ? JSON.stringify(inputContext, null, 2) : 'No input context available.';
    }

    if (outputCanvas) {
        if (!outputArtifact) {
            outputCanvas.innerHTML = `
                <div class="text-xs text-slate-500 flex flex-col items-center justify-center h-full gap-3 opacity-60">
                    <span class="material-symbols-outlined text-4xl">bolt</span>
                    <p>No sprint run yet.</p>
                </div>
            `;
        } else {
            outputCanvas.innerHTML = renderSprintArtifactHtml(outputArtifact, currentSprintInputContextJSON);
        }
    }
    
    currentSprintArtifactJSON = outputArtifact || null;
    if (copyBtn) {
        if (currentSprintArtifactJSON) {
            copyBtn.classList.remove('hidden');
        } else {
            copyBtn.classList.add('hidden');
        }
    }
}

function renderSprintArtifactHtml(artifact, inputContext) {
    let html = '';
    const availableStories = Array.isArray(inputContext?.available_stories) ? inputContext.available_stories : [];
    const storyMetaById = new Map(availableStories.map(story => [story.story_id, story]));

    if (artifact.error) {
        const rawOutput = artifact.raw_output || artifact.raw_output_preview || '';
        html += `
            <div class="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 p-4 rounded-lg mb-4">
                <div class="flex items-center gap-2 text-red-700 dark:text-red-400 font-bold mb-2">
                    <span class="material-symbols-outlined">error</span> Generation Failed
                </div>
                <p class="text-[11px] font-mono text-red-600 dark:text-red-300 whitespace-pre-wrap">${artifact.message || 'Unknown error'}</p>
        `;
        if (rawOutput) {
            const safeRaw = rawOutput.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            html += `
                <div class="mt-4 border-t border-red-200 dark:border-red-800/50 pt-3">
                    <p class="text-[10px] font-bold text-red-700 dark:text-red-400 mb-1 uppercase tracking-wide">Raw Agent Output Preview:</p>
                    <pre class="text-[10px] font-mono text-red-600 dark:text-red-300 bg-white/50 dark:bg-black/20 p-2 rounded overflow-x-auto whitespace-pre-wrap">${safeRaw}</pre>
                </div>
            `;
        }
        html += `</div>`;
    } else if (!artifact.is_complete && artifact.clarifying_questions?.length > 0) {
        html += `
            <div class="bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-700 p-4 rounded-lg mb-4">
                <div class="flex items-center gap-2 text-amber-700 dark:text-amber-400 font-bold mb-2">
                    <span class="material-symbols-outlined">help</span> Agent Needs Clarification
                </div>
                <ul class="text-[11px] text-amber-800 dark:text-amber-300 list-disc list-inside space-y-1">
                    ${artifact.clarifying_questions.map(q => `<li>${q}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    if (!artifact.error && artifact.sprint_goal) {
        const capacity = artifact.capacity_analysis || {};
        html += `
            <div class="mb-5 bg-gradient-to-r from-teal-50 to-emerald-50 dark:from-teal-900/20 dark:to-emerald-900/20 border border-emerald-200 dark:border-emerald-800 p-4 rounded-xl">
                <h4 class="text-xs font-black text-emerald-800 dark:text-emerald-400 uppercase tracking-widest mb-2 flex items-center gap-1.5"><span class="material-symbols-outlined text-[16px]">flag_circle</span> Sprint Goal</h4>
                <p class="text-sm font-medium text-slate-800 dark:text-slate-200">${artifact.sprint_goal}</p>
                
                <div class="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] text-slate-600 dark:text-slate-400">
                    <div><span class="font-bold text-slate-700 dark:text-slate-300">Sprint #:</span> ${artifact.sprint_number || '?'}</div>
                    <div><span class="font-bold text-slate-700 dark:text-slate-300">Duration:</span> ${artifact.duration_days || '?'} days</div>
                    <div><span class="font-bold text-slate-700 dark:text-slate-300">Velocity:</span> ${capacity.velocity_assumption || '-'}</div>
                    <div><span class="font-bold text-slate-700 dark:text-slate-300">Capacity Band:</span> ${capacity.capacity_band || '-'}</div>
                    <div><span class="font-bold text-slate-700 dark:text-slate-300">Selected Stories:</span> ${capacity.selected_count ?? artifact.selected_stories?.length ?? 0}</div>
                    <div><span class="font-bold text-slate-700 dark:text-slate-300">Story Points Used:</span> ${capacity.story_points_used ?? 'N/A'}</div>
                </div>
                ${capacity.commitment_note ? `<p class="mt-3 text-[11px] font-medium text-emerald-800 dark:text-emerald-300">${capacity.commitment_note}</p>` : ''}
                ${capacity.reasoning ? `<p class="mt-2 text-[11px] text-slate-600 dark:text-slate-400">${capacity.reasoning}</p>` : ''}
            </div>
        `;
    }

    const stories = Array.isArray(artifact.selected_stories) ? artifact.selected_stories : [];
    if (stories.length === 0 && !artifact.error) {
        html += `<p class="text-xs text-slate-500 italic">No stories selected for sprint.</p>`;
    } else {
        html += `<div class="space-y-4">`;
        stories.forEach((story, idx) => {
            const storyMeta = storyMetaById.get(story.story_id) || {};
            const pointsLabel = Number.isFinite(storyMeta.story_points) ? `${storyMeta.story_points} Points` : 'Points N/A';
            html += `
                <div class="border border-slate-200 dark:border-slate-700 rounded-lg p-4 bg-white dark:bg-slate-800/60 shadow-sm relative pt-4">
                    <div class="absolute top-0 right-0 bg-slate-100 dark:bg-slate-700 text-slate-500 text-[9px] font-black px-2 py-1 rounded-bl-lg rounded-tr-lg">STORY ${idx + 1}</div>
                    
                    <div class="flex gap-2 items-start justify-between mb-2 border-b border-slate-100 dark:border-slate-700 pb-2">
                        <h4 class="font-bold text-sm text-slate-800 dark:text-slate-200 pr-12">${story.story_title}</h4>
                        <span class="shrink-0 px-2 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-400 text-[10px] font-black uppercase">${pointsLabel}</span>
                    </div>
                    
                    <p class="text-[11px] text-slate-600 dark:text-slate-400 italic mb-3">${story.reason_for_selection || 'Selected for sprint scope.'}</p>
                    
                    <div>
                        <h5 class="text-[10px] uppercase font-bold text-slate-500 mb-1.5">Tasks (${(story.tasks || []).length})</h5>
                        ${story.tasks && story.tasks.length > 0 ? `
                        <ul class="text-[11px] text-slate-700 dark:text-slate-300 space-y-1.5 list-disc pl-4">
                            ${story.tasks.map(task => `<li>${task}</li>`).join('')}
                        </ul>
                        ` : '<p class="text-[11px] text-slate-400">No tasks defined.</p>'}
                    </div>
                </div>
            `;
        });
        html += `</div>`;
    }

    const deselectedStories = Array.isArray(artifact.deselected_stories) ? artifact.deselected_stories : [];
    if (deselectedStories.length > 0) {
        html += `
            <div class="mt-6 pt-4 border-t border-slate-200 dark:border-slate-700">
                <h4 class="text-xs font-black text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-1.5"><span class="material-symbols-outlined text-[14px]">inventory_2</span> Deselected Stories</h4>
                <div class="space-y-2">
        `;
        deselectedStories.forEach((story) => {
            const storyMeta = storyMetaById.get(story.story_id) || {};
            const title = storyMeta.story_title || `Story ${story.story_id}`;
            html += `
                <div class="text-[11px] bg-slate-100 dark:bg-slate-800/80 p-2 rounded border border-slate-200 dark:border-slate-700">
                    <span class="font-bold text-slate-700 dark:text-slate-300">${title}</span>
                    <p class="text-slate-500 mt-0.5">${story.reason}</p>
                </div>
            `;
        });
        html += `</div></div>`;
    }

    return html;
}

function updateSprintSaveButton() {
    const button = document.getElementById('btn-save-sprint');
    const hint = document.getElementById('sprint-save-hint');
    const teamNameInput = document.getElementById('sprint-team-name');
    const startDateInput = document.getElementById('sprint-start-date');
    if (!button || !hint || !teamNameInput || !startDateInput) return;

    const savePhaseReady = Boolean(selectedProjectId) && latestSprintIsComplete && activeFsmState === 'SPRINT_DRAFT';
    const hasRequiredFields = Boolean(teamNameInput.value.trim()) && Boolean(startDateInput.value);
    const canSave = savePhaseReady && hasRequiredFields;
    button.disabled = !canSave;
    teamNameInput.disabled = !savePhaseReady;
    startDateInput.disabled = !savePhaseReady;

    button.className = canSave
        ? 'inline-flex items-center gap-2 px-6 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold transition-all shadow-sm'
        : 'inline-flex items-center gap-2 px-6 py-2.5 rounded-lg bg-primary/40 text-white font-bold cursor-not-allowed transition-all shadow-sm';

    if (activeFsmState === 'SPRINT_PERSISTENCE') {
        hint.innerText = 'Sprint already saved for this draft.';
        return;
    }

    if (!latestSprintIsComplete) {
        hint.innerText = 'Save is disabled until the latest Sprint output is complete.';
        return;
    }

    if (!teamNameInput.value.trim()) {
        hint.innerText = 'Provide a team name to confirm this sprint.';
        return;
    }

    if (!startDateInput.value) {
        hint.innerText = 'Choose a sprint start date to confirm this sprint.';
        return;
    }

    hint.innerText = 'Sprint plan is complete. Proceed to save.';
}

async function deleteCurrentProject() {
    if (!selectedProjectId) return;

    if (!confirm('Are you sure you want to delete this project? This will permanently delete the specification, stories, and all AI generated data.')) {
        return;
    }

    const btn = document.getElementById('header-btn-delete-project');
    const original = btn?.innerHTML;
    if (btn) {
        btn.innerHTML = '<span class="material-symbols-outlined text-sm animate-spin">refresh</span>';
        btn.disabled = true;
    }

    try {
        const response = await fetch(`/api/projects/${selectedProjectId}`, {
            method: 'DELETE',
        });
        const data = await response.json();
        if (data.status === 'success') {
            window.location.href = '/dashboard';
        } else {
            alert(data.detail || 'Failed to delete project.');
        }
    } catch (error) {
        console.error('Error deleting project:', error);
        alert('Network error while deleting project.');
    } finally {
        if (btn) {
            btn.innerHTML = original;
            btn.disabled = false;
        }
    }
}


function formatSafeDate(dateString) {
    if (!dateString) return '-';
    try {
        const d = new Date(dateString);
        return isNaN(d) ? dateString : d.toLocaleDateString();
    } catch {
        return dateString;
    }
}

async function copyArtifactToClipboard(phase) {
    let payload = null;
    let btnId = null;

    if (phase === 'vision') {
        payload = currentVisionArtifactJSON;
        btnId = 'btn-copy-vision-output';
    } else if (phase === 'backlog') {
        payload = currentBacklogArtifactJSON;
        btnId = 'btn-copy-backlog-output';
    } else if (phase === 'roadmap') {
        payload = currentRoadmapArtifactJSON;
        btnId = 'btn-copy-roadmap-output';
    } else if (phase === 'story') {
        payload = currentStoryArtifactJSON;
        btnId = 'btn-copy-story-output';
    } else if (phase === 'sprint') {
        payload = currentSprintArtifactJSON;
        btnId = 'btn-copy-sprint-output';
    }

    if (!payload) {
        console.warn(`No artifact payload available for phase: ${phase}`);
        return;
    }

    try {
        const jsonString = JSON.stringify(payload, null, 2);
        await navigator.clipboard.writeText(jsonString);

        const btn = document.getElementById(btnId);
        if (btn) {
            const originalHtml = btn.innerHTML;
            btn.innerHTML = `<span class="material-symbols-outlined text-[12px]">check</span> Copied!`;
            btn.classList.add('bg-emerald-100', 'text-emerald-700', 'border-emerald-200');
            btn.classList.remove('bg-white', 'text-slate-600', 'border-slate-200', 'dark:bg-slate-900', 'dark:text-slate-400');

            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.classList.remove('bg-emerald-100', 'text-emerald-700', 'border-emerald-200');
                btn.classList.add('bg-white', 'text-slate-600', 'border-slate-200', 'dark:bg-slate-900', 'dark:text-slate-400');
            }, 2000);
        }
    } catch (err) {
        console.error('Failed to copy to clipboard', err);
        alert('Failed to copy to clipboard. Ensure you are using HTTPS or localhost.');
    }
}

// Assign globally for inline onclick handlers attached in project.html
window.retryProjectSetup = retryProjectSetup;
window.handleNextPhase = handleNextPhase;
window.generateVisionDraft = generateVisionDraft;
window.saveVisionDraft = saveVisionDraft;
window.generateBacklogDraft = generateBacklogDraft;
window.copyArtifactToClipboard = copyArtifactToClipboard;
window.saveBacklogDraft = saveBacklogDraft;
window.generateRoadmapDraft = generateRoadmapDraft;
window.saveRoadmapDraft = saveRoadmapDraft;
window.selectStoryRequirement = selectStoryRequirement;
window.generateStoryDraft = generateStoryDraft;
window.saveStoryDraft = saveStoryDraft;
window.deleteStoryDraft = deleteStoryDraft;
window.completeStoryPhase = completeStoryPhase;
window.generateSprintDraft = generateSprintDraft;
window.saveSprintDraft = saveSprintDraft;
window.deleteCurrentProject = deleteCurrentProject;
