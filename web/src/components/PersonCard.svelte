<script>
  import Sparkline from './Sparkline.svelte';

  let { card, loading, error, onClose, onPick } = $props();

  const fmt = new Intl.NumberFormat('fr-FR');
  const day = (iso) => (iso ? new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : '—');
  const kindLabel = { reply: 'réponses', mention: 'mentions', reaction: 'réactions' };
  // The other names, leaving out those that only differ by case or fancy letters from the one on the map
  const plain = (name) => name.normalize('NFKC').toLowerCase();
  let others = $derived(card ? card.names.seen_as.filter((n) => plain(n) !== plain(card.label)).slice(0, 5) : []);
</script>

<aside aria-label="Fiche de la personne">
  <button class="close" onclick={onClose} aria-label="Fermer la fiche">✕</button>
  {#if loading}
    <p class="muted">Chargement…</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else if card}
    <h2>{card.label}</h2>
    {#if others.length}<p class="muted small">Vu aussi sous : {others.join(', ')}</p>{/if}

    <section>
      <h3>Activité</h3>
      <dl>
        <div><dt>Messages</dt><dd>{fmt.format(card.activity.messages)}</dd></div>
        <div><dt>Jours actifs</dt><dd>{fmt.format(card.activity.active_days)}</dd></div>
        <div><dt>Par jour actif</dt><dd>{card.activity.messages_per_active_day}</dd></div>
        <div><dt>Longueur moyenne</dt><dd>{card.activity.average_length} car.</dd></div>
        <div><dt>Part de réponses</dt><dd>{Math.round(card.activity.share_of_replies * 100)} %</dd></div>
        <div><dt>Salons</dt><dd>{card.activity.channels}</dd></div>
      </dl>
      <p class="muted small">Du {day(card.activity.first_message_at)} au {day(card.activity.last_message_at)}</p>
      <Sparkline points={card.by_month} />
      <p class="muted small">Messages par mois</p>
    </section>

    <section>
      <h3>Échanges</h3>
      <table>
        <thead><tr><th></th><th>envoyés</th><th>reçus</th></tr></thead>
        <tbody>
          {#each Object.keys(kindLabel) as kind}
            <tr><td>{kindLabel[kind]}</td><td>{fmt.format(card.exchanges.sent[kind])}</td><td>{fmt.format(card.exchanges.received[kind])}</td></tr>
          {/each}
        </tbody>
      </table>
    </section>

    {#if card.top_links.length}
      <section>
        <h3>Liens principaux</h3>
        <ul class="links">
          {#each card.top_links as link}
            <li>
              <button class="link" onclick={() => onPick(link.id)}>{link.label}</button>
              <span class="muted small">{fmt.format(link.n)} échanges</span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if card.top_channels.length}
      <section>
        <h3>Salons les plus fréquentés</h3>
        <ul>
          {#each card.top_channels as channel}<li>#{channel.name} <span class="muted small">{fmt.format(channel.messages)}</span></li>{/each}
        </ul>
      </section>
    {/if}

    {#if card.claimed_roles.length}
      <section>
        <h3>Rôles que la personne s’est donnés</h3>
        <p class="tags">{#each card.claimed_roles as role}<span title={role.ideology}>{role.role}</span>{/each}</p>
        <p class="muted small">{card.claimed_roles_note}</p>
      </section>
    {/if}
  {/if}
</aside>

<style>
  aside { position: absolute; top: 0; right: 0; bottom: 0; width: min(360px, 100%); background: var(--panel); border-left: 1px solid var(--line); padding: 18px 18px 28px; overflow-y: auto; z-index: 5; }
  .close { position: absolute; top: 10px; right: 10px; padding: 3px 8px; }
  h2 { margin: 4px 36px 4px 0; font-size: 20px; overflow-wrap: anywhere; }
  h3 { margin: 18px 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
  .small { font-size: 12.5px; margin: 4px 0; }
  .error { color: var(--warn); }
  dl { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px; margin: 0; }
  dl div { background: var(--panel-2); border-radius: 6px; padding: 7px 9px; }
  dt { font-size: 12px; color: var(--muted); }
  dd { margin: 0; font-size: 17px; font-variant-numeric: tabular-nums; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { text-align: right; padding: 3px 0; font-weight: 400; }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--muted); font-size: 12px; }
  ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 3px; }
  .links li { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
  .link { background: none; border: none; padding: 2px 0; color: var(--accent); text-align: left; overflow-wrap: anywhere; }
  .link:hover { text-decoration: underline; }
  .tags { display: flex; flex-wrap: wrap; gap: 5px; margin: 0; }
  .tags span { background: var(--panel-2); border: 1px solid var(--line); border-radius: 12px; padding: 2px 9px; font-size: 12.5px; }
</style>
