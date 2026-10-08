<script>
  import { onDestroy, onMount } from 'svelte';
  import Icon from './Icon.svelte';

  // The window of Poulet's message history (components/HistoryModal): the dimmed page behind it, a glass panel, a title and a cross.
  // Escape and a click outside close it. For the keyboard: the focus enters the window when it opens, Tab stays inside it, and the
  // focus goes back to what opened it when it closes.
  let { title, titleId = 'modal-title', onClose, width = '40rem', children } = $props();

  let dialog;
  let opener = null;
  const FOCUSABLE = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex="-1"])';

  const focusable = () => [...dialog.querySelectorAll(FOCUSABLE)].filter((el) => !el.matches(':disabled') && el.offsetParent !== null);

  onMount(() => {
    opener = document.activeElement;
    // the first thing that can be filled in or pressed in the body, otherwise the window itself
    const body = dialog.querySelector('.body');
    (body?.querySelector('input:not(:disabled), select:not(:disabled), button:not(:disabled)') ?? dialog).focus();
  });

  onDestroy(() => {
    if (opener && opener.isConnected) opener.focus();
  });

  function keydown(event) {
    if (event.key === 'Escape') {
      onClose();
    } else if (event.key === 'Tab') {
      const items = focusable();
      if (!items.length) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    }
  }
</script>

<svelte:window onkeydown={keydown} />

<div class="overlay" role="presentation" onclick={(event) => event.target === event.currentTarget && onClose()}>
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} style:width tabindex="-1" bind:this={dialog}>
    <header>
      <h2 id={titleId}>{title}</h2>
      <button class="closeBtn" onclick={onClose} aria-label="Fermer"><span class="closeIcon"><Icon name="close" /></span></button>
    </header>
    <div class="body">{@render children()}</div>
  </div>
</div>

<style>
  /* HistoryModal.module.css */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 100;
    background: rgba(0, 0, 0, 0.65);
    backdrop-filter: blur(0.25rem);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    animation: fadeIn 150ms ease both;
  }

  .modal:focus {
    outline: none;
  }

  .modal {
    max-width: 100%;
    max-height: 90vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--bg-glass);
    backdrop-filter: blur(1.25rem);
    -webkit-backdrop-filter: blur(1.25rem);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg), 0 0 0 1px rgba(255, 255, 255, 0.04) inset;
    animation: modalEnter 200ms ease both;
  }

  @keyframes modalEnter {
    from { opacity: 0; transform: translateY(1rem) scale(0.96); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--border-subtle);
    flex-shrink: 0;
  }

  h2 {
    min-width: 0;
    overflow-wrap: anywhere;
    font-size: 0.9375rem;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }

  .closeBtn {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.75rem;
    height: 2.75rem;
    color: var(--text-muted);
    border-radius: var(--radius-sm);
    transition: color var(--transition-fast), background var(--transition-fast);
  }

  .closeBtn:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .closeIcon {
    width: 1rem;
    height: 1rem;
    display: inline-flex;
  }

  .closeIcon :global(svg) {
    width: 100%;
    height: 100%;
  }

  .body {
    overflow-y: auto;
    flex: 1;
    padding: 1rem 1.25rem 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.875rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
  }
</style>
