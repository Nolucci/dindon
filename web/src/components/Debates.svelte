<script>
  import { onMount, onDestroy } from 'svelte';
  import { api, AuthError } from '../lib/api.js';

  let { onAuthLost } = $props();

  const fmt = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
  const when = (iso) => (iso ? fmt.format(new Date(iso)) : '—');
  const POSITIONS = { for: '✅ Pour', unsure: '❔ Ne sait pas', against: '❌ Contre', none: '— sans position' };
  // A debate opened from an axis is answered with the two poles of the axis (never ✅ / ❌, which would make one of them the right one)
  const names = (axis) => (axis ? { ...POSITIONS, for: `🔵 ${axis.for}`, against: `🟠 ${axis.against}` } : POSITIONS);
  const POSITION = $derived(names(detail?.debate.axis));
  const VERDICT = { confirmed: ['✅', 'confirmée', 'ok'], contradicted: ['❌', 'contredite', 'danger'], partly: ['🟡', 'en partie vraie', ''], disputed: ['⚖️', 'contestée', ''], likely_true: ['🔎', 'probablement vraie (provisoire)', ''], likely_false: ['🔎', 'probablement fausse (provisoire)', ''], unverifiable: ['❔', 'non vérifiable', ''] };
  const STATUS = { open: 'en cours', closed: 'terminé' };
  const REASON = { ended: 'terminé avec le bouton', silence: 'personne n’a écrit depuis longtemps', no_participants: 'personne n’a participé', failed: 'n’a pas pu être mené' };
  const QUIET = { 3600: '1 heure', 21600: '6 heures', 86400: '24 heures', 259200: '3 jours', 604800: '7 jours' };

  let overview = $state(null);
  let chosen = $state(null);
  let detail = $state(null);
  let problem = $state('');

  const host = (url) => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; } };
  const pct = (n) => `${Math.round(n * 100)} %`;
  const jump = (claim) => `https://discord.com/channels/${detail.debate.guild_id}/${detail.debate.thread_id}/${claim.message_id}`;

  function fail(error) {
    if (error instanceof AuthError) onAuthLost();
    else problem = error.message;
  }

  async function load() {
    try {
      overview = await api.debates();
      problem = '';
    } catch (error) {
      fail(error);
    }
  }

  async function open(id) {
    chosen = id;
    detail = null;
    try {
      detail = await api.debate(id);
      problem = '';
    } catch (error) {
      fail(error);
    }
  }

  // The computers that check the debates (the server and its helpers), as the bot last said it: refreshed every few seconds, and only while the page is visible
  let fleet = $state(null);
  let timer;
  const seconds = (n) => (n == null ? '—' : n < 60 ? `${Math.round(n)} s` : `${Math.floor(n / 60)} min ${Math.round(n % 60)} s`);
  const machine = (c) => (c.local ? 'Ce serveur' : c.url.replace(/^https?:\/\//, ''));
  const condition = (c) => (!c.online ? ['hors ligne', 'danger'] : !c.has_model ? ['modèle absent', 'danger'] : c.active ? [`calcule depuis ${seconds(c.running_for)}`, 'success'] : ['libre', '']);

  async function loadFleet() {
    if (document.hidden) return;
    try {
      fleet = await api.debateComputers();
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();                    // any other failure: the last figures stay
    }
  }

  onMount(() => {
    load();
    loadFleet();
    timer = setInterval(loadFleet, 3000);
  });
  onDestroy(() => clearInterval(timer));
</script>

<div class="page">
  <header>
    <h1>Débats</h1>
    <p class="subtitle">Les débats ouverts avec <code>/dindon debat</code> : qui a pris quelle position, ce que chacun a écrit, et ce que Dindon a vérifié sur Internet, avec la citation exacte et le lien de chaque source.</p>
  </header>

  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  {#if overview}
    <section class="panel card" aria-label="État de la vérification">
      <h2 class="eyebrow">Vérification des affirmations</h2>
      {#if overview.checks.mode === 'off'}
        <p class="muted">Désactivée : rien n’est lu et rien ne sort de la machine. Pour l’activer, voir « Comment l’activer » dans <code>docs/regles-du-bot.md</code>.</p>
      {:else}
        <p>
          Mode <strong>{overview.checks.mode === 'live' ? 'Dindon répond, et les sources corrigent' : overview.checks.mode === 'answer' ? 'Dindon répond d’abord, sans Internet' : 'observation (rien n’est publié)'}</strong>
          · modèle {overview.checks.model} · services : {overview.checks.search_services.join(', ') || 'aucun'}
        </p>
        {#if overview.checks.why_not}<p class="banner" role="status">Les corrections par les sources seules ne sont pas actives : {overview.checks.why_not}.</p>{/if}
      {/if}
    </section>

    <section class="panel card" aria-label="Ordinateurs de vérification">
      <h2 class="eyebrow">Ordinateurs qui vérifient les débats</h2>
      {#if !fleet || fleet.computers.length === 0}
        <p class="muted small">Rien à montrer : le bot n’a pas encore dit ce que font ses ordinateurs (aucun débat ne tourne, ou les vérifications sont désactivées).</p>
      {:else}
        {#if !fleet.fresh}<p class="banner" role="status">Le bot n’a rien dit depuis {seconds(fleet.age_seconds)} : les chiffres ci-dessous sont les derniers connus.</p>{/if}
        <table>
          <thead><tr><th>Ordinateur</th><th>État</th><th>Vérifications</th><th>Durée moyenne</th><th>Part du travail</th><th>Erreurs</th></tr></thead>
          <tbody>
            {#each fleet.computers as c (c.url)}
              {@const [label, tone] = condition(c)}
              <tr>
                <td>{machine(c)}</td>
                <td><span class="badge small {tone}">{label}</span>{#if c.active && c.kind}<span class="muted small"> · {c.kind}</span>{/if}</td>
                <td>{c.calls}</td>
                <td>{seconds(c.average)}</td>
                <td>{c.observed} %</td>
                <td>{c.errors}{#if c.last_error}<span class="muted small"> · {c.last_error}</span>{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        <p class="hint">Modèle : {fleet.model}. « Calcule » veut dire qu’une vérification est en cours sur cet ordinateur : Ollama ne donne pas le taux d’utilisation du processeur, la page montre donc ce que Dindon lui a demandé. Les chiffres repartent de zéro quand le bot redémarre.</p>
      {/if}
    </section>

    <div class="layout">
      <section class="panel card list" aria-label="Les débats">
        <h2 class="eyebrow">Les derniers débats</h2>
        {#if overview.debates.length === 0}
          <p class="muted">Aucun débat pour l’instant.</p>
        {:else}
          <ul>
            {#each overview.debates as d (d.id)}
              <li>
                <button type="button" class="pick" class:on={chosen === d.id} onclick={() => open(d.id)}>
                  <span class="name">{d.topic}</span>
                  <span class="badge small">{STATUS[d.status] ?? d.status}</span>
                  <span class="muted small">{d.participants} participant(s) · {d.messages} message(s){d.claims ? ` · ${d.claims} vérifiée(s)` : ''}</span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </section>

      <div class="detail">
        {#if chosen && !detail}<p class="muted">Chargement…</p>{/if}
        {#if detail}
          <section class="panel card" aria-label="Résumé">
            <h2 class="eyebrow">{detail.debate.topic}</h2>
            {#if detail.debate.axis}<p class="muted small">Question posée par Dindon · axe « {detail.debate.axis.name} »</p>{/if}
            <p class="muted small">
              {STATUS[detail.debate.status] ?? detail.debate.status}{detail.debate.close_reason ? ` (${REASON[detail.debate.close_reason] ?? detail.debate.close_reason})` : ''}
              · {detail.debate.in_thread ? 'dans un fil' : 'dans le salon'} · {detail.debate.verify ? 'affirmations vérifiées' : 'sans vérification'}
              · fin si personne n’écrit pendant {QUIET[detail.debate.quiet_seconds] ?? `${detail.debate.quiet_seconds} s`}
              · du {when(detail.debate.started_at)} au {when(detail.debate.closed_at)}
            </p>
            {#if detail.debate.context}<p class="muted small">Contexte : {detail.debate.context}</p>{/if}
            <p>
              <strong>{detail.totals.participants}</strong> participant(s) · <strong>{detail.totals.messages}</strong> message(s)
              · {detail.totals.changed_mind} ont changé de position
            </p>
            <ul class="bars">
              {#each Object.entries(detail.totals.final) as [position, n]}
                <li><span class="label">{POSITION[position]}</span><span class="count">{n}</span></li>
              {/each}
            </ul>
            {#if detail.messages_waiting_to_be_read}<p class="muted small">{detail.messages_waiting_to_be_read} message(s) attendent d’être lus.</p>{/if}
            {#if detail.corrections.posted || detail.corrections.taken_back}
              <p class="muted small">Corrections publiées : {detail.corrections.posted} · retirées : {detail.corrections.taken_back}</p>
            {/if}
          </section>

          <section class="panel card" aria-label="Participants">
            <h2 class="eyebrow">Participants</h2>
            <table>
              <thead><tr><th>Personne</th><th>Position</th><th>Messages</th><th>Message phare</th><th>Vérifiées</th></tr></thead>
              <tbody>
                {#each detail.participants as p (p.user_id)}
                  <tr>
                    <td>{p.name ?? p.user_id}</td>
                    <td>{POSITION[p.position ?? 'none']}{p.changed ? ` (avant : ${POSITION[p.first_position]})` : ''}</td>
                    <td>{p.messages} ({pct(p.share)})</td>
                    <td>
                      {#if p.key_message}
                        « {p.key_message.excerpt} »
                        {#if p.key_message.url}<a href={p.key_message.url} target="_blank" rel="noopener noreferrer">ouvrir</a>{/if}
                        <span class="muted small">({p.key_message.replies} rép., {p.key_message.reactions} réact.)</span>
                      {:else}—{/if}
                    </td>
                    <td>{Object.entries(p.claims).filter(([, n]) => n).map(([v, n]) => `${n} ${VERDICT[v][1]}`).join(', ') || '—'}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
            <p class="hint">Message phare : le plus commenté et le plus apprécié du fil (réponses ×3 + réactions), le même critère pour tout le monde.</p>
          </section>

          {#if detail.answers.length}
            <section class="panel card" aria-label="Réponses de Dindon">
              <h2 class="eyebrow">Réponses de Dindon, sans Internet</h2>
              <p class="muted small">Quand Dindon est certain qu’une affirmation est fausse, il le dit sous le message, sans source ; les participants jugent sa réponse. S’il y a plus d’Invalide, il cherche sur Internet.</p>
              <ul class="claims">
                {#each detail.answers as a (a.id)}
                  <li>
                    <p>
                      <span class="badge small {a.verdict === 'false' ? 'danger' : 'ok'}">{a.verdict === 'false' ? 'jugée fausse' : 'jugée exacte (rien dit)'}</span>
                      <strong>« {a.claim} »</strong>
                      <a href={jump(a)} target="_blank" rel="noopener noreferrer">le message</a>
                    </p>
                    {#if a.answer}<p class="source">{a.answer}</p>{/if}
                    {#if a.verdict === 'false'}
                      <p class="muted small">✅ Valide {a.valid} · ❌ Invalide {a.invalid}{a.searched ? ` · Dindon a cherché sur Internet${a.found ? ` : ${VERDICT[a.found][1]}` : ' (impossible)'}` : ''}</p>
                    {/if}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          {#if detail.claims.length}
            <section class="panel card" aria-label="Affirmations vérifiées">
              <h2 class="eyebrow">Affirmations vérifiées</h2>
              {#if Object.keys(detail.parity).length}
                <table class="parity" aria-label="Parité par position">
                  <thead><tr><th>Position</th><th>Vérifiées</th>{#each detail.verdicts as v}<th>{VERDICT[v][1]}</th>{/each}</tr></thead>
                  <tbody>
                    {#each Object.entries(detail.parity) as [position, row]}
                      <tr><td>{POSITION[position]}</td><td>{row.total}</td>{#each detail.verdicts as v}<td>{row[v]}</td>{/each}</tr>
                    {/each}
                  </tbody>
                </table>
              {/if}
              <ul class="claims">
                {#each detail.claims as c (c.id)}
                  <li>
                    <p>
                      <span class="badge small {VERDICT[c.verdict][2]}">{VERDICT[c.verdict][0]} {VERDICT[c.verdict][1]}</span>
                      <strong>« {c.claim} »</strong>
                      <span class="muted small">— {c.author_name ?? c.author_id}{c.period ? ` · ${c.period}` : ''} · {c.queries} recherche(s), {c.pages} page(s)</span>
                      <a href={jump(c)} target="_blank" rel="noopener noreferrer">le message</a>
                    </p>
                    {#each c.sources as s}
                      <p class="source">
                        <a href={s.url} target="_blank" rel="noopener noreferrer">{host(s.url)}</a>
                        <span class="muted small">({s.tier === 'official' ? 'source officielle' : s.tier === 'checker' ? 'vérification de presse' : 'autre source, non vérifiée par Dindon'}, {s.stance === 'supports' ? 'confirme' : s.stance === 'contradicts' ? 'contredit' : 'en partie'})</span>
                        : « {s.quote} »
                      </p>
                    {/each}
                  </li>
                {/each}
              </ul>
            </section>
          {/if}
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .page { flex: 1; min-height: 0; overflow-y: auto; padding: 1.5rem 1.75rem 2.5rem; display: flex; flex-direction: column; gap: 1.25rem; animation: fadeIn var(--transition-slow) both; }
  h1 { font-size: clamp(1.5rem, 2vw, 1.9rem); line-height: 1.1; font-weight: 700; color: var(--text-primary); }
  .subtitle { max-width: 68ch; margin-top: 0.5rem; color: var(--text-secondary); }
  .card { padding: 1rem 1.125rem; display: flex; flex-direction: column; gap: 0.75rem; box-shadow: var(--shadow-sm); }
  .layout { display: grid; grid-template-columns: minmax(16rem, 22rem) 1fr; gap: 1.25rem; align-items: start; }
  .detail { display: flex; flex-direction: column; gap: 1.25rem; min-width: 0; }
  ul { list-style: none; display: flex; flex-direction: column; }
  .pick { width: 100%; display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; padding: 0.5rem 0.25rem; background: none; border: 1px solid transparent; border-radius: var(--radius-md); color: inherit; font: inherit; text-align: left; cursor: pointer; }
  .pick:hover, .pick.on { background: var(--surface-control); border-color: var(--border-subtle); }
  .name { flex: 1 1 100%; color: var(--text-primary); font-weight: 500; }
  .bars { flex-direction: row; flex-wrap: wrap; gap: 1rem; }
  .bars .count { margin-left: 0.4rem; font-weight: 700; color: var(--text-primary); }
  table { width: 100%; border-collapse: collapse; font-size: 0.8125rem; }
  th, td { text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border-subtle); vertical-align: top; }
  th { color: var(--text-muted); font-weight: 600; }
  .claims li { padding: 0.5rem 0; border-bottom: 1px solid var(--border-subtle); display: flex; flex-direction: column; gap: 0.25rem; }
  .source { padding-left: 1rem; font-size: 0.8125rem; color: var(--text-secondary); }
  a { color: var(--accent, #5865f2); }
  .hint { font-size: 0.75rem; line-height: 1.5; color: var(--text-muted); }
  .small { font-size: 0.75rem; }
  .badge.small { min-height: 1.5rem; font-size: 0.6875rem; }
  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .page { padding: 1rem 1rem 2rem; } }
</style>
