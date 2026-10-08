<script>
  import { api, AuthError } from '../lib/api.js';
  import PersonCard from './PersonCard.svelte';
  let { person, guild, positions, verdicts, claims = [], onAuthLost } = $props();
  let expanded = $state(false);
  let card = $state(null);
  let loading = $state(false);
  let error = $state('');
  const pct = (n) => `${Math.round(n * 100)} %`;
  async function load(id = person.user_id) {
    loading = true;
    error = '';
    try { card = await api.person(id, guild); }
    catch (e) { if (e instanceof AuthError) onAuthLost(); else error = e.message; }
    loading = false;
  }
  $effect(() => { if (expanded && !card && !loading && !error) load(); });
</script>
<details class="participant" bind:open={expanded}>
  <summary><strong>{person.name ?? person.user_id}</strong><span class="badge small">{positions[person.position ?? 'none']}</span><span class="muted small">{person.messages} message{person.messages !== 1 ? 's' : ''}</span></summary>
  {#if expanded}
    <div class="participantBody">
      <p class="muted small">{pct(person.share)} des messages{person.changed && person.first_position !== person.position ? ` · avant : ${positions[person.first_position]}` : ''}</p>
      {#if person.key_message}<details><summary>Message phare</summary><blockquote>{person.key_message.excerpt}</blockquote>{#if person.key_message.url}<a href={person.key_message.url} target="_blank" rel="noopener noreferrer">Voir sur Discord</a>{/if}</details>{/if}
      {#if person.position_history?.length}<details><summary>Historique des positions</summary><ul class="history">{#each person.position_history as position}<li><strong>{positions[position.position]}</strong><span class="muted small">{new Date(position.at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}</span></li>{/each}</ul></details>{/if}
      {#if claims.length}<details><summary>Affirmations dans ce débat ({claims.length})</summary><ul class="personClaims">{#each claims as claim (claim.id)}<li><span class="badge small">{verdicts[claim.verdict][1]}</span><p>{claim.claim}</p></li>{/each}</ul></details>{/if}
      <PersonCard {card} {loading} {error} {guild} embedded onPick={load} />
    </div>
  {/if}
</details>
<style>
  .participant { border-bottom: 1px solid var(--border-subtle); }
  summary { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem .75rem; padding: .875rem 0; cursor: pointer; list-style: none; }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: '▸'; color: var(--text-muted); }
  .participant[open] > summary::before { content: '▾'; }
  summary strong { flex: 1 1 10rem; min-width: 0; overflow-wrap: anywhere; }
  .participantBody { display: flex; flex-direction: column; gap: .75rem; padding: .5rem .75rem 1.25rem; }
  blockquote { margin: .5rem 0; padding-left: .75rem; border-left: 2px solid var(--border-subtle); }
  .history, .personClaims { list-style: none; display: flex; flex-direction: column; gap: .625rem; margin: .5rem 0; }
  .history li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .5rem; }
  a { color: var(--text-link); }
</style>
