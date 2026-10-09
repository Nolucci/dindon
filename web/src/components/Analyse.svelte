<script>
  import Help from './Help.svelte';
  import { api, AuthError } from '../lib/api.js';
  import Themes from './Themes.svelte';
  import Positions from './Positions.svelte';
  import Coherence from './Coherence.svelte';
  import Reread from './Reread.svelte';
  import Live from './Live.svelte';

  let { guild, section = $bindable('themes'), onAuthLost, onAutomate, onPerson } = $props();

  let summary = $state(null);
  let info = $state(null);
  let jobRevision = 0;
  let job = $state(null);
  let problem = $state('');
  let page;
  let request = 0;
  const fmt = new Intl.NumberFormat('fr-FR');
  const steps = [
    { name: 'Compacteur', prefix: 'compacteur', section: 'themes' },
    { name: 'Partitionneur', prefix: 'partitionneur', section: 'themes' },
    { name: 'Classeur', prefix: 'classeur', section: 'positions' },
    { name: 'Juge', prefix: 'juge', section: 'coherence' },
  ];
  const active = $derived(job?.state === 'running' || job?.state === 'cancelling');
  const progress = $derived(job?.of > 0 ? Math.round(100 * job.done / job.of) : null);

  function stateOf(step) {
    if (!job || job.guild !== String(guild)) return 'idle';
    if (job.stage?.startsWith(step.prefix) && active) return 'running';
    if (job.completed_stages?.some((name) => name.startsWith(step.prefix))) return 'done';
    return 'idle';
  }

  function detailOf(step) {
    if (!summary) return 'Chargement…';
    if (step.prefix === 'compacteur') return `${fmt.format(summary?.kept ?? 0)} conversations utiles`;
    if (step.prefix === 'partitionneur') return `${fmt.format(summary?.embedded ?? 0)} vecteurs · ${fmt.format(summary?.proposed ?? 0)} thèmes à examiner`;
    if (step.prefix === 'classeur') return `${fmt.format(summary?.read ?? 0)} / ${fmt.format(summary?.kept ?? 0)} conversations lues`;
    return `${fmt.format(summary?.contradictions ?? 0)} contradictions à vérifier`;
  }

  async function loadSummary(server = guild) {
    if (!server) return;
    const current = ++request;
    try {
      const analysis = await api.analysis(server);
      if (current !== request || server !== guild) return;
      info = analysis;
      summary = {
        messages: analysis.counts.messages,
        conversations: analysis.counts.conversations,
        embedded: analysis.counts.embedded,
        proposed: analysis.counts.topics.proposed ?? 0,
        read: analysis.counts.read,
        kept: analysis.counts.kept,
        contradictions: analysis.counts.contradictions,
      };
      if (!job) job = analysis.job;
      problem = '';
    } catch (error) {
      if (current !== request) return;
      if (error instanceof AuthError) onAuthLost();
      else problem = error.message;
    }
  }

  function updateJob(answer) {
    jobRevision += 1;
    job = answer;
  }

  $effect(() => {
    const server = guild;
    const controller = new AbortController();
    summary = null;
    info = null;
    job = null;
    problem = '';
    let stopped = false;
    let timer;
    if (server) loadSummary(server);
    async function follow() {
      const revision = jobRevision;
      try {
        const answer = await api.analysisStatus({ signal: controller.signal });
        if (stopped || server !== guild || revision !== jobRevision) return;
        const wasActive = job?.state === 'running' || job?.state === 'cancelling';
        const changedRound = wasActive && answer.job.round && answer.job.round !== job?.round;
        job = answer.job;
        if ((wasActive && !['running', 'cancelling'].includes(job.state)) || changedRound) loadSummary(server);
      } catch (error) {
        if (error instanceof AuthError) onAuthLost();
      } finally {
        if (!stopped) timer = setTimeout(follow, 2000);
      }
    }
    if (server) follow();
    return () => { stopped = true; request += 1; controller.abort(); clearTimeout(timer); };
  });

  function select(name) {
    section = name;
    page?.scrollTo({ top: 0, behavior: 'instant' });
  }
</script>

<main class="analysisPage" bind:this={page}>
  <div class="content">
    <header class="intro">

      <h1>Analyse</h1>
      <p>{summary ? `${fmt.format(summary.messages)} message${summary.messages > 1 ? 's' : ''} · ${fmt.format(summary.conversations)} conversation${summary.conversations > 1 ? 's' : ''}` : 'Chargement de l’analyse…'}</p>
    </header>

    {#if !guild}
      <p class="empty">Aucun serveur importé.</p>
    {:else}
      {#if problem}<p class="banner" role="alert">{problem}</p>{/if}
      <nav class="sections" aria-label="Sections de l’analyse">
        <button type="button" class:active={section === 'themes'} aria-current={section === 'themes' ? 'page' : undefined} onclick={() => select('themes')}>Thèmes</button>
        <button type="button" class:active={section === 'positions'} aria-current={section === 'positions' ? 'page' : undefined} onclick={() => select('positions')}>Positions</button>
        <button type="button" class:active={section === 'coherence'} aria-current={section === 'coherence' ? 'page' : undefined} onclick={() => select('coherence')}>Contradictions</button>
        <button type="button" class:active={section === 'reread'} aria-current={section === 'reread' ? 'page' : undefined} onclick={() => select('reread')}>Relecture</button>
        <button type="button" class:active={section === 'live'} aria-current={section === 'live' ? 'page' : undefined} onclick={() => select('live')}>Temps réel</button>
      </nav>
      {#if active && job?.guild === String(guild)}
        <div class="live" role="status" aria-live="polite">
          <strong>{job.stage}</strong>
          {#if job.of !== null && job.of > 0}
            <progress max={job.of} value={job.done}></progress><span>{fmt.format(job.done)} / {fmt.format(job.of)} · {progress} %</span>
          {:else}<span>Préparation du lot…</span>{/if}
        </div>
      {:else if job?.state === 'failed' && job.guild === String(guild)}
        <p class="banner" role="alert">Analyse interrompue : {job.error}</p>
      {/if}

      <section class="detail" aria-label={section === 'themes' ? 'Thèmes' : section === 'positions' ? 'Positions' : section === 'reread' ? 'Relecture' : section === 'live' ? 'Temps réel' : 'Contradictions'}>
        <div class="detailIntro">
          {#if section === 'themes'}
            <h2>Thèmes</h2>
          {:else if section === 'positions'}
            <h2>Positions</h2>
          {:else if section === 'reread'}
            <h2>Relecture</h2>
          {:else if section === 'live'}
            <h2>Temps réel</h2>
          {:else}
            <h2>Contradictions</h2>
          {/if}
          {#if section !== 'reread' && section !== 'live'}<Help label="Comprendre cette section">{section === 'themes' ? 'Regroupe les conversations par sujet. Validez les thèmes qui vous semblent pertinents.' : section === 'positions' ? 'Ouvrez une proposition pour voir les positions et leurs citations.' : 'Compare les rôles déclarés aux propos disponibles. Une contradiction reste à vérifier dans les citations.'}</Help>{/if}
        </div>
        {#if section === 'themes'}
          <Themes {guild} {onAuthLost} {onAutomate} embedded analysisInfo={info} analysisJob={job} onJob={updateJob} onUpdate={loadSummary} />
        {:else if section === 'positions'}
          <Positions {guild} {onAuthLost} {onAutomate} embedded analysisInfo={info} analysisJob={job} onJob={updateJob} onUpdate={loadSummary} />
        {:else if section === 'reread'}
          <Reread {guild} {onAuthLost} {onPerson} embedded />
        {:else if section === 'live'}
          <Live {guild} {onAuthLost} />
        {:else}
          <Coherence {guild} {onAuthLost} {onPerson} embedded />
        {/if}
      </section>
      <details class="analysisDetails"><summary>Suivi de l’analyse</summary>
      <div class="pipeline" aria-label="Progression de l’analyse">
        {#each steps as step, index}
          <button type="button" class:current={stateOf(step) === 'running'} class:complete={stateOf(step) === 'done'} onclick={() => select(step.section)}>
            <span class="stepTop"><span class="stepNumber">{index + 1}</span><strong>{step.name}</strong><span class="stepState">{stateOf(step) === 'running' ? 'En cours' : stateOf(step) === 'done' ? 'Fait' : ''}</span></span>
            <span class="stepDetail">{detailOf(step)}</span>
          </button>
        {/each}
      </div>
      </details>
    {/if}
  </div>
</main>

<style>
  .analysisDetails { color: var(--text-secondary); }
  .analysisDetails[open] > summary { margin-bottom: .5rem; }
  .analysisPage { flex: 1; min-height: 0; overflow-y: auto; background: var(--bg-primary); }
  .content { width: 100%; margin: 0 auto; padding: 1.5rem clamp(1rem, 3vw, 2.5rem) 2.5rem; display: flex; flex-direction: column; gap: 1.5rem; }
  .intro h1 { margin: .25rem 0 .5rem; font-size: clamp(1.7rem, 2.5vw, 2.1rem); line-height: 1.1; color: var(--text-primary); }
  .intro p { color: var(--text-secondary); max-width: 72ch; }
  .pipeline { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .55rem; }
  .pipeline button { display: flex; flex-direction: column; gap: .75rem; min-height: 6rem; text-align: left; padding: .85rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-secondary); color: var(--text-primary); cursor: pointer; font: inherit; }
  .pipeline button:hover, .pipeline button:focus-visible { border-color: var(--text-muted); }
  .pipeline button.current { border-color: var(--accent, #8b6cff); box-shadow: inset 0 0 0 1px var(--accent, #8b6cff); }
  .pipeline button.complete .stepNumber { background: var(--accent, #8b6cff); color: white; }
  .stepTop { display: flex; flex-wrap: wrap; align-items: center; gap: .45rem; font-size: .9rem; }
  .stepTop strong { flex: 1 1 5rem; min-width: 0; }
  .stepNumber { display: inline-grid; place-items: center; flex: none; width: 1.4rem; height: 1.4rem; border-radius: 50%; background: var(--bg-primary); font-size: .72rem; }
  .stepState { margin-left: auto; color: var(--text-muted); font-size: .7rem; }
  .stepDetail { color: var(--text-secondary); font-size: .78rem; font-variant-numeric: tabular-nums; }
  .live { display: flex; align-items: center; flex-wrap: wrap; gap: .75rem; padding: .75rem 1rem; border-radius: var(--radius-lg); background: var(--bg-secondary); font-size: .8rem; font-variant-numeric: tabular-nums; }
  .live progress { flex: 1 1 10rem; height: .65rem; accent-color: var(--accent, #8b6cff); }
  .sections { position: sticky; top: 0; z-index: 2; display: flex; gap: .3rem; padding: .35rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-primary); }
  .sections button { flex: 1; min-width: 0; padding: .65rem .75rem; border: 0; border-radius: var(--radius-md); background: transparent; color: var(--text-secondary); font: inherit; font-weight: 600; cursor: pointer; }
  .sections button:hover, .sections button:focus-visible { color: var(--text-primary); background: var(--bg-secondary); }
  .sections button.active { color: var(--text-primary); background: var(--bg-secondary); box-shadow: inset 0 0 0 1px var(--border-subtle); }
  .detail { display: flex; flex-direction: column; gap: 1rem; }
  .detailIntro { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  .detailIntro h2 { margin: 0 0 .35rem; font-size: 1.2rem; color: var(--text-primary); }
  .empty { padding: 1.25rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); color: var(--text-secondary); }
  @media (max-width: 720px) { .content { padding: 1rem 1rem 2rem; } .pipeline { grid-template-columns: repeat(2, minmax(0, 1fr)); } .sections button { padding: .6rem .25rem; font-size: .8rem; } }
  @media (max-width: 480px) {
    .sections { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .sections button { min-height: 44px; }
  }
</style>
