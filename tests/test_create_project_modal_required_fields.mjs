import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const indexHtmlPath = path.resolve(import.meta.dirname, '../frontend/index.html');
const indexHtmlSource = fs.readFileSync(indexHtmlPath, 'utf8');

test('create project modal marks required inputs semantically and hides decorative asterisks from assistive tech', () => {
    assert.match(
        indexHtmlSource,
        /<label for="modal-project-name"[^>]*>Project Name <span class="text-red-500" aria-hidden="true">\*<\/span><\/label>/,
    );
    assert.match(
        indexHtmlSource,
        /<input id="modal-project-name" type="text" required placeholder="e\.g\. Project Phoenix"/,
    );
    assert.match(
        indexHtmlSource,
        /<label for="modal-spec-path"[^>]*>Specification File\s+Path <span class="text-red-500" aria-hidden="true">\*<\/span><\/label>/,
    );
    assert.match(
        indexHtmlSource,
        /<input id="modal-spec-path" type="text" required placeholder="C:\\\\path\\\\to\\\\spec\.md"/,
    );
});
