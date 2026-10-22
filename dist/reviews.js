const STORAGE_KEY = 'sana-review-draft';
const ROLE_KEYS = {
  teacher: 'reviewRoleTeacher',
  student: 'reviewRoleStudent',
  parent: 'reviewRoleParent',
  other: 'reviewRoleOther',
};

function element(tag, attributes = {}, text = '') {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  node.textContent = text;
  return node;
}

function readDraft(value) {
  if (!value || typeof value !== 'object' || typeof value.impression !== 'string') return null;
  const impression = value.impression.slice(0, 1500).trim();
  if (!impression) return null;
  return {
    version: 1,
    name: typeof value.name === 'string' ? value.name.slice(0, 80).trim() : '',
    role: Object.hasOwn(ROLE_KEYS, value.role) ? value.role : 'other',
    impression,
  };
}

export function setupReviews(t) {
  const mount = document.querySelector('#review-community');
  if (!mount) return { render() {} };

  let draft = null;
  let storageAvailable = true;
  let lastAction = '';
  let opener = null;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try { draft = readDraft(JSON.parse(stored)); } catch { /* Ignore a malformed saved draft. */ }
    }
  } catch { storageAvailable = false; }

  const card = element('div', { class: 'review-community-card' });
  const invitation = element('div', { class: 'review-invitation' });
  const quote = element('span', { class: 'review-community-quote', 'aria-hidden': 'true' }, '“');
  const invitationCopy = element('div');
  const title = element('h3', { id: 'review-community-title' });
  const description = element('p', { class: 'review-community-description' });
  invitationCopy.append(title, description);
  invitation.append(quote, invitationCopy);

  const prompts = element('ul', { class: 'review-prompts' });
  const likePrompt = element('li');
  const improvePrompt = element('li');
  prompts.append(likePrompt, improvePrompt);

  const preview = element('section', { class: 'review-draft-preview', 'aria-labelledby': 'review-draft-label' });
  const draftLabel = element('h4', { id: 'review-draft-label', class: 'review-draft-label' });
  const author = element('p', { class: 'review-draft-author' });
  const draftText = element('p', { class: 'review-draft-text' });
  preview.append(draftLabel, author, draftText);

  const notice = element('p', { class: 'review-local-notice' });
  const actions = element('div', { class: 'review-community-actions' });
  const compose = element('button', { type: 'button', class: 'review-primary-button' });
  const download = element('button', { type: 'button', class: 'review-secondary-button' });
  const remove = element('button', { type: 'button', class: 'review-delete-button' });
  actions.append(compose, download, remove);
  const status = element('p', { class: 'review-action-status', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' });
  card.append(invitation, prompts, preview, notice, actions, status);
  mount.replaceChildren(card);

  const dialog = element('dialog', {
    id: 'review-dialog',
    class: 'review-dialog',
    'aria-labelledby': 'review-dialog-title',
    'aria-describedby': 'review-dialog-notice',
  });
  const dialogTop = element('div', { class: 'review-dialog-top' });
  const dialogEyebrow = element('span', { class: 'review-dialog-eyebrow' });
  const dialogTools = element('div', { class: 'review-dialog-tools' });
  const languages = element('div', { class: 'language-switch review-language-switch', role: 'group' });
  const languageButtons = [
    element('button', { type: 'button', 'data-language': 'ru', lang: 'ru', 'aria-label': 'Русский' }, 'РУС'),
    element('button', { type: 'button', 'data-language': 'kk', lang: 'kk', 'aria-label': 'Қазақша' }, 'ҚАЗ'),
  ];
  languages.append(...languageButtons);
  const close = element('button', { type: 'button', class: 'review-dialog-close' }, '×');
  dialogTools.append(languages, close);
  dialogTop.append(dialogEyebrow, dialogTools);
  const dialogTitle = element('h2', { id: 'review-dialog-title' });
  const dialogNotice = element('p', { id: 'review-dialog-notice', class: 'review-dialog-notice' });

  const form = element('form', { class: 'review-form' });
  const fieldGrid = element('div', { class: 'review-field-grid' });
  const nameField = element('div', { class: 'review-field' });
  const nameLabel = element('label', { for: 'review-name' });
  const nameInput = element('input', { id: 'review-name', name: 'name', type: 'text', maxlength: '80', autocomplete: 'given-name' });
  nameField.append(nameLabel, nameInput);
  const roleField = element('div', { class: 'review-field' });
  const roleLabel = element('label', { for: 'review-role' });
  const roleInput = element('select', { id: 'review-role', name: 'role' });
  const roleOptions = Object.entries(ROLE_KEYS).map(([value, key]) => ({ node: element('option', { value }), key }));
  roleInput.append(...roleOptions.map(({ node }) => node));
  roleField.append(roleLabel, roleInput);
  fieldGrid.append(nameField, roleField);

  const impressionField = element('div', { class: 'review-field' });
  const impressionLabel = element('label', { for: 'review-impression' });
  const impressionInput = element('textarea', {
    id: 'review-impression', name: 'impression', required: '', maxlength: '1500', rows: '6',
    'aria-describedby': 'review-impression-hint review-character-count',
  });
  const fieldFooter = element('div', { class: 'review-field-footer' });
  const impressionHint = element('span', { id: 'review-impression-hint' });
  const characterCount = element('span', { id: 'review-character-count' });
  fieldFooter.append(impressionHint, characterCount);
  impressionField.append(impressionLabel, impressionInput, fieldFooter);

  const formActions = element('div', { class: 'review-form-actions' });
  const save = element('button', { type: 'submit', class: 'review-primary-button' });
  const cancel = element('button', { type: 'button', class: 'review-secondary-button' });
  formActions.append(save, cancel);
  form.append(fieldGrid, impressionField, formActions);
  dialog.append(dialogTop, dialogTitle, dialogNotice, form);
  document.body.append(dialog);

  function updateCount() {
    characterCount.textContent = t('reviewCharacterCount', { count: impressionInput.value.length, max: 1500 });
  }

  function render() {
    title.textContent = t('reviewCommunityTitle');
    description.textContent = t('reviewCommunityDescription');
    prompts.setAttribute('aria-label', t('reviewPromptsLabel'));
    likePrompt.textContent = t('reviewPromptLike');
    improvePrompt.textContent = t('reviewPromptImprove');
    prompts.hidden = Boolean(draft);
    preview.hidden = !draft;
    draftLabel.textContent = t('reviewDraftLabel');
    if (draft) {
      author.textContent = `${draft.name || t('reviewUnnamed')} · ${t(ROLE_KEYS[draft.role])}`;
      draftText.textContent = draft.impression;
    }
    notice.textContent = t(storageAvailable ? 'reviewLocalNotice' : 'reviewStorageUnavailable');
    notice.classList.toggle('review-notice-warning', !storageAvailable);
    compose.textContent = t(draft ? 'reviewEdit' : 'reviewShare');
    download.textContent = t('reviewDownload');
    download.hidden = !draft;
    remove.textContent = t('reviewDelete');
    remove.hidden = !draft;
    const actionKeys = {
      saved: storageAvailable ? 'reviewSaved' : 'reviewSavedTemporarily',
      downloaded: 'reviewDownloadStarted',
      downloadError: 'reviewDownloadError',
      deleted: 'reviewDeleted',
      deleteUnavailable: 'reviewDeleteUnavailable',
    };
    status.textContent = lastAction ? t(actionKeys[lastAction]) : '';
    status.classList.toggle('review-status-warning', ['downloadError', 'deleteUnavailable'].includes(lastAction));
    dialogEyebrow.textContent = t('reviewDialogEyebrow');
    dialogTitle.textContent = t(draft ? 'reviewEditTitle' : 'reviewDialogTitle');
    dialogNotice.textContent = t(storageAvailable ? 'reviewLocalNotice' : 'reviewStorageUnavailable');
    languages.setAttribute('aria-label', t('reviewLanguageLabel'));
    for (const button of languageButtons) {
      const active = button.dataset.language === document.documentElement.lang;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('active', active);
    }
    close.setAttribute('aria-label', t('reviewClose'));
    nameLabel.textContent = t('reviewNameLabel');
    nameInput.placeholder = t('reviewNamePlaceholder');
    roleLabel.textContent = t('reviewRoleLabel');
    for (const { node, key } of roleOptions) node.textContent = t(key);
    impressionLabel.textContent = t('reviewImpressionLabel');
    impressionInput.placeholder = t('reviewImpressionPlaceholder');
    impressionHint.textContent = t('reviewImpressionHint');
    if (impressionInput.validity.customError) impressionInput.setCustomValidity(t('reviewRequired'));
    save.textContent = t('reviewSave');
    cancel.textContent = t('reviewCancel');
    updateCount();
  }

  compose.addEventListener('click', () => {
    opener = document.activeElement;
    nameInput.value = draft?.name || '';
    roleInput.value = draft?.role || 'teacher';
    impressionInput.value = draft?.impression || '';
    impressionInput.setCustomValidity('');
    render();
    dialog.showModal();
    document.body.classList.add('modal-open');
    impressionInput.focus({ preventScroll: true });
  });

  close.addEventListener('click', () => dialog.close());
  cancel.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => {
    const otherDialogOpen = Boolean(document.querySelector('dialog[open]'));
    document.body.classList.toggle('modal-open', otherDialogOpen);
    if (!otherDialogOpen && opener?.isConnected) opener.focus({ preventScroll: true });
  });
  impressionInput.addEventListener('input', () => {
    impressionInput.setCustomValidity('');
    updateCount();
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!impressionInput.value.trim()) {
      impressionInput.setCustomValidity(t('reviewRequired'));
      impressionInput.reportValidity();
      return;
    }
    if (!form.reportValidity()) return;
    draft = readDraft({ name: nameInput.value, role: roleInput.value, impression: impressionInput.value });
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
      storageAvailable = true;
    } catch { storageAvailable = false; }
    lastAction = 'saved';
    render();
    dialog.close();
  });

  download.addEventListener('click', () => {
    if (!draft) return;
    let objectUrl;
    try {
      const lines = [
        t('reviewDownloadTitle'),
        t('reviewDownloadPrivate'),
        '',
        `${t('reviewDownloadName')}: ${draft.name || t('reviewUnnamed')}`,
        `${t('reviewRoleLabel')}: ${t(ROLE_KEYS[draft.role])}`,
        '',
        t('reviewImpressionLabel'),
        draft.impression,
        '',
      ];
      objectUrl = URL.createObjectURL(new Blob(['\uFEFF', lines.join('\r\n')], { type: 'text/plain;charset=utf-8' }));
      const link = element('a', { href: objectUrl, download: 'sana-review-draft.txt', hidden: '' });
      document.body.append(link);
      link.click();
      link.remove();
      lastAction = 'downloaded';
    } catch { lastAction = 'downloadError'; }
    finally {
      if (objectUrl) setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    }
    render();
  });

  remove.addEventListener('click', () => {
    if (!draft) return;
    try {
      localStorage.removeItem(STORAGE_KEY);
      storageAvailable = true;
      lastAction = 'deleted';
    } catch {
      storageAvailable = false;
      lastAction = 'deleteUnavailable';
    }
    draft = null;
    nameInput.value = '';
    roleInput.value = 'teacher';
    impressionInput.value = '';
    impressionInput.setCustomValidity('');
    render();
    compose.focus({ preventScroll: true });
  });

  render();
  return { render };
}
