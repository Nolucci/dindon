<script>
  import ExportMenu from './ExportMenu.svelte';
  import { api, AuthError } from '../lib/api.js';
  import AxisBar from './AxisBar.svelte';
  import { matches, slash } from '../lib/text.js';

  let { guild, onAuthLost, onPerson, embedded = false } = $props();

  let data = $state(null);
  let problem = $state('');
  let verdictFilter = $state('discordant');   // discordant | concordant | not_verifiable | all
  let q = $state('');                         // a name, or a role
  let roleFilter = $state('');
  let evidenceFor = $state([]);

  const STANCE = { 1: 'Pour', 0: 'Nuancé', '-1': 'Contre' };
  const VERDICT = { discordant: ['À examiner', 'danger'], concordant: ['Sans contradiction repérée', 'success'], not_verifiable: ['Pas assez de propos', ''] };

  $effect(() => {
    const server = guild;
    if (!server) return;
    data = null;
    evidenceFor = [];
    api.coherence(server).then((d) => { if (server !== guild) return; data = d; problem = ''; }).catch((error) => {
      if (server !== guild) return;
      if (error instanceof AuthError) onAuthLost();
      else problem = error.message;
    });
  });

  const roleNames = $derived([...new Set((data?.people ?? []).flatMap((p) => p.roles.map((r) => r.role)))].sort((a, b) => a.localeCompare(b, 'fr')));
  const shown = $derived((data?.people ?? []).filter((p) =>
    matches(q, p.label, p.roles.map((r) => r.role).join(' ')) &&
    (roleFilter === '' || p.roles.some((r) => r.role === roleFilter)) &&
    (verdictFilter === 'all' || (verdictFilter === 'discordant' ? p.roles.some((r) => r.verdict === 'discordant') : verdictFilter === 'conflicts' ? p.role_conflict : p.roles.some((r) => r.verdict === verdictFilter)))));
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
        <div class="metric"><dt>Personnes</dt><dd>{data.totals.people}</dd></div>
        <div class="metric"><dt>À examiner</dt><dd class="bad">{data.totals.discordant}</dd></div>
        <div class="metric"><dt>Sans contradiction repérée</dt><dd>{data.totals.concordant}</dd></div>
        <div class="metric"><dt>Pas assez de propos</dt><dd>{data.totals.not_verifiable}</dd></div>
      </dl>
      <div class="actions">
        <ExportMenu {guild} part="contradictions" />
      </div>
      <div class="toolbar" role="search" aria-label="Chercher dans la liste">
        <input class="field-input" type="search" placeholder="Chercher une personne ou un rôle… (/)" bind:value={q} aria-label="Chercher une personne ou un rôle" use:slash />
        <select class="select" bind:value={verdictFilter} aria-label="Filtrer par verdict">
          <option value="discordant">Positions à examiner</option>
          <option value="conflicts">Rôles incompatibles</option>
          <option value="concordant">Sans contradiction repérée</option>
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
        <p class="banner info">Les propos disponibles ne suffisent pas à vérifier ces rôles.</p>
      {/if}
    </section>

    {#if !shown.length}<p class="muted empty">{filtering ? 'Personne ne correspond à ces filtres.' : 'Aucune contradiction repérée pour l’instant.'}</p>{/if}
    <ul class="list">
      {#each shown as p (p.id)}
        <li class="panel person">
          <header><strong>{p.label}</strong>{#if p.role_conflict}<span class="badge small danger">rôles qui s’excluent</span>{/if}<button type="button" class="btn evidence" aria-expanded={evidenceFor.includes(p.id)} onclick={() => evidenceFor = evidenceFor.includes(p.id) ? evidenceFor.filter((id) => id !== p.id) : [...evidenceFor, p.id]}>Voir les citations</button><button type="button" class="tool-btn" onclick={() => onPerson(p.id)}>Voir le profil</button></header>
          {#if p.role_conflict}<p class="small">Rôles incompatibles.</p>{/if}
          {#each p.roles as r}
            {#if verdictFilter !== 'discordant' || r.verdict === 'discordant'}
            <div class="role">
              <div class="roleHead"><span class="roleName">{r.role}</span><span class="badge small" class:success={r.verdict === 'concordant'} class:danger={r.verdict === 'discordant'}>{VERDICT[r.verdict][0]}</span></div>
              {#each r.against as a}
                <div class="against">
                  <p class="small">{a.axis} · {a.positions} position{a.positions > 1 ? 's' : ''} en contradiction.</p>
                    {#if evidenceFor.includes(p.id)}<ul class="said">
                      {#each a.contributions as c}
                        <li>
                          <span class="badge small" class:success={c.stance === 1} class:danger={c.stance === -1}>{STANCE[c.stance]}</span> {c.proposition}
                          <span class="muted small">{c.validated ? 'Lien validé' : 'Lien à examiner'}</span>
                          {#each c.evidence as e}<blockquote>« {e.quote} »<span class="muted small"> {e.channel ? `#${e.channel} · ` : ''}{e.at ? e.at.slice(0, 10) : ''}</span></blockquote>{/each}
                        </li>
                      {/each}
                    </ul>{/if}
                  <details><summary>Voir le calcul</summary><AxisBar axis={asAxis(a)} compact /><p class="small">Score {a.score.toFixed(2)} (± {a.uncertainty.toFixed(2)}) ; ce rôle attend entre {a.expected[0]} et {a.expected[1]}.</p>
                  </details>
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
  .page { flex: 1; min-height: 0; overflow-y: auto; padding: 1.5rem clamp(1rem, 3vw, 2.5rem) 2.5rem; display: flex; flex-direction: column; gap: 1.25rem; animation: fadeIn var(--transition-slow) both; }
  .page.embedded { flex: none; min-height: auto; overflow: visible; padding: 0; animation: none; }
  h1 { font-size: clamp(1.5rem, 2vw, 1.9rem); line-height: 1.1; font-weight: 700; color: var(--text-primary); }
  .subtitle { max-width: 70ch; margin-top: 0.5rem; color: var(--text-secondary); }
  .card { padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem; }
  .counts { display: flex; flex-wrap: wrap; gap: .75rem; }
  .metric { flex: 1 1 9rem; display: flex; flex-direction: column; gap: .25rem; padding: .25rem .5rem; border-left: 2px solid var(--border-subtle); }
  .metric dt { font-size: 0.6875rem; font-weight: 700; letter-spacing: normal; text-transform: none; color: var(--text-muted); }
  .metric dd { font-size: 1.25rem; font-weight: 700; color: var(--text-primary); font-variant-numeric: tabular-nums; }
  .metric dd.bad { color: #ed4245; }
  .list { list-style: none; display: flex; flex-direction: column; gap: 0.625rem; }
  .person { padding: 1rem 1.125rem; display: flex; flex-direction: column; gap: 0.625rem; }
  .person > header { display: flex; flex-wrap: wrap; align-items: center; gap: 0.625rem; }
  .evidence { margin-left: auto; }
  .role { display: flex; flex-direction: column; gap: 0.375rem; }
  .roleHead { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
  .roleName { font-weight: 600; color: var(--text-primary); }
  .against { max-width: 36rem; display: flex; flex-direction: column; gap: 0.375rem; }
  .small { font-size: 0.75rem; color: var(--text-secondary); }
  details summary { cursor: pointer; font-size: 0.75rem; color: var(--text-secondary); }
  details .small { margin-top: 0.375rem; }
  .said { list-style: none; display: flex; flex-direction: column; gap: 0.625rem; margin-top: 0.5rem; font-size: 0.8125rem; color: var(--text-primary); }
  .said blockquote { margin: 0.25rem 0 0; padding: 0.25rem 0.625rem; border-left: 3px solid var(--border-subtle); color: var(--text-secondary); line-height: 1.45; }
  .badge.small { min-height: 1.5rem; font-size: 0.6875rem; }
  @media (max-width: 720px) { .page { padding: 1rem 1rem 2rem; } }
</style>
