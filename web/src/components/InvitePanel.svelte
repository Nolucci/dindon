<script>
  import { onDestroy, onMount } from 'svelte';
  import { api, AuthError } from '../lib/api.js';
  import Modal from './Modal.svelte';
  import { matches } from '../lib/text.js';

  let { onClose, onAuthLost } = $props();

  let info = $state(null); // { configured, kind, application: { id, name, public }, url, permissions, servers: [{ id, name, following }] }
  let problem = $state('');
  let loading = $state(false);
  let copied = $state(false);
  let copiedTimer;
  let serverQ = $state('');

  const PERMISSIONS = {
    VIEW_CHANNEL: 'Voir les salons',
    READ_MESSAGE_HISTORY: 'Lire l’historique des messages',
    CREATE_PUBLIC_THREADS: 'Créer des fils publics (débats)',
    SEND_MESSAGES: 'Envoyer des messages (débats)',
    SEND_MESSAGES_IN_THREADS: 'Envoyer des messages dans les fils (débats)',
    SEND_POLLS: 'Créer des sondages',
    EMBED_LINKS: 'Intégrer des liens (débats)'
  };
  const waiting = $derived((info?.servers ?? []).filter((s) => !s.following));

  async function load() {
    loading = true;
    try {
      info = await api.botInvite();
      problem = '';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else problem = error.message;
    } finally {
      loading = false;
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(info.url);
      copied = true;
      clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => (copied = false), 2500);
    } catch {
      document.getElementById('invite-link')?.select(); // no clipboard (insecure page, refused): the link is selected for Ctrl+C
    }
  }

  // Coming back from Discord, the list shows the server that was just added
  function refocused() {
    if (!loading && info?.configured) load();
  }

  onMount(load);
  onDestroy(() => clearTimeout(copiedTimer));
</script>

<svelte:window onfocus={refocused} />

<Modal title="Inviter le bot" titleId="invite-title" {onClose}>
  {#if problem}
    <p class="banner" role="alert">{problem}</p>
  {:else if !info}
    <p class="muted">Interrogation de Discord…</p>
  {:else if !info.configured}
    <p class="muted">Aucun jeton n’est configuré (<code>DISCORD_TOKEN</code> dans <code>.env</code>) : il n’y a pas de bot à inviter.</p>
  {:else if info.kind === 'account'}
    <p class="banner" role="alert">
      Le jeton configuré est celui d’un <strong>compte personnel</strong>, pas d’un bot : un compte ne s’invite pas sur un serveur.
      Créez un bot dans le portail développeur de Discord et mettez son jeton dans <code>DISCORD_TOKEN</code>.
    </p>
  {:else}
    <p>
      <strong class="app">{info.application.name || 'Le bot'}</strong> s’ajoute depuis Discord : le bouton ouvre une page où vous choisissez le serveur.
      Il faut avoir la permission « Gérer le serveur » sur celui-ci.
    </p>

    <fieldset>
      <legend>Ce que le bot demande</legend>
      <ul class="permissions">
        {#each info.permissions as name}<li><span class="tick">✓</span>{PERMISSIONS[name] ?? name}</li>{/each}
      </ul>
      <p class="hint">
        Rien d’autre : il n’écrit pas, ne modère rien et ne gère rien. Le lien ajoute la commande <code>/dindon</code> (info, mes-données, stop, effacer, reprendre), par laquelle
        chaque membre gère ses données, arrête d’être enregistré ou se fait effacer.
      </p>
    </fieldset>

    <div class="actions">
      <a class="btn btn-primary" href={info.url} target="_blank" rel="noopener noreferrer">Ouvrir Discord</a>
      <button type="button" class="btn" onclick={copy}>{copied ? 'Lien copié' : 'Copier le lien'}</button>
    </div>
    <input id="invite-link" class="field-input link" type="text" readonly value={info.url} aria-label="Lien d’invitation" onfocus={(event) => event.currentTarget.select()} />

    {#if !info.application.public}
      <p class="banner info">
        Le réglage « Public Bot » de l’application est désactivé : seul son propriétaire peut l’ajouter à un serveur
        (portail développeur, onglet Bot).
      </p>
    {/if}

    {#if info.follow_all}
      <p class="banner info">
        <strong>Inviter suffit : Dindon suit tout serveur où le bot est.</strong> Dès l’invitation, il enregistre les messages de tous les salons
        que le bot peut voir. N’invitez-le que là où les personnes sont informées. (Pour limiter à certains serveurs, listez leurs identifiants dans
        <code>DINDON_GUILD_IDS</code>.)
      </p>
    {:else}
      <p class="banner info">
        <strong>Inviter ne suffit pas à enregistrer un serveur.</strong> Dindon ne suit que les serveurs de <code>DINDON_GUILD_IDS</code> ; sur les autres,
        le bot est présent mais rien n’est enregistré. Sur un serveur suivi, il enregistre les messages de tous les salons qu’il peut voir :
        ne l’y mettez que si les personnes sont informées.
      </p>
    {/if}

    <fieldset>
      <legend>
        Serveurs où le bot est
        <button type="button" class="tool-btn refresh" onclick={load} disabled={loading}>{loading ? 'Actualisation…' : 'Actualiser'}</button>
      </legend>
      {#if info.servers.length > 6}
        <input class="field-input" type="search" placeholder="Chercher un serveur" bind:value={serverQ} aria-label="Chercher un serveur" />
      {/if}
      {#if info.servers.length}
        <ul class="servers">
          {#each info.servers.filter((s) => matches(serverQ, s.name, s.id)) as server (server.id)}
            <li>
              <span class="name">{server.name || server.id}</span>
              <code>{server.id}</code>
              {#if server.following}
                <span class="badge success">suivi</span>
              {:else}
                <span class="badge">non suivi</span>
              {/if}
            </li>
          {/each}
        </ul>
        {#if waiting.length && !info.follow_all}
          <p class="hint">
            Pour suivre un serveur : ajoutez son identifiant à <code>DINDON_GUILD_IDS</code> dans <code>.env</code> (séparés par des virgules), puis recréez les
            conteneurs avec <code>docker compose --profile bot up -d</code>.
          </p>
        {/if}
      {:else}
        <p class="hint">Le bot n’est encore sur aucun serveur.</p>
      {/if}
    </fieldset>
  {/if}
</Modal>

<style>
  .app {
    color: var(--text-primary);
  }

  /* Settings.module.css .group, .groupTitle (the same as the import window) */
  fieldset {
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    background: var(--surface-control);
    padding: 0.25rem 1rem 1rem;
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

  .refresh {
    text-transform: none;
    letter-spacing: 0;
    font-weight: 500;
  }

  .permissions {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
    margin-top: 0.5rem;
    color: var(--text-primary);
    font-weight: 500;
  }

  .tick {
    display: inline-block;
    width: 1.25rem;
    color: var(--success);
    font-weight: 700;
  }

  .hint {
    margin-top: 0.75rem;
    font-size: 0.75rem;
    line-height: 1.5;
    color: var(--text-muted);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
  }

  .actions a {
    text-decoration: none;
  }

  .link {
    background: var(--bg-tertiary);
    font-size: 0.75rem;
    min-height: 2.125rem;
    color: var(--text-secondary);
  }

  .servers {
    list-style: none;
    display: flex;
    flex-direction: column;
    margin-top: 0.5rem;
  }

  .servers li {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    padding: 0.5rem 0.25rem;
    border-bottom: 1px solid var(--border-subtle);
  }

  .servers li:last-child {
    border-bottom: none;
  }

  .name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-primary);
    font-weight: 500;
  }

  .servers .badge {
    min-height: 1.5rem;
    font-size: 0.6875rem;
  }
</style>
