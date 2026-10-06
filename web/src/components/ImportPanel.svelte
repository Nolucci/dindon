<script>
  import { onDestroy, onMount } from 'svelte';
  import { api, AuthError } from '../lib/api.js';
  import Modal from './Modal.svelte';
  import { matches } from '../lib/text.js';

  let { onClose, onAuthLost } = $props();

  let options = $state(null); // { configured, guilds: [{ id, name, channels: [{ id, name, kind, empty }] }] }
  let loadError = $state('');
  let guildId = $state('');
  let chosen = $state({});
  let authors = $state('');
  let mentions = $state('');
  let after = $state('');
  let before = $state('');
  let job = $state(null);
  let formError = $state('');
  let sending = $state(false);
  let channelQ = $state('');   // narrows the list of channels
  let poll = null;

  const running = $derived(job?.state === 'running' || job?.state === 'cancelling');
  const channels = $derived(options?.guilds.find((g) => g.id === guildId)?.channels ?? []);
  const visible = $derived(channels.filter((c) => matches(channelQ, c.name)));
  const selectedIds = $derived(channels.filter((c) => chosen[c.id]).map((c) => c.id));
  const narrowed = $derived(Boolean(authors.trim() || mentions.trim() || after || before));
  const fmt = new Intl.NumberFormat('fr-FR');
  const STATES = { idle: '', running: 'En cours…', cancelling: 'Arrêt en cours…', done: 'Terminé', cancelled: 'Annulé', failed: 'Échec' };
  const STAGES = { reading: 'Lecture Discord', profiles: 'Récupération des profils', reactions: 'Récupération des réactions',
                   writing: 'Préparation du lot', importing: 'Enregistrement en base' };

  async function guard(action) {
    try {
      return await action();
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else return { problem: error.message };
      return undefined;
    }
  }

  async function refresh() {
    const answer = await guard(() => api.importStatus());
    if (answer && !answer.problem) job = answer;
    if (!running) stopPolling();
  }

  function startPolling() {
    if (!poll) poll = setInterval(refresh, 1200);
  }

  function stopPolling() {
    clearInterval(poll);
    poll = null;
  }

  onMount(async () => {
    const answer = await guard(() => api.importOptions());
    if (!answer) return;
    if (answer.problem) {
      loadError = answer.problem;
      return;
    }
    options = answer;
    guildId = answer.guilds[0]?.id ?? '';
    await refresh();
    if (running) startPolling();
  });
  onDestroy(stopPolling);

  const list = (text) => text.split(/[\s,;]+/).filter(Boolean);

  async function start() {
    formError = '';
    sending = true;
    const answer = await guard(() => api.importStart({ guild: guildId, channels: selectedIds, authors: list(authors), mentions: list(mentions),
                                                       after: after || null, before: before || null }));
    sending = false;
    if (!answer) return;
    if (answer.problem) {
      formError = answer.problem;
      return;
    }
    job = answer;
    startPolling();
  }

  async function cancel() {
    const answer = await guard(() => api.importCancel());
    if (answer && !answer.problem) job = answer;
  }

</script>

<Modal title="Importer l’historique" titleId="import-title" {onClose}>
    {#if loadError}
      <p class="banner" role="alert">{loadError}</p>
    {:else if !options}
      <p class="muted">Chargement des salons depuis Discord…</p>
    {:else if !options.configured}
      <p class="muted">Aucun jeton ou aucun serveur n’est configuré (<code>DISCORD_TOKEN</code>, <code>DINDON_GUILD_IDS</code> dans <code>.env</code>).</p>
    {:else}
      {#if options.guilds.length > 1}
        <label class="field">Serveur
          <select class="select" bind:value={guildId} disabled={running} onchange={() => (chosen = {})}>
            {#each options.guilds as g}<option value={g.id}>{g.name}</option>{/each}
          </select>
        </label>
      {/if}

      <fieldset disabled={running}>
        <legend>Salons <span class="count">{selectedIds.length} choisi{selectedIds.length > 1 ? 's' : ''}</span></legend>
        <div class="quick">
          <button type="button" class="tool-btn" onclick={() => (chosen = { ...chosen, ...Object.fromEntries(visible.map((c) => [c.id, true])) })}>{channelQ.trim() ? 'Tous ceux affichés' : 'Tous'}</button>
          <button type="button" class="tool-btn" onclick={() => (chosen = {})}>Aucun</button>
        </div>
        {#if channels.length > 6}
          <input class="field-input" type="search" placeholder="Chercher un salon" bind:value={channelQ} aria-label="Chercher un salon" />
        {/if}
        {#if channelQ.trim() && !visible.length}<p class="muted note">Aucun salon ne correspond.</p>{/if}
        <ul class="channels">
          {#each visible as c}
            <li><label><input type="checkbox" bind:checked={chosen[c.id]} /><span class="prefix">#</span><span class="channelName">{c.name}</span>{#if c.kind === 'forum'}<span class="muted note">forum</span>{/if}{#if c.empty}<span class="muted note">vide</span>{/if}</label></li>
          {/each}
        </ul>
      </fieldset>

      <fieldset disabled={running}>
        <legend>Filtres <span class="count">facultatifs</span></legend>
        <label class="field">Écrits par
          <input class="field-input" type="text" bind:value={authors} placeholder="identifiants Discord, séparés par des espaces ou des virgules" aria-label="Auteurs" />
        </label>
        <label class="field">Qui mentionnent
          <input class="field-input" type="text" bind:value={mentions} placeholder="identifiants Discord" aria-label="Personnes mentionnées" />
        </label>
        <div class="dates">
          <label class="field">Du <input class="field-input" type="date" bind:value={after} aria-label="Du" /></label>
          <label class="field">Au (inclus) <input class="field-input" type="date" bind:value={before} aria-label="Au" /></label>
        </div>
        <p class="hint">
          Un identifiant se copie par clic droit sur la personne dans Discord (mode développeur activé), « Copier l’identifiant ».
          {#if narrowed}
            <strong>Import partiel :</strong> seule une partie des salons est récupérée, donc il ne compte pas comme un premier import complet ;
            un import complet fait plus tard rapporte tout.
          {/if}
        </p>
      </fieldset>

      {#if formError}<p class="banner" role="alert">{formError}</p>{/if}

      <div class="actions">
        {#if running}
          <button class="btn btn-danger" onclick={cancel} disabled={job.state === 'cancelling'}>Annuler l’import</button>
        {:else}
          <button class="btn btn-primary" onclick={start} disabled={sending || selectedIds.length === 0}>Lancer l’import</button>
          {#if selectedIds.length === 0}<span class="muted">Choisissez au moins un salon.</span>{/if}
        {/if}
      </div>

      {#if job && job.state !== 'idle'}
        <section class="progress" aria-live="polite">
          <h3 class="badge" class:success={job.state === 'done'} class:danger={job.state === 'failed'} class:accent={running}>{STATES[job.state]}</h3>
          {#if job.planned !== null}
            <progress max={Math.max(job.planned, 1)} value={job.done + job.failed + job.cancelled}></progress>
            <p>
              {fmt.format(job.done + job.failed + job.cancelled)} salon(s) sur {fmt.format(job.planned)} · {fmt.format(job.messages)} nouveaux messages
              {#if job.failed}· <span class="warn">{job.failed} en échec</span>{/if}
              {#if job.cancelled}· {job.cancelled} annulé(s){/if}
            </p>
          {:else if running}
            <p class="muted">Préparation…</p>
          {/if}
          {#if running && job.active?.length}
            <div class="activeChannels">
              <strong>Salons en cours</strong>
              {#each job.active as channel (channel.id)}
                <div class="activeChannel">
                  <span class="channelName">[{channel.number}/{job.planned}] {channel.name}</span>
                  <span class="muted">
                    {#if channel.pages}
                      {fmt.format(channel.scanned)} messages parcourus · {fmt.format(channel.pages)} page{channel.pages > 1 ? 's' : ''}
                      {#if channel.saved != null} · {fmt.format(channel.saved)} nouveaux messages enregistrés{/if}
                    {:else}
                      Connexion à Discord…
                    {/if}
                    {#if channel.stage}<br />{STAGES[channel.stage] ?? channel.stage}{/if}
                  </span>
                </div>
              {/each}
            </div>
          {/if}
          {#if job.error}<p class="banner" role="alert">{job.error}</p>{/if}
          {#if job.lines.length}
            <pre class="lines">{job.lines.join('\n')}</pre>
          {/if}
          {#if running}<p class="muted">Vous pouvez fermer cette fenêtre : l’import continue.</p>{/if}
        </section>
      {/if}
    {/if}
</Modal>

<style>
  /* Settings.module.css .group, .groupTitle */
  fieldset {
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    background: var(--surface-control);
    padding: 0.25rem 1rem 1rem;
  }

  fieldset:disabled {
    opacity: 0.6;
  }

  legend {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0 0.5rem;
    margin-left: -0.5rem;
    font-size: 0.6875rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-muted);
  }

  .count {
    font-size: 0.625rem;
    font-weight: 600;
    letter-spacing: 0;
    text-transform: none;
    color: var(--text-muted);
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
    padding: 0 0.375rem;
    line-height: 1rem;
  }

  .quick {
    display: flex;
    gap: 0.375rem;
    margin: 0.5rem 0 0.375rem;
  }

  .channels {
    list-style: none;
    columns: 2;
    column-gap: 1rem;
  }

  .channels li {
    break-inside: avoid;
  }

  .channels label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.3125rem 0.5rem;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
  }

  .channels label:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  .prefix {
    color: var(--text-muted);
    font-weight: 700;
    font-size: 0.9375rem;
    margin-right: -0.125rem;
  }

  .channelName {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .note {
    font-size: 0.6875rem;
    flex-shrink: 0;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
    margin-top: 0.75rem;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--text-secondary);
  }

  .field :global(.field-input),
  .field :global(.select) {
    background: var(--bg-tertiary);
    min-height: 2.125rem;
  }

  .dates {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
  }

  .hint {
    margin-top: 0.75rem;
    font-size: 0.75rem;
    line-height: 1.5;
    color: var(--text-muted);
  }

  .hint strong {
    color: var(--text-secondary);
  }

  .actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .progress {
    padding-top: 0.875rem;
    border-top: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
    align-items: flex-start;
  }

  .progress p {
    align-self: stretch;
  }

  .progress .banner {
    align-self: stretch;
  }

  .activeChannels {
    align-self: stretch;
    display: grid;
    gap: 0.375rem;
    padding: 0.625rem 0.75rem;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    font-size: 0.8125rem;
  }

  .activeChannel {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  progress {
    appearance: none;
    -webkit-appearance: none;
    align-self: stretch;
    width: 100%;
    height: 0.5rem;
    border: none;
    border-radius: 62.4375rem;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.1);
  }

  progress::-webkit-progress-bar {
    background: rgba(255, 255, 255, 0.1);
  }

  progress::-webkit-progress-value {
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, white));
    border-radius: 62.4375rem;
    transition: width var(--transition-normal);
  }

  progress::-moz-progress-bar {
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, white));
    border-radius: 62.4375rem;
  }

  .lines {
    align-self: stretch;
    max-height: 10rem;
    overflow: auto;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: 0.625rem 0.75rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.75rem;
    color: var(--text-secondary);
    white-space: pre-wrap;
  }

  .warn {
    color: #ffb3b8;
  }

  @media (max-width: 448px) {
    .channels { columns: 1; }
    .dates { grid-template-columns: 1fr; }
  }
</style>
