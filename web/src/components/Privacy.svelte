<script>
  import { onMount } from 'svelte';
  import { api, AuthError } from '../lib/api.js';
  import { matches, slash } from '../lib/text.js';

  let { onAuthLost } = $props();

  const fmt = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
  let info = $state(null);
  let problem = $state('');
  let notice = $state('');
  let query = $state('');
  let found = $state([]);
  let searched = $state(false);
  let chosen = $state(null);       // { user_id, name }
  let confirming = $state('');     // 'erase' while the irreversible action waits for its second click
  let busy = $state(false);
  let listQ = $state('');          // the register: a name or an id
  let listStatus = $state('all');  // all | stopped | erased
  let logAction = $state('all');

  const STATUS = { stopped: ['Plus enregistré', ''], erased: ['Effacé', 'danger'] };
  const ACTIONS = { stop: 'arrêt', erase: 'effacement', release: 'reprise', export: 'copie remise', retention: 'purge', erase_server: 'serveur effacé' };
  const SOURCES = { interface: 'interface', discord: 'commande Discord', cli: 'ligne de commande', scheduled: 'programmée' };
  const subjects = $derived((info?.subjects ?? []).filter((s) => matches(listQ, s.name, s.user_id) && (listStatus === 'all' || s.status === listStatus)));
  const entries = $derived((info?.log ?? []).filter((e) => (logAction === 'all' || e.action === logAction) && matches(listQ, e.user_id, e.source)));
  const when = (iso) => (iso ? fmt.format(new Date(iso)) : '—');

  function fail(error) {
    if (error instanceof AuthError) onAuthLost();
    else problem = error.message;
  }

  async function load() {
    try {
      info = await api.privacy();
      problem = '';
    } catch (error) {
      fail(error);
    }
  }

  async function search(event) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    try {
      found = await api.privacyFind(query.trim());
      searched = true;
      problem = '';
    } catch (error) {
      fail(error);
    }
  }

  function choose(person) {
    chosen = { user_id: person.user_id, name: person.name };
    confirming = '';
    notice = '';
  }

  async function act(action) {
    if (action === 'erase' && confirming !== 'erase') {
      confirming = 'erase';
      return;
    }
    busy = true;
    try {
      const result = await api.privacyAct(action, chosen.user_id);
      notice =
        action === 'erase'
          ? `Effacé : ${result.messages} messages, ${result.reactions} réactions, ${result.conversations} conversations, ${result.files?.files ?? 0} fichier(s) réécrit(s). La personne ne sera plus enregistrée.`
          : action === 'stop'
            ? 'Cette personne n’est plus enregistrée. Ce qui était déjà gardé reste jusqu’à un effacement.'
            : result.released
              ? 'Cette personne peut de nouveau être enregistrée.'
              : 'Cette personne n’était pas dans la liste.';
      confirming = '';
      if (action === 'erase') chosen = null;
      await load();
      if (searched) found = await api.privacyFind(query.trim());
    } catch (error) {
      fail(error);
    } finally {
      busy = false;
    }
  }

  onMount(load);
</script>

<div class="page">
  <header>
    <h1>Vie privée</h1>
    <p class="subtitle">
      Les personnes qui ont demandé à ne plus être enregistrées, et ce que vous pouvez faire pour elles. Une personne s’arrête et s’efface seule depuis Discord avec
      <code>/dindon stop</code> ; ici vous traitez une demande reçue autrement. Le cadre (ce que cela couvre et ne couvre pas) est dans <code>docs/CONFORMITE.md</code>.
    </p>
  </header>

  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}
  {#if notice}<p class="banner info" role="status">{notice}</p>{/if}

  {#if info}
    <section class="panel card" aria-label="Traiter une demande">
      <h2 class="eyebrow">Traiter une demande</h2>
      <form onsubmit={search}>
        <label class="visually-hidden" for="privacy-q">Nom ou identifiant Discord</label>
        <input id="privacy-q" class="field-input" type="text" placeholder="Nom, ou identifiant Discord" bind:value={query} autocomplete="off" />
        <button class="btn" type="submit" disabled={query.trim().length < 2}>Chercher</button>
      </form>
      {#if searched && !found.length}
        <p class="muted small">Personne n’est connu sous ce nom. Pour agir sur quelqu’un que Dindon n’a jamais vu, cherchez son identifiant Discord en entier (des chiffres).</p>
      {/if}
      {#if found.length}
        <ul class="people">
          {#each found as person (person.user_id)}
            <li>
              <button type="button" class="pick" class:on={chosen?.user_id === person.user_id} onclick={() => choose(person)}>
                <span class="name">{person.name}</span>
                <code>{person.user_id}</code>
                <span class="muted small">{person.messages} messages</span>
                {#if person.registered}<span class="badge small">dans la liste</span>{/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}

      {#if chosen}
        <div class="chosen" role="group" aria-label="Actions pour {chosen.name}">
          <p><strong>{chosen.name}</strong> <code>{chosen.user_id}</code></p>
          <div class="actions">
            <button class="btn" type="button" disabled={busy} onclick={() => act('stop')}>Ne plus enregistrer</button>
            <button class="btn btn-danger" type="button" disabled={busy} onclick={() => act('erase')}>
              {confirming === 'erase' ? 'Confirmer : effacer pour toujours' : 'Ne plus enregistrer et effacer'}
            </button>
            <a class="btn" href="/api/privacy/export/{chosen.user_id}" download>Copie de ses données</a>
            <button class="btn" type="button" disabled={busy} onclick={() => act('release')}>Enregistrer de nouveau</button>
            {#if confirming === 'erase'}<button class="btn" type="button" onclick={() => (confirming = '')}>Annuler</button>{/if}
          </div>
          <p class="hint">
            « Effacer » supprime ses messages, réactions, mentions, noms, ce qui en a été tiré (conversations, vecteurs) et ses traces dans les fichiers déposés ou archivés.
            Les sauvegardes de la base disparaissent d’elles-mêmes sous 14 jours. Ce que d’autres ont écrit à son sujet reste (c’est leur message).
          </p>
        </div>
      {/if}
    </section>

    <section class="panel card" aria-label="Liste des personnes non enregistrées">
      <h2 class="eyebrow">Personnes non enregistrées ({subjects.length}{subjects.length !== info.subjects.length ? ` sur ${info.subjects.length}` : ''})</h2>
      {#if info.subjects.length > 3 || info.log.length > 3}
        <div class="toolbar" role="search" aria-label="Recherche et filtres du registre">
          <input class="field-input" type="search" placeholder="Chercher un nom ou un identifiant… (/)" bind:value={listQ} aria-label="Chercher dans le registre" use:slash />
          <select class="select" bind:value={listStatus} aria-label="Filtrer le registre par état">
            <option value="all">Tous les états</option>
            <option value="stopped">Plus enregistrés</option>
            <option value="erased">Effacés</option>
          </select>
        </div>
      {/if}
      {#if info.subjects.length}
        <ul class="rows">
          {#each subjects as subject (subject.user_id)}
            <li>
              <span class="name">{subject.name ?? 'inconnu'}</span>
              <code>{subject.user_id}</code>
              <span class="badge small" class:danger={STATUS[subject.status][1] === 'danger'}>{STATUS[subject.status][0]}</span>
              <span class="muted small">{when(subject.requested_at)} · {SOURCES[subject.source] ?? subject.source}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Personne n’a demandé à ne plus être enregistré.</p>
      {/if}
      <p class="muted small">Seul l’identifiant Discord est gardé, pour que la personne ne soit pas enregistrée de nouveau (import, rattrapage, bot).</p>
    </section>

    <section class="panel card" aria-label="Durée de conservation">
      <h2 class="eyebrow">Durée de conservation</h2>
      <p>
        {#if info.retention_days > 0}
          Les messages de plus de <strong>{info.retention_days} jours</strong> sont supprimés chaque jour.
        {:else}
          <strong>Aucune limite</strong> : rien n’est supprimé avec le temps. Pour en fixer une : <code>DINDON_RETENTION_DAYS</code> dans <code>.env</code>.
        {/if}
      </p>
      <p>
        {#if info.erase_on_removal}
          Si le bot est <strong>retiré d’un serveur</strong>, tout ce qui le concerne est <strong>supprimé aussitôt</strong>.
        {:else}
          Si le bot est retiré d’un serveur, ses données <strong>restent</strong>. Pour tout supprimer dans ce cas : <code>DINDON_ERASE_ON_REMOVAL=true</code> dans <code>.env</code>.
        {/if}
      </p>
    </section>

    <section class="panel card" aria-label="Journal">
      <h2 class="eyebrow">Journal (les 50 derniers actes)</h2>
      {#if info.log.length > 3}
        <div class="toolbar">
          <select class="select" bind:value={logAction} aria-label="Filtrer le journal par acte">
            <option value="all">Tous les actes</option>
            {#each Object.entries(ACTIONS) as [key, label]}<option value={key}>{label}</option>{/each}
          </select>
          <span class="found" aria-live="polite">{entries.length} sur {info.log.length}</span>
        </div>
      {/if}
      {#if info.log.length}
        <ul class="rows">
          {#each entries as entry (entry.id)}
            <li>
              <span class="muted small">{when(entry.at)}</span>
              <span class="name">{ACTIONS[entry.action] ?? entry.action}</span>
              {#if entry.user_id}<code>{entry.user_id}</code>{/if}
              <span class="muted small">{SOURCES[entry.source] ?? entry.source}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Rien pour l’instant. Le journal ne garde que des nombres et des identifiants, jamais un message.</p>
      {/if}
    </section>
  {:else if !problem}
    <p class="muted">Chargement…</p>
  {/if}
</div>

<style>
  .page { flex: 1; min-height: 0; overflow-y: auto; padding: 1.5rem 1.75rem 2.5rem; display: flex; flex-direction: column; gap: 1.25rem; animation: fadeIn var(--transition-slow) both; }
  h1 { font-size: clamp(1.5rem, 2vw, 1.9rem); line-height: 1.1; font-weight: 700; color: var(--text-primary); }
  .subtitle { max-width: 68ch; margin-top: 0.5rem; color: var(--text-secondary); }
  .card { padding: 1rem 1.125rem; display: flex; flex-direction: column; gap: 0.75rem; box-shadow: var(--shadow-sm); }
  form { display: flex; gap: 0.5rem; }
  form .field-input { flex: 1; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  ul { list-style: none; display: flex; flex-direction: column; }
  .rows li, .pick { display: flex; flex-wrap: wrap; align-items: center; gap: 0.625rem; padding: 0.5rem 0.25rem; border-bottom: 1px solid var(--border-subtle); }
  .rows li:last-child { border-bottom: none; }
  .pick { width: 100%; background: none; border: 1px solid transparent; border-radius: var(--radius-md); color: inherit; font: inherit; text-align: left; cursor: pointer; }
  .pick:hover, .pick.on { background: var(--surface-control); border-color: var(--border-subtle); }
  .name { flex: 1 1 8rem; min-width: 0; color: var(--text-primary); font-weight: 500; }
  .chosen { border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); padding: 0.875rem 1rem; display: flex; flex-direction: column; gap: 0.75rem; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.625rem; }
  .actions a { text-decoration: none; }
  .hint { font-size: 0.75rem; line-height: 1.5; color: var(--text-muted); }
  .small { font-size: 0.75rem; }
  .badge.small { min-height: 1.5rem; font-size: 0.6875rem; }
  @media (max-width: 720px) { .page { padding: 1rem 1rem 2rem; } }
</style>
