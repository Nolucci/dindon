<script>
  import { onMount, tick } from 'svelte';
  import { api, AuthError, openEvents } from '../lib/api.js';
  import { MapGraph } from '../lib/mapgraph.js';
  import PersonCard from './PersonCard.svelte';
  import ImportPanel from './ImportPanel.svelte';

  let { onLogout } = $props();

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
  let map = null;
  let guilds = $state([]);
  let guild = $state('');
  let preset = $state('all');
  let since = $state('');
  let until = $state('');
  let kinds = $state({ reply: true, mention: true, reaction: true });
  let density = $state('2500'); // how many links to draw at most: the strongest ones first
  let showImport = $state(false); // the window to import a part of the server
  let showIsolated = $state(true); // also the people who wrote and have no link on the map (points on their own)
  let lastExchange = $state(null);
  let exchangeTimer;
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
  const ago = (iso) => {
    if (!iso) return '—';
    const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
    if (seconds < 90) return `il y a ${seconds} s`;
    if (seconds < 5400) return `il y a ${Math.round(seconds / 60)} min`;
    return `il y a ${Math.round(seconds / 3600)} h`;
  };

  // A page that shows the present can be updated live; a page that shows a past period cannot
  let showsPresent = $derived(preset !== 'custom' || !until);

  function graphParams() {
    const params = { guild, kinds: KINDS.filter((k) => kinds[k.id]).map((k) => k.id).join(','), max_edges: density, isolated: showIsolated };
    const days = PRESETS.find((p) => p.id === preset)?.days;
    if (days) params.since = new Date(Date.now() - days * 86400000).toISOString();
    if (preset === 'custom') {
      if (since) params.since = new Date(since).toISOString();
      if (until) params.until = new Date(new Date(until).getTime() + 86400000).toISOString();
    }
    return params;
  }

  async function guard(action) {
    try {
      return await action();
    } catch (error) {
      if (error instanceof AuthError) onLogout();
      else problem = error.message;
      return undefined;
    }
  }

  async function reload() {
    clearTimeout(reloadTimer);
    reloadTimer = null;
    if (!guild || !map) return;
    if (!KINDS.some((k) => kinds[k.id])) return;
    const data = await guard(() => api.graph(graphParams()));
    loading = false;
    if (!data) return;
    problem = '';
    lastReload = Date.now();
    meta = data.meta;
    map.load(data);
    if (selectedId && !map.has(selectedId)) map.select(null);
    for (const event of pendingFlashes.splice(0)) map.flash(event); // exchanges that arrived while the person was not yet on the map
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
    if (event.type === 'edge' && showsPresent && kinds[event.kind]) {
      const label = (id) => map?.labelOf(id) ?? id;
      lastExchange = `${label(event.from)} → ${label(event.to)} · ${{ reply: 'réponse', mention: 'mention', reaction: 'réaction' }[event.kind]}`;
      clearTimeout(exchangeTimer);
      exchangeTimer = setTimeout(() => (lastExchange = null), 7000);
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
    });
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
    scheduleReload(0);
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
</script>

<div class="app">
  <header>
    <strong class="brand">Dindon</strong>
    {#if guilds.length > 1}
      <select bind:value={guild} onchange={filterChanged} aria-label="Serveur">
        {#each guilds as g}<option value={g.id}>{g.name}</option>{/each}
      </select>
    {:else if guilds.length === 1}
      <span class="muted">{guilds[0].name}</span>
    {/if}

    <div class="group" role="group" aria-label="Période">
      {#each PRESETS as p}
        <button aria-pressed={preset === p.id} onclick={() => { preset = p.id; filterChanged(); }}>{p.label}</button>
      {/each}
    </div>
    {#if preset === 'custom'}
      <input type="date" bind:value={since} onchange={filterChanged} aria-label="Du" />
      <input type="date" bind:value={until} onchange={filterChanged} aria-label="Au" />
    {/if}

    <div class="group" role="group" aria-label="Types d’échanges">
      {#each KINDS as k}
        <button aria-pressed={kinds[k.id]} onclick={() => { kinds[k.id] = !kinds[k.id]; filterChanged(); }}>{k.label}</button>
      {/each}
    </div>

    <select bind:value={density} onchange={filterChanged} aria-label="Nombre de liens affichés">
      <option value="800">Liens : essentiels</option>
      <option value="2500">Liens : lisibles</option>
      <option value="8000">Liens : détaillés</option>
      <option value="20000">Liens : tous (lent)</option>
    </select>
    <label class="check" title="Les personnes qui ont déjà écrit mais n’ont aucun lien affiché, quelle que soit la période">
      <input type="checkbox" bind:checked={showIsolated} onchange={isolatedChanged} /> Personnes sans lien
    </label>
    <button onclick={() => map?.resetView()} title="Revenir à la vue d’ensemble">Tout voir</button>

    <div class="search">
      <input type="search" placeholder="Chercher une personne…" bind:value={query} oninput={search} aria-label="Chercher une personne" />
      {#if suggestions.length}
        <ul role="listbox">
          {#each suggestions as person}
            <li><button role="option" aria-selected="false" onclick={() => choose(person)}>{person.label} <span class="muted">{fmt.format(person.messages)}</span></button></li>
          {/each}
        </ul>
      {/if}
    </div>

    <button onclick={() => (showImport = true)} title="Importer l’historique de certains salons, de certaines personnes, d’une période">Importer…</button>
    <button class="quiet" onclick={logout}>Quitter</button>
  </header>

  <div class="banners">
  {#if status?.warnings?.includes('account_token')}
    <p class="banner" role="alert">
      Attention : un <strong>compte personnel</strong> est utilisé en continu pour la collecte. Discord l’interdit et peut fermer ce compte.
      Un bot est recommandé (voir le README).
    </p>
  {/if}
  {#if status?.collector?.needs_backfill?.length}
    <p class="banner info">Le premier import du serveur n’est pas fait : lancez <code>dindon backfill</code>. La surveillance n’exporte rien avant.</p>
  {/if}
  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}
  </div>

  <main>
    <div class="canvas" class:with-card={selectedId} bind:this={container} aria-label="Carte des échanges"></div>

    {#if !loading && !guilds.length}
      <div class="empty">
        <h2>Aucun serveur importé</h2>
        <p class="muted">Déposez un export JSON dans le dossier <code>inbox/</code>, ou lancez <code>dindon backfill</code> avec un jeton.</p>
      </div>
    {:else if !loading && meta && meta.nodes_shown === 0}
      <div class="empty"><h2>Aucun échange sur cette période</h2><p class="muted">Changez de période ou de types d’échanges.</p></div>
    {/if}
    {#if loading}<div class="empty"><p class="muted">Chargement de la carte…</p></div>{/if}

    {#if selectedId}
      <PersonCard {card} loading={cardLoading} error={cardError} onClose={() => { selectPerson(null); }} onPick={pick} />
    {/if}

    <div class="legend" aria-hidden="true">
      <div><span class="dot big"></span> Taille : poids des échanges (les plus petits points n’ont aucun lien affiché) · couleur : activité récente (clair) ou ancienne (sombre)</div>
      <div><span class="bar"></span> Les liens se révèlent en <strong>survolant</strong> ou en <strong>cliquant</strong> une personne ; leur épaisseur est le poids de l’échange{#if meta && !meta.period}&nbsp;(les échanges récents comptent plus, demi-vie {meta.half_life_days} j){/if}</div>
    </div>
  </main>

  {#if showImport}
    <ImportPanel onClose={importClosed} onAuthLost={onLogout} />
  {/if}

  <footer>
    <span class="live" class:on={live}><i></i>{live ? 'En direct' : 'Hors ligne'}</span>
    {#if meta}
      <span>{fmt.format(meta.nodes_shown)} personnes{#if meta.isolated_shown > 0}&nbsp;(dont {fmt.format(meta.isolated_shown)} sans lien{#if meta.isolated_hidden > 0}, + {fmt.format(meta.isolated_hidden)} masquées{/if}){/if}{#if meta.nodes_hidden > 0}&nbsp;(+ {fmt.format(meta.nodes_hidden)} moins connectées, masquées){/if}</span>
      <span>{fmt.format(meta.edges_shown)} liens{#if meta.edges_hidden > 0}&nbsp;(+ {fmt.format(meta.edges_hidden)} plus faibles, masqués){/if}</span>
    {/if}
    {#if newMessages}<span>{fmt.format(newMessages)} nouveaux messages depuis l’ouverture</span>{/if}
    {#if lastExchange}<span class="exchange" aria-live="polite">{lastExchange}</span>{/if}
    {#if lastEventAt}<span class="muted">dernier événement {ago(lastEventAt)}</span>{/if}
    <span class="spacer"></span>
    {#if status?.collector?.enabled}
      <span class="muted">surveillance : relevé {ago(status.collector.last_poll_at)}{#if status.collector.last_error}&nbsp;· <span class="warn">{status.collector.last_error}</span>{/if}</span>
    {:else if status}
      <span class="muted">pas de surveillance : seuls les exports déposés dans inbox/ sont lus</span>
    {/if}
    {#if status?.inbox?.failed}<span class="warn">{status.inbox.failed} fichier(s) illisible(s) dans inbox/failed</span>{/if}
  </footer>
</div>

<style>
  .app { height: 100%; display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; } /* header, banners (maybe none), map, status */
  header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; padding: 8px 12px; background: var(--panel); border-bottom: 1px solid var(--line); }
  .brand { font-size: 18px; letter-spacing: 0.5px; margin-right: 2px; }
  header select { padding: 5px 8px; }
  .group { display: inline-flex; gap: 0; }
  .group button { border-radius: 0; margin-left: -1px; padding: 5px 10px; }
  .group button:first-child { border-radius: 6px 0 0 6px; margin-left: 0; }
  .group button:last-child { border-radius: 0 6px 6px 0; }
  .quiet { background: none; margin-left: auto; color: var(--muted); }
  .check { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 13px; cursor: pointer; user-select: none; }
  .check input { accent-color: #4f8fd1; margin: 0; cursor: pointer; }
  .search { position: relative; }
  .search input { width: 168px; }
  .search ul { position: absolute; top: 100%; left: 0; right: 0; margin: 4px 0 0; padding: 4px; list-style: none; background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px; z-index: 20; }
  .search li button { width: 100%; text-align: left; background: none; border: none; padding: 5px 8px; display: flex; justify-content: space-between; gap: 8px; }
  .search li button:hover { background: #1d3550; }
  .banner { margin: 0; padding: 8px 14px; background: #3a2a14; color: #f1c79a; border-bottom: 1px solid #5a4020; font-size: 14px; }
  .banner.info { background: #14283a; color: #a9cdea; border-color: #204666; }
  main { position: relative; min-height: 0; }
  .canvas { position: absolute; inset: 0; }
  .canvas.with-card { right: min(360px, 100%); } /* the map stays whole, next to the card */
  .empty { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; pointer-events: none; padding: 20px; }
  .empty h2 { margin: 0 0 6px; }
  .legend { position: absolute; left: 14px; bottom: 12px; font-size: 12.5px; color: var(--muted); display: grid; gap: 4px; pointer-events: none; background: rgba(11, 15, 20, 0.72); padding: 8px 10px; border-radius: 8px; max-width: min(420px, 60vw); }
  .dot { display: inline-block; border-radius: 50%; background: hsl(208, 62%, 70%); vertical-align: middle; }
  .dot.big { width: 12px; height: 12px; }
  .dot.bright { width: 9px; height: 9px; background: hsl(208, 62%, 70%); }
  .dot.dim { width: 9px; height: 9px; background: hsl(208, 62%, 36%); }
  .bar { display: inline-block; width: 22px; height: 3px; background: rgba(138, 154, 176, 0.6); vertical-align: middle; border-radius: 2px; }
  footer { display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: center; padding: 6px 14px; background: var(--panel); border-top: 1px solid var(--line); font-size: 13px; }
  .spacer { flex: 1; }
  .warn { color: var(--warn); }
  .exchange { color: #ffe28a; }
  .live { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); }
  .live i { width: 8px; height: 8px; border-radius: 50%; background: #6b3b3b; }
  .live.on { color: var(--ok); }
  .live.on i { background: var(--ok); box-shadow: 0 0 6px var(--ok); }
  code { background: var(--panel-2); padding: 1px 5px; border-radius: 4px; }
</style>
