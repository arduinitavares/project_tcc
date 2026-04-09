import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const indexHtmlPath = path.resolve(import.meta.dirname, '../frontend/index.html');
const indexHtmlSource = fs.readFileSync(indexHtmlPath, 'utf8');

test('create project modal marks required fields with decorative indicators', () => {
    assert.match(
        indexHtmlSource,
        /<label for="modal-project-name"[^>]*>Project Name\s*<span[^>]*aria-hidden="true"[^>]*>\*<\/span><\/label>/,
    );
    assert.match(
        indexHtmlSource,
        /<input id="modal-project-name"[^>]*required[^>]*>/,
    );
    assert.match(
        indexHtmlSource,
        /<label for="modal-spec-path"[^>]*>Specification File\s*Path\s*<span[^>]*aria-hidden="true"[^>]*>\*<\/span><\/label>/,
    );
    assert.match(
        indexHtmlSource,
        /<input id="modal-spec-path"[^>]*required[^>]*aria-describedby="modal-spec-path-help"[^>]*>/,
    );
    assert.match(
        indexHtmlSource,
        /<p id="modal-spec-path-help"[^>]*>Provide the absolute path to your markdown specification\.<\/p>/,
    );
});
