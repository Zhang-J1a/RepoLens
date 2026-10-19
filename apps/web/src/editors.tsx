import { useEffect, useRef } from 'react';
import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api.js';
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution';
import 'monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import type { Locator } from './types';

// All editor modules and workers are local. No CDN receives repository content.
self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });
const language = (path: string) =>
  path.endsWith('.py') ? 'python' : path.endsWith('.md') ? 'markdown' : 'plaintext';
export function CodeEditor({ locator, text }: { locator: Locator; text: string }) {
  return (
    <Editor
      height="100%"
      language={language(locator.path)}
      value={text}
      onMount={(editor) => {
        const start = locator.line_start || 1,
          end = locator.line_end || start;
        editor.revealLineInCenter(start);
        editor.setSelection(new monaco.Range(start, 1, end, 10000));
      }}
      options={{
        readOnly: true,
        domReadOnly: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 13,
        automaticLayout: true,
      }}
    />
  );
}
export function CodeDiff({ path, before, after }: { path: string; before: string; after: string }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const original = monaco.editor.createModel(before, language(path));
    const modified = monaco.editor.createModel(after, language(path));
    const editor = monaco.editor.createDiffEditor(container.current, {
      readOnly: true,
      originalEditable: false,
      renderSideBySide: true,
      useInlineViewWhenSpaceIsLimited: true,
      minimap: { enabled: false },
      automaticLayout: true,
      fontSize: 12,
    });
    editor.setModel({ original, modified });
    return () => {
      editor.setModel(null);
      editor.dispose();
      original.dispose();
      modified.dispose();
    };
  }, [path, before, after]);
  return <div ref={container} style={{ height: '100%', width: '100%' }} />;
}
