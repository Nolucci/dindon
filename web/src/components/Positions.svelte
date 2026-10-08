<script>
  import ExportMenu from './ExportMenu.svelte';
  import { onDestroy, untrack } from 'svelte';
  import { api, makeGuard } from '../lib/api.js';
  import { day } from '../lib/format.js';
  import { matches, slash } from '../lib/text.js';

  let { guild, onAuthLost, onAutomate, embedded = false, onUpdate = () => {} } = $props();

  const fmt = new Intl.NumberFormat('fr-FR');
  const STATES = { idle: '', running: 'Lecture en cours…', cancelling: 'Arrêt en cours…', done: 'Terminée', cancelled: 'Annulée', failed: 'Échec' };
  const STANCE = { 1: ['Pour', 'success'], 0: ['Nuancé', ''], '-1': ['Contre', 'danger'] };
  const dayOrNothing = (iso) => day(iso, '');

  let data = $state(null);        // /api/positions
  let info = $state(null);        // /api/analysis (ready, job)
  let opened = $state(null);      // { id, loading, people }
  let problem = $state('');
  // The choice of the batches (« étapes ») is kept in this browser, so that a reload does not undo it
  const SALVO_KEY = 'dindon.salvo';
  const saved = (() => { try { return JSON.parse(localStorage.getItem(SALVO_KEY) ?? '{}') ?? {}; } catch { return {}; } })();
  let perBatch = $state(saved.perBatch ?? 40);         // conversations read in each batch ("étape")
  let batches = $state(saved.batches ?? 1);            // how many batches
  let untilEnd = $state(saved.untilEnd === true);      // keep going until nothing is left to read
  $effect(() => {
    const value = JSON.stringify({ perBatch, batches, untilEnd });
    try { localStorage.setItem(SALVO_KEY, value); } catch { /* storage refused: the choice is only kept until the reload */ }
  });
  let busy = $state(false);
  let controlsOpen = $state(false);
  $effect(() => { if (running) controlsOpen = true; });
  let poll = null;

  // Search and filters: asked of the server (it knows the names of the people who take each position)
  let q = $state('');
  let themeFilter = $state('');
  let stanceFilter = $state('');
  let sort = $state('people');
  let personQ = $state('');          // inside an open proposition: narrow the people
  let showRejected = $state(false);
  let themes = $state([]);           // for the menu: all the themes, whatever the filter
  const filtering = $derived(q.trim() !== '' || themeFilter !== '' || stanceFilter !== '');
  let timer = null;
  let offset = $state(0);
  const pageSize = 50;
  let listLoading = $state(false);
  let listRequest = 0;
  let newAxis = $state('');          // adding a link to an axis
  let newPole = $state('1');
  let newStrength = $state('1');
  const catalog = $derived(data?.axes_catalog ?? []);
  const strengthWord = (loading) => (Math.abs(loading) >= 0.8 ? 'forte' : 'moyenne');

  const job = $derived(info?.job);
  const running = $derived(job?.state === 'running' || job?.state === 'cancelling');
  const ready = $derived(info?.ready);
  const missing = $derived(ready?.ollama ? Object.entries(ready.models).filter(([, there]) => !there).map(([name]) => name) : []);
  const remaining = $derived(data ? data.conversations.kept - data.conversations.read : 0);
  const canStart = $derived(!running && ready?.ollama && missing.length === 0 && remaining > 0);

  const guard = makeGuard(() => onAuthLost(), (message) => (problem = message));

  const filters = () => ({ offset, limit: pageSize, q: q.trim() || undefined, theme: themeFilter || undefined, stance: stanceFilter || undefined, sort,
    rejected: showRejected ? 'true' : undefined });

  async function load() {
    const server = guild;
    const current = ++listRequest;
    const [d, i] = await Promise.all([guard(() => api.positions(guild, filters())), guard(() => api.analysis(guild))]);
    if (server !== guild || current !== listRequest) return null;
    listLoading = false;
    if (d) {
      data = d;
      themes = d.themes;
      onUpdate();
    }
    if (i) info = i;
    if (d && i) problem = '';
    return i;
  }

  function stopPolling() {
    clearInterval(poll);
    poll = null;
  }

  function startPolling() {
    if (poll) return;
    poll = setInterval(async () => {
      const i = await load();
      if (i && !['running', 'cancelling'].includes(i.job.state)) stopPolling();
    }, 2500);
  }

  $effect(() => {
    if (!guild) return;
    opened = null;
    offset = 0;
    data = null;
    (async () => {
      await untrack(load);
      if (running) startPolling();
    })();
  });
  onDestroy(() => {
    stopPolling();
    clearTimeout(timer);
  });

  // The list follows what is typed, a moment after the last key
  async function loadList() {
    const current = ++listRequest;
    const server = guild;
    listLoading = true;
    const d = await guard(() => api.positions(server, filters()));
    if (current !== listRequest || server !== guild) return;
    listLoading = false;
    if (d) {
      data = d;
      if (!d.propositions.some((p) => p.id === opened?.id)) opened = null;
    }
  }
  function changed() {
    offset = 0;
    clearTimeout(timer);
    timer = setTimeout(loadList, 250);
  }
  async function changePage(next) {
    offset = next;
    opened = null;
    await loadList();
    document.getElementById('positions-results')?.scrollIntoView({ block: 'start' });
  }

  function reset() {
    q = '';
    themeFilter = '';
    stanceFilter = '';
    changed();
  }

  async function start() {
    busy = true;
    const body = { guild, stages: ['claims'], limit: Math.max(1, Math.floor(Number(perBatch)) || 1), rounds: untilEnd ? null : Math.max(1, Math.floor(Number(batches)) || 1) };
    const answer = await guard(() => api.analysisStart(body));
    busy = false;
    if (answer) {
      await load();
      startPolling();
    }
  }

  async function cancel() {
    await guard(() => api.analysisCancel());
    load();
  }

  async function toggle(proposition) {
    if (opened?.id === proposition.id) {
      opened = null;
      return;
    }
    personQ = '';
    opened = { id: proposition.id, loading: true, people: [], axes: [] };
    const detail = await guard(() => api.positionsProposition(proposition.id, guild));
    if (opened?.id === proposition.id) opened = { id: proposition.id, loading: false, people: detail?.people ?? [], axes: detail?.axes ?? [] };
  }

  // The propositions under their theme (the one of the conversations where they were read), the busiest theme first
  const groups = $derived.by(() => {
    const by = new Map();
    for (const p of data?.propositions ?? []) {
      const key = p.theme_id ?? 0;
      if (!by.has(key)) by.set(key, { key, theme: p.theme ?? 'Sans thème', items: [], people: 0 });
      const g = by.get(key);
      g.items.push(p);
      g.people += p.people;
    }
    return [...by.values()];
  });

  // The axes that a proposition moves someone on: the model proposes them, a person validates, corrects or removes them
  async function saveLinks(links) {
    const answer = await guard(() => api.positionsLinks(opened.id, guild, links));
    if (answer) {
      opened = { ...opened, axes: answer.axes };
      refreshCounts();
    }
  }

  const asLinks = (axes) => axes.map((l) => ({ axis: l.axis, loading: l.loading }));
  const flip = (axis) => saveLinks(asLinks(opened.axes).map((l) => (l.axis === axis ? { ...l, loading: -l.loading } : l)));
  const drop = (axis) => saveLinks(asLinks(opened.axes).filter((l) => l.axis !== axis));
  const add = () => {
    if (!newAxis) return;
    const rest = asLinks(opened.axes).filter((l) => l.axis !== newAxis);
    saveLinks([...rest, { axis: newAxis, loading: Number(newPole) * Number(newStrength) }]);
    newAxis = '';
  };

  async function validateLinks() {
    const answer = await guard(() => api.positionsValidateLinks(opened.id, guild));
    if (answer) {
      opened = { ...opened, axes: answer.axes };
      refreshCounts();
    }
  }

  async function onlyValidated(value) {
    const answer = await guard(() => api.positionsOnlyValidated(value, guild));
    if (answer) refreshCounts();
  }

  async function review(rejected) {
    if (!opened) return;
    const answer = await guard(() => api.positionsReview(opened.id, guild, rejected));
    if (answer) {
      opened = null;
      await load();
    }
  }

  async function refreshCounts() {
    const d = await guard(() => api.positions(guild, filters()));
    if (d) data = { ...data, axes_links: d.axes_links };
  }

  const share = (p, key) => (p.people ? (100 * p[key]) / p.people : 0);
</script>

<div class="page" class:embedded>
  {#if !embedded}
  <header>
    <h1>Positions</h1>
    <p class="subtitle">
      Lisez les conversations, puis ouvrez une proposition pour vérifier qui est pour ou contre et retrouver les citations.
    </p>
  </header>
  {/if}

  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  {#if !guild}
    <section class="panel card"><p class="muted">Aucun serveur n’est encore importé.</p></section>
  {:else}
    <section id="positions-results" aria-label="Propositions" aria-busy={listLoading}>
      <div class="toolbar" role="search" aria-label="Chercher dans les propositions">
        <input class="field-input" type="search" placeholder="Proposition ou personne…" bind:value={q} oninput={changed} aria-label="Chercher une proposition ou une personne" use:slash />
        <select class="select" bind:value={themeFilter} onchange={changed} aria-label="Filtrer par thème">
          <option value="">Tous les thèmes</option>
          {#each themes as t (t.id ?? 0)}<option value={t.id ?? '0'}>{t.label} ({t.propositions})</option>{/each}
        </select>
        <select class="select" bind:value={stanceFilter} onchange={changed} aria-label="Filtrer par position">
          <option value="">Toutes les positions</option>
          <option value="for">Avec des « pour »</option>
          <option value="against">Avec des « contre »</option>
          <option value="nuanced">Avec des « nuancé »</option>
        </select>
        <select class="select" bind:value={sort} onchange={changed} aria-label="Trier">
          <option value="people">Les plus partagées</option>
          <option value="divided">Les plus clivantes</option>
          <option value="recent">Les plus récentes</option>
        </select>
        {#if filtering}<button type="button" class="tool-btn reset" onclick={reset}>Effacer les filtres</button>{/if}
        <ExportMenu {guild} part="positions" />
        <span class="found" aria-live="polite">{data ? fmt.format(data.matching) : '—'} proposition{(data?.matching ?? 0) > 1 ? 's' : ''}{filtering ? ` sur ${data?.propositions_total ?? 0}` : ''}</span>
      </div>
      <label class="check"><input type="checkbox" bind:checked={showRejected} onchange={changed} /> Voir aussi les propositions écartées</label>
      {#if data && !data.propositions.length && filtering}
        <p class="muted empty">Aucune proposition ne correspond.</p>
      {:else if data && !data.propositions.length}
        <p class="muted empty">Aucune position pour l’instant. Ouvrez « Analyse et réglages » pour lancer une analyse.</p>
      {/if}
      {#each groups as group (group.key)}
        <h3 class="theme">{group.theme} <span class="count">{group.items.length} proposition{group.items.length > 1 ? 's' : ''} · {group.people} positions</span></h3>
        <ul class="list">
          {#each group.items as p (p.id)}
            <li class="panel prop" class:open={opened?.id === p.id}>
              <button class="row" type="button" aria-expanded={opened?.id === p.id} onclick={() => toggle(p)}>
                <span class="text">{p.text}</span>
                <span class="bar" role="img" aria-label="{p.for} pour, {p.nuanced} nuancés, {p.against} contre">
                  <span class="seg for" style="width: {share(p, 'for')}%"></span><span class="seg mid" style="width: {share(p, 'nuanced')}%"></span><span class="seg against" style="width: {share(p, 'against')}%"></span>
                </span>
                <span class="nums">{p.for} pour · {p.nuanced} nuancés · {p.against} contre</span>
              </button>
              {#if opened?.id === p.id}
                <div class="people">
                  {#if opened.loading}<p class="muted">Chargement…</p>{/if}
                  {#if opened.people.length > 4}
                    <input class="field-input" type="search" placeholder="Chercher une personne ou un rôle dans cette proposition" bind:value={personQ} aria-label="Chercher une personne dans cette proposition" />
                  {/if}
                  {#each opened.people.filter((w) => matches(personQ, w.label, w.roles.join(' '), w.evidence.map((e) => e.quote).join(' '))) as who (who.id)}
                    <article class="person">
                      <header>
                        <strong>{who.label}</strong>
                        <span class="badge small" class:success={who.stance === 1} class:danger={who.stance === -1}>{STANCE[who.stance][0]}</span>
                        {#each who.roles as role}<span class="role">{role}</span>{/each}
                        <details class="confidence"><summary>Estimation</summary><span class="muted small">Confiance estimée : {Math.round(who.confidence * 100)} %</span></details>
                      </header>
                      {#each who.evidence as e}
                        <blockquote>« {e.quote} » <span class="muted small">— #{e.channel}, {dayOrNothing(e.at)}</span></blockquote>
                      {/each}
                    </article>
                  {/each}
                  {#if !opened.loading}<details class="reviewDetails"><summary>Réviser la proposition et ses axes</summary>                    <div class="review">
                      {#if p.status === 'rejected'}
                        <span class="badge small">Écartée des résultats et des scores</span>
                        <button type="button" class="btn" onclick={() => review(false)}>Rétablir</button>
                      {:else if p.status === 'proposed'}
                        <button type="button" class="btn btn-danger" onclick={() => review(true)}>Écarter cette proposition</button>
                      {/if}
                    </div>
                    <section class="links" aria-label="Axes de cette proposition">
                      <h4 class="eyebrow">Axes associés</h4>
                      {#each opened.axes as l (l.axis)}
                        <div class="link">
                          <span class="linkName">{l.name}</span>
                          <span class="muted small">vers</span> <strong>{l.toward}</strong> <span class="muted small">({strengthWord(l.loading)})</span>
                          <span class="badge small" class:success={l.validated}>{l.validated ? 'validé' : 'proposé par l’IA'}</span>
                          <button type="button" class="tool-btn" onclick={() => flip(l.axis)}>Inverser</button>
                          <button type="button" class="tool-btn" onclick={() => drop(l.axis)}>Retirer</button>
                        </div>
                      {:else}
                        <p class="muted small">Aucun axe : cette proposition ne pèse sur aucun axe.</p>
                      {/each}
                      <div class="add">
                        <select class="select" bind:value={newAxis} aria-label="Ajouter un axe">
                          <option value="">Ajouter un axe…</option>
                          {#each catalog as a}<option value={a.code}>{a.name}</option>{/each}
                        </select>
                        {#if newAxis}
                          {@const chosen = catalog.find((a) => a.code === newAxis)}
                          <select class="select" bind:value={newPole} aria-label="Pôle">
                            <option value="-1">vers {chosen.negative_pole}</option>
                            <option value="1">vers {chosen.positive_pole}</option>
                          </select>
                          <select class="select" bind:value={newStrength} aria-label="Force">
                            <option value="1">forte</option>
                            <option value="0.6">moyenne</option>
                          </select>
                          <button type="button" class="btn" onclick={add}>Ajouter</button>
                        {/if}
                        {#if opened.axes.some((l) => !l.validated)}
                          <button type="button" class="btn btn-primary" onclick={validateLinks}>Valider ces liens</button>
                        {/if}
                      </div>
                    </section></details>{/if}
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {/each}
      {#if data && data.matching > pageSize}
        <nav class="pagination" aria-label="Pages des propositions">
          <button type="button" class="btn" disabled={offset === 0 || listLoading} onclick={() => changePage(Math.max(0, offset - pageSize))}>Précédent</button>
          <span aria-live="polite">{offset + 1}–{offset + data.propositions.length} sur {fmt.format(data.matching)}</span>
          <button type="button" class="btn" disabled={offset + pageSize >= data.matching || listLoading} onclick={() => changePage(offset + pageSize)}>Suivant</button>
        </nav>
      {/if}
    </section>
    <details class="panel card" bind:open={controlsOpen} aria-label="Lecture"><summary>Analyse et réglages</summary>
      <div class="head">
        <span class="eyebrow">Lecture</span>
        {#if !info}<span class="muted">Chargement…</span>
        {:else if !ready.ollama}<span class="badge danger">Analyse indisponible</span>
        {:else if missing.length}<span class="badge danger">Modèle à installer</span>
        {:else}<span class="badge success">Analyse disponible</span>{/if}
      </div>
      {#if info && !ready.ollama}<p class="banner">Ollama n’est pas joignable : {ready.problem}</p>{/if}
      {#if info && ready.ollama && missing.length}<p class="banner">Il manque : {#each missing as name}<code>ollama pull {name}</code> {/each}</p>{/if}

      {#if data}
        <dl class="counts">
          <div class="metric"><dt>Conversations lues</dt><dd>{fmt.format(data.conversations.read)} <span class="unit">/ {fmt.format(data.conversations.kept)}</span></dd></div>
          <div class="metric"><dt>Personnes</dt><dd>{fmt.format(data.claims.people)}</dd></div>
          <div class="metric"><dt>Positions retenues</dt><dd>{fmt.format(data.claims.positions)}</dd></div>
          <div class="metric"><dt>Propositions</dt><dd>{fmt.format(data.propositions_total)}</dd></div>
        </dl>
        <div class="actions">
          {#if running}
            <button class="btn btn-danger" onclick={cancel} disabled={job.state === 'cancelling'}>Arrêter la lecture</button>
          {:else}
            <button class="btn btn-primary" onclick={start} disabled={!canStart || busy}>Analyser les conversations restantes</button>
          {/if}
          <button type="button" class="btn" onclick={onAutomate}>Automatiser les prochaines lectures</button>

        </div>
        <p class="muted hint">{fmt.format(remaining)} conversation{remaining > 1 ? 's' : ''} restante{remaining > 1 ? 's' : ''}. Les conversations déjà lues ne sont pas relues.</p>
        <details class="advanced"><summary>Options de lecture</summary>      {#if data?.axes_links?.total}
        <label class="check" title="Les liens que personne n'a relus sont ignorés dans les scores des personnes">
          <input type="checkbox" checked={data.axes_links.only_validated} onchange={(e) => onlyValidated(e.currentTarget.checked)} />
          <span>Ne compter dans les scores que les liens validés ({data.axes_links.validated} sur {data.axes_links.total})</span>
        </label>
      {/if}

          <label class="inline">Conversations par étape
            <input class="field-input num" type="number" min="1" max="100000" step="1" bind:value={perBatch} aria-label="Nombre de conversations lues par étape" />
          </label>
          <label class="inline">Nombre d’étapes
            <input class="field-input num" type="number" min="1" max="10000" step="1" bind:value={batches} disabled={untilEnd} aria-label="Nombre d’étapes" />
          </label>
          <label class="check"><input type="checkbox" bind:checked={untilEnd} /> <span>Continuer jusqu’à la fin ({fmt.format(remaining)} restantes)</span></label>
          <p class="muted hint">Après chaque étape, les positions sont vérifiées et reliées aux axes : les contradictions apparaissent au fur et à mesure.
            {untilEnd ? 'Toutes les conversations restantes seront lues.' : `Jusqu’à ${fmt.format(Math.max(1, Math.floor(Number(perBatch)) || 1) * Math.max(1, Math.floor(Number(batches)) || 1))} conversations.`}</p>
          <p class="muted hint">Environ 15 s par conversation. {fmt.format(data.claims.refused)} position{data.claims.refused > 1 ? 's' : ''} refusée{data.claims.refused > 1 ? 's' : ''} faute de preuve. Modèle : <code>{info?.models.naming}</code>. Les ordinateurs d’analyse ajoutés dans Système peuvent recevoir le texte nécessaire au calcul.</p>
        </details>
        {#if job && job.state !== 'idle'}
          <div class="progress" aria-live="polite">
            <span class="badge" class:success={job.state === 'done'} class:danger={job.state === 'failed'} class:accent={running}>{STATES[job.state]}</span>
            {#if running && job.round && (job.rounds !== 1)}<span class="muted">étape {job.round}{job.rounds ? ` / ${job.rounds}` : ''}</span>{/if}
            {#if running && job.of}<progress max={job.of} value={job.done}></progress><span class="muted">{job.done} / {job.of}</span>{/if}
            {#if job.error}<p class="banner" role="alert">{job.error}</p>{/if}
            {#if job.lines.length}<details class="jobLog"><summary>Journal de lecture</summary><pre class="lines">{job.lines.join('\n')}</pre></details>{/if}
          </div>
        {/if}
      {/if}
    </details>

  {/if}
</div>

<style>
  .pagination { display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: .75rem; padding: 1rem 0; }
  .reviewDetails { margin-top: .75rem; padding-top: .5rem; border-top: 1px solid var(--border-subtle); }
  #positions-results { scroll-margin-top: 5rem; }
  .page { flex: 1; min-height: 0; overflow-y: auto; padding: 1.5rem clamp(1rem, 3vw, 2.5rem) 2.5rem; display: flex; flex-direction: column; gap: 1.25rem; animation: fadeIn var(--transition-slow) both; }
  .page.embedded { flex: none; min-height: auto; overflow: visible; padding: 0; animation: none; }
  h1 { font-size: clamp(1.5rem, 2vw, 1.9rem); line-height: 1.1; font-weight: 700; color: var(--text-primary); }
  .subtitle { max-width: 68ch; margin-top: 0.5rem; color: var(--text-secondary); }
  .card { padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  .counts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 8rem), 1fr)); gap: 0.625rem; }
  .metric { display: flex; flex-direction: column; gap: 0.25rem; padding: 0.75rem 0.875rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); }
  .metric dt { font-size: 0.6875rem; font-weight: 700; letter-spacing: normal; text-transform: none; color: var(--text-muted); }
  .metric dd { font-size: 1.25rem; font-weight: 700; color: var(--text-primary); font-variant-numeric: tabular-nums; }
  .unit { font-size: 0.8rem; font-weight: 500; color: var(--text-muted); }
  .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; }
  .inline { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; font-size: 0.8125rem; color: var(--text-secondary); }
  .hint { font-size: 0.75rem; }
  .advanced .inline { margin-top: 0.75rem; margin-right: 1rem; }
  .num { width: 6rem; }
  .advanced .check { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem; font-size: 0.8125rem; color: var(--text-secondary); }
  .advanced .hint { margin-top: 0.5rem; }
  .jobLog { flex-basis: 100%; }
  .jobLog .lines { margin-top: 0.5rem; }
  .progress { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; }
  .progress progress { flex: 1 1 12rem; }
  .lines { flex-basis: 100%; max-height: 9rem; overflow: auto; padding: 0.625rem 0.75rem; border-radius: var(--radius-md); background: var(--bg-tertiary); font-size: 0.75rem; color: var(--text-secondary); white-space: pre-wrap; }
  .count { margin-left: 0.375rem; color: var(--text-muted); font-weight: 400; }
  .theme { margin-top: 1rem; font-size: 1rem; font-weight: 700; color: var(--text-primary); }
  .list { list-style: none; display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem; }
  .prop { padding: 0; overflow: hidden; }
  .row { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) 11rem; gap: 0.25rem 1rem; align-items: center; padding: 0.75rem 1rem; background: none; border: none; text-align: left; color: inherit; font: inherit; cursor: pointer; }
  .row:hover { background: var(--surface-control); }
  .text { color: var(--text-primary); font-weight: 600; }
  .bar { display: flex; height: 0.5rem; border-radius: 999px; overflow: hidden; background: var(--bg-tertiary); }
  .seg.for { background: var(--success); }
  .seg.mid { background: var(--text-muted); }
  .seg.against { background: var(--danger); }
  .nums { grid-column: 1 / -1; font-size: 0.75rem; color: var(--text-muted); }
  .people { display: flex; flex-direction: column; gap: 0.625rem; padding: 0.25rem 1rem 1rem; border-top: 1px solid var(--border-subtle); }
  .person { display: flex; flex-direction: column; gap: 0.25rem; padding-top: 0.625rem; }
  .person header { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
  .role { padding: 0.0625rem 0.5rem; border-radius: 999px; border: 1px solid var(--border-subtle); font-size: 0.6875rem; color: var(--text-secondary); }
  blockquote { margin: 0; padding: 0.375rem 0.75rem; border-left: 3px solid var(--border-strong, var(--border-subtle)); color: var(--text-secondary); font-size: 0.875rem; line-height: 1.5; }
  .small { font-size: 0.75rem; }
  .links { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.75rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); }
  .link { display: flex; flex-wrap: wrap; align-items: center; gap: 0.375rem 0.5rem; font-size: 0.8125rem; color: var(--text-secondary); }
  .linkName { font-weight: 600; color: var(--text-primary); }
  .add { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
  .badge.small { min-height: 1.5rem; font-size: 0.6875rem; }
  @media (max-width: 720px) { .page { padding: 1rem 1rem 2rem; } .row { grid-template-columns: 1fr; } }
</style>
