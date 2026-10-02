<script>
  import { onDestroy, onMount } from 'svelte';
  import { api, AuthError } from '../lib/api.js';

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
  let poll = null;

  const running = $derived(job?.state === 'running' || job?.state === 'cancelling');
  const channels = $derived(options?.guilds.find((g) => g.id === guildId)?.channels ?? []);
  const selectedIds = $derived(channels.filter((c) => chosen[c.id]).map((c) => c.id));
  const narrowed = $derived(Boolean(authors.trim() || mentions.trim() || after || before));
  const fmt = new Intl.NumberFormat('fr-FR');
  const STATES = { idle: '', running: 'En cours…', cancelling: 'Arrêt en cours…', done: 'Terminé', cancelled: 'Annulé', failed: 'Échec' };

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

  function keydown(event) {
    if (event.key === 'Escape') onClose();
  }
</script>

<svelte:window onkeydown={keydown} />

<div class="backdrop" role="presentation" onclick={(event) => event.target === event.currentTarget && onClose()}>
  <div class="panel" role="dialog" aria-modal="true" aria-labelledby="import-title">
    <header>
      <h2 id="import-title">Importer l’historique</h2>
      <button class="quiet" onclick={onClose} aria-label="Fermer">✕</button>
    </header>

    {#if loadError}
      <p class="error" role="alert">{loadError}</p>
    {:else if !options}
      <p class="muted">Chargement des salons depuis Discord…</p>
    {:else if !options.configured}
      <p class="muted">Aucun jeton ou aucun serveur n’est configuré (<code>DISCORD_TOKEN</code>, <code>DINDON_GUILD_IDS</code> dans <code>.env</code>).</p>
    {:else}
      {#if options.guilds.length > 1}
        <label class="field">Serveur
          <select bind:value={guildId} disabled={running} onchange={() => (chosen = {})}>
            {#each options.guilds as g}<option value={g.id}>{g.name}</option>{/each}
          </select>
        </label>
      {/if}

      <fieldset disabled={running}>
        <legend>Salons <span class="muted">({selectedIds.length} choisi{selectedIds.length > 1 ? 's' : ''})</span></legend>
        <div class="quick">
          <button type="button" onclick={() => (chosen = Object.fromEntries(channels.map((c) => [c.id, true])))}>Tous</button>
          <button type="button" onclick={() => (chosen = {})}>Aucun</button>
        </div>
        <ul class="channels">
          {#each channels as c}
            <li><label><input type="checkbox" bind:checked={chosen[c.id]} /> {c.name}{#if c.kind === 'forum'} <span class="muted">(forum)</span>{/if}{#if c.empty} <span class="muted">(vide)</span>{/if}</label></li>
          {/each}
        </ul>
      </fieldset>

      <fieldset disabled={running}>
        <legend>Filtres <span class="muted">(facultatifs)</span></legend>
        <label class="field">Écrits par
          <input type="text" bind:value={authors} placeholder="identifiants Discord, séparés par des espaces ou des virgules" aria-label="Auteurs" />
        </label>
        <label class="field">Qui mentionnent
          <input type="text" bind:value={mentions} placeholder="identifiants Discord" aria-label="Personnes mentionnées" />
        </label>
        <div class="dates">
          <label class="field">Du <input type="date" bind:value={after} aria-label="Du" /></label>
          <label class="field">Au (inclus) <input type="date" bind:value={before} aria-label="Au" /></label>
        </div>
        <p class="hint muted">
          Un identifiant se copie par clic droit sur la personne dans Discord (mode développeur activé), « Copier l’identifiant ».
          {#if narrowed}
            <strong>Import partiel :</strong> seule une partie des salons est récupérée, donc il ne compte pas comme un premier import complet ;
            un import complet fait plus tard rapporte tout.
          {/if}
        </p>
      </fieldset>

      {#if formError}<p class="error" role="alert">{formError}</p>{/if}

      <div class="actions">
        {#if running}
          <button onclick={cancel} disabled={job.state === 'cancelling'}>Annuler l’import</button>
        {:else}
          <button class="primary" onclick={start} disabled={sending || selectedIds.length === 0}>Lancer l’import</button>
          {#if selectedIds.length === 0}<span class="muted">Choisissez au moins un salon.</span>{/if}
        {/if}
      </div>

      {#if job && job.state !== 'idle'}
        <section class="progress" aria-live="polite">
          <h3>{STATES[job.state]}</h3>
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
          {#if job.error}<p class="error" role="alert">{job.error}</p>{/if}
          {#if job.lines.length}
            <pre class="lines">{job.lines.join('\n')}</pre>
          {/if}
          {#if running}<p class="muted">Vous pouvez fermer cette fenêtre : l’import continue.</p>{/if}
        </section>
      {/if}
    {/if}
  </div>
</div>

<style>
  .backdrop { position: fixed; inset: 0; z-index: 50; background: rgba(5, 8, 12, 0.72); display: grid; place-items: start center; padding: 6vh 16px; overflow: auto; }
  .panel { width: min(640px, 100%); background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 20px 20px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5); }
  header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  h2 { margin: 0; font-size: 18px; }
  h3 { margin: 0 0 6px; font-size: 14px; }
  .quiet { background: none; border: none; color: var(--muted); font-size: 16px; }
  fieldset { border: 1px solid var(--line); border-radius: 8px; margin: 12px 0 0; padding: 8px 12px 12px; }
  fieldset:disabled { opacity: 0.6; }
  legend { padding: 0 6px; font-weight: 600; font-size: 13px; }
  .quick { display: flex; gap: 6px; margin-bottom: 6px; }
  .quick button { padding: 3px 9px; font-size: 13px; }
  .channels { list-style: none; margin: 0; padding: 0; columns: 2; column-gap: 20px; }
  .channels li { break-inside: avoid; padding: 2px 0; }
  .channels label { cursor: pointer; }
  .field { display: grid; gap: 4px; margin-top: 8px; font-size: 13px; color: var(--muted); }
  .field input, .field select { color: var(--text); }
  .dates { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .hint { font-size: 12.5px; margin: 10px 0 0; line-height: 1.45; }
  .actions { display: flex; align-items: center; gap: 12px; margin-top: 14px; }
  .primary { background: #1d3550; border-color: var(--accent); }
  .primary:disabled { opacity: 0.5; cursor: default; }
  .progress { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line); }
  progress { width: 100%; height: 10px; accent-color: var(--accent); }
  .lines { max-height: 160px; overflow: auto; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 8px; font-size: 12px; white-space: pre-wrap; margin: 8px 0; }
  .error { color: #f0a0a0; margin: 10px 0 0; }
  .warn { color: var(--warn); }
  @media (max-width: 560px) { .channels { columns: 1; } .dates { grid-template-columns: 1fr; } }
</style>
