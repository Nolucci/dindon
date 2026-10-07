<script>
  import { onMount, tick } from 'svelte';
  import { api, makeGuard, openEvents } from '../lib/api.js';
  import { MapGraph } from '../lib/mapgraph.js';
  import { imageProgram, pictureLoader } from '../lib/pictures.js';
  import { plural, ago as agoOf } from '../lib/format.js';
  import Navbar from './Navbar.svelte';
  import FilterBar from './FilterBar.svelte';
  import PersonCard from './PersonCard.svelte';
  import ImportPanel from './ImportPanel.svelte';
  import InvitePanel from './InvitePanel.svelte';
  import Analyse from './Analyse.svelte';
  import System from './System.svelte';
  import Privacy from './Privacy.svelte';
  import Debates from './Debates.svelte';

  let { onLogout } = $props();

  const PEOPLE_STEPS = [10, 25, 50, 100, 200, 500, 1000, 3000];     // the slider on the map: how many people at most (the most connected first)
  const PEOPLE_STEPS_DEFAULT = 100;
  const PRESETS = [
    { id: 'all', label: 'Tout', days: null },
    { id: '90', label: '90 j', days: 90 },
    { id: '30', label: '30 j', days: 30 },
    { id: '7', label: '7 j', days: 7 },
    { id: 'custom', label: 'Dates…', days: null },
  ];
  const KINDS = [
    { id: 'reply', label: 'Réponses' },
    { id: 'mention', label: 'Mentions' },
    { id: 'reaction', label: 'Réactions' },
  ];
  const RELOAD_EVERY_MS = 8000;

  let container;
  let pictures = null;           // the photos of the people on the map (lib/pictures.js)
  let map = null;
  let guilds = $state([]);
  let guild = $state('');
  let preset = $state('all');
  let since = $state('');
  let until = $state('');
  let kinds = $state({ reply: true, mention: true, reaction: true });
  let channel = $state('');       // narrow the map to one channel, one topic, one role of the server; and hide the weakest links
  let theme = $state('');
  let role = $state('');
  let minWeight = $state('0');
  let mapOptions = $state({ channels: [], themes: [], roles: [] });
  let people = $state(String(PEOPLE_STEPS_DEFAULT)); // how many people at most, the most connected first (a slider on the map itself)
  let density = $state('2500'); // how many links to draw at most: the strongest ones first
  let showImport = $state(false); // the window to import a part of the server
  let showInvite = $state(false); // the window to invite the bot to a server
  let view = $state('map');       // the map is kept alive (hidden) while another page is shown
  let analysisSection = $state('themes');
  let stale = false;              // something happened to the map while it was hidden: it is brought up to date when it comes back
  let grouped = $state(false);     // placed by role and by resemblance of names instead of by exchanges
  let showIsolated = $state(false); // also the people who wrote and have no link on the map (points on their own)
  let lastExchange = $state(null);
  let exchangeTimer;
  let recent = [];                // the exchanges of the last seconds, to name the people who talk together
  const CONVERSATION_MS = 8000;
  let meta = $state(null);
  let status = $state(null);
  let live = $state(false);
  let loading = $state(true);
  let problem = $state('');
  let newMessages = $state(0);
  let lastEventAt = $state(null);
  let now = $state(Date.now());

  let selectedId = $state(null);
  let card = $state(null);
  let cardLoading = $state(false);
  let cardError = $state('');

  let query = $state('');
  let suggestions = $state([]);
  let searchTimer;

  let reloadTimer = null;
  let lastReload = 0;
  let pendingFlashes = [];

  const fmt = new Intl.NumberFormat('fr-FR');
  const ago = (iso) => agoOf(iso, now);

  // A page that shows the present can be updated live; a page that shows a past period cannot
  let showsPresent = $derived(preset !== 'custom' || !until);
  let noKind = $derived(!KINDS.some((k) => kinds[k.id]));

  const DEFAULTS = { preset: 'all', density: '2500', minWeight: '0', people: String(PEOPLE_STEPS_DEFAULT) };
  // Something differs from what the map shows when it is opened
  let dirty = $derived(preset !== DEFAULTS.preset || since !== '' || until !== '' || !KINDS.every((k) => kinds[k.id]) || density !== DEFAULTS.density || people !== DEFAULTS.people
    || channel !== '' || theme !== '' || role !== '' || minWeight !== DEFAULTS.minWeight || showIsolated || grouped || query !== '');

  function resetFilters() {
    preset = DEFAULTS.preset;
    since = until = '';
    kinds = { reply: true, mention: true, reaction: true };
    density = DEFAULTS.density;
    people = DEFAULTS.people;
    channel = theme = role = '';
    minWeight = DEFAULTS.minWeight;
    showIsolated = false;
    query = '';
    suggestions = [];
    if (grouped) {
      grouped = false;
      map?.setGrouped(false);
    }
    filterChanged();
    map?.resetView();
  }

  function layoutChanged() {
    map?.setGrouped(grouped);
  }

  function graphParams() {
    const params = { guild, kinds: KINDS.filter((k) => kinds[k.id]).map((k) => k.id).join(','), max_edges: density, limit: people, isolated: showIsolated,
      channels: channel || undefined, theme: theme || undefined, role: role || undefined, min_weight: Number(minWeight) || undefined };
    const days = PRESETS.find((p) => p.id === preset)?.days;
    if (days) params.since = new Date(Date.now() - days * 86400000).toISOString();
    if (preset === 'custom') {
      if (since) params.since = new Date(since).toISOString();
      if (until) params.until = new Date(new Date(until).getTime() + 86400000).toISOString();
    }
    return params;
  }

  const guard = makeGuard(() => onLogout(), (message) => (problem = message));

  async function reload() {
    clearTimeout(reloadTimer);
    reloadTimer = null;
    if (!guild || !map) return;
    if (noKind) {                                            // nothing to draw: the map is emptied, and the page says why
      map.load({ nodes: [], edges: [] });
      meta = null;
      loading = false;
      return;
    }
    if (view !== 'map') {                                    // hidden: nothing to draw now
      stale = true;
      return;
    }
    const data = await guard(() => api.graph(graphParams()));
    loading = false;
    if (!data) return;
    problem = '';
    lastReload = Date.now();
    meta = data.meta;
    map.load(data);
    pictures?.show(data.nodes);
    if (selectedId && !map.has(selectedId)) map.select(null);
    for (const event of pendingFlashes.splice(0)) map.flash(event); // exchanges that arrived while the person was not yet on the map
  }

  // What the person just asked for (a filter, a server) shows at once; a few quick clicks make one reload
  function reloadSoon() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(reload, 120);
  }

  // At most one reload every few seconds, however many events arrive
  function scheduleReload(delay = 0) {
    if (reloadTimer) return;
    const wait = Math.max(delay, RELOAD_EVERY_MS - (Date.now() - lastReload));
    reloadTimer = setTimeout(reload, Math.max(wait, 0));
  }

  function onEvent(event) {
    if (event.type === 'hello') return;
    lastEventAt = new Date().toISOString();
    if (event.guild && event.guild !== guild) return;
    if (view !== 'map') {                                    // the map is hidden: no light to show, it is reloaded when it comes back
      if (event.type !== 'messages') stale = true;
      else newMessages += event.count;
      return;
    }
    if (event.type === 'edge' && showsPresent && kinds[event.kind]) {
      const label = (id) => map?.labelOf(id) ?? id;
      // Exchanges of the last few seconds: those who talk together are named together (A, B and C), not only the last pair
      const at = Date.now();
      recent = [...recent.filter((r) => at - r.at < CONVERSATION_MS), { at, from: event.from, to: event.to, kind: event.kind }];
      const names = [...new Set(recent.flatMap((r) => [r.from, r.to]))];
      const shownNames = names.slice(0, 4).map(label).join(', ') + (names.length > 4 ? ` et ${names.length - 4} autres` : '');
      lastExchange = recent.length > 1 && names.length > 2
        ? `${shownNames} · ${recent.length} échanges`
        : `${label(event.from)} → ${label(event.to)} · ${{ reply: 'réponse', mention: 'mention', reaction: 'réaction' }[event.kind]}`;
      clearTimeout(exchangeTimer);
      exchangeTimer = setTimeout(() => { lastExchange = null; recent = []; }, 7000);
      if (!map?.flash(event)) {
        pendingFlashes.push(event);
        scheduleReload(1500);
      } else {
        scheduleReload();
      }
    } else if (event.type === 'messages') {
      newMessages += event.count;
      if (showIsolated && showsPresent) scheduleReload(); // someone may have written for the first time, without a link yet
    } else if (event.type === 'graph') {
      scheduleReload(500);
    }
  }

  async function selectPerson(id) {
    const cardWasOpen = selectedId !== null;
    selectedId = id;
    map?.select(id);
    if (cardWasOpen !== (id !== null)) tick().then(() => map?.resized());
    if (!id) {
      card = null;
      return;
    }
    cardLoading = true;
    cardError = '';
    const person = await guard(() => api.person(id, guild));
    cardLoading = false;
    if (selectedId !== id) return;
    if (person) card = person;
    else cardError = problem || 'Fiche indisponible.';
  }

  function pick(id) {
    selectPerson(id);
    map?.focus(id);
  }

  function search() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      suggestions = query.trim() ? (await guard(() => api.people(query.trim(), guild))) ?? [] : [];
    }, 180);
  }

  function choose(person) {
    suggestions = [];
    query = '';
    pick(person.id);
  }

  async function refreshStatus() {
    const s = await guard(() => api.status());
    if (s) status = s;
  }

  async function logout() {
    await api.logout().catch(() => {});
    onLogout();
  }

  onMount(() => {
    map = new MapGraph(container, {
      onSelect: (id) => selectPerson(id),
      onHover: () => {},
      imageProgram,
    });
    pictures = pictureLoader(map, (path) => fetch(path));       // the session cookie goes with it
    const stopEvents = openEvents(onEvent, (open) => (live = open));
    const tick = setInterval(() => (now = Date.now()), 1000);
    const statusTimer = setInterval(refreshStatus, 15000);
    (async () => {
      guilds = (await guard(() => api.guilds())) ?? [];
      if (guilds.length) {
        guild = guilds.reduce((a, b) => ((b.last_message_at ?? '') > (a.last_message_at ?? '') ? b : a)).id;
        await reload();
      } else {
        loading = false;
      }
      refreshStatus();
    })();
    return () => {
      stopEvents();
      clearInterval(tick);
      clearInterval(statusTimer);
      clearTimeout(reloadTimer);
      clearTimeout(searchTimer);
      clearTimeout(exchangeTimer);
      map?.destroy();
    };
  });

  // Changing a filter shows the map again
  function filterChanged() {
    selectedId = null;
    card = null;
    reloadSoon();
  }

  // Once the window of the import is closed, the map shows what it brought (also when no server was there before)
  async function importClosed() {
    showImport = false;
    const list = await guard(() => api.guilds());
    if (list) {
      guilds = list;
      if (!guild && list.length) guild = list.reduce((a, b) => ((b.last_message_at ?? '') > (a.last_message_at ?? '') ? b : a)).id;
    }
    reload();
  }

  // The box of the people without a link answers at once (the other filters wait for the next reload)
  function isolatedChanged() {
    selectedId = null;
    card = null;
    reload();
  }

  // Escape closes the person's card (a window that is open has the Escape for itself, and so does the box of the search)
  function escape(event) {
    if (event.key === 'Escape' && selectedId && !showImport && !showInvite && !event.defaultPrevented) selectPerson(null);
  }

  // The page of the left bar. The map is only hidden: coming back, it takes its size again
  function showView(name) {
    view = name;
    if (name === 'map') {
      tick().then(() => {
        map?.resized();
        if (stale) {
          stale = false;
          reload();
        }
      });
    }
  }

  function showPerson(id) {
    showView('map');
    pick(id);
  }

  // Another server was picked in the left bar: its map is shown
  async function loadOptions() {
    const options = guild ? await guard(() => api.mapFilters(guild)) : null;
    mapOptions = options ?? { channels: [], themes: [], roles: [] };
  }

  $effect(() => {
    guild;                               // another server: its own channels, topics and ideologies
    channel = theme = role = '';
    loadOptions();
  });

  function guildPicked(id) {
    guild = id;
    analysisSection = 'themes';
    filterChanged();
  }
</script>

<svelte:window onkeydown={escape} />

<div class="layout">
  <Navbar {guilds} {guild} {view} onView={showView} onGuildChange={guildPicked} onImport={() => (showImport = true)} onInvite={() => (showInvite = true)} onLogout={logout} />

  <div class="mainContent">
    <div class="mapView" class:hidden={view !== 'map'}>
      <FilterBar
        bind:query
        {suggestions}
        bind:preset
        bind:since
        bind:until
        bind:kinds
        bind:density
        bind:channel
        bind:theme
        bind:role
        bind:minWeight
        {mapOptions}
        bind:showIsolated
        bind:grouped
        {dirty}
        onReset={resetFilters}
        onLayout={layoutChanged}
        presets={PRESETS}
        kindList={KINDS}
        onSearch={search}
        onChoose={choose}
        onChange={filterChanged}
        onIsolated={isolatedChanged}
        onFit={() => map?.resetView()}
      />

      <div class="banners">
        {#if status?.warnings?.includes('account_token')}
          <p class="banner" role="alert">
            Attention : un <strong>compte personnel</strong> est utilisé en continu pour la collecte. Discord l’interdit et peut fermer ce compte.
            Un bot est recommandé (voir le README).
          </p>
        {/if}
        {#if problem}<p class="banner" role="alert">{problem}</p>{/if}
      </div>

      <main>
        <div class="canvas" class:with-card={selectedId} bind:this={container} aria-label="Carte des échanges"></div>

        <div class="zoomPad" class:with-card={selectedId} role="group" aria-label="Zoom de la carte">
          <button type="button" class="zoomBtn" aria-label="Zoomer" onclick={() => map?.zoomIn()}>+</button>
          <button type="button" class="zoomBtn" aria-label="Dézoomer" onclick={() => map?.zoomOut()}>−</button>
          <button type="button" class="zoomBtn" aria-label="Recentrer la carte" onclick={() => map?.resetView()}>⌂</button>
        </div>

        <label class="people" class:with-card={selectedId} title="Combien de personnes afficher sur la carte : les plus connectées d’abord. Moins de monde, c’est aussi une carte plus fluide.">
          <span>Personnes</span>
          <input type="range" min="0" max={PEOPLE_STEPS.length - 1} step="1" value={Math.max(PEOPLE_STEPS.indexOf(Number(people)), 0)} aria-label="Nombre de personnes affichées"
                 oninput={(e) => { people = String(PEOPLE_STEPS[Number(e.currentTarget.value)]); }} onchange={reloadSoon} />
          <output>{meta ? `${fmt.format(meta.nodes_shown)} / ` : ''}{fmt.format(Number(people))}</output>
        </label>

        {#if !loading && !guilds.length}
          <div class="empty">
            <h2>Aucun serveur importé</h2>
            <p>Déposez un export JSON dans le dossier <code>inbox/</code>, ou lancez <code>dindon backfill</code> avec un jeton.</p>
          </div>
        {:else if !loading && noKind}
          <div class="empty"><h2>Aucun type d’échange choisi</h2><p>Activez au moins un des trois : réponses, mentions ou réactions.</p></div>
      {:else if !loading && meta && meta.nodes_shown === 0}
          <div class="empty"><h2>Aucun échange sur cette période</h2><p>Changez de période ou de types d’échanges.</p></div>
        {/if}
        {#if loading}<div class="empty"><p>Chargement de la carte…</p></div>{/if}

        {#if selectedId}
          <PersonCard {card} {guild} loading={cardLoading} error={cardError} onClose={() => { selectPerson(null); }} onPick={pick} />
        {/if}

        <div class="legend" aria-hidden="true">
          <div><span class="dot big"></span> Taille : poids des échanges (les plus petits points n’ont aucun lien affiché) · couleur : celle de la personne sur Discord (son rôle le plus haut qui a une couleur)</div>
          <div><span class="bar"></span> Les liens se révèlent en <strong>survolant</strong> ou en <strong>cliquant</strong> une personne ; leur épaisseur est le poids de l’échange{#if meta && !meta.period}&nbsp;(les échanges récents comptent plus, demi-vie {meta.half_life_days} j){/if}</div>
        </div>
      </main>

      <footer>
        <span class="live on" class:reconnecting={!live} title={live ? 'Les nouveaux échanges s’allument sur la carte dès qu’ils arrivent.' : 'Le flux en direct est en train de se reconnecter : la carte reste juste, elle se rallumera seule.'}><i></i>En direct</span>
        {#if meta}
          <span>{fmt.format(meta.nodes_shown)} {plural(meta.nodes_shown, 'personne', 'personnes')}{#if meta.isolated_shown > 0}&nbsp;(dont {fmt.format(meta.isolated_shown)} sans lien{#if meta.isolated_hidden > 0}, + {fmt.format(meta.isolated_hidden)} masquées{/if}){/if}{#if meta.nodes_hidden > 0}&nbsp;(+ {fmt.format(meta.nodes_hidden)} moins connectées, masquées){/if}</span>
          <span>{fmt.format(meta.edges_shown)} {plural(meta.edges_shown, 'lien', 'liens')}{#if meta.edges_hidden > 0}&nbsp;(+ {fmt.format(meta.edges_hidden)} plus faibles, masqués){/if}</span>
        {/if}
        {#if newMessages}<span>{fmt.format(newMessages)} nouveaux messages depuis l’ouverture</span>{/if}
        {#if lastExchange}<span class="exchange" aria-live="polite">{lastExchange}</span>{/if}
        {#if lastEventAt}<span class="muted">dernier événement {ago(lastEventAt)}</span>{/if}
        <span class="spacer"></span>
        {#if status?.collector?.enabled && status.collector.mode === 'catchup'}
          <span class="muted">rattrapage nocturne : {status.collector.last_catchup_at ? `dernier ${ago(status.collector.last_catchup_at)}` : 'pas encore fait'} (le bot reçoit le direct){#if status.collector.last_error}&nbsp;· <span class="warn">{status.collector.last_error}</span>{/if}</span>
        {:else if status?.collector?.enabled}
          <span class="muted">surveillance : relevé {ago(status.collector.last_poll_at)}{#if status.collector.last_error}&nbsp;· <span class="warn">{status.collector.last_error}</span>{/if}</span>
        {:else if status}
          <span class="muted">pas de surveillance : seuls les exports déposés dans inbox/ sont lus</span>
        {/if}
        {#if status?.inbox?.failed}<span class="warn">{status.inbox.failed} fichier(s) illisible(s) dans inbox/failed</span>{/if}
      </footer>
    </div>

    {#if view === 'analyse'}
      <Analyse {guild} bind:section={analysisSection} onAuthLost={onLogout} onAutomate={() => showView('system')} onPerson={showPerson} />
    {:else if view === 'system'}
      <System {guild} onAuthLost={onLogout} />
    {:else if view === 'debates'}
      <Debates onAuthLost={onLogout} />
    {:else if view === 'privacy'}
      <Privacy onAuthLost={onLogout} />
    {/if}
  </div>

  {#if showImport}
    <ImportPanel onClose={importClosed} onAuthLost={onLogout} />
  {/if}

  {#if showInvite}
    <InvitePanel onClose={() => (showInvite = false)} onAuthLost={onLogout} />
  {/if}
</div>

<style>
  /* app/layout.module.css: the left bar, then the content */
  .layout {
    display: flex;
    height: 100dvh;
    width: 100%;
    overflow: clip;
    background: var(--bg-tertiary);
  }

  .mainContent {
    flex: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--bg-primary);
  }

  .mapView {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .mapView.hidden {
    display: none;
  }

  .banners {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    flex-shrink: 0;
  }

  .banners:not(:empty) {
    padding: 0.625rem 1rem 0;
  }

  /* The web map fills its page on the same neutral color used for the graph's contrast calculations. */
  main {
    position: relative;
    flex: 1;
    min-height: 0;
    background: var(--bg-primary);
  }

  .canvas {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: var(--bg-primary);
  }

  .people {
    position: absolute;
    top: 0.75rem;
    left: 0.75rem;
    z-index: 3;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.375rem 0.75rem;
    border-radius: 999px;
    background: color-mix(in srgb, var(--bg-secondary) 88%, transparent);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  .people input { width: 7.5rem; accent-color: var(--accent, #5865f2); }
  .people output { min-width: 5rem; font-variant-numeric: tabular-nums; color: var(--text-primary); }

  .canvas.with-card {
    right: min(22.5rem, 100%); /* the map stays whole, next to the card */
  }

  /* ui.module.css .emptyState */
  .empty {
    position: absolute;
    inset: 0;
    display: grid;
    place-content: center;
    justify-items: center;
    gap: var(--space-3);
    text-align: center;
    pointer-events: none;
    padding: var(--space-6);
    color: var(--text-secondary);
  }

  .empty h2 {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .empty p {
    max-width: 44ch;
  }

  .legend {
    position: absolute;
    left: 0.875rem;
    bottom: 0.75rem;
    font-size: 0.75rem;
    color: var(--text-muted);
    display: grid;
    gap: 0.375rem;
    pointer-events: none;
    background: var(--bg-glass);
    backdrop-filter: blur(0.75rem);
    -webkit-backdrop-filter: blur(0.75rem);
    border: 1px solid var(--border-subtle);
    box-shadow: var(--shadow-md);
    padding: 0.625rem 0.75rem;
    border-radius: var(--radius-md);
    max-width: min(26.25rem, 60vw);
  }

  .legend strong {
    color: var(--text-secondary);
    font-weight: 600;
  }

  /* The colors of the points and lines are in lib/mapgraph.js: a point is the color of its person in Discord */
  .dot {
    display: inline-block;
    border-radius: 50%;
    background: conic-gradient(#e74c3c, #f1c40f, #2ecc71, #3498db, #9b59b6, #e74c3c);
    vertical-align: middle;
  }

  .dot.big {
    width: 0.75rem;
    height: 0.75rem;
  }

  .bar {
    display: inline-block;
    width: 1.375rem;
    height: 0.1875rem;
    background: rgba(181, 186, 193, 0.6);
    vertical-align: middle;
    border-radius: 0.125rem;
  }

  /* The status line: the bar of the filters, upside down */
  footer {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 1rem;
    align-items: center;
    padding: 0.5rem 1rem;
    background: var(--bg-primary);
    border-top: 1px solid var(--border-subtle);
    font-size: 0.75rem;
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  .spacer {
    flex: 1;
  }

  .warn {
    color: #ffb3b8;
  }

  .exchange {
    color: #f0b232;
    font-weight: 600;
  }

  .live {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.125rem 0.625rem;
    border-radius: var(--radius-full);
    border: 1px solid var(--border-strong);
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-muted);
    font-size: 0.6875rem;
    font-weight: 700;
    white-space: nowrap;
  }

  .live i {
    width: 0.4375rem;
    height: 0.4375rem;
    border-radius: 50%;
    background: var(--text-muted);
  }

  .live.on {
    color: #9de7b7;
    background: rgba(35, 165, 90, 0.14);
    border-color: rgba(35, 165, 90, 0.3);
  }

  .live.on i {
    background: var(--success);
    box-shadow: 0 0 0.375rem var(--success);
  }

  .live.reconnecting i { opacity: 0.35; box-shadow: none; }

  .zoomPad { display: none; }

  @media (max-width: 720px) {
    .mainContent {
      padding-top: calc(3.75rem + env(safe-area-inset-top));
      padding-bottom: calc(4rem + env(safe-area-inset-bottom));      /* the bar of pages at the bottom */
    }

    /* A finger: big buttons, in reach of the thumb, on the right of the map */
    .zoomPad {
      position: absolute;
      right: 0.75rem;
      bottom: 0.75rem;
      z-index: 3;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }

    .zoomBtn {
      width: 3.5rem;
      height: 3.5rem;
      border-radius: 50%;
      border: 1px solid var(--border-strong, rgba(255, 255, 255, 0.2));
      background: color-mix(in srgb, var(--bg-secondary) 92%, transparent);
      color: var(--text-primary);
      font-size: 1.25rem;
      line-height: 1;
      box-shadow: var(--shadow-md);
    }

    .people { right: 0.75rem; justify-content: space-between; }
    .people input { flex: 1; width: auto; min-width: 0; }
    .legend { bottom: 0.75rem; max-width: calc(100% - 5.75rem); }

    /* The card of a person opens as a sheet at the bottom: the map stays visible above it */
    .canvas.with-card { right: 0; bottom: 62%; }
    .zoomPad.with-card { display: none; }
  }

  /* On a phone the legend only keeps its first line: there is nothing to hover with a finger */
  @media (max-width: 608px) {
    .legend {
      font-size: 0.6875rem;
      max-width: calc(100% - 1.75rem);
    }

    .legend div:nth-child(2) {
      display: none;
    }
  }
</style>
