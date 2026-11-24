// Shared browser behavior for sign-in panels, notices, dashboard navigation, and forms.
// Recheck authentication when the browser restores a signed-in page from history.
if (document.body.hasAttribute('data-authenticated')) {
  window.addEventListener('pagehide', (event) => {
    if (event.persisted) document.documentElement.style.visibility = 'hidden';
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) window.location.reload();
  });
}

// Use native dialogs when the browser supports them.
if (typeof HTMLDialogElement !== 'undefined' && HTMLDialogElement.prototype.showModal) {
  let activePanel;
  let returnTo;
  const landing = document.querySelector('.landing');
  const panels = document.querySelectorAll('.login-panel');

  // Open the matching role dialog and focus the username or password after an error.
  function openPanel(panel, trigger) {
    returnTo = trigger;
    activePanel = panel;
    landing.dataset.panel = panel.dataset.role;
    panel.showModal();
    const field = panel.querySelector('.feedback-notice[data-level="error"]')
      ? 'current-password'
      : 'username';
    panel.querySelector(`input[autocomplete="${field}"]`).focus();
  }

  for (const panel of panels) {
    const back = panel.querySelector('[data-close-panel]');
    const trigger = document.querySelector(`[data-open-panel="${panel.dataset.role}"]`);
    // Open the dialog for ordinary clicks and keep the normal link behavior for modified
    // clicks.
    trigger.addEventListener('click', (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      openPanel(panel, trigger);
    });
    back.addEventListener('click', (event) => {
      event.preventDefault();
      panel.close();
    });
    // Restore the landing page and return focus to the control that opened the dialog.
    panel.addEventListener('close', () => {
      if (activePanel !== panel || panel.open) return;
      activePanel = undefined;
      landing.dataset.panel = '';
      if (location.pathname === new URL(trigger.href).pathname) {
        history.replaceState(history.state, '', back.href);
      }
      returnTo?.focus();
    });
    // Restore a dialog that Django marked open after loading its sign-in page.
    if (panel.open) {
      panel.removeAttribute('open');
      openPanel(panel, trigger);
    }
  }

  // Open required password dialogs immediately and keep the keyboard dismissal disabled.
  for (const modal of document.querySelectorAll('[data-modal-auto][data-required]')) {
    modal.removeAttribute('open');
    modal.showModal();
    modal.addEventListener('cancel', (event) => event.preventDefault());
  }
}

// Find the feedback area where Django and the scanner display messages.
const feedbackStack = document.querySelector('[data-feedback-stack]');
if (feedbackStack) {
  let feedbackTimer;

  // Display the current notice and reset the timer that hides it.
  function showFeedback() {
    clearTimeout(feedbackTimer);
    feedbackStack.hidden = false;

    // The top layer keeps feedback above the open sign-in panel without blocking it.
    if (typeof feedbackStack.showPopover === 'function') {
      feedbackStack.setAttribute('popover', 'manual');
      if (!feedbackStack.matches(':popover-open')) feedbackStack.showPopover();
    }

    // Leave error feedback visible longer so the user can read it.
    const duration = feedbackStack.querySelector('[data-level="error"]') ? 6000 : 4500;
    feedbackTimer = setTimeout(() => {
      if (feedbackStack.hasAttribute('popover') && feedbackStack.matches(':popover-open')) {
        feedbackStack.hidePopover();
      }
      feedbackStack.hidden = true;
    }, duration);
  }

  if (feedbackStack.childElementCount) showFeedback();
  // Listen for browser-generated notices and skip duplicate messages.
  document.addEventListener('bsit:feedback', (event) => {
    const { message, level } = event.detail;
    const current = feedbackStack.firstElementChild;
    if (!feedbackStack.hidden && current?.textContent === message && current.dataset.level === level) return;

    const notice = document.createElement('p');
    notice.className = 'feedback-notice';
    notice.dataset.level = level;
    notice.setAttribute('role', level === 'error' ? 'alert' : 'status');
    // Insert the message as text so it displays as written.
    notice.textContent = message;
    feedbackStack.replaceChildren(notice);
    showFeedback();
  });
}

// Switch the matching password field between hidden and visible text.
for (const toggle of document.querySelectorAll('[data-password-toggle]')) {
  toggle.addEventListener('click', () => {
    const input = toggle.parentElement.querySelector('input');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    toggle.textContent = show ? 'Hide' : 'Show';
    toggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });
}

// Preview a selected image in the browser until the user saves the profile.
const profilePhotoInput = document.querySelector('[data-profile-photo]');
if (profilePhotoInput) {
  const preview = document.querySelector('[data-profile-photo-preview]');
  const status = document.querySelector('[data-profile-photo-status]');
  const image = preview.querySelector('img') || document.createElement('img');
  image.alt = '';
  let photoUrl;

  profilePhotoInput.addEventListener('change', () => {
    const file = profilePhotoInput.files[0];
    if (!file) return;

    // Release the previous preview URL before replacing it with the new one.
    if (photoUrl) URL.revokeObjectURL(photoUrl);
    photoUrl = URL.createObjectURL(file);
    image.src = photoUrl;
    preview.replaceChildren(image);
    status.textContent = 'Photo selected. Save changes to update it.';
  });
}

// Match the manual attendance fields to the selected record type.
const attendanceAddForm = document.querySelector('[data-attendance-add-form]');
if (attendanceAddForm) {
  const recordType = attendanceAddForm.elements.namedItem('record_type');
  const timeIn = attendanceAddForm.elements.namedItem('time_in');
  const timeOut = attendanceAddForm.elements.namedItem('time_out');
  const timeOutField = timeOut.closest('.management-field');
  const timeInHelp = document.getElementById('id_time_in_helptext');

  function updateAttendanceFields() {
    const isTimeIn = recordType.value === 'IN';
    timeIn.required = isTimeIn;
    timeInHelp.hidden = isTimeIn;
    timeOut.disabled = isTimeIn;
    timeOut.required = !isTimeIn;
    timeOutField.hidden = isTimeIn;
  }

  recordType.addEventListener('change', updateAttendanceFields);
  updateAttendanceFields();
}
