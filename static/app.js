document.addEventListener('submit', e => {
  const form = e.target;
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) { e.preventDefault(); return; }
  const button = form.querySelector('[data-loading]');
  if (button) { button.disabled = true; button.textContent = button.dataset.loading; }
});

