<script>
  import { api, AuthError } from '../lib/api.js';
  import Themes from './Themes.svelte';
  import Positions from './Positions.svelte';
  import Coherence from './Coherence.svelte';

  let { guild, section = $bindable('themes'), onAuthLost, onAutomate, onPerson } = $props();

  let summary = $state(null);
  let problem = $state('');
  let page;
  let request = 0;
  const fmt = new Intl.NumberFormat('fr-FR');

  async function loadSummary(server = guild) {
    if (!server) return;
    const current = ++request;
    try {
      const [analysis, positions, coherence] = await Promise.all([
        api.analysis(server), api.positions(server), api.coherence(server),
      ]);
      if (current !== request || server !== guild) return;
      summary = {
        proposed: analysis.counts.topics.proposed ?? 0,
        read: positions.conversations.read,
        kept: positions.conversations.kept,
        contradictions: coherence.totals.discordant,
      };
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
    problem = '';
    if (server) loadSummary(server);
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
      <p>Suivez les thèmes du serveur, vérifiez les positions lues dans les conversations et examinez les contradictions signalées.</p>
    </header>

    {#if !guild}
      <p class="empty">Aucun serveur n’est encore importé. Utilisez « Importer » pour commencer l’analyse.</p>
    {:else}
      {#if problem}<p class="banner" role="alert">{problem}</p>{/if}
      <div class="overview" aria-label="Résumé de l’analyse">
        <div>
          <span>Thèmes à examiner</span><strong>{summary ? fmt.format(summary.proposed) : '…'}</strong>
        </div>
        <div>
          <span>Conversations lues</span><strong>{summary ? `${fmt.format(summary.read)} / ${fmt.format(summary.kept)}` : '…'}</strong>
        </div>
        <div>
          <span>Contradictions</span><strong>{summary ? fmt.format(summary.contradictions) : '…'}</strong>
        </div>
      </div>

      <nav class="sections" aria-label="Sections de l’analyse">
        <button type="button" class:active={section === 'themes'} aria-current={section === 'themes' ? 'page' : undefined} onclick={() => select('themes')}>Thèmes</button>
        <button type="button" class:active={section === 'positions'} aria-current={section === 'positions' ? 'page' : undefined} onclick={() => select('positions')}>Positions</button>
        <button type="button" class:active={section === 'coherence'} aria-current={section === 'coherence' ? 'page' : undefined} onclick={() => select('coherence')}>Contradictions</button>
      </nav>

      <section class="detail" aria-label={section === 'themes' ? 'Thèmes' : section === 'positions' ? 'Positions' : 'Contradictions'}>
        <div class="detailIntro">
          {#if section === 'themes'}
            <h2>Thèmes</h2><p>Validez les sujets utiles, corrigez ou rejetez les autres.</p>
          {:else if section === 'positions'}
            <h2>Positions</h2><p>Lisez les conversations et vérifiez les positions avec leurs citations.</p>
          {:else}
            <h2>Contradictions</h2><p>Comparez les rôles déclarés aux propos tenus avant de conclure.</p>
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
  .overview { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .75rem; }
  .overview > div { display: flex; flex-direction: column; align-items: flex-start; gap: .55rem; padding: 1rem 1.1rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-secondary); color: var(--text-secondary); }
  .overview strong { font-size: 1.35rem; line-height: 1; font-variant-numeric: tabular-nums; color: var(--text-primary); }
  .sections { position: sticky; top: 0; z-index: 2; display: flex; gap: .3rem; padding: .35rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--bg-primary); }
  .sections button { flex: 1; min-width: 0; padding: .65rem .75rem; border: 0; border-radius: var(--radius-md); background: transparent; color: var(--text-secondary); font: inherit; font-weight: 600; cursor: pointer; }
  .sections button:hover, .sections button:focus-visible { color: var(--text-primary); background: var(--bg-secondary); }
  .sections button.active { color: var(--text-primary); background: var(--bg-secondary); box-shadow: inset 0 0 0 1px var(--border-subtle); }
  .detail { display: flex; flex-direction: column; gap: 1rem; }
  .detailIntro h2 { margin: 0 0 .35rem; font-size: 1.2rem; color: var(--text-primary); }
  .empty { padding: 1.25rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); color: var(--text-secondary); }
  @media (max-width: 720px) { .content { padding: 1.25rem 1rem 2rem; } .overview { gap: .4rem; } .overview > div { padding: .7rem; font-size: .75rem; } .overview strong { font-size: 1rem; } .sections button { padding: .6rem .25rem; font-size: .8rem; } }
</style>
