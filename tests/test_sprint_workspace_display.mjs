import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const projectJsPath = path.resolve(import.meta.dirname, '../frontend/project.js');
const projectJsSource = fs.readFileSync(projectJsPath, 'utf8');
const projectHtmlPath = path.resolve(import.meta.dirname, '../frontend/project.html');
const projectHtmlSource = fs.readFileSync(projectHtmlPath, 'utf8');

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

test('renderSprintValidationErrors lists actionable retry guidance', () => {
    const renderSprintValidationErrors = loadSprintFunction(
        'renderSprintValidationErrors',
        [/function renderSprintValidationErrors\(validationErrors\) \{[\s\S]*?\n\}/],
    );

    const html = renderSprintValidationErrors([
        'Add acceptance criteria for the login task',
        'Separate the API work from the UI work',
        '',
        null,
    ]);

    assert.match(html, /What to fix/);
    assert.match(html, /Add acceptance criteria for the login task/);
    assert.match(html, /Separate the API work from the UI work/);
    assert.doesNotMatch(html, /<li[^>]*>\s*<\/li>/);
});

test('sprint planning notes copy mentions retry guidance', () => {
    assert.match(projectHtmlSource, /Planning or Retry Notes/);
    assert.match(projectHtmlSource, /retry guidance from the latest failed attempt/);
    assert.match(projectHtmlSource, /retry instructions/);
});
