import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

describe('notes dialog affordance', () => {
  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    global.CSS = { escape: (s) => String(s) };
    document.body.innerHTML = `
      <div id="tableWrap" class="table-hide-notes"></div>
      <div id="notesDialogModal" class="hidden">
        <div role="dialog">
          <h3 id="notesDialogTitle"></h3>
          <textarea id="notesDialogInput"></textarea>
          <button id="notesDialogClose"></button>
          <button id="notesDialogCancel"></button>
          <button id="notesDialogSave"></button>
        </div>
      </div>
    `;
    vi.resetModules();
    vi.doMock('../js/game-core.js', () => ({
      findGameByKey: (key) => (key === 'steam:1' ? { store: 'steam', id: 1, name: 'Test' } : null),
      gameKey: (g) => `${g.store}:${g.id}`,
    }));
    vi.doMock('../js/personal-storage.js', () => ({
      getPersonal: () => ({ notes: 'hello' }),
      setPersonal: vi.fn(),
    }));
    vi.doMock('../js/focus-trap.js', () => ({
      trapFocus: () => () => {},
      bindEscapeClose: () => () => {},
    }));
  });

  it('notesAffordanceHtml shows open button when notes column hidden', async () => {
    const { notesAffordanceHtml } = await import('../js/notes-dialog.js');
    const html = notesAffordanceHtml('steam:1', 'hello');
    expect(html).toContain('notes-open-btn');
    expect(html).toContain('data-notes-key="steam:1"');
  });

  it('notesAffordanceHtml shows + note when empty and column hidden', async () => {
    const { notesAffordanceHtml } = await import('../js/notes-dialog.js');
    const html = notesAffordanceHtml('steam:1', '');
    expect(html).toContain('notes-open-btn--empty');
    expect(html).toContain('+ note');
  });

  it('openNotesDialog populates textarea', async () => {
    const { openNotesDialog } = await import('../js/notes-dialog.js');
    openNotesDialog('steam:1');
    const modal = document.getElementById('notesDialogModal');
    expect(modal.classList.contains('flex')).toBe(true);
    expect(document.getElementById('notesDialogInput').value).toBe('hello');
    expect(document.getElementById('notesDialogTitle').textContent).toContain('Test');
  });

  it('requestCloseNotesDialog confirms when textarea differs from opened value', async () => {
    const confirm = vi.fn(() => false);
    window.confirm = confirm;
    const { openNotesDialog, requestCloseNotesDialog } = await import('../js/notes-dialog.js');
    openNotesDialog('steam:1');
    document.getElementById('notesDialogInput').value = 'edited';
    requestCloseNotesDialog();
    expect(confirm).toHaveBeenCalled();
    expect(document.getElementById('notesDialogModal').classList.contains('flex')).toBe(true);

    confirm.mockReturnValue(true);
    requestCloseNotesDialog();
    expect(document.getElementById('notesDialogModal').classList.contains('hidden')).toBe(true);
  });

  it('requestCloseNotesDialog closes without confirm when unchanged', async () => {
    const confirm = vi.fn(() => true);
    window.confirm = confirm;
    const { openNotesDialog, requestCloseNotesDialog } = await import('../js/notes-dialog.js');
    openNotesDialog('steam:1');
    requestCloseNotesDialog();
    expect(confirm).not.toHaveBeenCalled();
    expect(document.getElementById('notesDialogModal').classList.contains('hidden')).toBe(true);
  });
});
