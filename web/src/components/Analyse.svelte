<script>
  import { api, AuthError } from '../lib/api.js';
  import Themes from './Themes.svelte';
  import Positions from './Positions.svelte';
  import Coherence from './Coherence.svelte';

  let { guild, section = $bindable('themes'), onAuthLost, onAutomate, onPerson } = $props();

  let summary = $state(null);
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
    if (step.prefix === 'compacteur') return `${fmt.format(summary?.kept ?? 0)} conversations utiles`;
    if (step.prefix === 'partitionneur') return `${fmt.format(summary?.embedded ?? 0)} vecteurs · ${fmt.format(summary?.proposed ?? 0)} thèmes à examiner`;
    if (step.prefix === 'classeur') return `${fmt.format(summary?.read ?? 0)} / ${fmt.format(summary?.kept ?? 0)} conversations lues`;
    return `${fmt.format(summary?.contradictions ?? 0)} contradictions à vérifier`;
  }

  async function loadSummary(server = guild) {
    if (!server) return;
    const current = ++request;
    try {
      const [analysis, positions, coherence] = await Promise.all([
        api.analysis(server), api.positions(server), api.coherence(server),
      ]);
      if (current !== request || server !== guild) return;
      summary = {
        messages: analysis.counts.messages,
        conversations: analysis.counts.conversations,
        embedded: analysis.counts.embedded,
        proposed: analysis.counts.topics.proposed ?? 0,
        read: positions.conversations.read,
        kept: positions.conversations.kept,
        contradictions: coherence.totals.discordant,
      };
      job = analysis.job;
      problem = '';
    } catch (error) {
      if (current !== request) return;
      if (error instanceof AuthError) onAuthLost();
      else problem = error.message;
    }
  }

  $effect(() => {
    const server = guild;
    summary = null;
    job = null;
    problem = '';
    if (server) loadSummary(server);
    const timer = setInterval(async () => {
      if (!server || server !== guild) return;
      try {
        const answer = await api.analysis(server);
        if (server !== guild) return;
        const wasActive = job?.state === 'running' || job?.state === 'cancelling';
        job = answer.job;
        summary = summary ? { ...summary, messages: answer.counts.messages, conversations: answer.counts.conversations,
          kept: answer.counts.kept, embedded: answer.counts.embedded, proposed: answer.counts.topics.proposed ?? 0 } : summary;
        if (wasActive && !['running', 'cancelling'].includes(job.state)) loadSummary(server);
      } catch (error) {
        if (error instanceof AuthError) onAuthLost();
      }
    }, 2000);
    return () => clearInterval(timer);
  });

  function select(name) {
    section = name;
    page?.scrollTo({ top: 0, behavior: 'instant' });
    loadSummary();
  }
</script>

<main class="analysisPage" bind:this={page}>
  <div class="content">
    <header class="intro">
      <span class="eyebrow">Vue d’ensemble</span>
      <h1>Analyse</h1>
      <p>{summary ? `${fmt.format(summary.messages)} messages importés · ${fmt.format(summary.conversations)} conversations` : 'Chargement de l’analyse…'}</p>
    </header>

    {#if !guild}
      <p class="empty">Aucun serveur n’est encore importé. Utilisez « Importer » pour commencer l’analyse.</p>
    {:else}
      {#if problem}<p class="banner" role="alert">{problem}</p>{/if}
      <div class="pipeline" aria-label="Progression de l’analyse">
        {#each steps as step, index}
          <button type="button" class:current={stateOf(step) === 'running'} class:complete={stateOf(step) === 'done'} onclick={() => select(step.section)}>
            <span class="stepTop"><span class="stepNumber">{index + 1}</span><strong>{step.name}</strong><span class="stepState">{stateOf(step) === 'running' ? 'En cours' : stateOf(step) === 'done' ? 'Fait' : ''}</span></span>
            <span class="stepDetail">{detailOf(step)}</span>
          </button>
        {/each}
      </div>
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
      {#if job?.computers?.length > 1 && job.guild === String(guild)}
        <section class="machines" aria-label="Activité de chaque ordinateur">
          <h2>Ordinateurs</h2>
          <ul>
            {#each job.computers as machine}
              <li class:busy={machine.active > 0} class:down={machine.failed}>
                <span class="dot" aria-hidden="true"></span>
                <strong>{machine.local ? 'Serveur' : machine.url.replace('http://', '')}</strong>
                <span class="state">
                  {#if machine.failed}Hors service pour cette analyse
                  {:else if machine.active > 0}Calcule : {machine.kind}{machine.running_for !== null ? ` · depuis ${Math.round(machine.running_for)} s` : ''}
                  {:else if machine.calls > 0}En attente
                  {:else}Rien reçu pour l’instant{/if}
                </span>
                <span class="numbers">
                  {fmt.format(machine.calls)} appels · {fmt.format(machine.items)} éléments{machine.average !== null ? ` · ${String(machine.average).replace('.', ',')} s en moyenne` : ''}
                </span>
                <span class="share" title="Part des appels reçus, comparée à la part demandée">
                  {machine.observed} %{machine.share !== null ? ` / ${machine.share} % demandés` : ''}
                </span>
                <progress max="100" value={machine.observed} aria-label="Part des appels reçus"></progress>
                {#if machine.errors}<span class="err">{machine.errors} erreur{machine.errors > 1 ? 's' : ''}{machine.last_error ? ` · ${machine.last_error}` : ''}</span>{/if}
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      <nav class="sections" aria-label="Sections de l’analyse">
        <button type="button" class:active={section === 'themes'} aria-current={section === 'themes' ? 'page' : undefined} onclick={() => select('themes')}>Thèmes</button>
        <button type="button" class:active={section === 'positions'} aria-current={section === 'positions' ? 'page' : undefined} onclick={() => select('positions')}>Positions</button>
        <button type="button" class:active={section === 'coherence'} aria-current={section === 'coherence' ? 'page' : undefined} onclick={() => select('coherence')}>Contradictions</button>
      </nav>

      <section class="detail" aria-label={section === 'themes' ? 'Thèmes' : section === 'positions' ? 'Positions' : 'Contradictions'}>
        <div class="detailIntro">
          {#if section === 'themes'}
            <h2>Thèmes</h2><p>Le compacteur retire le bruit ; le partitionneur regroupe les conversations. Validez les sujets utiles, corrigez ou rejetez les autres.</p>
          {:else if section === 'positions'}
            <h2>Positions</h2><p>Le classeur cherche des propositions précises dans chaque thème. Vérifiez les positions avec leurs citations.</p>
          {:else}
            <h2>Contradictions</h2><p>Le juge compare les rôles déclarés aux positions étayées. Ouvrez les citations avant de conclure.</p>
          {/if}
        </div>
        {#if section === 'themes'}
          <Themes {guild} {onAuthLost} {onAutomate} embedded onUpdate={loadSummary} />
        {:else if section === 'positions'}
          <Positions {guild} {onAuthLost} {onAutomate} embedded onUpdate={loadSummary} />
        {:else}
          <Coherence {guild} {onAuthLost} {onPerson} embedded />
        {/if}
      </section>
    {/if}
  </div>
</main>

<style>
  .analysisPage { flex: 1; min-height: 0; overflow-y: auto; background: var(--bg-primary); }
  .content { width: min(100%, 1120px); margin: 0 auto; padding: 2rem 2rem 3rem; display: flex; flex-direction: column; gap: 1.5rem; }
  .intro h1 { margin: .25rem 0 .5rem; font-size: clamp(1.7rem, 2.5vw, 2.1rem); line-height: 1.1; color: var(--text-primary); }
  .intro p, .detailIntro p { color: var(--text-secondary); max-width: 72ch; }
  .eyebrow { color: var(--text-muted); font-size: .7rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
  .pipeline { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .55rem; }
  .pipeline button { display: flex; flex-direction: column; gap: .75rem; min-height: 6rem; text-align: left; padding: .85rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-secondary); color: var(--text-primary); cursor: pointer; font: inherit; }
  .pipeline button:hover, .pipeline button:focus-visible { border-color: var(--text-muted); }
  .pipeline button.current { border-color: var(--accent, #8b6cff); box-shadow: inset 0 0 0 1px var(--accent, #8b6cff); }
  .pipeline button.complete .stepNumber { background: var(--accent, #8b6cff); color: white; }
  .stepTop { display: flex; align-items: center; gap: .45rem; font-size: .9rem; }
  .stepNumber { display: inline-grid; place-items: center; flex: none; width: 1.4rem; height: 1.4rem; border-radius: 50%; background: var(--bg-primary); font-size: .72rem; }
  .stepState { margin-left: auto; color: var(--text-muted); font-size: .7rem; }
  .stepDetail { color: var(--text-secondary); font-size: .78rem; font-variant-numeric: tabular-nums; }
  .live { display: flex; align-items: center; flex-wrap: wrap; gap: .75rem; padding: .75rem 1rem; border-radius: var(--radius-lg); background: var(--bg-secondary); font-size: .8rem; font-variant-numeric: tabular-nums; }
  .live progress { flex: 1 1 10rem; height: .65rem; accent-color: var(--accent, #8b6cff); }
  .machines h2 { margin: 0 0 .5rem; font-size: 1rem; color: var(--text-primary); }
  .machines ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr)); gap: .55rem; }
  .machines li { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: .25rem .5rem; padding: .75rem .85rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-secondary); font-size: .78rem; font-variant-numeric: tabular-nums; }
  .machines li.busy { border-color: var(--accent, #8b6cff); }
  .machines li.down { opacity: .7; }
  .machines .dot { width: .6rem; height: .6rem; border-radius: 50%; background: var(--text-muted); }
  .machines li.busy .dot { background: var(--accent, #8b6cff); animation: machine-pulse 1.1s ease-in-out infinite; }
  .machines li.down .dot { background: var(--danger, #d9534f); }
  .machines strong { color: var(--text-primary); overflow-wrap: anywhere; }
  .machines .state, .machines .numbers { grid-column: 1 / -1; color: var(--text-secondary); }
  .machines .share { color: var(--text-primary); }
  .machines progress { grid-column: 1 / -1; width: 100%; height: .45rem; accent-color: var(--accent, #8b6cff); }
  .machines .err { grid-column: 1 / -1; color: var(--danger, #d9534f); overflow-wrap: anywhere; }
  @keyframes machine-pulse { 50% { opacity: .35; } }
  @media (prefers-reduced-motion: reduce) { .machines li.busy .dot { animation: none; } }
  .sections { position: sticky; top: 0; z-index: 2; display: flex; gap: .3rem; padding: .35rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-primary); }
  .sections button { flex: 1; min-width: 0; padding: .65rem .75rem; border: 0; border-radius: var(--radius-md); background: transparent; color: var(--text-secondary); font: inherit; font-weight: 600; cursor: pointer; }
  .sections button:hover, .sections button:focus-visible { color: var(--text-primary); background: var(--bg-secondary); }
  .sections button.active { color: var(--text-primary); background: var(--bg-secondary); box-shadow: inset 0 0 0 1px var(--border-subtle); }
  .detail { display: flex; flex-direction: column; gap: 1rem; }
  .detailIntro h2 { margin: 0 0 .35rem; font-size: 1.2rem; color: var(--text-primary); }
  .empty { padding: 1.25rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); color: var(--text-secondary); }
  @media (max-width: 720px) { .content { padding: 1.25rem 1rem 2rem; } .pipeline { grid-template-columns: repeat(2, minmax(0, 1fr)); } .sections button { padding: .6rem .25rem; font-size: .8rem; } }
</style>
