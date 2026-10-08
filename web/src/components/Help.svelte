<script module>
  let next = 0;
</script>
<script>
  import { onMount } from 'svelte';
  let { label, children } = $props();
  const id = `help-${++next}`;
  let panel;
  let opened = $state(false);
  onMount(() => {
    const close = () => { if (opened) panel.hidePopover(); };
    document.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => { document.removeEventListener('scroll', close, true); window.removeEventListener('resize', close); };
  });
  function toggle(event) {
    if (opened) { panel.hidePopover(); return; }
    const anchor = event.currentTarget.getBoundingClientRect();
    panel.showPopover();
    const box = panel.getBoundingClientRect();
    panel.style.left = `${Math.max(12, Math.min(anchor.left, innerWidth - box.width - 12))}px`;
    panel.style.top = `${Math.max(12, Math.min(anchor.bottom + 8, innerHeight - box.height - 12))}px`;
  }
</script>
<button type="button" class="help" aria-label={label} aria-expanded={opened} aria-controls={id} aria-describedby={opened ? id : undefined} onclick={toggle}>?</button>
<span {id} class="bubble" popover="auto" role="tooltip" bind:this={panel} ontoggle={(event) => opened = event.newState === 'open'}>{@render children()}</span>
<style>
  .help { flex: none; display: inline-grid; place-items: center; width: 2rem; height: 2rem; border: 1px solid var(--border-strong); border-radius: 50%; font-size: .8rem; font-weight: 700; color: var(--text-secondary); }
  .help:hover { background: var(--bg-hover); color: var(--text-primary); }
  .bubble { position: fixed; inset: auto; margin: 0; width: min(22rem, calc(100vw - 24px)); max-height: calc(100dvh - 24px); overflow: auto; padding: .875rem 1rem; border: 1px solid var(--border-strong); border-radius: var(--radius-lg); background: var(--bg-tertiary); color: var(--text-secondary); box-shadow: var(--shadow-lg); font-size: .875rem; line-height: 1.5; overflow-wrap: anywhere; }
  @media (max-width: 720px) { .help { width: 44px; height: 44px; } }
</style>
