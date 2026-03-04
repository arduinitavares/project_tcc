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
const projectsById = new Map();

let panelMode = 'hidden';
let selectedProjectId = null;
let activeFsmState = 'SETUP_REQUIRED';
let activePhaseId = 'setup';
let viewPhaseId = 'setup';
let currentProjectState = { setup_status: 'failed', setup_error: null };

let latestVisionIsComplete = false;
let visionAttemptCount = 0;

window.addEventListener('DOMContentLoaded', async () => {
    await initializeDashboard();
});

async function initializeDashboard() {
    await fetchDashboardConfig();
    await fetchProjects();
    setPanelMode('hidden');
    setPhaseState('SETUP_REQUIRED', 'setup');
}

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

function getBadgeMeta(stateKey) {
    const stepId = getPhaseIdForState(stateKey);
    if (stepId === 'setup') {
        return { icon: 'settings', color: 'bg-amber-100 text-amber-700' };
    }
    if (stepId === 'vision') {
        return { icon: 'visibility', color: 'bg-sky-100 text-sky-700' };
    }
    if (stepId === 'backlog') {
        return { icon: 'format_list_bulleted', color: 'bg-indigo-100 text-indigo-700' };
    }
    if (stepId === 'roadmap') {
        return { icon: 'timeline', color: 'bg-violet-100 text-violet-700' };
    }
    if (stepId === 'story') {
        return { icon: 'description', color: 'bg-amber-100 text-amber-700' };
    }
    return { icon: 'bolt', color: 'bg-emerald-100 text-emerald-700' };
}

function setPanelMode(mode) {
    panelMode = mode;

    const panel = document.getElementById('setup-panel');
    const createActions = document.getElementById('setup-create-actions');
    const selectedActions = document.getElementById('setup-selected-actions');
    const hint = document.getElementById('setup-mode-hint');
    const nameInput = document.getElementById('setup-project-name');
    const specInput = document.getElementById('setup-spec-path');

    if (!panel || !createActions || !selectedActions || !hint || !nameInput || !specInput) {
        return;
    }

    if (mode === 'hidden') {
        panel.classList.add('hidden');
        return;
    }

    panel.classList.remove('hidden');

    if (mode === 'creating') {
        createActions.classList.remove('hidden');
        selectedActions.classList.add('hidden');
        nameInput.readOnly = false;
        specInput.readOnly = false;
        hint.innerText = 'Provide project name and specification file path to complete setup.';
    } else {
        createActions.classList.add('hidden');
        selectedActions.classList.remove('hidden');
        nameInput.readOnly = true;
        specInput.readOnly = currentProjectState.setup_status !== 'failed';
        hint.innerText = currentProjectState.setup_status === 'failed'
            ? 'Setup failed. Correct file path and retry setup.'
            : 'Setup passed. Vision interview can continue.';
    }

    updateRetryButton();
    updateSetupStatusBanner();
    renderPhaseSection();
    updateNextButton();
}

function updateRetryButton() {
    const retryBtn = document.getElementById('btn-retry-setup');
    if (!retryBtn) return;

    if (panelMode === 'selected_project' && currentProjectState.setup_status === 'failed') {
        retryBtn.classList.remove('hidden');
    } else {
        retryBtn.classList.add('hidden');
    }
}

function updateSetupStatusBanner() {
    const banner = document.getElementById('setup-status-banner');
    if (!banner) return;

    if (panelMode === 'hidden') {
        banner.classList.add('hidden');
        return;
    }

    banner.classList.remove('hidden');
    if (currentProjectState.setup_status === 'passed') {
        banner.className = 'text-sm rounded-lg border px-4 py-3 border-emerald-200 bg-emerald-50 text-emerald-700';
        banner.innerText = 'Setup passed. Specification linked and authority compiled.';
        return;
    }

    banner.className = 'text-sm rounded-lg border px-4 py-3 border-amber-200 bg-amber-50 text-amber-700';
    banner.innerText = currentProjectState.setup_error || 'Setup is required before Vision.';
}

function resetSetupPanel() {
    const title = document.getElementById('setup-panel-title');
    const nameInput = document.getElementById('setup-project-name');
    const specInput = document.getElementById('setup-spec-path');
    const feedback = document.getElementById('vision-user-input');

    if (title) title.innerText = 'Project Setup';
    if (nameInput) nameInput.value = '';
    if (specInput) specInput.value = '';
    if (feedback) feedback.value = '';

    latestVisionIsComplete = false;
    visionAttemptCount = 0;
    renderVisionAttemptPanels(null, null);
    renderVisionHistory([]);
    updateVisionSaveButton();
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
    if (panelMode === 'hidden') {
        return {
            label: 'Next',
            enabled: false,
            hint: 'Select or create a project to continue.',
        };
    }

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
    button.innerText = model.label;
    button.disabled = !model.enabled;
    hint.innerText = model.hint;

    button.className = model.enabled
        ? 'px-5 py-2.5 rounded-lg bg-primary hover:bg-primary/90 text-white font-bold transition-colors'
        : 'px-5 py-2.5 rounded-lg bg-primary/40 text-white font-bold cursor-not-allowed transition-colors';
}

function handleNextPhase() {
    const model = getNextButtonModel();
    if (!model.enabled) return;

    const target = NEXT_PHASE[viewPhaseId];
    if (!target) return;

    viewPhaseId = target;
    renderPhaseSection();
    updateNextButton();
}

async function fetchProjects() {
    try {
        const response = await fetch('/api/projects');
        const data = await response.json();
        if (data.status === 'success') {
            renderProjects(Array.isArray(data.data) ? data.data : []);
        }
    } catch (error) {
        console.error('Error fetching projects:', error);
    }
}

function renderProjects(projects) {
    const container = document.getElementById('projects-grid');
    if (!container) return;

    projectsById.clear();
    container.innerHTML = '';

    if (projects.length === 0) {
        container.innerHTML = `
            <div class="col-span-1 md:col-span-2 text-center p-8 bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl">
                <span class="material-symbols-outlined text-4xl text-slate-400 mb-2">inbox</span>
                <h3 class="text-lg font-bold">No Projects Found</h3>
                <p class="text-slate-500 text-sm">Create a new project to start the workflow.</p>
            </div>
        `;
        return;
    }

    projects.forEach((project) => {
        const stateKey = normalizeStateKey(project.fsm_state);
        const badge = getBadgeMeta(stateKey);

        projectsById.set(project.id, { ...project, fsm_state: stateKey });

        container.innerHTML += `
            <div class="bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 p-5 rounded-xl hover:border-primary/50 transition-all cursor-pointer" onclick="selectProject(${project.id})">
                <div class="flex justify-between items-start mb-4">
                    <div class="bg-primary/10 p-2 rounded-lg text-primary">
                        <span class="material-symbols-outlined">${badge.icon}</span>
                    </div>
                    <span class="px-2.5 py-1 rounded-full text-xs font-semibold ${badge.color}">${stateKey.replace(/_/g, ' ')}</span>
                </div>
                <h3 class="text-lg font-bold">${project.name}</h3>
                <p class="text-sm text-slate-500 mt-2 line-clamp-2">${project.summary || 'No description provided'}</p>
                <div class="mt-6 flex items-center justify-between border-t border-slate-100 dark:border-slate-700 pt-4">
                    <span class="text-xs font-medium text-slate-400 uppercase tracking-wider">Project ID: ${project.id}</span>
                    <span class="text-primary text-sm font-semibold">Open Workflow</span>
                </div>
            </div>
        `;
    });
}

function openCreateProjectPanel() {
    selectedProjectId = null;
    currentProjectState = { setup_status: 'failed', setup_error: null };

    setPanelMode('creating');
    resetSetupPanel();
    setPhaseState('SETUP_REQUIRED', 'setup');

    const title = document.getElementById('setup-panel-title');
    if (title) title.innerText = 'Project Setup: New Project';

    const nameInput = document.getElementById('setup-project-name');
    if (nameInput) nameInput.focus();
}

function closeCreateProjectPanel() {
    if (panelMode !== 'creating') return;

    setPanelMode('hidden');
    resetSetupPanel();
    selectedProjectId = null;
    currentProjectState = { setup_status: 'failed', setup_error: null };
    setPhaseState('SETUP_REQUIRED', 'setup');
}

function hideSetupPanel() {
    setPanelMode('hidden');
}

async function submitCreateProjectInline() {
    const nameInput = document.getElementById('setup-project-name');
    const specInput = document.getElementById('setup-spec-path');

    const projectName = nameInput?.value?.trim() || '';
    const specFilePath = specInput?.value?.trim() || '';

    if (!projectName) {
        alert('Please enter a project name.');
        return;
    }

    if (!specFilePath) {
        alert('Please enter a specification file path.');
        return;
    }

    const btn = document.getElementById('btn-create-project-inline');
    const original = btn?.innerHTML;
    if (btn) {
        btn.innerHTML = 'Creating...';
        btn.disabled = true;
    }

    try {
        const response = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: projectName, spec_file_path: specFilePath }),
        });

        const data = await response.json();
        if (data.status === 'success' && data.data?.id) {
            await fetchProjects();
            await selectProject(data.data.id);
        } else {
            alert(data.detail || 'Failed to create project.');
        }
    } catch (error) {
        console.error(error);
        alert('Network error while creating project.');
    } finally {
        if (btn) {
            btn.innerHTML = original || 'Create Project';
            btn.disabled = false;
        }
    }
}

async function selectProject(projectId) {
    selectedProjectId = projectId;

    const project = projectsById.get(projectId);
    const title = document.getElementById('setup-panel-title');
    const nameInput = document.getElementById('setup-project-name');

    if (title) title.innerText = `Project Setup: ${project?.name || `Project ${projectId}`}`;
    if (nameInput) {
        nameInput.value = project?.name || `Project ${projectId}`;
        nameInput.readOnly = true;
    }

    setPanelMode('selected_project');
    await fetchProjectFSMState(projectId);
    await loadVisionHistory();
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

        const project = projectsById.get(projectId);
        if (project) {
            projectsById.set(projectId, {
                ...project,
                fsm_state: stateKey,
                setup_status: currentProjectState.setup_status,
                setup_error: currentProjectState.setup_error,
            });
        }

        const specInput = document.getElementById('setup-spec-path');
        if (specInput) {
            specInput.value = state.setup_spec_file_path || '';
            specInput.readOnly = currentProjectState.setup_status !== 'failed';
        }

        if (currentProjectState.setup_status === 'failed') {
            setPhaseState('SETUP_REQUIRED', 'setup');
        } else {
            setPhaseState(stateKey, getPhaseIdForState(stateKey));
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
        btn.innerHTML = 'Retrying...';
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
            await fetchProjects();
            await fetchProjectFSMState(selectedProjectId);
        } else {
            alert(data.detail || 'Setup retry failed.');
        }
    } catch (error) {
        console.error('Setup retry error:', error);
        alert('Network error while retrying setup.');
    } finally {
        if (btn) {
            btn.innerHTML = original || 'Retry Setup';
            btn.disabled = false;
        }
    }
}

function updateStepperUI(fsmState) {
    const stateKey = normalizeStateKey(fsmState);
    const steps = getWorkflowSteps();
    const activeStepId = getPhaseIdForState(stateKey);
    const activeIndex = Math.max(0, steps.findIndex((step) => step.id === activeStepId));

    steps.forEach((step, index) => {
        const stepEl = document.getElementById(`step-${step.id}`);
        if (!stepEl) return;

        const iconContainer = stepEl.querySelector('[data-role="icon"]');
        const labelSpan = stepEl.querySelector('[data-role="label"]');
        const statusSpan = stepEl.querySelector('[data-role="status"]');
        if (!iconContainer || !labelSpan || !statusSpan) return;

        if (index < activeIndex) {
            iconContainer.className = 'w-10 h-10 rounded-full bg-emerald-500 text-white flex items-center justify-center ring-4 ring-white dark:ring-background-dark shadow-md';
            iconContainer.innerHTML = '<span class="material-symbols-outlined text-xl">check</span>';
            labelSpan.className = 'text-xs font-bold text-emerald-600 dark:text-emerald-400';
            statusSpan.className = 'text-[10px] text-emerald-500 uppercase font-black';
            statusSpan.innerText = 'Completed';
            return;
        }

        if (index === activeIndex) {
            const icon = STEP_ICONS[step.id] || 'play_circle';
            iconContainer.className = 'w-10 h-10 rounded-full bg-primary text-white flex items-center justify-center ring-4 ring-white dark:ring-background-dark shadow-md';
            iconContainer.innerHTML = `<span class="material-symbols-outlined text-xl">${icon}</span>`;
            labelSpan.className = 'text-xs font-bold text-primary';
            statusSpan.className = 'text-[10px] text-primary/80 uppercase font-black';
            statusSpan.innerText = 'Active';
            return;
        }

        iconContainer.className = 'w-10 h-10 rounded-full bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400 flex items-center justify-center ring-4 ring-white dark:ring-background-dark';
        iconContainer.innerHTML = '<span class="material-symbols-outlined text-xl">lock</span>';
        labelSpan.className = 'text-xs font-medium text-slate-500';
        statusSpan.className = 'text-[10px] text-slate-400 uppercase font-black';
        statusSpan.innerText = 'Locked';
    });
}

function renderVisionAttemptPanels(inputContext, outputArtifact) {
    const inputEl = document.getElementById('vision-input-context');
    const outputEl = document.getElementById('vision-output-artifact');

    if (inputEl) {
        inputEl.innerText = inputContext ? JSON.stringify(inputContext, null, 2) : 'No vision run yet.';
    }

    if (outputEl) {
        outputEl.innerText = outputArtifact ? JSON.stringify(outputArtifact, null, 2) : 'No vision run yet.';
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
        const color = item.is_complete ? 'text-emerald-600' : 'text-amber-600';
        const trigger = item.trigger === 'auto_setup_transition' ? 'Auto setup' : 'Manual refine';

        const row = document.createElement('div');
        row.className = 'border border-slate-200 dark:border-slate-700 rounded-lg p-2 bg-slate-50 dark:bg-slate-800/60';
        row.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-xs font-semibold">Attempt ${items.length - index}</span>
                <span class="text-[11px] ${color} font-semibold">${state}</span>
            </div>
            <p class="text-[11px] text-slate-500 mt-1">Trigger: ${trigger}</p>
            <p class="text-[11px] text-slate-500 mt-1">${stamp}</p>
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
        ? 'px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-white font-semibold'
        : 'px-3 py-1.5 rounded-lg bg-primary/40 text-white font-semibold cursor-not-allowed';

    hint.innerText = canSave
        ? 'Vision is complete. Save is available.'
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
    if (visionAttemptCount > 0 && !userInput) {
        alert('Please provide feedback to refine Vision.');
        return;
    }

    const button = document.getElementById('btn-generate-vision');
    const original = button?.innerHTML;
    if (button) {
        button.innerHTML = 'Running...';
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
        await fetchProjects();
    } catch (error) {
        console.error(error);
        alert(error.message || 'Vision generation failed.');
    } finally {
        if (button) {
            button.innerHTML = original || 'Generate / Refine';
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
        button.innerHTML = 'Saving...';
        button.disabled = true;
    }

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
        updateVisionSaveButton();

        await fetchProjects();
        await fetchProjectFSMState(selectedProjectId);
    } catch (error) {
        console.error(error);
        alert(error.message || 'Failed to save vision.');
    } finally {
        if (button) {
            button.innerHTML = original || 'Save Vision';
        }
        updateVisionSaveButton();
    }
}

window.openCreateProjectPanel = openCreateProjectPanel;
window.closeCreateProjectPanel = closeCreateProjectPanel;
window.hideSetupPanel = hideSetupPanel;
window.submitCreateProjectInline = submitCreateProjectInline;
window.selectProject = selectProject;
window.retryProjectSetup = retryProjectSetup;
window.handleNextPhase = handleNextPhase;
window.generateVisionDraft = generateVisionDraft;
window.saveVisionDraft = saveVisionDraft;
