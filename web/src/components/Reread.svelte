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
  let q = $state('');
  let kindFilter = $state('');
  let runFilter = $state('');
  let stateFilter = $state('all');
  let total = $state(0);
  let selected = $state([]);
  let notice = $state('');
  let searchTimer;
  let grouped = $state(true);
  let openGroups = $state([]);
  const searching = $derived(q.trim() !== '' || kindFilter !== '' || runFilter !== '' || stateFilter !== 'all');
  let groupsTouched = $state(false);        // until the person opens or folds a theme, the first one (the busiest) is open: something is always in sight
  const isOpen = (key) => searching || openGroups.includes(key) || (!groupsTouched && groups[0]?.key === key);
  const setGroup = (key, on) => { if (!groupsTouched) { groupsTouched = true; openGroups = groups[0] && groups[0].key !== key && !on ? [groups[0].key] : openGroups; } openGroups = on ? [...new Set([...openGroups, key])] : openGroups.filter((k) => k !== key); };
  // The corrections under the theme they now have (the new one when the reread moved them), the busiest theme first
  const groups = $derived.by(() => {
    const by = new Map();
    for (const c of changes) {
      const key = c.theme_id ?? 0;
      if (!by.has(key)) by.set(key, { key, label: c.theme ?? 'Sans thème', items: [] });
      by.get(key).items.push(c);
    }
    return [...by.values()].sort((x, y) => y.items.length - x.items.length);
  });
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
      const answer = await api.rereadChanges(server, {
        verdict: shown, offset: append ? changes.length : 0, q: q.trim() || undefined, change: kindFilter || undefined, run: runFilter || undefined, state: stateFilter === 'all' ? undefined : stateFilter,
      });
      if (current !== changesRequest || server !== guild) return;
      changes = append ? [...changes, ...answer.changes] : answer.changes;
      total = answer.total;
      more = answer.next;
      if (!append) selected = selected.filter((id) => changes.some((c) => c.claim === id && !c.undone));
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
      notice = 'Position remise comme avant. Une relecture ne la touchera plus.';
      await Promise.all([loadChanges(), load()]);
    } catch (error) {
      fail(error);
    }
  }

  const choosable = $derived(changes.filter((c) => c.verdict === 'corrected' && !c.undone));
  const allChosen = $derived(choosable.length > 0 && choosable.every((c) => selected.includes(c.claim)));
  const choose = (claim, on) => { selected = on ? [...selected, claim] : selected.filter((id) => id !== claim); };

  async function undoSelected() {
    if (!selected.length || busy) return;
    busy = true;
    try {
      const answer = await api.rereadUndoMany(selected);
      notice = `${fmt.format(answer.undone)} position${answer.undone > 1 ? 's remises' : ' remise'} comme avant${answer.skipped ? ` · ${fmt.format(answer.skipped)} impossible${answer.skipped > 1 ? 's' : ''} (déjà remises, ou modifiées depuis par une autre relecture)` : ''}.`;
      selected = [];
      await Promise.all([loadChanges(), load()]);
    } catch (error) {
      fail(error);
    }
    busy = false;
  }

  async function undoRun() {
    const run = Number(runFilter);
    if (!run || busy) return;
    const label = info?.runs?.find((r) => r.id === run);
    if (!window.confirm(`Revenir à l’état d’avant la relecture du ${when(label?.at)} ? Toutes ses corrections seront remises comme avant (celles qu’une relecture plus récente a modifiées de nouveau restent).`)) return;
    busy = true;
    try {
      const answer = await api.rereadUndoRun(run);
      notice = `Relecture annulée : ${fmt.format(answer.undone)} position${answer.undone > 1 ? 's remises' : ' remise'} comme avant${answer.skipped ? `, ${fmt.format(answer.skipped)} laissée${answer.skipped > 1 ? 's' : ''} (modifiée${answer.skipped > 1 ? 's' : ''} depuis)` : ''}.`;
      selected = [];
      await Promise.all([loadChanges(), load()]);
    } catch (error) {
      fail(error);
    }
    busy = false;
  }

  function refilter() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadChanges(), 300);
  }

  function show(value) {
    shown = value;
    selected = [];
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
  onDestroy(() => { clearInterval(timer); clearTimeout(searchTimer); });

  const value = (kind, text) => kind === 'stance' ? ({ accord: 'Pour', désaccord: 'Contre', nuance: 'Nuancé', aucune: 'Sans position' }[text] ?? text ?? '—') : kind === 'kind' ? ({ opinion: 'Opinion', fact: 'Fait', fait: 'Fait', question: 'Question', humour: 'Humour', other: 'Autre' }[text] ?? text ?? '—') : text ?? '—';
  // The whole change on one line: « Position : Pour → Contre · Thème : A → B »
  const summary = (change) => lines(change).map((l) => `${l.kind} : ${l.before} → ${l.after}`).join(' · ') || { corrected: 'Corrigée', uncertain: 'Incertaine', confirmed: 'Confirmée' }[change.verdict];
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
    {#if notice}<p class="notice" role="status">{notice}</p>{/if}
    <div class="finder" role="search" aria-label="Retrouver des positions">
      <input class="field-input" type="search" placeholder="Chercher une personne, une phrase, une proposition…" aria-label="Chercher une position" bind:value={q} oninput={refilter} />
      <select class="field-input" aria-label="Type de changement" bind:value={kindFilter} onchange={() => loadChanges()}>
        <option value="">Tous les changements</option><option value="stance">Sens de la position</option><option value="kind">N’était pas une opinion</option><option value="proposition_id">Proposition</option><option value="theme">Thème</option>
      </select>
      <select class="field-input" aria-label="Quelle relecture" bind:value={runFilter} onchange={() => loadChanges()}>
        <option value="">Toutes les relectures</option>
        {#each info?.runs ?? [] as r (r.id)}<option value={r.id}>{when(r.at)} · {r.counts?.corrected ?? 0} corrigées</option>{/each}
      </select>
      <select class="field-input" aria-label="Positions gardées ou remises comme avant" bind:value={stateFilter} onchange={() => loadChanges()}>
        <option value="all">Toutes</option><option value="kept">Corrections gardées</option><option value="undone">Remises comme avant</option>
      </select>
    </div>
    {#if shown === 'corrected' && (choosable.length || runFilter)}
      <div class="bulk" aria-live="polite">
        {#if choosable.length}
          <label class="check"><input type="checkbox" checked={allChosen} onchange={(e) => (selected = e.currentTarget.checked ? choosable.map((c) => c.claim) : [])} /> <span>Tout sélectionner ({fmt.format(choosable.length)})</span></label>
          <button type="button" class="btn btn-primary" onclick={undoSelected} disabled={!selected.length || busy}>Garder l’ancienne position{selected.length ? ` (${selected.length})` : ''}</button>
        {/if}
        {#if runFilter}<button type="button" class="btn btn-danger" onclick={undoRun} disabled={busy}>Annuler toute cette relecture</button>{/if}
      </div>
    {/if}
    {#if changes.length}<p class="muted small">{fmt.format(total)} résultat{total > 1 ? 's' : ''}{changes.length < total ? ` · ${fmt.format(changes.length)} affichés` : ''}</p>{/if}
    {#if !changes.length}
      <p class="muted">{q || kindFilter || runFilter || stateFilter !== 'all' ? 'Aucune position ne correspond à cette recherche.' : 'Rien à montrer pour l’instant.'}</p>
    {:else}
      <div class="viewbar">
        <label class="check"><input type="checkbox" bind:checked={grouped} /> <span>Regrouper par thème</span></label>
        {#if grouped && groups.length > 1}
          <button type="button" class="tool-btn" onclick={() => { groupsTouched = true; openGroups = groups.map((g) => g.key); }}>Tout déplier</button>
          <button type="button" class="tool-btn" onclick={() => { groupsTouched = true; openGroups = []; }}>Tout replier</button>
        {/if}
      </div>
      {#snippet entry(change)}
        <li class:undone={change.undone}>
          <details class="entry">
            <summary>
              {#if change.verdict === 'corrected' && !change.undone}<input class="pick" type="checkbox" checked={selected.includes(change.claim)} onclick={(e) => e.stopPropagation()} onchange={(e) => choose(change.claim, e.currentTarget.checked)} aria-label={`Sélectionner la position de ${change.person}`} />{/if}
              <strong class="who">{change.person}</strong>
              <span class="what">{summary(change)}</span>
              {#if change.undone}<span class="badge small">remise comme avant</span>{/if}
              <span class="muted small when">{when(change.at)}</span>
            </summary>
            <div class="body">
              {#if onPerson}<p><button type="button" class="link" onclick={() => onPerson(change.user)}>Voir la fiche de {change.person}</button></p>{/if}
              {#if change.proposition}<p class="proposition">{change.proposition}</p>{/if}
              {#if change.theme}<p class="muted small">Thème : {change.theme}</p>{/if}
              {#each lines(change) as line}
                <div class="diff"><span class="diffKind">{line.kind}</span><dl><div><dt>Avant</dt><dd><s>{line.before}</s></dd></div><div><dt>Après</dt><dd><strong>{line.after}</strong></dd></div></dl></div>
              {/each}
              {#if change.quotes.length || change.reason}
                <details class="evidence"><summary>Citations et motif</summary>
                  {#each change.quotes as quote}<blockquote>{quote}</blockquote>{/each}
                  {#if change.reason}<p class="muted small">{change.reason}</p>{/if}
                </details>
              {/if}
              {#if change.context}
                <details class="evidence context"><summary>Voir tout le contexte lu</summary>
                  <p class="muted small">Ce que le modèle a lu, tel quel : les auteurs y sont anonymes, <code>EVIDENCE</code> marque les messages cités comme preuve.</p>
                  <ul class="legend">
                    {#each Object.entries(change.people) as [ref, name]}<li><code>{ref}</code> = {name ?? 'inconnu'}{ref === change.person_ref ? ' (la personne évaluée)' : ''}</li>{/each}
                  </ul>
                  <pre class="lines">{change.context}</pre>
                </details>
              {/if}
              {#if change.verdict === 'corrected' && !change.undone}<button type="button" class="btn small" onclick={() => undo(change)}>Garder l’ancienne position</button>{/if}
            </div>
          </details>
        </li>
      {/snippet}
      {#if grouped}
        {#each groups as group (group.key)}
          {@const mine = group.items.filter((c) => c.verdict === 'corrected' && !c.undone)}
          <details class="themeBlock" open={isOpen(group.key)} ontoggle={(e) => { if (!searching) setGroup(group.key, e.currentTarget.open); }}>
            <summary class="theme">
              {#if mine.length}<input class="pick" type="checkbox" checked={mine.every((c) => selected.includes(c.claim))} onclick={(e) => e.stopPropagation()}
                onchange={(e) => (selected = e.currentTarget.checked ? [...new Set([...selected, ...mine.map((c) => c.claim)])] : selected.filter((id) => !mine.some((c) => c.claim === id)))} aria-label={`Sélectionner tout le thème ${group.label}`} />{/if}
              <span class="themeName">{group.label}</span> <span class="count">{group.items.length} position{group.items.length > 1 ? 's' : ''}</span>
            </summary>
            <ul class="changes">{#each group.items as change (`${change.run}-${change.claim}`)}{@render entry(change)}{/each}</ul>
          </details>
        {/each}
      {:else}
        <ul class="changes">{#each changes as change (`${change.run}-${change.claim}`)}{@render entry(change)}{/each}</ul>
      {/if}
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
  .changes { list-style: none; display: flex; flex-direction: column; margin: 0; padding: 0; }
  .changes > li { border-bottom: 1px solid var(--border-subtle); }
  .changes > li:last-child { border-bottom: 0; }
  .changes li.undone { opacity: .6; }
  .entry > summary { display: flex; flex-wrap: wrap; align-items: center; gap: .25rem .75rem; padding: .4375rem .5rem; cursor: pointer; list-style: none; min-width: 0; }
  .entry > summary::-webkit-details-marker { display: none; }
  .entry > summary::before { content: '▸'; flex: none; width: .875rem; color: var(--text-muted); font-size: .75rem; }
  .entry[open] > summary::before { display: inline-block; transform: rotate(90deg); }
  .entry > summary:hover { background: var(--surface-control); }
  .entry .who { display: block; flex: 0 1 auto; min-width: 0; max-width: 10rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .entry .what { flex: 1 1 8rem; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); font-size: .875rem; }
  .entry .when { flex: none; white-space: nowrap; }
  .entry .body { display: flex; flex-direction: column; align-items: flex-start; gap: .75rem; padding: .5rem .75rem 1rem 1.75rem; }
  .entry .body > * { max-width: 100%; overflow-wrap: anywhere; }
  .entry .body { min-width: 0; }
  .pick { flex: none; margin: 0; }
  .themeBlock { border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); }
  .themeBlock + .themeBlock { margin-top: .5rem; }
  .theme { display: flex; flex-wrap: wrap; align-items: baseline; gap: .25rem .5rem; padding: .625rem .875rem; font-weight: 700; color: var(--text-primary); cursor: pointer; list-style: none; }
  .theme::-webkit-details-marker { display: none; }
  .theme::before { content: '▸'; display: inline-block; width: 1rem; color: var(--text-muted); transition: transform .15s; }
  .themeBlock[open] > .theme::before { transform: rotate(90deg); }
  .theme .pick { align-self: center; }
  .themeName { overflow-wrap: anywhere; }
  .count { color: var(--text-muted); font-weight: 400; font-size: .8125rem; }
  .themeBlock > .changes { padding: 0 .5rem .5rem; }
  .viewbar { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem 1rem; }
  .proposition { font-weight: 600; overflow-wrap: anywhere; }
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
  .finder { display: grid; grid-template-columns: minmax(0, 2fr) repeat(3, minmax(0, 1fr)); gap: .5rem; }
  .bulk { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem 1rem; padding: .625rem .75rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); }
  .notice { padding: .5rem .75rem; border-radius: var(--radius-md); background: var(--bg-secondary); font-size: .875rem; }
  .pick { display: inline-flex; align-items: center; margin-right: .5rem; }
  @media (max-width: 900px) { .finder { grid-template-columns: 1fr 1fr; } .finder input { grid-column: 1 / -1; } }
  @media (max-width: 480px) { .finder { grid-template-columns: 1fr; } }
  .legend { list-style: none; display: flex; flex-wrap: wrap; gap: .25rem 1rem; margin: .25rem 0 .5rem; padding: 0; font-size: .8125rem; }
  .context .lines { max-height: 18rem; }
  @media (max-width: 720px) { .metrics dt { font-size: .75rem; } }
  @media (max-width: 480px) { .options, .diff dl { grid-template-columns: 1fr; } }
</style>
