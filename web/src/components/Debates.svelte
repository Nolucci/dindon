<script>
  import Help from './Help.svelte';
  import { onMount } from 'svelte';
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
      const answer = await api.debate(id);
      if (chosen !== id) return;
      detail = answer;
      problem = '';
    } catch (error) {
      fail(error);
    }
  }

  onMount(load);
</script>

<div class="page">
  <header>
    <h1>Débats</h1>

  </header>

  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  {#if overview}
    <div class="layout" class:selected={chosen !== null}>
      <section class="panel card list" aria-label="Les débats">
        <h2 class="eyebrow">{overview.debates.length} débats</h2>
        {#if overview.debates.length === 0}
          <p class="muted">Aucun débat pour l’instant.</p>
        {:else}
          <ul>
            {#each overview.debates as d (d.id)}
              <li>
                <button type="button" class="pick" class:on={chosen === d.id} onclick={() => open(d.id)}>
                  <span class="name">{d.topic}</span>
                  <span class="badge small">{STATUS[d.status] ?? d.status}</span>
                  <span class="muted small">{d.participants} participant{d.participants > 1 ? 's' : ''} · {d.messages} message{d.messages > 1 ? 's' : ''}{d.claims ? ` · ${d.claims} examinée${d.claims > 1 ? 's' : ''}` : ''}</span>
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
            <button type="button" class="tool-btn back" onclick={() => { chosen = null; detail = null; }}>← Tous les débats</button>
            <h2 class="debateTitle">{detail.debate.topic}</h2>
            {#if detail.debate.axis}<p class="muted small">{detail.debate.axis.name}</p>{/if}
            <p class="muted small">{STATUS[detail.debate.status] ?? detail.debate.status} · {when(detail.debate.started_at)}</p>
            <details><summary>Détails du débat</summary>            <p class="muted small">
              {STATUS[detail.debate.status] ?? detail.debate.status}{detail.debate.close_reason ? ` (${REASON[detail.debate.close_reason] ?? detail.debate.close_reason})` : ''}
              · {detail.debate.in_thread ? 'dans un fil' : 'dans le salon'} · {detail.debate.verify ? 'affirmations vérifiées' : 'sans vérification'}
              · fin si personne n’écrit pendant {QUIET[detail.debate.quiet_seconds] ?? `${detail.debate.quiet_seconds} s`}
              · du {when(detail.debate.started_at)} au {when(detail.debate.closed_at)}
            </p>
</details>
            {#if detail.debate.context}<details><summary>Contexte</summary><p class="muted small">{detail.debate.context}</p></details>{/if}
            <p>
              <strong>{detail.totals.participants}</strong> participant{detail.totals.participants > 1 ? 's' : ''} · <strong>{detail.totals.messages}</strong> message{detail.totals.messages > 1 ? 's' : ''}
              {#if detail.totals.changed_mind}· {detail.totals.changed_mind} changement{detail.totals.changed_mind > 1 ? 's' : ''} de position{/if}
            </p>
            <ul class="bars">
              {#each Object.entries(detail.totals.final).filter(([, n]) => n > 0) as [position, n]}
                <li><span class="label">{POSITION[position]}</span><span class="count">{n}</span></li>
              {/each}
            </ul>
            {#if detail.messages_waiting_to_be_read}<p class="muted small">{detail.messages_waiting_to_be_read} message{detail.messages_waiting_to_be_read > 1 ? 's' : ''} à lire.</p>{/if}
            {#if detail.corrections.posted || detail.corrections.taken_back}
              <p class="muted small">Corrections publiées : {detail.corrections.posted} · retirées : {detail.corrections.taken_back}</p>
            {/if}
          </section>

          {#if detail.participants.length}
          <section class="panel card" aria-label="Participants">
            <header class="cardHead"><h2 class="eyebrow">Participants</h2><Help label="Comment est choisi le message phare ?">Le message qui reçoit le plus de réponses et de réactions (réponses × 3 + réactions). Le même critère pour tout le monde.</Help></header>
            <ul class="participants">
              {#each detail.participants as p (p.user_id)}
                <li>
                  <header class="cardHead"><strong>{p.name ?? p.user_id}</strong><span class="badge small">{POSITION[p.position ?? 'none']}</span></header>
                  <p class="muted small">{p.messages} message{p.messages > 1 ? 's' : ''} · {pct(p.share)}{p.changed && p.first_position !== p.position ? ` · avant : ${POSITION[p.first_position]}` : ''}</p>
                  {#if p.key_message}
                    <details><summary>Message phare</summary><blockquote>{p.key_message.excerpt}</blockquote>
                      {#if p.key_message.url}<a href={p.key_message.url} target="_blank" rel="noopener noreferrer">Voir sur Discord</a>{/if}
                    </details>
                  {/if}
                  {#if Object.values(p.claims).some((n) => n)}<p class="muted small">{Object.entries(p.claims).filter(([, n]) => n).map(([v, n]) => `${n} ${VERDICT[v][1]}`).join(' · ')}</p>{/if}
                </li>
              {/each}
            </ul>
          </section>

          {/if}

          {#if detail.answers.some((a) => !detail.claims.some((c) => c.message_id === a.message_id && c.claim === a.claim))}
            <section class="panel card" aria-label="Réponses de Dindon">
              <header class="cardHead"><div class="answerTitle"><h2 class="eyebrow">Réponses de Dindon</h2><span class="badge small">Sans source</span></div><Help label="À propos des réponses de Dindon">Réponses provisoires, sans source. Les votes permettent de demander une vérification.</Help></header>
              <ul class="claims">
                {#each detail.answers.filter((a) => !detail.claims.some((c) => c.message_id === a.message_id && c.claim === a.claim)) as a (a.id)}
                  <li>
                    <p>
                      <span class="badge small {a.verdict === 'false' ? 'danger' : 'ok'}">{a.verdict === 'false' ? 'jugée fausse' : 'jugée exacte'}</span>
                      <strong>« {a.claim} »</strong>
                      <a href={jump(a)} target="_blank" rel="noopener noreferrer">Voir sur Discord</a>
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
            <section class="panel card" aria-label="Affirmations examinées">
              <h2 class="eyebrow">Affirmations examinées</h2>
              {#if Object.keys(detail.parity).length}
                <details><summary>Répartition par position</summary>                <div class="parityScroll"><table class="parity" aria-label="Parité par position">
                  <thead><tr><th>Position</th><th>Examinées</th>{#each detail.verdicts.filter((v) => detail.claims.some((c) => c.verdict === v)) as v}<th>{VERDICT[v][1]}</th>{/each}</tr></thead>
                  <tbody>
                    {#each Object.entries(detail.parity) as [position, row]}
                      <tr><td>{POSITION[position]}</td><td>{row.total}</td>{#each detail.verdicts.filter((v) => detail.claims.some((c) => c.verdict === v)) as v}<td>{row[v]}</td>{/each}</tr>
                    {/each}
                  </tbody>
                </table></div></details>
              {/if}
              <ul class="claims">
                {#each detail.claims as c (c.id)}
                  <li>
                    <p>
                      <span class="badge small {VERDICT[c.verdict][2]}">{VERDICT[c.verdict][0]} {VERDICT[c.verdict][1]}</span>
                      <strong>« {c.claim} »</strong>
                      <span class="muted small">— {c.author_name ?? c.author_id}{c.period ? ` · ${c.period}` : ''} </span>
                      <a href={jump(c)} target="_blank" rel="noopener noreferrer">Voir sur Discord</a>
                    </p>
                    {#each detail.answers.filter((a) => a.message_id === c.message_id && a.claim === c.claim) as a}
                      <details><summary>Réponse initiale de Dindon</summary><p class="source">{a.answer || (a.verdict === 'false' ? 'Jugée fausse' : 'Jugée exacte')} · {a.valid} valide, {a.invalid} invalide</p></details>
                    {/each}
                    {#each c.sources as s}
                      <p class="source">
                        <a href={s.url} target="_blank" rel="noopener noreferrer">{host(s.url)}</a>
                        <span class="muted small">· {s.stance === 'supports' ? 'confirme' : s.stance === 'contradicts' ? 'contredit' : 'en partie'}</span><Help label="Nature de la source">{s.tier === 'official' ? 'Source officielle' : s.tier === 'checker' ? 'Vérification de presse' : 'Source non vérifiée par Dindon'}</Help>
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
  .layout.selected { grid-template-columns: minmax(15rem, 20rem) minmax(0, 1fr); }
  .back { align-self: flex-start; }
  .debateTitle { font-size: 1.25rem; line-height: 1.35; }
  .cardHead { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .5rem; }
  .answerTitle { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
  .participants { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr)); gap: .75rem; }
  .participants > li { display: flex; flex-direction: column; gap: .5rem; padding: .875rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); }
  blockquote { margin: .5rem 0; padding-left: .75rem; border-left: 2px solid var(--border-subtle); color: var(--text-secondary); }
  .parityScroll { overflow-x: auto; }
  .layout.selected > .list { position: sticky; top: 0; max-height: calc(100dvh - 8rem); overflow-y: auto; }
  .claims > li > p:first-child { display: flex; flex-wrap: wrap; align-items: baseline; gap: .5rem; }
  .claims > li > p:first-child > strong { flex-basis: 100%; }
  .source { overflow-wrap: anywhere; }

  @media (max-width: 900px) { .layout.selected { grid-template-columns: 1fr; } .layout.selected > .list { display: none; } }
  .page { flex: 1; min-height: 0; overflow-y: auto; padding: 1.5rem clamp(1rem, 3vw, 2.5rem) 2.5rem; display: flex; flex-direction: column; gap: 1.25rem; animation: fadeIn var(--transition-slow) both; }
  h1 { font-size: clamp(1.5rem, 2vw, 1.9rem); line-height: 1.1; font-weight: 700; color: var(--text-primary); }
  .card { padding: 1rem 1.125rem; display: flex; flex-direction: column; gap: 0.75rem; box-shadow: var(--shadow-sm); }
  .layout { display: grid; grid-template-columns: 1fr; gap: 1.25rem; align-items: start; }
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
  .source { padding-left: .75rem; border-left: 2px solid var(--border-subtle); font-size: 0.8125rem; color: var(--text-secondary); }
  a { color: var(--accent, #5865f2); }
  .hint { font-size: 0.75rem; line-height: 1.5; color: var(--text-muted); }
  .small { font-size: 0.75rem; }
  .badge.small { min-height: 1.5rem; font-size: 0.6875rem; }
  @media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .page { padding: 1rem 1rem 2rem; } }
</style>
