<script>
  import { onMount, onDestroy } from 'svelte';
  import { api, AuthError } from '../lib/api.js';
  import Help from './Help.svelte';

  let { guild, onAuthLost } = $props();

  const fmt = new Intl.NumberFormat('fr-FR');
  const decimal = (n) => String(n).replace('.', ',');
  const STATES = { running: 'En cours', cancelling: 'Arrêt…', done: 'Terminée', cancelled: 'Arrêtée', failed: 'Interrompue' };

  let live = $state(null);
  let problem = $state('');
  let timer;

  const tasks = $derived(live ? [
    { name: 'Analyse', job: live.analysis, label: live.analysis?.stage },
    { name: 'Relecture', job: live.reread, label: live.reread?.step },
  ].filter((t) => t.job && t.job.state !== 'idle' && (!t.job.guild || t.job.guild === String(guild))) : []);
  const busy = $derived(tasks.some((t) => ['running', 'cancelling'].includes(t.job.state)));
  const computers = $derived(live?.computers ?? []);
  const working = $derived(computers.filter((c) => c.active > 0).length);
  const ago = (machine) => (machine.last_at ? Math.max(0, Math.round(live.now - machine.last_at)) : null);

  async function load() {
    if (document.hidden) return;
    try {
      live = await api.analysisLive();
      problem = '';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else problem = error.message;
    }
  }

  onMount(() => {
    load();
    timer = setInterval(load, 1000);
  });
  onDestroy(() => clearInterval(timer));

  function progressOf(job) {
    return job.of > 0 ? Math.round((100 * job.done) / job.of) : null;
  }
</script>

<div class="live">
  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  <section class="panel card" aria-label="Tâche en cours">
    <header class="head"><h2>Tâche en cours</h2><Help label="Comprendre le temps réel">Cette page se met à jour toutes les secondes. L’analyse et la relecture ne tournent jamais en même temps. Elle ne montre que des nombres et des durées, jamais un message.</Help></header>
    {#if !live}
      <p class="muted">Chargement…</p>
    {:else if !tasks.length}
      <p class="muted">Aucune analyse ni relecture en cours. Lancez-en une depuis les onglets Thèmes, Positions ou Relecture : la répartition entre les ordinateurs apparaîtra ici.</p>
    {:else}
      {#each tasks as task}
        <div class="task" class:active={['running', 'cancelling'].includes(task.job.state)}>
          <span class="badge" class:accent={['running', 'cancelling'].includes(task.job.state)} class:success={task.job.state === 'done'} class:danger={task.job.state === 'failed'}>{STATES[task.job.state]}</span>
          <strong>{task.name}</strong>
          {#if task.label}<span class="muted">{task.label}</span>{/if}
          {#if task.job.round && task.job.rounds !== 1}<span class="muted">étape {task.job.round}{task.job.rounds ? ` sur ${task.job.rounds}` : ''}</span>{/if}
          {#if task.job.of > 0}
            <progress max={task.job.of} value={task.job.done} aria-label="Avancement"></progress>
            <span class="numbers">{fmt.format(task.job.done)} / {fmt.format(task.job.of)}{progressOf(task.job) !== null ? ` · ${progressOf(task.job)} %` : ''}</span>
          {:else if ['running', 'cancelling'].includes(task.job.state)}<span class="muted">Préparation…</span>{/if}
          {#if task.job.error}<p class="banner" role="alert">{task.job.error}</p>{/if}
        </div>
        {#if task.job.lines?.length && ['running', 'cancelling'].includes(task.job.state)}
          <details class="log" open><summary>Journal</summary><pre>{task.job.lines.slice(-8).join('\n')}</pre></details>
        {/if}
      {/each}
    {/if}
  </section>

  <section class="panel card" aria-label="Répartition entre les ordinateurs">
    <header class="head">
      <h2>Ordinateurs</h2>
      {#if computers.length}<span class="muted small">{working} sur {computers.length} {working > 1 ? 'calculent' : 'calcule'} en ce moment{busy ? '' : ' · dernière activité'}</span>{/if}
    </header>
    {#if !live}
      <p class="muted">Chargement…</p>
    {:else if !live.pool}
      <p class="muted">Un seul ordinateur travaille : le serveur. Ajoutez des ordinateurs d’analyse dans Système pour répartir le travail entre eux.</p>
    {:else}
      <ul class="machines">
        {#each computers as machine (machine.url)}
          <li class:busy={machine.active > 0} class:down={machine.failed}>
            <span class="dot" aria-hidden="true"></span>
            <strong>{machine.name || (machine.local ? 'Serveur' : machine.url.replace('http://', ''))}</strong>
            <span class="share" title="Part des calculs reçus, et part visée par le réglage">{machine.observed} %{machine.share !== null ? ` / ${machine.share} % visés` : ''}</span>
            {#if machine.name}<span class="address muted small">{machine.url.replace('http://', '')}</span>{/if}
            <span class="state">
              {#if machine.failed}Hors service pour cette tâche
              {:else if machine.active > 0}Calcule : {machine.kind}{machine.running_for !== null ? ` · depuis ${Math.round(machine.running_for)} s` : ''}
              {:else if machine.calls > 0}En attente{ago(machine) !== null ? ` · dernier calcul il y a ${ago(machine)} s` : ''}
              {:else}Rien reçu pour l’instant{/if}
            </span>
            <progress max="100" value={machine.observed} aria-label="Part des calculs reçus"></progress>
            <span class="numbers">{fmt.format(machine.calls)} appels · {fmt.format(machine.items)} éléments{machine.average !== null ? ` · ${decimal(machine.average)} s en moyenne` : ''}</span>
            {#if machine.round}
              <span class="numbers">Étape {machine.round.number} : {fmt.format(machine.round.calls)} calculs{machine.round.average !== null ? ` · ${decimal(machine.round.average)} s en moyenne` : ''}</span>
            {/if}
            {#if machine.errors}<span class="err">{machine.errors} erreur{machine.errors > 1 ? 's' : ''}{machine.last_error ? ` · ${machine.last_error}` : ''}</span>{/if}
          </li>
        {/each}
      </ul>
      <p class="muted small">Les parts visées s’ajustent après chaque étape selon la vitesse de chaque ordinateur. Un ordinateur à 0 % reste en réserve.</p>
    {/if}
  </section>
</div>

<style>
  .live { display: flex; flex-direction: column; gap: 1rem; }
  .card { padding: 1rem 1.125rem; display: flex; flex-direction: column; gap: .875rem; }
  .head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .5rem 1rem; }
  h2 { font-size: 1rem; color: var(--text-primary); display: inline-flex; align-items: center; gap: .5rem; }
  .task { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem .75rem; }
  .task progress { flex: 1 1 14rem; height: .7rem; accent-color: var(--accent, #8b6cff); }
  .numbers { font-variant-numeric: tabular-nums; color: var(--text-secondary); }
  .log pre { max-height: 10rem; overflow: auto; font-size: .75rem; white-space: pre-wrap; }
  .machines { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, max(19rem, calc((100% - 1.8rem) / 4))), 1fr)); gap: .6rem; }
  .machines li { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: .3rem .6rem; padding: .85rem .95rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-secondary); font-size: .8125rem; font-variant-numeric: tabular-nums; }
  .machines li.busy { border-color: var(--accent, #8b6cff); box-shadow: inset 0 0 0 1px var(--accent, #8b6cff); }
  .machines li.down { opacity: .7; }
  .dot { width: .65rem; height: .65rem; border-radius: 50%; background: var(--text-muted); }
  li.busy .dot { background: var(--accent, #8b6cff); animation: machine-pulse 1.1s ease-in-out infinite; }
  li.down .dot { background: var(--danger, #d9534f); }
  .machines strong { color: var(--text-primary); overflow-wrap: anywhere; }
  .machines .state, .machines .numbers { grid-column: 1 / -1; color: var(--text-secondary); }
  .machines .address { grid-column: 1 / -1; overflow-wrap: anywhere; }
  .machines .share { color: var(--text-primary); font-weight: 600; }
  .machines progress { grid-column: 1 / -1; width: 100%; height: .5rem; accent-color: var(--accent, #8b6cff); }
  .machines .err { grid-column: 1 / -1; color: var(--danger, #d9534f); overflow-wrap: anywhere; }
  .small { font-size: .8125rem; }
  @keyframes machine-pulse { 50% { opacity: .35; } }
  @media (prefers-reduced-motion: reduce) { li.busy .dot { animation: none; } }
</style>
