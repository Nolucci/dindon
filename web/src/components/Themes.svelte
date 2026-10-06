<script>
  import { onDestroy } from 'svelte';
  import { api, makeGuard } from '../lib/api.js';
  import { day } from '../lib/format.js';
  import { matches, slash } from '../lib/text.js';

  let { guild, onAuthLost, onAutomate, embedded = false, onUpdate = () => {} } = $props();

  const fmt = new Intl.NumberFormat('fr-FR');
  const STATES = { idle: '', running: 'En cours…', cancelling: 'Arrêt en cours…', done: 'Terminée', cancelled: 'Annulée', failed: 'Échec' };

  let info = $state(null);        // /api/analysis: ready, job, models, counts, last_run
  let topics = $state([]);
  let loaded = $state(false);
  let problem = $state('');
  let fixedTopics = $state('');   // the number of topics, when the person wants to choose it
  let showRejected = $state(false);
  let editing = $state(null);     // { id, label, description }
  let merging = $state(null);     // { id, into }
  let busy = $state(false);
  let selected = $state([]);
  let poll = null;

  const job = $derived(info?.job);
  const running = $derived(job?.state === 'running' || job?.state === 'cancelling');
  let q = $state('');              // search: the name, the description, the keywords
  let statusFilter = $state('all'); // all | proposed | validated | rejected
  let sort = $state('size');        // size | recent | name
  const order = (a, b) => (sort === 'name' ? a.label.localeCompare(b.label, 'fr') : sort === 'recent' ? (b.last_at ?? '').localeCompare(a.last_at ?? '') : b.conversations - a.conversations);
  const seen = $derived(topics.filter((t) => matches(q, t.label, t.description, t.keywords.join(' ')) && (statusFilter === 'all' || t.status === statusFilter)).sort(order));
  const proposed = $derived(seen.filter((t) => t.status === 'proposed'));
  const validated = $derived(seen.filter((t) => t.status === 'validated'));
  const rejected = $derived(seen.filter((t) => t.status === 'rejected'));
  const filtering = $derived(q.trim() !== '' || statusFilter !== 'all');
  const ready = $derived(info?.ready);
  const missing = $derived(ready?.ollama ? Object.entries(ready.models).filter(([, there]) => !there).map(([name]) => name) : []);
  const canStart = $derived(!running && ready?.ollama && missing.length === 0 && (info?.counts.messages ?? 0) > 0);

  const guard = makeGuard(() => onAuthLost(), (message) => (problem = message));

  async function refresh() {
    const answer = await guard(() => api.analysis(guild));
    if (answer) {
      info = answer;
      problem = '';
    }
    return answer;
  }

  async function loadTopics() {
    const list = await guard(() => api.topics(guild, showRejected));
    if (list) {
      topics = list;
      selected = selected.filter((id) => list.some((t) => t.id === id && t.status === 'proposed'));
    }
    loaded = true;
    onUpdate();
  }

  function startPolling() {
    if (poll) return;
    poll = setInterval(async () => {
      const answer = await refresh();
      if (answer && !['running', 'cancelling'].includes(answer.job.state)) {
        stopPolling();
        loadTopics();
      }
    }, 1500);
  }

  function stopPolling() {
    clearInterval(poll);
    poll = null;
  }

  // At the start, and again when another server is picked in the left bar
  $effect(() => {
    if (!guild) {                  // no server imported yet: nothing to ask
      loaded = true;
      return;
    }
    (async () => {
      await refresh();
      await loadTopics();
      if (running) startPolling();
    })();
  });
  onDestroy(stopPolling);

  async function start() {
    busy = true;
    const body = { guild, topics: fixedTopics ? Number(fixedTopics) : null };
    const answer = await guard(() => api.analysisStart(body));
    busy = false;
    if (answer) {
      await refresh();
      startPolling();
    }
  }

  async function cancel() {
    await guard(() => api.analysisCancel());
    refresh();
  }

  async function change(topic, body) {
    const answer = await guard(() => api.topicChange(topic.id, body));
    if (answer) await loadTopics();
  }

  function selectTopic(id, checked) {
    selected = checked ? [...selected, id] : selected.filter((other) => other !== id);
  }

  async function validateSelected() {
    if (!selected.length || busy) return;
    busy = true;
    const answer = await guard(() => api.topicsValidate(guild, selected));
    busy = false;
    if (answer) {
      selected = [];
      await loadTopics();
      await refresh();
    }
  }

  async function saveName() {
    const { id, label, description } = editing;
    editing = null;
    await change({ id }, { label, description });
  }

  async function merge() {
    const { id, into } = merging;
    merging = null;
    if (!into) return;
    const answer = await guard(() => api.topicMerge(id, Number(into)));
    if (answer) await loadTopics();
  }

  const when = day;
</script>

<div class="page" class:embedded>
  {#if !embedded}
  <header class="pageHeader">
    <div>
      <h1>Thèmes</h1>
      <p class="subtitle">
        Examinez les thèmes proposés à partir des conversations. Validez ceux qui conviennent ; corrigez ou rejetez les autres.
      </p>
    </div>
  </header>
  {/if}

  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  {#if !guild}
    <section class="panel status">
      <p class="muted">Aucun serveur n’est encore importé : il n’y a rien à analyser. Importez d’abord un serveur (entrée <strong>Importer</strong> de la barre de gauche, ou <code>dindon backfill</code>).</p>
    </section>
  {:else}
  <section class="panel status">
    <div class="statusHead">
      <span class="eyebrow">Analyse</span>
      {#if !info}
        <span class="muted">Chargement…</span>
      {:else if !ready.ollama}
        <span class="badge danger">Ollama ne répond pas</span>
      {:else if missing.length}
        <span class="badge danger">Modèle à installer</span>
      {:else}
        <span class="badge success">Ollama prêt</span>
      {/if}
    </div>

    {#if info}
      {#if !ready.ollama}
        <p class="banner">Ollama n’est pas lancé ou pas joignable : {ready.problem}. Installez-le et lancez-le (voir le README), puis rechargez cette page.</p>
      {:else if missing.length}
        <p class="banner">Il manque : {#each missing as name}<code>ollama pull {name}</code> {/each}</p>
      {/if}

      <dl class="counts">
        <div class="metric"><dt>À examiner</dt><dd>{fmt.format(info.counts.topics.proposed ?? 0)}</dd></div>
        <div class="metric"><dt>Validés</dt><dd>{fmt.format(info.counts.topics.validated ?? 0)}</dd></div>
      </dl>

      <div class="actions">
        {#if running}
          <button class="btn btn-danger" onclick={cancel} disabled={job.state === 'cancelling'}>Annuler l’analyse</button>
        {:else}
          <button class="btn btn-primary" onclick={start} disabled={!canStart || busy}>Lancer l’analyse</button>
        {/if}
        <button type="button" class="btn" onclick={onAutomate}>Automatiser les prochaines analyses</button>
      </div>
      <details class="advanced">
        <summary>Réglages et détails de l’analyse</summary>
        <p class="muted hint">{fmt.format(info.counts.messages)} messages · {fmt.format(info.counts.conversations)} conversations · {fmt.format(info.counts.kept)} retenues · {fmt.format(info.counts.embedded)} vecteurs</p>
        <label class="inline">Nombre de thèmes
          <input class="field-input small" type="number" min="2" max="80" placeholder="auto" bind:value={fixedTopics} aria-label="Nombre de thèmes" />
        </label>
        <p class="muted hint">Laissez vide pour laisser l’analyse choisir. Modèles : <code>{info.models.embeddings}</code> (vecteurs), <code>{info.models.naming}</code> (noms). Rien ne sort de cette machine.
          {#if info.last_run} Dernière recherche : {when(info.last_run.at)}, {info.last_run.k} thèmes.{/if}</p>
      </details>

      {#if job.state !== 'idle'}
        <div class="progress" aria-live="polite">
          <span class="badge" class:success={job.state === 'done'} class:danger={job.state === 'failed'} class:accent={running}>{STATES[job.state]}</span>
          {#if running && job.stage}<span class="muted">étape : {job.stage}</span>{/if}
          {#if running && job.of}<progress max={job.of} value={job.done}></progress><span class="muted">{fmt.format(job.done)} / {fmt.format(job.of)}</span>{/if}
          {#if job.error}<p class="banner" role="alert">{job.error}</p>{/if}
          {#if job.lines.length}<details class="jobLog"><summary>Journal de l’analyse</summary><pre class="lines">{job.lines.join('\n')}</pre></details>{/if}
        </div>
      {/if}
    {/if}
  </section>

  {#snippet card(topic)}
    <article class="panel topic" class:isValidated={topic.status === 'validated'}>
      <header>
        {#if editing?.id === topic.id}
          <input class="field-input" bind:value={editing.label} aria-label="Nom du thème" minlength="2" maxlength="80" />
        {:else}
          <h3>{topic.label}</h3>
        {/if}
        <span class="badge" class:success={topic.status === 'validated'} class:accent={topic.status === 'proposed'}>
          {topic.status === 'validated' ? 'validé' : topic.status === 'rejected' ? 'rejeté' : 'proposé'}
        </span>
      </header>
      <p class="size">{fmt.format(topic.conversations)} conversations{#if topic.last_at} · dernière le {when(topic.last_at)}{/if}</p>
      {#if editing?.id === topic.id}
        <textarea class="field-input" rows="2" bind:value={editing.description} aria-label="Description du thème" maxlength="400"></textarea>
      {:else if topic.description}
        <p class="description">{topic.description}</p>
      {/if}
      {#if topic.keywords.length}
        <p class="tags">{#each topic.keywords as word}<span>{word}</span>{/each}</p>
      {/if}
      {#if topic.examples.length}
        <details>
          <summary>Extraits typiques (sans les noms)</summary>
          <ul>{#each topic.examples as text}<li>{text}</li>{/each}</ul>
        </details>
      {/if}

      <div class="topicActions">
        {#if editing?.id === topic.id}
          <button class="btn btn-primary" onclick={saveName} disabled={editing.label.trim().length < 2}>Enregistrer</button>
          <button class="btn" onclick={() => (editing = null)}>Annuler</button>
        {:else if merging?.id === topic.id}
          <select class="select" bind:value={merging.into} aria-label="Fusionner avec">
            <option value="">Fusionner avec…</option>
            {#each topics.filter((t) => t.id !== topic.id && t.status !== 'rejected') as other}<option value={other.id}>{other.label}</option>{/each}
          </select>
          <button class="btn btn-primary" onclick={merge} disabled={!merging.into}>Fusionner</button>
          <button class="btn" onclick={() => (merging = null)}>Annuler</button>
        {:else if topic.status === 'rejected'}
          <button class="btn" onclick={() => change(topic, { status: 'proposed' })}>Remettre en proposition</button>
        {:else}
          {#if topic.status === 'proposed'}
            <label class="check selectTopic"><input type="checkbox" checked={selected.includes(topic.id)} onchange={(e) => selectTopic(topic.id, e.currentTarget.checked)} aria-label={`Sélectionner ${topic.label}`} /> Sélectionner</label>
          {/if}
          {#if topic.status === 'proposed'}<button class="btn btn-primary" onclick={() => change(topic, { status: 'validated' })}>Valider</button>{/if}
          {#if topic.status === 'validated'}<button class="btn" onclick={() => change(topic, { status: 'proposed' })}>Annuler la validation</button>{/if}
          <button class="btn" onclick={() => (editing = { id: topic.id, label: topic.label, description: topic.description ?? '' })}>Renommer</button>
          <button class="btn" onclick={() => (merging = { id: topic.id, into: '' })}>Fusionner…</button>
          <button class="btn btn-danger" onclick={() => change(topic, { status: 'rejected' })}>Rejeter</button>
        {/if}
      </div>
    </article>
  {/snippet}

  <div class="toolbar" role="search" aria-label="Chercher dans les thèmes">
    <input class="field-input" type="search" placeholder="Chercher un thème, un mot… (/)" bind:value={q} aria-label="Chercher un thème" use:slash />
    <select class="select" bind:value={statusFilter} aria-label="Filtrer par état">
      <option value="all">Tous les états</option>
      <option value="proposed">À examiner</option>
      <option value="validated">Validés</option>
      <option value="rejected" disabled={!showRejected}>Rejetés{showRejected ? '' : ' (cochez « montrer »)'}</option>
    </select>
    <select class="select" bind:value={sort} aria-label="Trier">
      <option value="size">Les plus gros d’abord</option>
      <option value="recent">Les plus récents d’abord</option>
      <option value="name">Par nom</option>
    </select>
    {#if filtering}<button type="button" class="tool-btn reset" onclick={() => { q = ''; statusFilter = 'all'; }}>Effacer les filtres</button>{/if}
    <span class="found" aria-live="polite">{seen.length} thème{seen.length > 1 ? 's' : ''}{filtering ? ` sur ${topics.length}` : ''}</span>
  </div>

  <section>
    <h2 class="eyebrow">À examiner <span class="count">{proposed.length}</span></h2>
    {#if selected.length}
      <div class="bulkActions" aria-live="polite"><span>{selected.length} thème{selected.length > 1 ? 's' : ''} sélectionné{selected.length > 1 ? 's' : ''}</span><button type="button" class="btn btn-primary" onclick={validateSelected} disabled={busy}>Valider la sélection</button><button type="button" class="btn" onclick={() => (selected = [])}>Effacer</button></div>
    {/if}
    {#if !loaded}
      <p class="muted">Chargement…</p>
    {:else if !proposed.length}
      <p class="muted empty">{filtering ? 'Aucun thème ne correspond à la recherche.' : 'Aucun thème à examiner. Lancez l’analyse : elle fait les conversations, leurs vecteurs, puis propose les thèmes.'}</p>
    {:else}
      <div class="grid">{#each proposed as topic (topic.id)}{@render card(topic)}{/each}</div>
    {/if}
  </section>

  {#if validated.length}
    <section>
      <h2 class="eyebrow">Validés <span class="count">{validated.length}</span></h2>
      <div class="grid">{#each validated as topic (topic.id)}{@render card(topic)}{/each}</div>
    </section>
  {/if}

  <section>
    <label class="check">
      <input type="checkbox" bind:checked={showRejected} onchange={loadTopics} />
      <span>Montrer les thèmes rejetés</span>
    </label>
    {#if showRejected && rejected.length}
      <div class="grid">{#each rejected as topic (topic.id)}{@render card(topic)}{/each}</div>
    {/if}
  </section>
  {/if}
</div>

<style>
  .page {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 1.5rem 1.75rem 2.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    animation: fadeIn var(--transition-slow) both;
  }
  .page.embedded { flex: none; min-height: auto; overflow: visible; padding: 0; animation: none; }

  h1 {
    font-size: clamp(1.5rem, 2vw, 1.9rem);
    line-height: 1.1;
    font-weight: 700;
    color: var(--text-primary);
  }

  .subtitle {
    max-width: 62ch;
    margin-top: 0.5rem;
    color: var(--text-secondary);
  }

  .status {
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .statusHead {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .counts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(7.5rem, 1fr));
    gap: 0.625rem;
  }

  /* The metric tiles of the person's card */
  .metric {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.625rem 0.75rem 0.625rem 0.9375rem;
    border-radius: 0.75rem;
    border: 1px solid color-mix(in srgb, var(--accent) 32%, rgba(255, 255, 255, 0.06));
    background: color-mix(in srgb, var(--bg-tertiary) 92%, black);
    overflow: hidden;
  }

  .metric::before {
    content: '';
    position: absolute;
    inset: 0 auto 0 0;
    width: 3px;
    background: var(--accent);
  }

  dt {
    font-size: 0.75rem;
    font-weight: 600;
    color: color-mix(in srgb, var(--accent) 58%, white);
  }

  dd {
    font-size: 1.375rem;
    line-height: 1.1;
    font-weight: 700;
    color: #f7f8fa;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem 1rem;
  }

  .inline {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
    color: var(--text-secondary);
  }

  .small {
    width: 5rem;
  }

  .hint {
    font-size: 0.75rem;
    line-height: 1.5;
    flex-basis: 100%;
  }

  .progress {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.625rem;
    padding-top: 0.875rem;
    border-top: 1px solid var(--border-subtle);
  }

  progress {
    appearance: none;
    -webkit-appearance: none;
    flex: 1 1 12rem;
    height: 0.5rem;
    border: none;
    border-radius: 999px;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.1);
  }

  progress::-webkit-progress-bar {
    background: rgba(255, 255, 255, 0.1);
  }

  progress::-webkit-progress-value {
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, white));
    border-radius: 999px;
  }

  progress::-moz-progress-bar {
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, white));
    border-radius: 999px;
  }

  .progress .banner,
  .lines {
    flex-basis: 100%;
  }

  .lines {
    max-height: 9rem;
    overflow: auto;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 0.625rem 0.75rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.75rem;
    color: var(--text-secondary);
    white-space: pre-wrap;
  }

  h2.eyebrow {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }

  .count {
    font-size: 0.625rem;
    font-weight: 600;
    letter-spacing: 0;
    color: var(--text-muted);
    background: var(--bg-tertiary);
    border-radius: 8px;
    padding: 0 0.375rem;
    line-height: 1rem;
  }

  .empty {
    padding: 1.5rem 0;
    text-align: center;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(21rem, 1fr));
    gap: 1rem;
  }

  .topic {
    padding: 1rem 1.125rem;
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
    box-shadow: var(--shadow-sm);
  }

  .topic.isValidated {
    border-color: rgba(35, 165, 90, 0.35);
  }

  .topic > header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  h3 {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.3;
    overflow-wrap: anywhere;
  }

  .size {
    font-size: 0.75rem;
    color: var(--text-muted);
  }

  .description {
    font-size: 0.8125rem;
    color: var(--text-secondary);
    line-height: 1.5;
  }

  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  .tags span {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-full);
    color: var(--text-secondary);
    font-size: 0.75rem;
    padding: 0.1875rem 0.625rem;
  }

  details {
    font-size: 0.8125rem;
    color: var(--text-secondary);
  }

  summary {
    cursor: pointer;
    color: var(--text-muted);
    font-size: 0.75rem;
  }

  details ul {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }

  details li {
    padding: 0.5rem 0.625rem;
    background: var(--bg-tertiary);
    border-radius: var(--radius-md);
    line-height: 1.45;
    overflow-wrap: anywhere;
  }

  .topicActions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.25rem;
  }

  .topicActions .btn {
    min-height: 2.125rem;
    padding: 0 0.75rem;
    font-size: 0.8125rem;
  }

  textarea.field-input {
    resize: vertical;
    min-height: 3rem;
  }

  .check {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
    font-size: 0.8125rem;
    color: var(--text-muted);
    cursor: pointer;
  }
  .selectTopic { margin: 0 0.25rem 0 0; }
  .bulkActions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; font-size: 0.8125rem; }
  .advanced { display: flex; flex-direction: column; gap: 0.5rem; }
  .advanced[open] .inline { margin-top: 0.75rem; }
  .jobLog { flex-basis: 100%; }
  .jobLog .lines { margin-top: 0.5rem; }

  @media (max-width: 720px) {
    .page {
      padding: 1rem 1rem 2rem;
    }

    .grid {
      grid-template-columns: 1fr;
    }
  }
</style>
