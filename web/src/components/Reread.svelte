<script>
  import { onMount, onDestroy } from 'svelte';
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
    try {
      themes = (await api.topics(guild, false)).filter((t) => t.status !== 'rejected');
    } catch (error) {
      fail(error);
    }
  }

  async function loadChanges(append = false) {
    try {
      const answer = await api.rereadChanges(guild, { verdict: shown, offset: append ? changes.length : 0 });
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
      loadChanges();
    }
  });
  onMount(() => { timer = setInterval(() => { if (guild && !document.hidden && (running || !info)) load(); }, 2000); });
  onDestroy(() => clearInterval(timer));

  const lines = (change) => Object.entries(change.changes).map(([kind, [before, after]]) => ({
    kind: { stance: 'Position', kind: 'Nature', proposition: 'Proposition', theme: 'Thème' }[kind] ?? kind, before: before ?? '—', after: after ?? '—',
  }));
</script>

<div class="page" class:embedded>
  {#if !embedded}
    <header><h1>Relecture</h1></header>
  {/if}
  <p class="subtitle">Relit chaque position de chaque personne avec les messages qui la précèdent, vérifie qu’elle est juste, la corrige si elle ne l’est pas (le sens de la position, la proposition, le thème), puis recalcule et contrôle les scores. C’est à part de l’analyse : à lancer quand vous le voulez, jamais en même temps qu’elle.</p>
  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  <section class="panel card" aria-label="Lancer une relecture">
    <h2 class="eyebrow">Lancer une relecture</h2>
    {#if info}
      <p>{fmt.format(info.todo.positions)} position{info.todo.positions > 1 ? 's' : ''} relisable{info.todo.positions > 1 ? 's' : ''} · {fmt.format(info.todo.reread)} déjà relue{info.todo.reread > 1 ? 's' : ''} avec la méthode actuelle · <strong>{fmt.format(info.todo.waiting)} à relire</strong></p>
      <div class="options">
        <label class="inline">Thème
          <select class="field-input" bind:value={theme} disabled={running}>
            <option value="">Tous les thèmes</option>
            {#each themes as t (t.id)}<option value={t.id}>{t.label}</option>{/each}
          </select>
        </label>
        <label class="inline">Au plus
          <input class="field-input num" type="number" min="1" step="1" placeholder="toutes" bind:value={limit} disabled={running} aria-label="Nombre maximal de positions à relire" />
        </label>
        <label class="check"><input type="checkbox" bind:checked={force} disabled={running} /> <span>Relire aussi ce que la méthode actuelle a déjà relu</span></label>
      </div>
      <div class="actions">
        {#if running}
          <button class="btn btn-danger" onclick={cancel} disabled={job.state === 'cancelling'}>Arrêter la relecture</button>
        {:else}
          <button class="btn btn-primary" onclick={start} disabled={busy || (!force && info.todo.waiting === 0)}>Lancer la relecture</button>
        {/if}
      </div>
      <p class="muted hint">Une position n’est modifiée que si le modèle (<code>{info.model}</code>) est sûr de lui ; sinon elle reste telle quelle. Ce qu’une personne a confirmé ou rejetée n’est jamais relu. Chaque correction garde ce qu’elle était et peut être annulée ci-dessous.</p>
    {:else}<p class="muted">Chargement…</p>{/if}

    {#if job && job.state !== 'idle'}
      <div class="progress" aria-live="polite">
        <span class="badge" class:success={job.state === 'done'} class:danger={job.state === 'failed'} class:accent={running}>{STATES[job.state]}</span>
        {#if running}<span class="muted">{job.step}</span>{/if}
        {#if running && job.of}<progress max={job.of} value={job.done}></progress><span class="muted">{fmt.format(job.done)} / {fmt.format(job.of)}{progress !== null ? ` · ${progress} %` : ''}</span>{/if}
        {#if job.error}<p class="banner" role="alert">{job.error}</p>{/if}
        {#if job.lines?.length}<details class="jobLog" open={running}><summary>Journal</summary><pre class="lines">{job.lines.join('\n')}</pre></details>{/if}
      </div>
    {/if}
  </section>

  {#if last && last.counts}
    <section class="panel card" aria-label="Dernière relecture">
      <h2 class="eyebrow">Dernière relecture · {when(last.at)} · {STATES[last.state]}</h2>
      <p>
        {fmt.format((last.counts.confirmed ?? 0) + (last.counts.corrected ?? 0) + (last.counts.uncertain ?? 0))} positions relues :
        <strong>{fmt.format(last.counts.confirmed ?? 0)}</strong> confirmées, <strong>{fmt.format(last.counts.corrected ?? 0)}</strong> corrigées,
        {fmt.format(last.counts.uncertain ?? 0)} incertaines (gardées telles quelles){last.counts.failed ? `, ${fmt.format(last.counts.failed)} à reprendre` : ''}.
      </p>
      {#if last.counts.corrected}
        <p class="muted small">
          {last.counts.stance_changed ?? 0} sens de position · {last.counts.not_an_opinion ?? 0} qui n’étaient pas une opinion · {last.counts.proposition_changed ?? 0} propositions · {last.counts.theme_changed ?? 0} thèmes
        </p>
      {/if}
      {#if last.counts.audit}
        <p class:ok={last.counts.audit.different === 0}>
          Contrôle des scores : {fmt.format(last.counts.audit.checked)} recalculés à part, {last.counts.audit.different === 0 ? 'aucun écart.' : `${last.counts.audit.different} écart(s) constaté(s), puis scores recalculés.`}
          {#if last.counts.audit.first_check_different}<span class="muted"> ({last.counts.audit.first_check_different} écarts avant le nouveau calcul)</span>{/if}
        </p>
      {/if}
    </section>
  {/if}

  <section class="panel card" aria-label="Ce que la relecture a décidé">
    <h2 class="eyebrow">Ce que la relecture a décidé</h2>
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
            <p class="who">
              {#if onPerson}<button type="button" class="link" onclick={() => onPerson(change.user)}>{change.person}</button>{:else}<strong>{change.person}</strong>{/if}
              <span class="muted small"> · {when(change.at)}{change.certainty ? ` · sûr à ${change.certainty} %` : ''}</span>
            </p>
            {#if change.quotes.length}<blockquote>{change.quotes.map((q) => `« ${q} »`).join(' ')}</blockquote>{/if}
            {#if change.proposition}<p class="muted small">Proposition : {change.proposition}</p>{/if}
            {#each lines(change) as line}
              <p class="diff"><span class="muted">{line.kind} :</span> <s>{line.before}</s> → <strong>{line.after}</strong></p>
            {/each}
            {#if change.reason}<p class="muted small">Pourquoi : {change.reason}</p>{/if}
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
  .page:not(.embedded) { flex: 1; min-height: 0; overflow-y: auto; padding: 1.5rem clamp(1rem, 3vw, 2.5rem) 2.5rem; }
  .subtitle { max-width: 72ch; color: var(--text-secondary); }
  .panel { display: flex; flex-direction: column; gap: .75rem; }
  .options { display: flex; flex-wrap: wrap; align-items: center; gap: .75rem 1.25rem; }
  .actions { display: flex; gap: .5rem; flex-wrap: wrap; }
  .progress { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; }
  .progress progress { flex: 1 1 12rem; height: .65rem; accent-color: var(--accent, #8b6cff); }
  .jobLog { flex-basis: 100%; }
  .lines { max-height: 14rem; overflow: auto; font-size: .75rem; white-space: pre-wrap; }
  .tabs { display: flex; gap: .4rem; flex-wrap: wrap; }
  .tabs .active { box-shadow: inset 0 0 0 1px var(--accent, #8b6cff); }
  .changes { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .6rem; }
  .changes li { display: flex; flex-direction: column; gap: .25rem; padding: .75rem .9rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-primary); }
  .changes li.undone { opacity: .55; }
  blockquote { margin: 0; padding-left: .75rem; border-left: 2px solid var(--border-subtle); color: var(--text-secondary); overflow-wrap: anywhere; }
  .diff { margin: 0; font-size: .85rem; }
  .diff s { color: var(--text-muted); }
  .link { background: none; border: 0; padding: 0; color: var(--accent, #8b6cff); font: inherit; font-weight: 600; cursor: pointer; }
  .ok { color: var(--success, #3fa66a); }
  .small { font-size: .8rem; }
  .hint { font-size: .8rem; }
</style>
