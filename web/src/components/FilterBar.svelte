<script>
  import Icon from './Icon.svelte';

  // The bar above the content (Poulet's components/FilterBar and the preset buttons of its stats page)
  let {
    query = $bindable(''),
    suggestions,
    preset = $bindable('all'),
    since = $bindable(''),
    until = $bindable(''),
    kinds = $bindable({}),
    density = $bindable('2500'),
    channel = $bindable(''),
    theme = $bindable(''),
    ideology = $bindable(''),
    minWeight = $bindable('0'),
    mapOptions = { channels: [], themes: [], ideologies: [] },
    showIsolated = $bindable(true),
    presets,
    kindList,
    onSearch,
    onChoose,
    onChange,
    onIsolated,
    onFit,
  } = $props();

  const fmt = new Intl.NumberFormat('fr-FR');

  let box;                 // the search box (input and suggestions)
  let dismissed = $state(false); // Escape, or a click elsewhere, closed the suggestions until the next letter

  function clearSearch() {
    query = '';
    dismissed = false;
    onSearch();
  }

  function typed() {
    dismissed = false;
    onSearch();
  }

  const options = () => [...box.querySelectorAll('li button')];

  // From the box: Down goes into the suggestions, Enter opens the first one, Escape closes them
  function inputKey(event) {
    if (!suggestions.length || dismissed) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      options()[0]?.focus();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      onChoose(suggestions[0]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation(); // the person's card behind does not close with it
      dismissed = true;
    }
  }

  // Inside the suggestions: Up and Down move, Escape goes back to the box
  function listKey(event) {
    const items = options();
    const at = items.indexOf(document.activeElement);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      items[Math.min(at + 1, items.length - 1)]?.focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (at <= 0) box.querySelector('input').focus();
      else items[at - 1].focus();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      box.querySelector('input').focus(); // focusing the box reopens the suggestions...
      dismissed = true;                   // ...so they are closed after
    }
  }

  function elsewhere(event) {
    if (!dismissed && box && !box.contains(event.target)) dismissed = true;
  }
</script>

<svelte:window onclick={elsewhere} />

<div class="bar">
  <div class="search searchWrapper" bind:this={box}>
    <span class="searchIcon"><Icon name="search" /></span>
    <input class="searchInput" type="search" placeholder="Chercher une personne…" bind:value={query} oninput={typed} onkeydown={inputKey} onfocus={() => (dismissed = false)} aria-label="Chercher une personne" autocomplete="off" aria-autocomplete="list" aria-controls="people-found" />
    {#if query}
      <button type="button" class="clearBtn" onclick={clearSearch} aria-label="Effacer">×</button>
    {/if}
    {#if suggestions.length && !dismissed}
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <ul id="people-found" role="listbox" aria-label="Personnes trouvées" onkeydown={listKey}>
        {#each suggestions as person (person.id)}
          <li><button role="option" aria-selected="false" onclick={() => onChoose(person)}><span class="personName">{person.label}</span> <span class="count">{fmt.format(person.messages)}</span></button></li>
        {/each}
      </ul>
    {/if}
  </div>

  <div class="segmented" role="group" aria-label="Période">
    {#each presets as p (p.id)}
      <button type="button" aria-pressed={preset === p.id} onclick={() => { preset = p.id; onChange(); }}>{p.label}</button>
    {/each}
  </div>

  {#if preset === 'custom'}
    <div class="dateRange">
      <label class="dateLabel" aria-label="Du">
        <span class="calIcon"><Icon name="calendar" /></span>
        <input class="dateInput" type="date" bind:value={since} onchange={onChange} aria-label="Du" />
      </label>
      <span class="dateSep">→</span>
      <label class="dateLabel" aria-label="Au">
        <span class="calIcon"><Icon name="calendar" /></span>
        <input class="dateInput" type="date" bind:value={until} onchange={onChange} aria-label="Au" />
      </label>
    </div>
  {/if}

  <div class="kinds" role="group" aria-label="Types d’échanges">
    {#each kindList as k (k.id)}
      <button type="button" class="kind" aria-pressed={kinds[k.id]} onclick={() => { kinds[k.id] = !kinds[k.id]; onChange(); }}>
        <span class="swatch"></span>{k.label}
      </button>
    {/each}
  </div>

  <select class="select fsel" bind:value={density} onchange={onChange} aria-label="Nombre de liens affichés">
    <option value="800">Liens : essentiels</option>
    <option value="2500">Liens : lisibles</option>
    <option value="8000">Liens : détaillés</option>
    <option value="20000">Liens : tous (lent)</option>
  </select>

  <select class="select fsel" bind:value={channel} onchange={onChange} aria-label="Salon">
    <option value="">Salon</option>
    {#each mapOptions.channels as c (c.id)}<option value={c.id}>#{c.name} ({fmt.format(c.messages)})</option>{/each}
  </select>

  {#if mapOptions.themes.length}
    <select class="select fsel" bind:value={theme} onchange={onChange} aria-label="Thème">
      <option value="">Thème</option>
      {#each mapOptions.themes as t (t.id)}<option value={t.id}>{t.label}</option>{/each}
    </select>
  {/if}

  {#if mapOptions.ideologies.length}
    <select class="select fsel" bind:value={ideology} onchange={onChange} aria-label="Rôle d’idées">
      <option value="">Rôle</option>
      {#each mapOptions.ideologies as i (i.id)}<option value={i.id}>{i.name} ({fmt.format(i.people)})</option>{/each}
    </select>
  {/if}

  <select class="select fsel" bind:value={minWeight} onchange={onChange} aria-label="Force minimale des liens">
    <option value="0">Force</option>
    <option value="0.5">Force : au moins 0,5</option>
    <option value="1">Force : au moins 1</option>
    <option value="3">Force : au moins 3</option>
    <option value="10">Force : au moins 10</option>
  </select>

  <label class="toggle" title="Les personnes qui ont déjà écrit mais n’ont aucun lien affiché, quelle que soit la période">
    <input type="checkbox" bind:checked={showIsolated} onchange={onIsolated} />
    <span class="toggleLabel">Sans lien</span>
  </label>

  <button type="button" class="tool-btn fit" onclick={onFit} title="Revenir à la vue d’ensemble">
    <span class="fitIcon"><Icon name="fit" /></span>
    <span class="fitText">Tout voir</span>
  </button>
</div>

<style>
  /* FilterBar.module.css */
  .bar {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border-subtle);
    background: var(--bg-primary);
    flex-wrap: nowrap;               /* one line; on a narrow window it wraps again (below) */
    flex-shrink: 0;
  }

  /* The menus take the room they are left (the longest channel name must not stretch the bar) and cut what does not fit */
  .fsel {
    flex: 0 1 auto;
    min-width: 5rem;
    max-width: 9.5rem;
    font-size: 0.75rem;
    padding: 0.3125rem 0.375rem;
    text-overflow: ellipsis;
  }

  .segmented :global(button) {
    padding: 0.3125rem 0.5rem;
  }

  .kind,
  .fit {
    white-space: nowrap;
    flex-shrink: 0;
  }

  @media (max-width: 1100px) {
    .bar {
      flex-wrap: wrap;
    }
  }

  @media (max-width: 1500px) {
    .fitText {
      display: none;                 /* the icon alone, its title says the rest */
    }
  }

  .searchWrapper {
    position: relative;
    display: flex;
    align-items: center;
    flex: 1 1 9rem;
    min-width: 6.5rem;
    max-width: 14rem;
  }

  .searchIcon {
    position: absolute;
    left: 0.5rem;
    width: 0.875rem;
    height: 0.875rem;
    display: inline-flex;
    color: var(--text-muted);
    pointer-events: none;
  }

  .searchIcon :global(svg),
  .calIcon :global(svg),
  .fitIcon :global(svg) {
    width: 100%;
    height: 100%;
  }

  .searchInput {
    width: 100%;
    background: var(--bg-secondary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 0.3125rem 0.625rem 0.3125rem 1.75rem;
    color: var(--text-primary);
    font-size: 0.8125rem;
    outline: none;
    transition: border-color var(--transition-fast);
  }

  .searchInput:not(:placeholder-shown) {
    padding-right: 1.75rem; /* room for the cross that clears it */
  }

  .searchInput::-webkit-search-cancel-button {
    appearance: none;
    display: none;
  }

  .searchInput::placeholder {
    color: var(--text-muted);
  }

  .searchInput:focus {
    border-color: var(--accent);
  }

  .clearBtn {
    position: absolute;
    right: 0.375rem;
    color: var(--text-muted);
    font-size: 1rem;
    padding: 0 0.125rem;
    line-height: 1;
    transition: color var(--transition-fast);
  }

  .clearBtn:hover {
    color: var(--text-primary);
  }

  /* The suggestions: the menu of the server picker (Navbar.module.css .guildPickerMenu) */
  ul {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    margin-top: 0.375rem;
    padding: 0.375rem;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
    border-radius: var(--radius-lg);
    border: 1px solid var(--border-strong);
    background: linear-gradient(180deg, color-mix(in srgb, #fff 4%, transparent), transparent), var(--bg-secondary);
    box-shadow: var(--shadow-lg);
    max-height: min(60vh, 26.25rem);
    overflow-y: auto;
    z-index: 20;
  }

  li button {
    width: 100%;
    min-height: 2.25rem;
    padding: 0 0.5625rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    text-align: left;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: 0.8125rem;
    font-weight: 500;
    transition: background var(--transition-fast), color var(--transition-fast);
  }

  li button:hover,
  li button:focus-visible {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .personName {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .count {
    flex-shrink: 0;
    font-size: 0.625rem;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
    padding: 0 0.3125rem;
    line-height: 1rem;
  }

  /* Stats.module.css .seriesToggleRow, .seriesToggleBtn: a kind that is hidden fades */
  .kinds {
    display: flex;
    flex-wrap: nowrap;
    flex-shrink: 0;
    gap: 0.25rem;
  }

  .kind {
    display: inline-flex;
    align-items: center;
    gap: 0.3125rem;
    padding: 0.3125rem 0.5rem;
    border: 1px solid var(--border-subtle);
    border-radius: 62.4375rem;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-size: 0.75rem;
    transition: background var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast), opacity var(--transition-fast);
  }

  .kind:hover {
    background: var(--bg-hover);
    border-color: var(--border-strong);
    color: var(--text-primary);
  }

  .kind[aria-pressed='false'] {
    opacity: 0.45;
  }

  .swatch {
    width: 0.625rem;
    height: 0.625rem;
    border-radius: 62.4375rem;
    flex-shrink: 0;
    background: var(--accent);
  }

  .dateRange {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
  }

  .dateLabel {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 0.25rem 0.5rem;
    cursor: pointer;
    transition: border-color var(--transition-fast);
  }

  .dateLabel:focus-within {
    border-color: var(--accent);
  }

  .calIcon {
    width: 0.8125rem;
    height: 0.8125rem;
    display: inline-flex;
    color: var(--text-muted);
    flex-shrink: 0;
  }

  .dateInput {
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 0.75rem;
    outline: none;
    width: 6.875rem;
    cursor: pointer;
    color-scheme: dark;
  }

  .dateSep {
    color: var(--text-muted);
    font-size: 0.75rem;
  }

  .toggle {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    cursor: pointer;
    flex-shrink: 0;
  }

  .toggleLabel {
    font-size: 0.75rem;
    color: var(--text-muted);
    white-space: nowrap;
    user-select: none;
    transition: color var(--transition-fast);
  }

  .toggle:hover .toggleLabel {
    color: var(--text-secondary);
  }

  .fit {
    margin-left: auto;
  }

  .fitIcon {
    width: 0.8125rem;
    height: 0.8125rem;
    display: inline-flex;
    flex-shrink: 0;
  }

  @media (max-width: 608px) {
    .bar {
      gap: 0.5rem;
      padding: 0.625rem 0.75rem;
    }

    .searchWrapper,
    .dateRange {
      flex-basis: 100%;
      max-width: none;
    }

    .dateRange {
      flex-direction: column;
      align-items: stretch;
    }

    .dateLabel {
      width: 100%;
    }

    .dateInput {
      width: 100%;
      min-width: 0;
    }

    .dateSep {
      display: none;
    }

    .fit {
      margin-left: 0;
    }
  }
</style>
