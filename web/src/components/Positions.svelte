<script>
  import { onDestroy } from 'svelte';
  import { api, makeGuard } from '../lib/api.js';
  import { day } from '../lib/format.js';
  import { matches, slash } from '../lib/text.js';

  let { guild, onAuthLost } = $props();

  const fmt = new Intl.NumberFormat('fr-FR');
  const STATES = { idle: '', running: 'Lecture en cours…', cancelling: 'Arrêt en cours…', done: 'Terminée', cancelled: 'Annulée', failed: 'Échec' };
  const STANCE = { 1: ['Pour', 'success'], 0: ['Nuancé', ''], '-1': ['Contre', 'danger'] };
  const dayOrNothing = (iso) => day(iso, '');

  let data = $state(null);        // /api/positions
  let info = $state(null);        // /api/analysis (ready, job)
  let opened = $state(null);      // { id, loading, people }
  let problem = $state('');
  let amount = $state('40');
  let busy = $state(false);
  let poll = null;

  // Search and filters: asked of the server (it knows the names of the people who take each position)
  let q = $state('');
  let themeFilter = $state('');
  let stanceFilter = $state('');
  let sort = $state('people');
  let personQ = $state('');          // inside an open proposition: narrow the people
  let themes = $state([]);           // for the menu: all the themes, whatever the filter
  const filtering = $derived(q.trim() !== '' || themeFilter !== '' || stanceFilter !== '');
  let timer = null;
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

  const filters = () => ({ q: q.trim() || undefined, theme: themeFilter || undefined, stance: stanceFilter || undefined, sort });

  async function load() {
    const [d, i] = await Promise.all([guard(() => api.positions(guild, filters())), guard(() => api.analysis(guild))]);
    if (d) {
      data = d;
      if (!filtering) themes = d.themes;
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
    (async () => {
      await load();
      if (running) startPolling();
    })();
  });
  onDestroy(() => {
    stopPolling();
    clearTimeout(timer);
  });

  // The list follows what is typed, a moment after the last key
  function changed() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const d = await guard(() => api.positions(guild, filters()));
      if (d) {
        data = d;
        if (!d.propositions.some((p) => p.id === opened?.id)) opened = null;      // a proposition that was opened in the meantime stays open
      }
    }, 250);
  }

  function reset() {
    q = '';
    themeFilter = '';
    stanceFilter = '';
    changed();
  }

  async function start() {
    busy = true;
    const body = { guild, stages: ['claims'], limit: amount === 'all' ? null : Number(amount) };
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
    return [...by.values()].sort((a, b) => b.people - a.people);
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

  async function refreshCounts() {
    const d = await guard(() => api.positions(guild, filters()));
    if (d) data = { ...data, axes_links: d.axes_links };
  }

  const share = (p, key) => (p.people ? (100 * p[key]) / p.people : 0);
</script>

<div class="page">
  <header>
    <h1>Positions</h1>
    <p class="subtitle">
      Ce qu’un modèle local lit des positions de chaque personne, conversation par conversation, <strong>avec la citation qui le prouve</strong>.
      Une position sans citation exacte, écrite par la personne elle-même, est refusée par le programme. C’est une lecture, pas un verdict : jugez-la sur les citations.
    </p>
  </header>

  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  {#if !guild}
    <section class="panel card"><p class="muted">Aucun serveur n’est encore importé.</p></section>
  {:else}
    <section class="panel card" aria-label="Lecture">
      <div class="head">
        <span class="eyebrow">Lecture</span>
        {#if !info}<span class="muted">Chargement…</span>
        {:else if !ready.ollama}<span class="badge danger">Ollama ne répond pas</span>
        {:else if missing.length}<span class="badge danger">Modèle à installer</span>
        {:else}<span class="badge success">Ollama prêt</span>{/if}
      </div>
      {#if info && !ready.ollama}<p class="banner">Ollama n’est pas joignable : {ready.problem}</p>{/if}
      {#if info && ready.ollama && missing.length}<p class="banner">Il manque : {#each missing as name}<code>ollama pull {name}</code> {/each}</p>{/if}

      {#if data}
        <dl class="counts">
          <div class="metric"><dt>Conversations lues</dt><dd>{fmt.format(data.conversations.read)} <span class="unit">/ {fmt.format(data.conversations.kept)}</span></dd></div>
          <div class="metric"><dt>Personnes</dt><dd>{fmt.format(data.claims.people)}</dd></div>
          <div class="metric"><dt>Positions retenues</dt><dd>{fmt.format(data.claims.positions)}</dd></div>
          <div class="metric"><dt>Propositions</dt><dd>{fmt.format(data.propositions_total)}</dd></div>
          <div class="metric"><dt>Refusées (sans preuve)</dt><dd>{fmt.format(data.claims.refused)}</dd></div>
        </dl>
        <div class="actions">
          {#if running}
            <button class="btn btn-danger" onclick={cancel} disabled={job.state === 'cancelling'}>Arrêter la lecture</button>
          {:else}
            <button class="btn btn-primary" onclick={start} disabled={!canStart || busy}>Lire les positions</button>
            <label class="inline">Combien de conversations
              <select class="select" bind:value={amount} aria-label="Combien de conversations lire">
                <option value="20">20 les plus importantes</option>
                <option value="40">40 les plus importantes</option>
                <option value="150">150 les plus importantes</option>
                <option value="all">toutes ({fmt.format(remaining)})</option>
              </select>
            </label>
          {/if}
          <span class="muted hint">Modèle : <code>{info?.models.naming}</code>, environ 15 s par conversation. Rien ne sort de cette machine. Ce qui est lu n’est pas relu.</span>
        </div>
        {#if job && job.state !== 'idle'}
          <div class="progress" aria-live="polite">
            <span class="badge" class:success={job.state === 'done'} class:danger={job.state === 'failed'} class:accent={running}>{STATES[job.state]}</span>
            {#if running && job.of}<progress max={job.of} value={job.done}></progress><span class="muted">{job.done} / {job.of}</span>{/if}
            {#if job.error}<p class="banner" role="alert">{job.error}</p>{/if}
            {#if job.lines.length}<pre class="lines">{job.lines.join('\n')}</pre>{/if}
          </div>
        {/if}
      {/if}
    </section>

    <section aria-label="Propositions">
      <h2 class="eyebrow">Propositions <span class="count">{data?.propositions.length ?? 0}</span></h2>
      <div class="toolbar" role="search" aria-label="Chercher dans les propositions">
        <input class="field-input" type="search" placeholder="Chercher une proposition ou une personne… (/)" bind:value={q} oninput={changed} aria-label="Chercher une proposition ou une personne" use:slash />
        <select class="select" bind:value={themeFilter} onchange={changed} aria-label="Filtrer par thème">
          <option value="">Tous les thèmes</option>
          {#each themes as t (t.id ?? 0)}<option value={t.id ?? ''} disabled={t.id === null}>{t.label} ({t.propositions})</option>{/each}
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
        <span class="found" aria-live="polite">{data?.matching ?? 0} proposition{(data?.matching ?? 0) > 1 ? 's' : ''}{filtering ? ` sur ${data?.propositions_total ?? 0}` : ''}</span>
      </div>
      {#if data && !data.propositions.length && filtering}
        <p class="muted empty">Aucune proposition ne correspond.</p>
      {:else if data && !data.propositions.length}
        <p class="muted empty">Aucune position lue pour l’instant. Lancez la lecture (elle suppose que les conversations et leurs vecteurs ont été faits : page <strong>Thèmes</strong>).</p>
      {/if}
      {#if data?.axes_links?.total}
        <label class="check" title="Les liens que personne n'a relus sont ignorés dans les scores des personnes">
          <input type="checkbox" checked={data.axes_links.only_validated} onchange={(e) => onlyValidated(e.currentTarget.checked)} />
          <span>Ne compter dans les scores que les liens validés ({data.axes_links.validated} sur {data.axes_links.total})</span>
        </label>
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
                  {#if !opened.loading}
                    <section class="links" aria-label="Axes de cette proposition">
                      <h4 class="eyebrow">Axes sur lesquels être d’accord avec cette proposition déplace quelqu’un</h4>
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
                    </section>
                  {/if}
                  {#if opened.people.length > 4}
                    <input class="field-input" type="search" placeholder="Chercher une personne ou un rôle dans cette proposition" bind:value={personQ} aria-label="Chercher une personne dans cette proposition" />
                  {/if}
                  {#each opened.people.filter((w) => matches(personQ, w.label, w.roles.join(' '), w.evidence.map((e) => e.quote).join(' '))) as who (who.id)}
                    <article class="person">
                      <header>
                        <strong>{who.label}</strong>
                        <span class="badge small" class:success={who.stance === 1} class:danger={who.stance === -1}>{STANCE[who.stance][0]}</span>
                        {#each who.roles as role}<span class="role">{role}</span>{/each}
                        <span class="muted small">confiance {Math.round(who.confidence * 100)} %</span>
                      </header>
                      {#each who.evidence as e}
                        <blockquote>« {e.quote} » <span class="muted small">— #{e.channel}, {dayOrNothing(e.at)}</span></blockquote>
                      {/each}
                    </article>
                  {/each}
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {/each}
      {#if data && data.propositions_total > data.propositions.length}<p class="muted small">Les {data.propositions.length} plus partagées sur {data.propositions_total}.</p>{/if}
    </section>
  {/if}
</div>

<style>
  .page { flex: 1; min-height: 0; overflow-y: auto; padding: 1.5rem 1.75rem 2.5rem; display: flex; flex-direction: column; gap: 1.25rem; animation: fadeIn var(--transition-slow) both; }
  h1 { font-size: clamp(1.5rem, 2vw, 1.9rem); line-height: 1.1; font-weight: 700; color: var(--text-primary); }
  .subtitle { max-width: 68ch; margin-top: 0.5rem; color: var(--text-secondary); }
  .subtitle strong { color: var(--text-primary); }
  .card { padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  .counts { display: grid; grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr)); gap: 0.625rem; }
  .metric { display: flex; flex-direction: column; gap: 0.25rem; padding: 0.75rem 0.875rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); }
  .metric dt { font-size: 0.6875rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-muted); }
  .metric dd { font-size: 1.25rem; font-weight: 700; color: var(--text-primary); font-variant-numeric: tabular-nums; }
  .unit { font-size: 0.8rem; font-weight: 500; color: var(--text-muted); }
  .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; }
  .inline { display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.8125rem; color: var(--text-secondary); }
  .hint { font-size: 0.75rem; }
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
