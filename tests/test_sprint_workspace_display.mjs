import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const projectJsPath = path.resolve(import.meta.dirname, '../frontend/project.js');
const projectJsSource = fs.readFileSync(projectJsPath, 'utf8');

function loadSprintFunction(name, patterns) {
    const source = patterns.map((pattern) => {
        const match = projectJsSource.match(pattern);
        assert.ok(match, `${name} dependency should exist in frontend/project.js`);
        return match[0];
    }).join('\n');
    return new Function(`${source}; return ${name};`)();
}

test('getSprintMode uses canonical status instead of started_at inference', () => {
    const getSprintMode = loadSprintFunction(
        'getSprintMode',
        [/function getSprintMode\(savedSprint\) \{[\s\S]*?\n\}/],
    );

    assert.equal(
        getSprintMode({ status: 'Completed', started_at: '2026-03-01T09:00:00Z' }),
        'completed',
    );
    assert.equal(getSprintMode({ status: 'Active', started_at: null }), 'active');
    assert.equal(
        getSprintMode({ status: 'Planned', started_at: '2026-03-01T09:00:00Z' }),
        'planned',
    );
});

test('chooseLandingSprint prefers active, then planned, then latest completed', () => {
    const getSprintMode = loadSprintFunction(
        'getSprintMode',
        [/function getSprintMode\(savedSprint\) \{[\s\S]*?\n\}/],
    );
    globalThis.getSprintMode = getSprintMode;
    globalThis.savedSprints = [
        { id: 3, status: 'Completed', completed_at: '2026-03-12T12:00:00Z', created_at: '2026-03-10T12:00:00Z' },
        { id: 2, status: 'Planned', created_at: '2026-03-13T12:00:00Z' },
        { id: 1, status: 'Active', started_at: '2026-03-14T09:00:00Z', created_at: '2026-03-14T08:00:00Z' },
    ];

    const chooseLandingSprint = loadSprintFunction(
        'chooseLandingSprint',
        [
            /function getSprintMode\(savedSprint\) \{[\s\S]*?\n\}/,
            /function chooseLandingSprint\(\) \{[\s\S]*?\n\}/,
        ],
    );

    assert.equal(chooseLandingSprint().id, 1);

    globalThis.savedSprints = [
        { id: 3, status: 'Completed', completed_at: '2026-03-12T12:00:00Z', created_at: '2026-03-10T12:00:00Z' },
        { id: 2, status: 'Planned', created_at: '2026-03-13T12:00:00Z' },
    ];
    assert.equal(chooseLandingSprint().id, 2);

    globalThis.savedSprints = [
        { id: 3, status: 'Completed', completed_at: '2026-03-12T12:00:00Z', created_at: '2026-03-10T12:00:00Z' },
        { id: 4, status: 'Completed', completed_at: '2026-03-15T12:00:00Z', created_at: '2026-03-11T12:00:00Z' },
    ];
    assert.equal(chooseLandingSprint().id, 4);
});

test('openSprintPlanner resets planner working state for create-next mode', async () => {
    const openSprintPlanner = loadSprintFunction(
        'openSprintPlanner',
        [
            /function resetSprintPlannerWorkingSet\(\) \{[\s\S]*?\n\}/,
            /async function openSprintPlanner\(\) \{[\s\S]*?\n\}/,
        ],
    );

    const calls = {
        resetClose: 0,
        resetCycle: 0,
        renderPhase: 0,
        nextButton: 0,
        loadCandidates: 0,
        loadHistory: 0,
        historyRender: null,
        attemptPanels: null,
        saveButton: 0,
    };

    globalThis.resetSprintClosePanel = () => { calls.resetClose += 1; };
    globalThis.resetSprintPlannerStateForCreateNext = async () => { calls.resetCycle += 1; };
    globalThis.renderPhaseSection = () => { calls.renderPhase += 1; };
    globalThis.updateNextButton = () => { calls.nextButton += 1; };
    globalThis.loadSprintCandidates = async () => { calls.loadCandidates += 1; };
    globalThis.loadSprintHistory = async () => { calls.loadHistory += 1; };
    globalThis.renderSprintHistory = (items) => { calls.historyRender = items; };
    globalThis.renderSprintAttemptPanels = (inputContext, outputArtifact) => {
        calls.attemptPanels = [inputContext, outputArtifact];
    };
    globalThis.updateSprintSaveButton = () => { calls.saveButton += 1; };

    globalThis.sprintRuntimeSummary = { can_create_next_sprint: true };
    globalThis.selectedSprintStoryIds = new Set([12, 18]);
    globalThis.latestSprintIsComplete = true;
    globalThis.sprintAttemptCount = 4;
    globalThis.currentSprintArtifactJSON = { sprint_goal: 'Old sprint' };
    globalThis.currentSprintInputContextJSON = { available_stories: [{ story_id: 12 }] };
    globalThis.viewPhaseId = 'overview';
    globalThis.showSprintPlanner = false;

    await openSprintPlanner();

    assert.deepEqual(Array.from(globalThis.selectedSprintStoryIds), []);
    assert.equal(globalThis.latestSprintIsComplete, false);
    assert.equal(globalThis.sprintAttemptCount, 0);
    assert.equal(globalThis.currentSprintArtifactJSON, null);
    assert.equal(globalThis.currentSprintInputContextJSON, null);
    assert.equal(globalThis.viewPhaseId, 'sprint');
    assert.equal(globalThis.showSprintPlanner, true);
    assert.deepEqual(calls.historyRender, []);
    assert.deepEqual(calls.attemptPanels, [null, null]);
    assert.equal(calls.saveButton, 1);
    assert.equal(calls.resetClose, 1);
    assert.equal(calls.resetCycle, 1);
    assert.equal(calls.renderPhase, 1);
    assert.equal(calls.nextButton, 1);
    assert.equal(calls.loadCandidates, 1);
    assert.equal(calls.loadHistory, 1);
});

test('openSprintPlanner preserves planner working state for modify-planned mode', async () => {
    const openSprintPlanner = loadSprintFunction(
        'openSprintPlanner',
        [
            /function resetSprintPlannerWorkingSet\(\) \{[\s\S]*?\n\}/,
            /async function openSprintPlanner\(\) \{[\s\S]*?\n\}/,
        ],
    );

    const calls = {
        resetCycle: 0,
        historyRender: null,
        attemptPanels: null,
    };

    globalThis.resetSprintClosePanel = () => {};
    globalThis.resetSprintPlannerStateForCreateNext = async () => { calls.resetCycle += 1; };
    globalThis.renderPhaseSection = () => {};
    globalThis.updateNextButton = () => {};
    globalThis.loadSprintCandidates = async () => {};
    globalThis.loadSprintHistory = async () => {};
    globalThis.renderSprintHistory = (items) => { calls.historyRender = items; };
    globalThis.renderSprintAttemptPanels = (inputContext, outputArtifact) => {
        calls.attemptPanels = [inputContext, outputArtifact];
    };
    globalThis.updateSprintSaveButton = () => {};

    globalThis.sprintRuntimeSummary = { can_create_next_sprint: false };
    globalThis.selectedSprintStoryIds = new Set([12, 18]);
    globalThis.latestSprintIsComplete = true;
    globalThis.sprintAttemptCount = 4;
    globalThis.currentSprintArtifactJSON = { sprint_goal: 'Existing planned sprint' };
    globalThis.currentSprintInputContextJSON = { available_stories: [{ story_id: 12 }] };
    globalThis.viewPhaseId = 'overview';
    globalThis.showSprintPlanner = false;

    await openSprintPlanner();

    assert.deepEqual(Array.from(globalThis.selectedSprintStoryIds), [12, 18]);
    assert.equal(globalThis.latestSprintIsComplete, true);
    assert.equal(globalThis.sprintAttemptCount, 4);
    assert.deepEqual(globalThis.currentSprintArtifactJSON, { sprint_goal: 'Existing planned sprint' });
    assert.deepEqual(globalThis.currentSprintInputContextJSON, { available_stories: [{ story_id: 12 }] });
    assert.equal(globalThis.viewPhaseId, 'sprint');
    assert.equal(globalThis.showSprintPlanner, true);
    assert.equal(calls.resetCycle, 0);
    assert.equal(calls.historyRender, null);
    assert.equal(calls.attemptPanels, null);
});
