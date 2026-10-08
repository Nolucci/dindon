<script>
  import { onMount, onDestroy, untrack } from 'svelte';
  import Help from './Help.svelte';
  import { api, AuthError } from '../lib/api.js';

  let { guild, onAuthLost, onPerson = null, embedded = false } = $props();

  const fmt = new Intl.NumberFormat('fr-FR');
  const when = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—');
  const STATES = { idle: 'Inactive', running: 'En cours', cancelling: 'Arrêt…', done: 'Terminée', cancelled: 'Arrêtée', failed: 'Interrompue' };

  let info = $state(null);
  let themes = $state([]);
  let changes = $state([]);
  let more = $state(null);
  let shown = $state('corrected');
  let problem = $state('');
  let busy = $state(false);
  let theme = $state('');
  let limit = $state('');
  let force = $state(false);
  let timer;
  let request = 0;
  let changesRequest = 0;

  const job = $derived(info?.job);
  const running = $derived(job?.state === 'running' || job?.state === 'cancelling');
  const progress = $derived(job?.of > 0 ? Math.round((100 * job.done) / job.of) : null);
  const last = $derived(info?.runs?.[0]);

  function fail(error) {
    if (error instanceof AuthError) onAuthLost();
    else problem = error.message;
  }

  async function load() {
    const current = ++request;
    try {
      const answer = await api.reread(guild);
      if (current !== request) return;
      const wasRunning = running;
      info = answer;
      problem = '';
      if (wasRunning && !['running', 'cancelling'].includes(answer.job.state)) await loadChanges();
    } catch (error) {
      fail(error);
    }
  }

  async function loadThemes() {
    const server = guild;
    try {
      const answer = await api.topics(server, false);
      if (server !== guild) return;
      themes = answer.filter((t) => t.status !== 'rejected');
    } catch (error) {
      fail(error);
    }
  }

  async function loadChanges(append = false) {
    const current = ++changesRequest;
    const server = guild;
    try {
      const answer = await api.rereadChanges(server, { verdict: shown, offset: append ? changes.length : 0 });
      if (current !== changesRequest || server !== guild) return;
      changes = append ? [...changes, ...answer.changes] : answer.changes;
      more = answer.next;
    } catch (error) {
      fail(error);
    }
  }

  async function start() {
    busy = true;
    try {
      info = { ...info, job: await api.rereadStart({ guild: String(guild), theme: theme ? Number(theme) : null, force, limit: limit ? Number(limit) : null }) };
      problem = '';
    } catch (error) {
      fail(error);
    }
    busy = false;
  }

  async function cancel() {
    try {
      info = { ...info, job: await api.rereadCancel() };
    } catch (error) {
      fail(error);
    }
  }

  async function undo(change) {
    try {
      await api.rereadUndo(change.claim);
      await Promise.all([loadChanges(), load()]);
    } catch (error) {
      fail(error);
    }
  }

  function show(value) {
    shown = value;
    loadChanges();
  }

  $effect(() => {
    if (guild) {
      info = null;
      changes = [];
      load();
      loadThemes();
      untrack(() => loadChanges());
    }
  });
  onMount(() => { timer = setInterval(() => { if (guild && !document.hidden && (running || !info)) load(); }, 2000); });
  onDestroy(() => clearInterval(timer));

  const value = (kind, text) => kind === 'stance' ? ({ accord: 'Pour', désaccord: 'Contre', nuance: 'Nuancé', aucune: 'Sans position' }[text] ?? text ?? '—') : kind === 'kind' ? ({ opinion: 'Opinion', fact: 'Fait', fait: 'Fait', question: 'Question', humour: 'Humour', other: 'Autre' }[text] ?? text ?? '—') : text ?? '—';
  const lines = (change) => Object.entries(change.changes).map(([kind, [before, after]]) => ({
    kind: { stance: 'Position', kind: 'Nature', proposition: 'Proposition', theme: 'Thème' }[kind] ?? kind, before: value(kind, before), after: value(kind, after),
  }));
</script>

<div class="page" class:embedded>
  {#if !embedded}
    <header><h1>Relecture</h1></header>
  {/if}
  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  <section class="panel card" aria-label="Lancer une relecture">
    <header class="cardHead"><h2>Relire les positions</h2><Help label="À propos de la relecture">Vérifie les positions avec les messages précédents. Les décisions validées ou rejetées manuellement sont préservées. Chaque correction peut être annulée. Une analyse et une relecture ne peuvent pas tourner ensemble.</Help></header>
    {#if info}
      <div class="todo"><strong>{fmt.format(info.todo.waiting)} à relire</strong><span class="muted small">{fmt.format(info.todo.reread)} déjà relues</span></div>
      <div class="options">
        <label class="inline">Thème
          <select class="field-input" bind:value={theme} disabled={running}>
            <option value="">Tous les thèmes</option>
            {#each themes as t (t.id)}<option value={t.id}>{t.label}</option>{/each}
          </select>
        </label>
        <label class="inline">Limite
          <input class="field-input num" type="number" min="1" step="1" placeholder="toutes" bind:value={limit} disabled={running} aria-label="Nombre maximal de positions à relire" />
        </label>
        <label class="check"><input type="checkbox" bind:checked={force} disabled={running} /> <span>Inclure les positions déjà relues</span></label>
      </div>
      <div class="actions">
        {#if running}
          <button class="btn btn-danger" onclick={cancel} disabled={job.state === 'cancelling'}>Arrêter la relecture</button>
        {:else}
          <button class="btn btn-primary" onclick={start} disabled={busy || (!force && info.todo.waiting === 0)}>Lancer la relecture</button>
        {/if}
      </div>
    {:else}<p class="muted">Chargement…</p>{/if}

    {#if job && job.state !== 'idle'}
      <div class="progress" aria-live="polite">
        <span class="badge" class:success={job.state === 'done'} class:danger={job.state === 'failed'} class:accent={running}>{STATES[job.state]}</span>
        {#if running}<span class="muted">{job.step}</span>{/if}
        {#if running && job.of}<progress max={job.of} value={job.done}></progress><span class="muted">{fmt.format(job.done)} / {fmt.format(job.of)}{progress !== null ? ` · ${progress} %` : ''}</span>{/if}
        {#if job.error}<p class="banner" role="alert">{job.error}</p>{/if}
        {#if job.lines?.length}<details class="jobLog"><summary>Journal</summary><pre class="lines">{job.lines.join('\n')}</pre></details>{/if}
      </div>
    {/if}
  </section>

  {#if last && last.counts}
    <section class="panel card" aria-label="Dernière relecture">
      <header class="cardHead"><div class="title"><h2>Dernière relecture</h2><Help label="Comprendre les résultats de relecture">Les positions incertaines restent inchangées. Les corrections peuvent être annulées dans les résultats.</Help></div><span class="muted small">{when(last.at)} · {STATES[last.state]}</span></header>
      <dl class="metrics">
        <div><dt>Corrigées</dt><dd>{fmt.format(last.counts.corrected ?? 0)}</dd></div>
        <div><dt>Confirmées</dt><dd>{fmt.format(last.counts.confirmed ?? 0)}</dd></div>
        <div><dt>Incertaines</dt><dd>{fmt.format(last.counts.uncertain ?? 0)}</dd></div>
        {#if last.counts.failed}<div><dt>À reprendre</dt><dd>{fmt.format(last.counts.failed)}</dd></div>{/if}
      </dl>
      {#if last.counts.audit}
        <details><summary>Contrôle des scores</summary><p class="small">{fmt.format(last.counts.audit.checked)} scores contrôlés · {last.counts.audit.different === 0 ? 'aucun écart' : `${last.counts.audit.different} écarts, scores recalculés`}</p>
          {#if last.counts.audit.first_check_different}<p class="muted small">{last.counts.audit.first_check_different} écarts avant recalcul.</p>{/if}
        </details>
      {/if}
    </section>
  {/if}

  <section class="panel card" aria-label="Ce que la relecture a décidé">
    <h2>Résultats</h2>
    <div class="tabs" role="group" aria-label="Quelles décisions montrer">
      <button type="button" class="btn" class:active={shown === 'corrected'} aria-pressed={shown === 'corrected'} onclick={() => show('corrected')}>Corrigées</button>
      <button type="button" class="btn" class:active={shown === 'uncertain'} aria-pressed={shown === 'uncertain'} onclick={() => show('uncertain')}>Incertaines</button>
      <button type="button" class="btn" class:active={shown === 'confirmed'} aria-pressed={shown === 'confirmed'} onclick={() => show('confirmed')}>Confirmées</button>
    </div>
    {#if !changes.length}
      <p class="muted">Rien à montrer pour l’instant.</p>
    {:else}
      <ul class="changes">
        {#each changes as change (`${change.run}-${change.claim}`)}
          <li class:undone={change.undone}>
            <header class="who">
              {#if onPerson}<button type="button" class="link" onclick={() => onPerson(change.user)}>{change.person}</button>{:else}<strong>{change.person}</strong>{/if}
              <span class="muted small">{when(change.at)}</span>
            </header>
            {#if change.proposition}<p class="proposition">{change.proposition}</p>{/if}
            {#each lines(change) as line}
              <div class="diff"><span class="diffKind">{line.kind}</span><dl><div><dt>Avant</dt><dd><s>{line.before}</s></dd></div><div><dt>Après</dt><dd><strong>{line.after}</strong></dd></div></dl></div>
            {/each}
            {#if change.quotes.length || change.reason}
              <details class="evidence"><summary>Citations et motif</summary>
                {#each change.quotes as quote}<blockquote>{quote}</blockquote>{/each}
                {#if change.reason}<p class="muted small">{change.reason}</p>{/if}
              </details>
            {/if}
            {#if change.verdict === 'corrected'}
              {#if change.undone}<span class="badge small">annulée</span>{:else}<button type="button" class="btn small" onclick={() => undo(change)}>Annuler cette correction</button>{/if}
            {/if}
          </li>
        {/each}
      </ul>
      {#if more !== null}<button type="button" class="btn" onclick={() => loadChanges(true)}>Voir la suite</button>{/if}
    {/if}
  </section>
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 1rem; }
  .page:not(.embedded) { flex: 1; min-height: 0; overflow-y: auto; }
  .card { padding: 1rem 1.125rem; display: flex; flex-direction: column; gap: 1rem; }
  .title { display: flex; align-items: center; gap: .5rem; }
  .cardHead, .who, .todo { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .5rem 1rem; }
  h2 { font-size: 1rem; color: var(--text-primary); }
  .options { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: .75rem 1rem; }
  .inline { display: flex; flex-direction: column; gap: .375rem; font-size: .8125rem; color: var(--text-secondary); }
  .check { grid-column: 1 / -1; display: flex; align-items: flex-start; gap: .5rem; font-size: .8125rem; }
  .check input { flex: none; margin-top: .2rem; }
  .actions, .progress, .tabs { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
  .progress progress { flex: 1 1 12rem; max-width: 100%; height: .65rem; accent-color: var(--accent); }
  .jobLog { flex-basis: 100%; min-width: 0; }
  .lines { max-height: 14rem; overflow: auto; font-size: .75rem; white-space: pre-wrap; }
  .metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .75rem; }
  .metrics dt { display: flex; align-items: center; gap: .5rem; min-height: 2rem; font-size: .8125rem; color: var(--text-secondary); }
  .metrics dd { font-size: 1.5rem; font-weight: 700; }
  .tabs .active { box-shadow: inset 0 0 0 1px var(--accent); }
  .changes { list-style: none; display: flex; flex-direction: column; gap: .75rem; }
  .changes > li { display: flex; flex-direction: column; gap: .875rem; padding: 1rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); }
  .changes > li > .btn { align-self: flex-start; }
  .changes li.undone { opacity: .65; }
  .proposition { font-weight: 600; }
  blockquote { margin: .5rem 0; padding-left: .75rem; border-left: 2px solid var(--border-subtle); color: var(--text-secondary); }
  .diff { display: flex; flex-direction: column; gap: .375rem; font-size: .875rem; }
  .diffKind { font-weight: 600; }
  .diff dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; }
  .diff dl > div { min-width: 0; padding: .625rem .75rem; border-radius: var(--radius-md); background: var(--bg-secondary); }
  .diff dt { margin-bottom: .25rem; font-size: .75rem; color: var(--text-muted); }
  .diff dd { overflow-wrap: anywhere; }
  .diff s { color: var(--text-secondary); }
  .link { padding: 0; color: var(--text-link); font: inherit; font-weight: 600; text-align: left; overflow-wrap: anywhere; }
  .small { font-size: .8125rem; }
  @media (max-width: 720px) { .metrics dt { font-size: .75rem; } }
  @media (max-width: 480px) { .options, .diff dl { grid-template-columns: 1fr; } }
</style>
