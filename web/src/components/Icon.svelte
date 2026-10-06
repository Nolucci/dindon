<script>
  // The icons of the Poulet dashboard (Feather, 24x24, a 2px line) plus the small ones that its sidebar and filter bar draw by hand.
  let { name, size = null } = $props();
  const small = { search: '0 0 20 20', calendar: '0 0 16 16', 'chevron-down': '0 0 12 12', 'chevron-right': '0 0 12 12', check: '0 0 16 16' };
  let box = $derived(small[name] ?? '0 0 24 24');
  let line = $derived(name === 'search' || name === 'chevron-down' || name === 'chevron-right' ? 1.5 : name === 'calendar' ? 1.2 : name === 'check' ? 1.8 : 2);
</script>

<svg viewBox={box} fill="none" stroke="currentColor" stroke-width={line} stroke-linecap="round" stroke-linejoin="round" width={size} height={size} aria-hidden="true">
  {#if name === 'map'}
    <circle cx="6" cy="12" r="3" /><circle cx="18" cy="5" r="3" /><circle cx="18" cy="19" r="3" />
    <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" /><line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
  {:else if name === 'import'}
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
  {:else if name === 'themes'}
    <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" /><line x1="7" y1="7" x2="7.01" y2="7" />
  {:else if name === 'system'}
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  {:else if name === 'positions'}
    <line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" /><line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" /><line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" /><line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="17" y1="16" x2="23" y2="16" />
  {:else if name === 'coherence'}
    <path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
  {:else if name === 'debates'}
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><line x1="8" y1="9" x2="16" y2="9" /><line x1="8" y1="13" x2="13" y2="13" />
  {:else if name === 'privacy'}
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  {:else if name === 'invite'}
    <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="8.5" cy="7" r="4" /><line x1="20" y1="8" x2="20" y2="14" /><line x1="23" y1="11" x2="17" y2="11" />
  {:else if name === 'logout'}
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
  {:else if name === 'fit'}
    <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
  {:else if name === 'menu'}
    <line x1="4" y1="7" x2="20" y2="7" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="17" x2="20" y2="17" />
  {:else if name === 'close'}
    <line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" />
  {:else if name === 'search'}
    <circle cx="8.5" cy="8.5" r="5.5" /><path d="M13 13l3.5 3.5" />
  {:else if name === 'calendar'}
    <rect x="1.5" y="3.5" width="13" height="11" rx="1.5" /><path d="M1.5 7h13" /><path d="M5 1.5v3M11 1.5v3" />
  {:else if name === 'chevron-down'}
    <path d="M3 4.5 6 7.5l3-3" />
  {:else if name === 'chevron-right'}
    <path d="M4 2l4 4-4 4" />
  {:else if name === 'check'}
    <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />
  {/if}
</svg>
