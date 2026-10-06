<script>
  import { tick } from 'svelte';
  import Icon from './Icon.svelte';

  // The left bar of the Poulet dashboard (components/Navbar): the server picker, the pages, the session
  let { guilds, guild, view = 'map', onView, onGuildChange, onImport, onInvite, onLogout } = $props();

  let mobileOpen = $state(false);
  let menuOpen = $state(false);
  let picker = $state();
  let menu = $state();
  let touchStartX = null;

  let selected = $derived(guilds.find((g) => g.id === guild));
  const initials = (name) => (name || 'D').trim().slice(0, 2).toUpperCase();

  async function openMenu() {
    menuOpen = true;
    await tick();
    (menu?.querySelector('[aria-checked="true"]') ?? menu?.querySelector('button'))?.focus();
  }

  function closeMenu(refocus = false) {
    menuOpen = false;
    if (refocus) picker?.focus();
  }

  function menuKey(event) {
    const items = [...menu.querySelectorAll('button')];
    const at = items.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeMenu(true);
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      items[(at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    }
  }

  function choose(id) {
    closeMenu(true);
    mobileOpen = false;
    onGuildChange(id);
  }

  function windowClick(event) {
    if (menuOpen && !event.target.closest?.('.logoContainer')) menuOpen = false;
  }

  function importing() {
    mobileOpen = false;
    onImport();
  }

  function showView(name) {
    mobileOpen = false;
    onView(name);
  }

  function inviting() {
    mobileOpen = false;
    onInvite();
  }

  function inviteFromMenu() {
    closeMenu();
    inviting();
  }
</script>

<svelte:window onclick={windowClick} />

<div class="mobileTopbar">
  <button type="button" class="mobileMenuButton" aria-expanded={mobileOpen} aria-controls="dashboard-mobile-drawer" aria-label="Ouvrir le menu" onclick={() => (mobileOpen = !mobileOpen)}>
    <Icon name="menu" />
  </button>
  <div class="mobileTitle">
    <span class="mobileTitleLabel">Serveur</span>
    <span class="mobileTitleName">{selected?.name || 'Aucun serveur'}</span>
  </div>
</div>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="mobileOverlay" class:mobileOverlayOpen={mobileOpen} onclick={() => (mobileOpen = false)} aria-hidden={!mobileOpen}></div>

<nav
  id="dashboard-mobile-drawer"
  class="navbar"
  class:mobileDrawerOpen={mobileOpen}
  aria-label="Navigation principale"
  ontouchstart={(event) => (touchStartX = event.touches[0]?.clientX ?? null)}
  ontouchend={(event) => {
    if (touchStartX === null) return;
    const delta = (event.changedTouches[0]?.clientX ?? touchStartX) - touchStartX;
    touchStartX = null;
    if (delta < -50) mobileOpen = false;
  }}
>
  <button type="button" class="mobileDrawerHeader" onclick={() => (mobileOpen = false)} aria-label="Fermer le menu">
    <span>Navigation</span>
    <span class="mobileCloseIcon"><Icon name="close" /></span>
  </button>

  <div class="logoContainer">
    <button bind:this={picker} type="button" class="guildPicker" aria-haspopup="menu" aria-expanded={menuOpen} onclick={() => (menuOpen ? closeMenu() : openMenu())}>
      <span class="guildPickerFallback">{initials(selected?.name)}</span>
      <span class="guildPickerBody">
        <span class="guildPickerLabel">Serveur</span>
        <span class="guildPickerName">{selected?.name || 'Aucun serveur'}</span>
      </span>
      <span class="guildPickerChevron" class:guildPickerChevronOpen={menuOpen}><Icon name="chevron-down" /></span>
    </button>
    {#if menuOpen}
      <!-- svelte-ignore a11y_interactive_supports_focus -->
      <div bind:this={menu} class="guildPickerMenu" role="menu" aria-label="Sélectionner un serveur" onkeydown={menuKey}>
        {#each guilds as g (g.id)}
          <button type="button" role="menuitemradio" aria-checked={g.id === guild} class="guildPickerOption" class:guildPickerOptionSelected={g.id === guild} onclick={() => choose(g.id)}>
            <span class="guildPickerOptionLabel">{g.name || g.id}</span>
            {#if g.id === guild}<span class="guildPickerOptionCheck"><Icon name="check" /></span>{/if}
          </button>
        {/each}
        <div class="guildPickerSeparator" role="separator"></div>
        <button type="button" role="menuitem" class="guildPickerOption" onclick={inviteFromMenu}>
          <span class="guildPickerOptionLabel">Ajouter un autre serveur…</span>
        </button>
        <p class="guildPickerHint">Un serveur apparaît ici une fois suivi par le bot et ses messages arrivés.</p>
      </div>
    {/if}
  </div>

  <div class="navItems">
    <button type="button" class="navItem" class:active={view === 'map'} aria-current={view === 'map' ? 'page' : undefined} title="Carte des échanges" onclick={() => showView('map')}>
      <span class="icon"><Icon name="map" /></span>
      <span class="navLabel">Carte</span>
    </button>
    <button type="button" class="navItem" class:active={view === 'debates'} aria-current={view === 'debates' ? 'page' : undefined} title="Les débats ouverts avec /dindon debat : positions, statistiques, affirmations vérifiées et leurs sources" onclick={() => showView('debates')}>
      <span class="icon"><Icon name="debates" /></span>
      <span class="navLabel">Débats</span>
    </button>
    <button type="button" class="navItem" class:active={view === 'analyse'} aria-current={view === 'analyse' ? 'page' : undefined} title="Thèmes, positions et contradictions du serveur" onclick={() => showView('analyse')}>
      <span class="icon"><Icon name="themes" /></span>
      <span class="navLabel">Analyse</span>
    </button>
    <button type="button" class="navItem" title="Importer l’historique de certains salons, de certaines personnes, d’une période" onclick={importing}>
      <span class="icon"><Icon name="import" /></span>
      <span class="navLabel">Importer</span>
    </button>
    <button type="button" class="navItem" class:active={view === 'system'} aria-current={view === 'system' ? 'page' : undefined} title="L’état du bot, de la base et de l’IA locale" onclick={() => showView('system')}>
      <span class="icon"><Icon name="system" /></span>
      <span class="navLabel">Système</span>
    </button>
    <button type="button" class="navItem" class:active={view === 'privacy'} aria-current={view === 'privacy' ? 'page' : undefined} title="Les personnes qui ne sont pas enregistrées, l’effacement, l’accès aux données" onclick={() => showView('privacy')}>
      <span class="icon"><Icon name="privacy" /></span>
      <span class="navLabel">Vie privée</span>
    </button>
    <button type="button" class="navItem" title="Ajouter le bot à un serveur Discord, et voir les serveurs où il est" onclick={inviting}>
      <span class="icon"><Icon name="invite" /></span>
      <span class="navLabel">Inviter le bot</span>
    </button>
  </div>

  <div class="bottomItems">
    <div class="profileCard">
      <span class="profileFallback">DI</span>
      <div class="profileBody">
        <span class="profileName">Session</span>
        <span class="profileHandle">accès local</span>
      </div>
      <button type="button" class="logoutBtn" title="Quitter" aria-label="Quitter" onclick={onLogout}>
        <span class="logoutIcon"><Icon name="logout" /></span>
      </button>
    </div>
  </div>
</nav>

<style>
  /* Navbar.module.css, class for class */
  .navbar {
    width: 14.5rem;
    min-width: 14.5rem;
    background: linear-gradient(180deg, color-mix(in srgb, var(--bg-secondary) 55%, transparent) 0%, transparent 18%), var(--bg-tertiary);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0.75rem 0;
    border-right: 1px solid var(--border-subtle);
    flex-shrink: 0;
    z-index: 10;
  }

  .mobileTopbar,
  .mobileOverlay,
  .mobileDrawerHeader {
    display: none;
  }

  .logoContainer {
    position: relative;
    width: 100%;
    padding: 0 0.75rem;
    margin-bottom: 1.5rem;
  }

  .guildPicker {
    width: 100%;
    min-height: 3.5rem;
    background: linear-gradient(180deg, color-mix(in srgb, #fff 4%, transparent), transparent), var(--bg-primary);
    color: var(--text-primary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    display: flex;
    align-items: center;
    gap: 0.625rem;
    padding: 0.625rem 0.75rem;
    position: relative;
    text-align: left;
    transition: border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease;
  }

  button.guildPicker:hover {
    border-color: color-mix(in srgb, var(--accent) 22%, var(--border-subtle));
    background-color: color-mix(in srgb, var(--bg-hover) 88%, var(--bg-primary));
  }

  .guildPickerFallback {
    width: 2.125rem;
    height: 2.125rem;
    border-radius: 50%;
    flex-shrink: 0;
    background: var(--accent);
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: 700;
  }

  .guildPickerBody {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }

  .guildPickerName {
    color: var(--text-primary);
    font-size: 0.8125rem;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .guildPickerChevron {
    width: 0.875rem;
    height: 0.875rem;
    color: var(--text-muted);
    margin-left: auto;
    flex-shrink: 0;
    display: inline-flex;
    transition: color 180ms ease, transform 180ms ease;
  }

  .guildPickerChevron :global(svg) {
    width: 100%;
    height: 100%;
  }

  .guildPicker:hover .guildPickerChevron {
    color: var(--text-secondary);
    transform: translateY(1px);
  }

  .guildPickerChevronOpen,
  .guildPicker:hover .guildPickerChevronOpen {
    transform: rotate(180deg);
    color: var(--text-secondary);
  }

  .guildPickerLabel {
    font-size: 0.625rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
  }

  .guildPicker:focus-visible {
    outline: 0.125rem solid color-mix(in srgb, var(--accent) 56%, #ffffff);
    outline-offset: 0.125rem;
  }

  .guildPickerMenu {
    position: absolute;
    top: calc(100% + 0.5rem);
    left: 0.75rem;
    right: 0.75rem;
    z-index: 60;
    max-height: 60vh;
    overflow-y: auto;
    outline: none;
    padding: 0.375rem;
    border-radius: var(--radius-lg);
    border: 1px solid var(--border-strong);
    background: linear-gradient(180deg, color-mix(in srgb, #fff 4%, transparent), transparent), var(--bg-secondary);
    box-shadow: var(--shadow-lg);
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .guildPickerOption {
    width: 100%;
    min-height: 2.5rem;
    padding: 0 0.75rem;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.625rem;
    text-align: left;
    transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
  }

  .guildPickerOption:hover,
  .guildPickerOption:focus-visible {
    background: linear-gradient(180deg, color-mix(in srgb, #fff 3%, transparent), transparent), color-mix(in srgb, var(--bg-hover) 82%, var(--bg-primary));
    border-color: color-mix(in srgb, var(--accent) 18%, var(--border-subtle));
  }

  .guildPickerOptionSelected {
    background: linear-gradient(180deg, color-mix(in srgb, #fff 4%, transparent), transparent), color-mix(in srgb, var(--accent) 10%, var(--bg-tertiary));
    border-color: color-mix(in srgb, var(--accent) 28%, var(--border-subtle));
  }

  .guildPickerOptionLabel {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.8125rem;
    font-weight: 600;
  }

  .guildPickerSeparator {
    height: 1px;
    margin: 0.125rem 0.25rem;
    background: var(--border-subtle);
  }

  .guildPickerHint {
    padding: 0.25rem 0.75rem 0.5rem;
    font-size: 0.6875rem;
    line-height: 1.4;
    color: var(--text-muted);
  }

  .guildPickerOptionCheck {
    width: 1rem;
    height: 1rem;
    flex-shrink: 0;
    display: inline-flex;
    color: color-mix(in srgb, var(--accent) 72%, #ffffff);
  }

  .guildPickerOptionCheck :global(svg) {
    width: 100%;
    height: 100%;
  }

  .navItems {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    width: 100%;
    align-items: flex-start;
    padding: 0 0.75rem;
  }

  .bottomItems {
    margin-top: auto;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    width: 100%;
    align-items: flex-start;
    padding: 0 0.75rem 0.75rem;
  }

  .profileCard {
    width: 100%;
    background: linear-gradient(180deg, color-mix(in srgb, #fff 4%, transparent), transparent), var(--bg-primary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    padding: 0.625rem;
    display: grid;
    grid-template-columns: 2.25rem 1fr auto;
    gap: 0.5rem;
    align-items: center;
    transition: border-color 180ms ease, box-shadow 180ms ease, background-color 180ms ease;
  }

  .profileCard:hover {
    border-color: color-mix(in srgb, var(--accent) 18%, var(--border-subtle));
    box-shadow: 0 0.875rem 1.75rem rgba(0, 0, 0, 0.12);
  }

  .profileFallback {
    width: 2.25rem;
    height: 2.25rem;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: 700;
    color: #fff;
    background: linear-gradient(135deg, var(--accent), #7d89ff);
  }

  .profileBody {
    min-width: 0;
    display: flex;
    flex-direction: column;
  }

  .profileName,
  .profileHandle {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .profileName {
    color: var(--text-primary);
    font-size: 0.8125rem;
    font-weight: 600;
  }

  .profileHandle {
    color: var(--text-muted);
    font-size: 0.75rem;
  }

  .logoutBtn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.125rem;
    height: 2.125rem;
    border-radius: var(--radius-md);
    background: var(--bg-hover);
    color: var(--text-secondary);
    flex-shrink: 0;
    transition: background-color 180ms ease, color 180ms ease, transform 180ms ease;
  }

  .logoutBtn:hover {
    background: rgba(237, 66, 69, 0.18);
    color: #f23f42;
    transform: translateY(-1px);
  }

  .logoutIcon {
    width: 1.0625rem;
    height: 1.0625rem;
    flex-shrink: 0;
    display: inline-flex;
  }

  .logoutIcon :global(svg),
  .icon :global(svg),
  .mobileCloseIcon :global(svg) {
    width: 100%;
    height: 100%;
  }

  .navItem {
    width: 100%;
    height: 2.75rem;
    border-radius: var(--radius-md);
    background-color: transparent;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.625rem;
    cursor: pointer;
    transition: background-color 160ms ease, color 160ms ease, border-color 160ms ease;
    position: relative;
    padding: 0 0.75rem;
    border: 1px solid transparent;
    isolation: isolate;
  }

  .navItem::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 8%, transparent), transparent 58%);
    opacity: 0;
    transition: opacity 160ms ease;
    z-index: -1;
  }

  .navItem:hover {
    background: linear-gradient(180deg, color-mix(in srgb, #fff 3%, transparent), transparent), color-mix(in srgb, var(--bg-hover) 82%, var(--bg-primary));
    color: var(--text-primary);
    border-color: color-mix(in srgb, var(--accent) 18%, var(--border-subtle));
  }

  .navItem:hover::after {
    opacity: 1;
  }

  .navItem.active {
    background: linear-gradient(180deg, color-mix(in srgb, #fff 4%, transparent), transparent), color-mix(in srgb, var(--accent) 10%, var(--bg-tertiary));
    color: var(--text-primary);
    border-color: color-mix(in srgb, var(--accent) 28%, var(--border-subtle));
  }

  .navItem.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    height: 1.375rem;
    width: 0.25rem;
    background-color: var(--accent);
    border-radius: 0 0.25rem 0.25rem 0;
  }

  .navItem.active .icon {
    color: color-mix(in srgb, var(--accent) 72%, #ffffff);
  }

  .icon {
    width: 1.5rem;
    height: 1.5rem;
    flex-shrink: 0;
    display: inline-flex;
  }

  .navLabel {
    font-size: 0.8125rem;
    font-weight: 600;
    white-space: nowrap;
  }

  @media (max-width: 720px) {
    .mobileTopbar {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      z-index: 40;
      display: flex;
      align-items: center;
      gap: 0.75rem;
      height: calc(3.75rem + env(safe-area-inset-top));
      padding: calc(0.625rem + env(safe-area-inset-top)) 1rem 0.625rem;
      background: color-mix(in srgb, var(--bg-tertiary) 92%, transparent);
      backdrop-filter: blur(0.875rem);
      border-bottom: 1px solid var(--border-subtle);
    }

    .mobileMenuButton {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 2.5rem;
      height: 2.5rem;
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      background: var(--bg-secondary);
      color: var(--text-primary);
    }

    .mobileMenuButton :global(svg) {
      width: 1.125rem;
      height: 1.125rem;
    }

    .mobileTitle {
      min-width: 0;
      display: flex;
      flex-direction: column;
    }

    .mobileTitleLabel {
      font-size: 0.625rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-muted);
    }

    .mobileTitleName {
      color: var(--text-primary);
      font-size: 0.875rem;
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .mobileOverlay {
      display: block;
      position: fixed;
      inset: 0;
      z-index: 45;
      background: rgba(0, 0, 0, 0.45);
      opacity: 0;
      pointer-events: none;
      transition: opacity var(--transition-normal);
    }

    .mobileOverlayOpen {
      opacity: 1;
      pointer-events: auto;
    }

    .navbar {
      position: fixed;
      top: 0;
      left: 0;
      bottom: 0;
      z-index: 50;
      width: min(86vw, 20rem);
      min-width: 0;
      max-width: 20rem;
      padding-top: env(safe-area-inset-top);
      transform: translateX(-100%);
      transition: transform var(--transition-normal);
      overflow-y: auto;
      border-right: 1px solid var(--border-strong);
      box-shadow: var(--shadow-lg);
    }

    .mobileDrawerOpen {
      transform: translateX(0);
    }

    .mobileDrawerHeader {
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
      padding: 0.75rem 0.75rem 0.25rem;
      color: var(--text-secondary);
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      text-align: left;
    }

    .mobileDrawerHeader:hover {
      color: var(--text-primary);
    }

    .mobileCloseIcon {
      width: 1.125rem;
      height: 1.125rem;
      flex-shrink: 0;
      display: inline-flex;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .guildPicker,
    .guildPickerChevron,
    .profileCard,
    .logoutBtn,
    .navItem,
    .navItem::after,
    .mobileOverlay,
    .navbar {
      transition: none;
    }
  }
</style>
