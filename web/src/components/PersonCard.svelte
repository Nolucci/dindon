<script>
  import Sparkline from './Sparkline.svelte';
  import Icon from './Icon.svelte';
  import AxisBar from './AxisBar.svelte';
  import { api } from '../lib/api.js';
  import { day } from '../lib/format.js';

  let { card, loading, error, onClose, onPick, guild } = $props();

  // What the AI read of this person (the Positions page lists them by proposition): only when something was read
  let read = $state(null);
  let openAxis = $state(null);
  let openTheme = $state(null);
  let tab = $state('activity');
  $effect(() => {
    const id = card?.id;
    tab = 'activity';
    read = null;
    openAxis = null;
    openTheme = null;
    if (!id) return;
    api.positionsPerson(id, guild).then((answer) => { if (card?.id === id) read = answer; }).catch(() => {});
  });
  const stanceName = { 1: 'Pour', 0: 'Nuancé', '-1': 'Contre' };

  const fmt = new Intl.NumberFormat('fr-FR');
  const kindLabel = { reply: 'réponses', mention: 'mentions', reaction: 'réactions' };
  // The other names, leaving out those that only differ by case or fancy letters from the one on the map
  const plain = (name) => name.normalize('NFKC').toLowerCase();
  let others = $derived(card ? card.names.seen_as.filter((n) => plain(n) !== plain(card.label)).slice(0, 5) : []);
</script>

<aside aria-label="Fiche de la personne">
  <button class="close closeBtn" onclick={onClose} aria-label="Fermer la fiche"><span class="closeIcon"><Icon name="close" /></span></button>
  {#if loading}
    <p class="muted">Chargement…</p>
  {:else if error}
    <p class="banner" role="alert">{error}</p>
  {:else if card}
    <header class="hero" style:--tint={card.color ?? '#5865f2'}>
      <span class="portrait">
        <img src={`/api/avatar/${card.id}?guild=${guild}`} alt="" onerror={(e) => e.currentTarget.remove()} />
        <span class="initial" aria-hidden="true">{[...card.label][0]?.toUpperCase()}</span>
      </span>
    </header>
    <div class="identity">
      <span class="eyebrow">Personne</span>
      <h2>{card.label}</h2>
      {#if others.length}<p class="muted small">Vu aussi sous : {others.join(', ')}</p>{/if}
      <div class="facts">
        {#each card.claimed_roles.slice(0, 3) as role (role.role)}<span class="fact role" title={role.ideology}>{role.role}</span>{/each}
        <span class="fact">{fmt.format(card.activity.messages)} message{card.activity.messages > 1 ? 's' : ''}</span>
        <span class="fact">{fmt.format(card.top_links.length ? card.top_links.reduce((n, l) => n + l.n, 0) : 0)} échanges</span>
        {#if card.activity.last_message_at}<span class="fact">vu le {day(card.activity.last_message_at)}</span>{/if}
      </div>
    </div>

    <nav class="personTabs" aria-label="Sections de la fiche">
      {#each [['activity', 'Activité'], ['positions', 'Positions'], ['roles', 'Rôles']] as [key, label]}
        <button type="button" class:active={tab === key} aria-pressed={tab === key} onclick={() => tab = key}>{label}</button>
      {/each}
    </nav>
    {#if tab === 'activity'}
    <section>
      <h3 class="eyebrow">Activité</h3>
      <dl>

        <div class="metric"><dt>Jours actifs</dt><dd>{fmt.format(card.activity.active_days)}</dd></div>
        <div class="metric"><dt>Par jour actif</dt><dd>{card.activity.messages_per_active_day}</dd></div>
        <div class="metric"><dt>Longueur moyenne</dt><dd>{card.activity.average_length}<span class="unit">&nbsp;car.</span></dd></div>
        <div class="metric"><dt>Part de réponses</dt><dd>{Math.round(card.activity.share_of_replies * 100)}<span class="unit">&nbsp;%</span></dd></div>
        <div class="metric"><dt>Salons</dt><dd>{card.activity.channels}</dd></div>
      </dl>
      <p class="muted small">Du {day(card.activity.first_message_at)} au {day(card.activity.last_message_at)}</p>
      <div class="sparkWrap"><Sparkline points={card.by_month} /></div>
      <p class="muted small">Messages par mois</p>
    </section>

    {/if}
    {#if tab === 'positions'}
      {#if !read}<p class="muted small">Chargement des positions…</p>{:else if !read.axes.some((a) => a.score !== null) && !read.themes.length}<p class="muted small">Aucune position étayée disponible.</p>{/if}
    {#if read && read.axes.some((a) => a.score !== null)}
      <section>
        <h3 class="eyebrow">Où elle se situe</h3>
        <p class="muted small">Point : position estimée · Crochet : incertitude · Cadre : rôle déclaré.</p>
        <ul class="axes">
          {#each read.axes.filter((a) => a.score !== null) as axis (axis.code)}
            {@const bad = axis.expected.find((e) => e.verdict === 'incompatible')}
            <li>
              <button type="button" class="axisHead" onclick={() => (openAxis = openAxis === axis.code ? null : axis.code)} aria-expanded={openAxis === axis.code} disabled={!axis.contributions.length}>
                <span class="axisName">{axis.name}</span>
                {#if bad}<span class="flag">contredit « {bad.role} »</span>{/if}
                {#if axis.score === null}<span class="muted small">pas assez de propos</span>{:else}<span class="muted small">{axis.positions} position{axis.positions > 1 ? 's' : ''}</span>{/if}
              </button>
              <AxisBar {axis} compact />
              {#if openAxis === axis.code}
                <ul class="contrib">
                  {#each axis.contributions as c}
                    <li><span class="badge small" class:success={c.stance === 1} class:danger={c.stance === -1}>{stanceName[c.stance]}</span> {c.proposition}
                      <span class="muted small" title="Poids de la proposition sur l’axe : négatif = pôle de gauche, positif = pôle de droite">#{c.proposition_id} · lien {c.loading > 0 ? '+' : ''}{c.loading}{c.validated ? ' · validé' : ''}</span></li>
                  {/each}
                </ul>
              {/if}
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if read && read.themes.length}
      <section>
        <h3 class="eyebrow">Par sujet</h3>
        <div class="chips">
          {#each read.themes as t (t.id ?? 0)}
            <button type="button" class="chip" class:on={openTheme === (t.id ?? 0)} onclick={() => (openTheme = openTheme === (t.id ?? 0) ? null : (t.id ?? 0))}>{t.label} <span class="muted">{t.positions.length}</span></button>
          {/each}
        </div>
        {#each read.themes.filter((t) => (t.id ?? 0) === openTheme) as t}
          <ul class="positions">
            {#each t.positions as p}
              <li>
                <span class="propText">{p.proposition}</span>
                <span class="badge small" class:success={p.stance === 1} class:danger={p.stance === -1}>{stanceName[p.stance]}</span>
                {#if p.history.length}<span class="muted small">a changé : {p.history.map((h) => stanceName[h.stance]).join(' → ')}</span>{/if}
                {#each p.evidence as e}<blockquote>« {e.quote} »</blockquote>{/each}
              </li>
            {/each}
          </ul>
          {#if t.talked_with.length}
            <h4 class="eyebrow">En a parlé avec</h4>
            <ul class="talked">
              {#each t.talked_with as w}
                <li><button type="button" class="link" onclick={() => onPick?.(w.id)}>{w.label}</button> <span class="muted small">{w.messages} message{w.messages > 1 ? 's' : ''}{w.relation ? ` · ${w.relation}` : ''}</span></li>
              {/each}
            </ul>
          {/if}
        {/each}
      </section>
    {/if}

    {/if}
    {#if tab === 'activity'}
    <section>
      <h3 class="eyebrow">Échanges</h3>
      <div class="tableShell">
        <table>
          <thead><tr><th></th><th>envoyés</th><th>reçus</th></tr></thead>
          <tbody>
            {#each Object.keys(kindLabel) as kind}
              <tr><td>{kindLabel[kind]}</td><td>{fmt.format(card.exchanges.sent[kind])}</td><td>{fmt.format(card.exchanges.received[kind])}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>

    {#if card.top_links.length}
      <section>
        <h3 class="eyebrow">Liens principaux</h3>
        <ul>
          {#each card.top_links as link}
            <li>
              <button class="row link" onclick={() => onPick(link.id)}>
                <span class="rowName">{link.label}</span>
                <span class="pill">{fmt.format(link.n)} échanges</span>
              </button>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if card.top_channels.length}
      <section>
        <h3 class="eyebrow">Salons les plus fréquentés</h3>
        <ul>
          {#each card.top_channels as channel}
            <li class="row"><span class="prefix">#</span><span class="rowName">{channel.name}</span><span class="pill">{fmt.format(channel.messages)}</span></li>
          {/each}
        </ul>
      </section>
    {/if}

    {/if}
    {#if tab === 'roles'}
    {#if read && read.roles.length}
      <section>
        <h3 class="eyebrow">Rôles qu’elle s’est donnés</h3>
        <ul class="roles">
          {#each read.roles as r}
            <li>
              <span class="roleName">{r.role}</span>
              <span class="badge small" class:success={r.verdict === 'concordant'} class:danger={r.verdict === 'discordant'}>
                {r.verdict === 'discordant' ? 'contradiction' : r.verdict === 'concordant' ? 'cohérent' : 'pas assez de propos'}
              </span>
            </li>
          {/each}
        </ul>
        {#each read.role_conflicts as c}<p class="muted small">« {c.a} » et « {c.b} » s’excluent sur l’axe « {c.axis} ».</p>{/each}
      </section>
    {/if}

    {#if card.claimed_roles.length && !read?.roles.length}
      <section>
        <h3 class="eyebrow">Rôles que la personne s’est donnés</h3>
        <p class="tags">{#each card.claimed_roles as role}<span title={role.ideology}>{role.role}</span>{/each}</p>
        <p class="muted small">{card.claimed_roles_note}</p>
      </section>
    {/if}
      {#if !card.claimed_roles.length && !read?.roles.length}<p class="muted small">Aucun rôle déclaré.</p>{/if}
    {/if}
  {/if}
</aside>

<style>
  .personTabs { display: flex; gap: .25rem; margin-top: 1rem; border-bottom: 1px solid var(--border-subtle); }
  .personTabs button { flex: 1; padding: .625rem .25rem; color: var(--text-secondary); }
  .personTabs button.active { color: var(--text-primary); border-bottom: 2px solid var(--accent); }
  .axes, .roles, .talked, .contrib { list-style: none; display: flex; flex-direction: column; gap: 0.625rem; margin-top: 0.5rem; }
  .axes > li { display: flex; flex-direction: column; gap: 0.25rem; }
  .axisHead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.125rem 0.5rem; background: none; border: none; padding: 0; color: inherit; font: inherit; text-align: left; cursor: pointer; }
  .axisHead:disabled { cursor: default; }
  .axisName { font-size: 0.8125rem; font-weight: 600; color: var(--text-primary); }
  .flag { font-size: 0.6875rem; font-weight: 700; color: #ed4245; }
  .contrib { gap: 0.25rem; padding-left: 0.5rem; font-size: 0.75rem; color: var(--text-secondary); }
  .roles li { display: flex; align-items: center; gap: 0.5rem; }
  .roleName { font-weight: 600; color: var(--text-primary); font-size: 0.875rem; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.375rem; margin: 0.5rem 0; }
  .chip { padding: 0.25rem 0.625rem; border-radius: 999px; border: 1px solid var(--border-subtle); background: var(--surface-control); color: var(--text-secondary); font: inherit; font-size: 0.75rem; cursor: pointer; }
  .chip.on { border-color: var(--accent, #5865f2); color: var(--text-primary); }
  .talked { gap: 0.25rem; }
  .link { background: none; border: none; padding: 0; color: var(--text-primary); font: inherit; font-weight: 600; text-decoration: underline; cursor: pointer; }
  .positions { list-style: none; display: flex; flex-direction: column; gap: 0.75rem; margin-top: 0.5rem; }
  .positions li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.375rem 0.5rem; }
  .propText { font-weight: 600; color: var(--text-primary); }
  .positions blockquote { flex-basis: 100%; margin: 0; padding: 0.25rem 0.625rem; border-left: 3px solid var(--border-subtle); color: var(--text-secondary); font-size: 0.8125rem; line-height: 1.45; }
  .hero { display: flow-root; margin: -1.25rem -1.125rem 0; height: 4.5rem; background: linear-gradient(135deg, color-mix(in srgb, var(--tint) 70%, #000), color-mix(in srgb, var(--tint) 25%, var(--bg-secondary))); }
  .portrait { position: relative; display: block; width: 4.75rem; height: 4.75rem; margin: 2.25rem 0 0 0.25rem; border: 4px solid var(--bg-secondary); border-radius: 50%; overflow: hidden; background: var(--tint); box-shadow: 0 0 0 2px var(--tint), var(--shadow-md); }
  .portrait img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
  .initial { display: grid; place-items: center; width: 100%; height: 100%; font-size: 1.75rem; font-weight: 700; color: #fff; }
  .identity { padding-top: 2.75rem; }
  .identity h2 { margin: 0.125rem 0 0.25rem; }
  .facts { display: flex; flex-wrap: wrap; gap: 0.375rem; margin-top: 0.625rem; }
  .fact { padding: 0.1875rem 0.5rem; border-radius: 999px; background: var(--bg-tertiary); border: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 0.6875rem; font-weight: 600; }
  .fact.role { border-color: var(--tint); color: var(--text-primary); }
  aside {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(22.5rem, 100%);
    background: var(--bg-secondary);
    border-left: 1px solid var(--border-subtle);
    padding: 1.25rem 1.125rem 1.75rem;
    padding-top: 1.25rem;
    overflow-y: auto;
    z-index: 5;
    animation: fadeIn var(--transition-normal) both;
  }

  /* A phone: the card is a sheet at the bottom (the map stays visible above it), its close button is easy to hit */
  @media (max-width: 720px) {
    aside {
      top: auto;
      left: 0;
      right: 0;
      bottom: 0;
      width: 100%;
      height: 62%;
      border-left: none;
      border-top: 1px solid var(--border-strong);
      border-radius: 1rem 1rem 0 0;
      box-shadow: 0 -0.5rem 1.5rem rgba(0, 0, 0, 0.35);
      -webkit-overflow-scrolling: touch;
      overscroll-behavior: contain;
      padding-bottom: calc(1.75rem + env(safe-area-inset-bottom));
    }

    aside::before {
      content: '';
      position: sticky;
      top: 0;
      display: block;
      width: 2.5rem;
      height: 0.25rem;
      margin: -0.5rem auto 0.5rem;
      border-radius: 999px;
      background: var(--border-strong);
    }

    .closeBtn { top: 0.5rem; right: 0.5rem; width: 3.5rem; height: 3.5rem; }
    .closeIcon { width: 1.25rem; height: 1.25rem; }
  }

  /* HistoryModal.module.css .closeBtn */
  .closeBtn {
    position: absolute;
    top: 0.875rem;
    right: 0.875rem;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.75rem;
    height: 2.75rem;
    color: var(--text-muted);
    border-radius: var(--radius-sm);
    transition: color var(--transition-fast), background var(--transition-fast);
  }

  .closeBtn:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .closeIcon {
    width: 1rem;
    height: 1rem;
    display: inline-flex;
  }

  .closeIcon :global(svg) {
    width: 100%;
    height: 100%;
  }

  h2 {
    margin: 0.125rem 2.25rem 0.25rem 0;
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.2;
    overflow-wrap: anywhere;
  }

  h3 {
    margin: 1.375rem 0 0.5rem;
  }

  .small {
    font-size: 0.75rem;
    margin: 0.375rem 0;
  }

  dl {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.625rem;
  }

  /* Stats.module.css .metricCard, smaller */
  .metric {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.625rem 0.75rem 0.625rem 0.9375rem;
    border-radius: 0.75rem;
    border: 1px solid color-mix(in srgb, var(--accent) 32%, rgba(255, 255, 255, 0.06));
    background: color-mix(in srgb, var(--bg-tertiary) 92%, black);
    box-shadow: 0 0.625rem 1.75rem rgba(0, 0, 0, 0.16);
    overflow: hidden;
  }

  .metric::before {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: 0.1875rem;
    background: var(--accent);
  }

  dt {
    font-size: 0.75rem;
    font-weight: 600;
    color: color-mix(in srgb, var(--accent) 58%, white);
  }

  dd {
    font-size: 1.375rem;
    line-height: 1.1;
    font-weight: 700;
    color: #f7f8fa;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
  }

  .unit {
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0;
    color: var(--text-muted);
  }

  .sparkWrap {
    margin: 0.625rem 0 0.125rem;
    padding: 0.625rem 0.75rem;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    background: var(--bg-tertiary);
  }

  /* Stats.module.css .tableShell, .table */
  .tableShell {
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    background: var(--bg-secondary);
    overflow: hidden;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8125rem;
    font-variant-numeric: tabular-nums;
  }

  th {
    font-size: 0.6875rem;
    font-weight: 700;
    text-transform: none;
    letter-spacing: normal;
    color: var(--text-muted);
    padding: 0.5rem 0.75rem;
    text-align: right;
    border-bottom: 1px solid var(--border-subtle);
  }

  td {
    padding: 0.4375rem 0.75rem;
    text-align: right;
    color: var(--text-primary);
    font-weight: 600;
  }

  th:first-child,
  td:first-child {
    text-align: left;
  }

  td:first-child {
    color: var(--text-secondary);
    font-weight: 400;
  }

  tbody tr {
    border-bottom: 1px solid var(--border-subtle);
  }

  tbody tr:last-child {
    border-bottom: none;
  }

  tbody tr:nth-child(even) {
    background: rgba(255, 255, 255, 0.015);
  }

  ul {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
  }

  /* Sidebar.module.css .item and .groupCount */
  .row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.375rem 0.5rem;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: 0.875rem;
    font-weight: 500;
    text-align: left;
  }

  .link {
    transition: background var(--transition-fast), color var(--transition-fast), transform var(--transition-fast);
  }

  .link:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  .link:active {
    transform: scale(0.98);
  }

  .rowName {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .prefix {
    color: var(--text-muted);
    font-weight: 700;
    font-size: 0.9375rem;
    flex-shrink: 0;
  }

  .pill {
    flex-shrink: 0;
    font-size: 0.625rem;
    font-weight: 600;
    color: var(--text-muted);
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
    padding: 0 0.375rem;
    line-height: 1rem;
  }

  /* Stats.module.css .pieLegendItem */
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .tags span {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-full);
    color: var(--text-secondary);
    font-size: 0.75rem;
    padding: 0.375rem 0.625rem;
  }
</style>
