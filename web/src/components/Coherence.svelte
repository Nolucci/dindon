<script>
  import { api, AuthError } from '../lib/api.js';
  import AxisBar from './AxisBar.svelte';
  import { matches, slash } from '../lib/text.js';

  let { guild, onAuthLost, onPerson, embedded = false } = $props();

  let data = $state(null);
  let problem = $state('');
  let verdictFilter = $state('discordant');   // discordant | concordant | not_verifiable | all
  let q = $state('');                         // a name, or a role
  let roleFilter = $state('');

  const VERDICT = { discordant: ['Contradiction', 'danger'], concordant: ['Cohérent', 'success'], not_verifiable: ['Pas assez de propos', ''] };

  $effect(() => {
    if (!guild) return;
    data = null;
    api.coherence(guild).then((d) => { data = d; problem = ''; }).catch((error) => {
      if (error instanceof AuthError) onAuthLost();
      else problem = error.message;
    });
  });

  const roleNames = $derived([...new Set((data?.people ?? []).flatMap((p) => p.roles.map((r) => r.role)))].sort((a, b) => a.localeCompare(b, 'fr')));
  const shown = $derived((data?.people ?? []).filter((p) =>
    matches(q, p.label, p.roles.map((r) => r.role).join(' ')) &&
    (roleFilter === '' || p.roles.some((r) => r.role === roleFilter)) &&
    (verdictFilter === 'all' || (verdictFilter === 'discordant' ? p.roles.some((r) => r.verdict === 'discordant') || p.role_conflict : p.roles.some((r) => r.verdict === verdictFilter)))));
  const filtering = $derived(q.trim() !== '' || roleFilter !== '' || verdictFilter !== 'discordant');
  const asAxis = (a) => ({ name: a.axis, negative_pole: a.negative_pole, positive_pole: a.positive_pole, score: a.score, uncertainty: a.uncertainty,
                          expected: [{ role: '', min: a.expected[0], max: a.expected[1], verdict: 'incompatible' }] });
</script>

<div class="page" class:embedded>
  {#if !embedded}
  <header>
    <h1>Contradictions</h1>
    <p class="subtitle">
      Compare les rôles d’idées choisis par les personnes avec leurs positions lues. Ouvrez une fiche pour examiner les citations avant de conclure.
    </p>
  </header>
  {/if}

  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  {#if !guild}
    <section class="panel card"><p class="muted">Aucun serveur n’est encore importé.</p></section>
  {:else if !data}
    <p class="muted">Chargement…</p>
  {:else}
    <section class="panel card" aria-label="Résumé">
      <dl class="counts">
        <div class="metric"><dt>Personnes avec un rôle d’idées</dt><dd>{data.totals.people}</dd></div>
        <div class="metric"><dt>Contradictions</dt><dd class="bad">{data.totals.discordant}</dd></div>
        <div class="metric"><dt>Cohérents</dt><dd>{data.totals.concordant}</dd></div>
        <div class="metric"><dt>Pas assez de propos</dt><dd>{data.totals.not_verifiable}</dd></div>
      </dl>
      <div class="toolbar" role="search" aria-label="Chercher dans la liste">
        <input class="field-input" type="search" placeholder="Chercher une personne ou un rôle… (/)" bind:value={q} aria-label="Chercher une personne ou un rôle" use:slash />
        <select class="select" bind:value={verdictFilter} aria-label="Filtrer par verdict">
          <option value="discordant">Contradictions</option>
          <option value="concordant">Cohérents</option>
          <option value="not_verifiable">Pas assez de propos</option>
          <option value="all">Tous</option>
        </select>
        <select class="select" bind:value={roleFilter} aria-label="Filtrer par rôle">
          <option value="">Tous les rôles</option>
          {#each roleNames as r}<option value={r}>{r}</option>{/each}
        </select>
        {#if filtering}<button type="button" class="tool-btn reset" onclick={() => { q = ''; roleFilter = ''; verdictFilter = 'discordant'; }}>Effacer les filtres</button>{/if}
        <span class="found" aria-live="polite">{shown.length} personne{shown.length > 1 ? 's' : ''} sur {data.totals.people}</span>
      </div>
      {#if data.totals.not_verifiable === data.totals.people && data.totals.people > 0}
        <p class="banner info">Rien n’est encore vérifiable : il faut avoir lu les positions (section <strong>Positions</strong>) et les avoir reliées aux axes (étape « axes » de la lecture), et assez de propos par personne.</p>
      {/if}
    </section>

    {#if !shown.length}<p class="muted empty">{filtering ? 'Personne ne correspond à ces filtres.' : 'Aucune contradiction repérée pour l’instant.'}</p>{/if}
    <ul class="list">
      {#each shown as p (p.id)}
        <li class="panel person">
          <header><strong>{p.label}</strong>{#if p.role_conflict}<span class="badge small danger">rôles qui s’excluent</span>{/if}<button type="button" class="btn evidence" onclick={() => onPerson(p.id)}>Voir les citations</button></header>
          {#if p.role_conflict}<p class="small">Cette personne porte aussi des rôles d’idées incompatibles entre eux.</p>{/if}
          {#each p.roles as r}
            {#if verdictFilter !== 'discordant' || r.verdict === 'discordant'}
            <div class="role">
              <div class="roleHead"><span class="roleName">{r.role}</span><span class="badge small" class:success={r.verdict === 'concordant'} class:danger={r.verdict === 'discordant'}>{VERDICT[r.verdict][0]}</span></div>
              {#each r.against as a}
                <div class="against">
                  <p class="small">« {a.axis} » : {a.positions} position{a.positions > 1 ? 's' : ''} lue{a.positions > 1 ? 's' : ''} vont à l’encontre de ce rôle.</p>
                  <details><summary>Voir le calcul</summary><AxisBar axis={asAxis(a)} compact /><p class="small">Score {a.score.toFixed(2)} (± {a.uncertainty.toFixed(2)}) ; ce rôle attend entre {a.expected[0]} et {a.expected[1]}.</p></details>
                </div>
              {/each}
            </div>
            {/if}
          {/each}
          {#if verdictFilter === 'discordant' && p.roles.some((r) => r.verdict !== 'discordant')}
            <details><summary>Voir les autres rôles ({p.roles.filter((r) => r.verdict !== 'discordant').length})</summary>
              {#each p.roles.filter((r) => r.verdict !== 'discordant') as r}<p class="small">{r.role} · {VERDICT[r.verdict][0]}</p>{/each}
            </details>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .page { flex: 1; min-height: 0; overflow-y: auto; padding: 1.5rem 1.75rem 2.5rem; display: flex; flex-direction: column; gap: 1.25rem; animation: fadeIn var(--transition-slow) both; }
  .page.embedded { flex: none; min-height: auto; overflow: visible; padding: 0; animation: none; }
  h1 { font-size: clamp(1.5rem, 2vw, 1.9rem); line-height: 1.1; font-weight: 700; color: var(--text-primary); }
  .subtitle { max-width: 70ch; margin-top: 0.5rem; color: var(--text-secondary); }
  .card { padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem; }
  .counts { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.625rem; }
  .metric { display: flex; flex-direction: column; gap: 0.25rem; padding: 0.75rem 0.875rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); }
  .metric dt { font-size: 0.6875rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-muted); }
  .metric dd { font-size: 1.25rem; font-weight: 700; color: var(--text-primary); font-variant-numeric: tabular-nums; }
  .metric dd.bad { color: #ed4245; }
  .list { list-style: none; display: flex; flex-direction: column; gap: 0.625rem; }
  .person { padding: 1rem 1.125rem; display: flex; flex-direction: column; gap: 0.625rem; }
  .person > header { display: flex; align-items: center; gap: 0.625rem; }
  .evidence { margin-left: auto; }
  .role { display: flex; flex-direction: column; gap: 0.375rem; }
  .roleHead { display: flex; align-items: center; gap: 0.5rem; }
  .roleName { font-weight: 600; color: var(--text-primary); }
  .against { max-width: 36rem; display: flex; flex-direction: column; gap: 0.375rem; }
  .small { font-size: 0.75rem; color: var(--text-secondary); }
  details summary { cursor: pointer; font-size: 0.75rem; color: var(--text-secondary); }
  details .small { margin-top: 0.375rem; }
  .badge.small { min-height: 1.5rem; font-size: 0.6875rem; }
  @media (max-width: 720px) { .page { padding: 1rem 1rem 2rem; } }
</style>
