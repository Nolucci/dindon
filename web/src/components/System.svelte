<script>
  import { onDestroy, onMount } from 'svelte';
  import { api, AuthError } from '../lib/api.js';
  import { ago as agoOf } from '../lib/format.js';
  import { matches, slash } from '../lib/text.js';

  let { guild = '', section = $bindable('status'), onAuthLost } = $props();

  // Deleting what the analysis derived (never the messages), one kind at a time, after a confirmation
  const RESULTS = {
    themes: ['Thèmes', 'les thèmes trouvés ou validés pour ce serveur'],
    positions: ['Positions', 'les positions lues, leurs citations et les scores qui en viennent (les conversations pourront être relues)'],
    contradictions: ['Contradictions', 'les scores par axe dont les contradictions sont calculées'],
  };
  let resetNote = $state('');
  let resetting = $state('');
  async function resetResults(what) {
    if (!confirm(`Supprimer ${RESULTS[what][1]} ? Les messages ne sont pas touchés. Serveur : ${info?.followed.find((s) => s.id === guild)?.name || guild}. Cette action est définitive.`)) return;
    resetting = what;
    resetNote = '';
    try {
      const done = await api.analysisReset(guild, what);
      resetNote = `${RESULTS[what][0]} supprimé${what === 'themes' ? 's' : 'es'} (${Object.values(done.deleted).reduce((a, b) => a + b, 0)} lignes).`;
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else resetNote = error.message;
    } finally {
      resetting = '';
    }
  }

  const fmt = new Intl.NumberFormat('fr-FR');
  let info = $state(null);
  let problem = $state('');
  let debateFleet = $state(null);
  let debateChecks = $state(null);
  const duration = (n) => n == null ? '—' : `${Math.round(n)} s`;
  async function loadDebateStatus() {
    try { const [fleet, overview] = await Promise.all([api.debateComputers(), api.debates()]); debateFleet = fleet; debateChecks = overview.checks; }
    catch (error) { if (error instanceof AuthError) onAuthLost(); }
  }
  let now = $state(Date.now());
  let timer;
  let fleetTimer;
  let tick;
  // Automatic reading: the AI reads what the bot records, by itself, when it was asked to
  let auto = $state(null);         // /api/automation: settings, state, pending, next_at, timezone, intervals
  let autoForm = $state(null);
  let autoNote = $state('');
  const autoChanged = $derived(auto && autoForm && JSON.stringify(autoForm) !== JSON.stringify(auto.settings));
  const hours = Array.from({ length: 24 }, (_, h) => h);
  const everyday = $derived(autoForm && Number(autoForm.window_from) === 0 && Number(autoForm.window_to) === 24);
  const EVERY = { 10: '10 minutes', 15: '15 minutes', 30: '30 minutes', 60: 'heure', 180: '3 heures', 360: '6 heures', 1440: 'jour' };

  async function loadAuto() {
    try {
      auto = await api.automation();
      if (!autoForm || !autoChanged) autoForm = { ...auto.settings };
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
    }
  }

  async function saveAuto() {
    autoNote = '';
    try {
      const f = autoForm;
      auto = await api.automationSave({ ...f, interval_minutes: Number(f.interval_minutes), batch: Number(f.batch), window_from: Number(f.window_from), window_to: Number(f.window_to),
                                        positions_acknowledged: Boolean(f.positions && f.positions_acknowledged) });
      autoForm = { ...auto.settings };
      autoNote = 'Enregistré.';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else autoNote = error.message;
    }
  }

  let dmap = $state(null);         // /api/discord-map: enabled, max_people, names, kinds (what `/dindon map` shows on Discord)
  let dmapSaved = $state(null);
  let dmapNote = $state('');
  const dmapChanged = $derived(dmap && dmapSaved && JSON.stringify(dmap) !== JSON.stringify(dmapSaved));
  const DMAP_KINDS = { reply: 'Réponses', mention: 'Mentions', reaction: 'Réactions' };
  const DMAP_SECTIONS = { activity: 'Activité (messages, rang, jours actifs, contacts, réactions reçues)', months: 'Messages par mois (graphique)', habits: 'Rythme (heures et jours habituels)', links: 'Liens principaux (avec qui la personne échange)' };
  const DMAP_FILTERS = { weight: 'Force minimale des liens' };
  const dmapSensitive = $derived(dmap && (dmap.sections.includes('roles') || dmap.sections.includes('axes') || dmap.filters.includes('theme') || dmap.filters.includes('ideology')));

  async function loadDmap() {
    try {
      dmapSaved = await api.discordMap();
      dmap = { ...dmapSaved, kinds: [...dmapSaved.kinds], sections: [...dmapSaved.sections] };
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
    }
  }

  async function saveDmap() {
    dmapNote = '';
    try {
      dmapSaved = await api.discordMapSave({ ...dmap, max_people: Number(dmap.max_people), names: Number(dmap.names), acknowledged: Boolean(dmapSensitive && dmap.acknowledged) });
      dmap = { ...dmapSaved, kinds: [...dmapSaved.kinds], sections: [...dmapSaved.sections] };
      dmapNote = 'Enregistré.';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else dmapNote = error.message;
    }
  }

  // The card of /dindon card: which pages and which blocks of each page it shows (only the administrator changes this, from here).
  let dcard = $state(null);
  let dcardSaved = $state(null);
  let dcardNote = $state('');
  const dcardChanged = $derived(dcard && dcardSaved && JSON.stringify({ pages: dcard.pages, blocks: dcard.blocks }) !== JSON.stringify({ pages: dcardSaved.pages, blocks: dcardSaved.blocks }));
  const DCARD_PAGES = { profile: 'Profil', interactions: 'Interactions', positions: 'Positions', contradictions: 'Contradictions' };
  const DCARD_BLOCKS = {
    headline: 'Chiffres clés (messages, jours actifs, rang)', activity: 'Activité récente', channels: 'Salons les plus utilisés', roles: 'Rôles que la personne s’est donnés', presence: 'Dates de présence',
    close: 'Échanges les plus proches', replies: 'Réponses données et reçues', sides: 'Accords et désaccords',
    axes: 'Barres des axes', positions: 'Positions avec preuve (citation et lien)',
    verdicts: 'Rôles face aux propos', against: 'Rôles contredits (avec preuve)', conflicts: 'Rôles qui s’opposent entre eux', changes: 'Changements d’avis',
  };
  const cloneCard = (c) => ({ pages: [...c.pages], blocks: Object.fromEntries(Object.entries(c.blocks).map(([k, v]) => [k, [...v]])), available: c.available });

  async function loadDcard() {
    try {
      dcardSaved = await api.discordCard();
      dcard = cloneCard(dcardSaved);
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
    }
  }

  async function saveDcard() {
    dcardNote = '';
    try {
      dcardSaved = { ...(await api.discordCardSave({ pages: dcard.pages, blocks: dcard.blocks })), available: dcard.available };
      dcard = cloneCard(dcardSaved);
      dcardNote = 'Enregistré.';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else dcardNote = error.message;
    }
  }

  function limitDmapNames(event) {
    dmap.names = Math.min(Number(dmap.names), Number(event.currentTarget.value));
  }

  async function runNow() {
    try {
      auto = await api.automationRun();
      autoNote = 'Un cycle va démarrer dans quelques secondes.';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
    }
  }

  const ago2 = (iso) => (iso ? ago(iso) : 'jamais');
  const planned = (iso) => (iso ? new Date(iso).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—');
  const summary = (result) => {
    if (!result) return null;
    if (result.idle) return 'rien à lire';
    return result.servers.map((s) => `${s.stages.length} étape${s.stages.length > 1 ? 's' : ''} : ${s.state === 'done' ? 'terminé' : s.state === 'failed' ? `échec (${s.error})` : s.error ?? ({ cancelled: 'annulé', running: 'en cours', idle: 'en attente' }[s.state] ?? s.state)}`).join(' ; ');
  };

  // Performance: what the bot and the AI may take of the machine, at the cost of speed
  let perf = $state(null);          // /api/performance: settings, presets, limits, keep_alive, cpu_count
  let workers = $state(null);
  let workerUrl = $state('');
  let workerNote = $state('');
  let shareForm = $state(null);     // the percentage of the work by computer ("local" is the server), while it is edited
  const shareKey = (worker) => (worker.local ? 'local' : worker.url);
  const sharesChanged = $derived(shareForm && workers?.shares && JSON.stringify(shareForm) !== JSON.stringify(workers.shares));
  let performanceOpen = $state(false);
  $effect(() => { if (form?.preset === 'custom') performanceOpen = true; });
  let form = $state(null);          // what the person is editing
  let saved = $state('');
  const PRESET_NAMES = { saver: 'Économe', balanced: 'Équilibré', full: 'Plein régime', custom: 'Personnalisé' };
  const PRESET_HELP = { saver: 'La machine reste disponible ; tout est plus lent.', balanced: 'Un compromis.', full: 'Le plus rapide ; la machine est très sollicitée pendant une analyse.', custom: 'Vos propres réglages.' };
  const changed = $derived(perf && form && JSON.stringify(form) !== JSON.stringify(perf.settings));
  const slower = $derived(form ? (100 / form.ai_max_load).toFixed(1).replace('.0', '').replace('.', ',') : '1');

  async function loadPerf() {
    try {
      perf = await api.performance();
      form = { ...perf.settings };
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
    }
  }

  async function loadWorkers() {
    try {
      workers = await api.analysisWorkers();
      shareForm = { ...workers.shares };
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else workerNote = error.message;
    }
  }

  async function saveWorkers(urls) {
    workerNote = '';
    try {
      workers = await api.analysisWorkersSave(urls);
      shareForm = { ...workers.shares };
      workerUrl = '';
      workerNote = 'Liste enregistrée. Les prochaines analyses utiliseront les ordinateurs connectés.';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else workerNote = error.message;
    }
  }

  function setShare(key, value) {
    const selected = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
    const others = Object.keys(shareForm).filter((other) => other !== key);
    if (!others.length) { shareForm = { [key]: 100 }; return; }
    const remaining = 100 - selected;
    const total = others.reduce((sum, other) => sum + shareForm[other], 0);
    const exact = others.map((other) => ({ key: other, value: remaining * (total ? shareForm[other] / total : 1 / others.length) }));
    const next = Object.fromEntries(exact.map((entry) => [entry.key, Math.floor(entry.value)]));
    const extra = remaining - Object.values(next).reduce((sum, amount) => sum + amount, 0);
    exact.sort((a, b) => (b.value - Math.floor(b.value)) - (a.value - Math.floor(a.value)));
    for (let i = 0; i < extra; i++) next[exact[i].key]++;
    shareForm = Object.fromEntries(Object.keys(shareForm).map((other) => [other, other === key ? selected : next[other]]));
  }

  function equalShares() {
    const keys = Object.keys(shareForm);
    const base = Math.floor(100 / keys.length);
    shareForm = Object.fromEntries(keys.map((key, index) => [key, base + (index < 100 - base * keys.length ? 1 : 0)]));
  }

  async function saveShares() {
    workerNote = '';
    try {
      workers = await api.analysisSharesSave(shareForm);
      shareForm = { ...workers.shares };
      workerNote = 'Répartition enregistrée. Elle s’applique dès les prochains calculs, même pendant une analyse.';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else workerNote = error.message;
    }
  }

  function pickPreset(name) {
    saved = '';
    form = name === 'custom' ? { ...form, preset: 'custom' } : { ...perf.presets[name], preset: name };
  }

  function edited() {
    saved = '';
    form = { ...form, preset: 'custom' };
  }

  async function savePerf() {
    try {
      const body = { ...form, ai_max_load: Number(form.ai_max_load), ai_threads: Number(form.ai_threads), ai_batch: Number(form.ai_batch), bot_batch_seconds: Number(form.bot_batch_seconds) };
      perf = await api.performanceSave(body);
      form = { ...perf.settings };
      saved = 'Enregistré. Le bot en tient compte dans la demi-minute, l’IA tout de suite si elle travaille.';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else problem = error.message;
    }
  }

  let level = $state('all');     // all | error | warning | info: the points to look at
  let q = $state('');            // the followed servers

  const worst = $derived(info?.checks.some((c) => c.level === 'error') ? 'error' : info?.checks.some((c) => c.level === 'warning') ? 'warning' : 'ok');
  const checks = $derived((info?.checks ?? []).filter((c) => level === 'all' || c.level === level));
  const servers = $derived((info?.followed ?? []).filter((s) => matches(q, s.name, s.id)));
  const attention = $derived(info ? info.checks.filter((c) => c.level !== 'info').length : 0);

  async function refresh() {
    try {
      info = await api.system();
      problem = '';
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else problem = error.message;
    }
  }

  onMount(() => {
    loadDebateStatus();
    fleetTimer = setInterval(() => { if (!document.hidden && section === 'status') loadDebateStatus(); }, 5000);
    refresh();
    loadPerf();
    loadWorkers();
    loadAuto();
    loadDmap();
    loadDcard();
    timer = setInterval(() => { refresh(); loadAuto(); }, 10000);
    tick = setInterval(() => (now = Date.now()), 1000);
  });
  onDestroy(() => {
    clearInterval(timer);
    clearInterval(fleetTimer);
    clearInterval(tick);
  });

  const ago = (iso) => agoOf(iso, now);
  const size = (bytes) => (bytes > 1e9 ? `${(bytes / 1e9).toFixed(1)} Go` : `${Math.max(1, Math.round(bytes / 1e6))} Mo`);
  const BOT = { connected: ['Connecté', 'success'], disconnected: ['Déconnecté', 'danger'], silent: ['Ne répond plus', 'danger'], unknown: ['Jamais vu', ''] };
</script>

<div class="page">
  <header>
    <div>
      <h1>Système</h1>

    </div>
    {#if info}
      <span class="badge" class:success={worst === 'ok' && !workers?.workers?.some((w) => !w.online)} class:danger={worst === 'error'} class:accent={worst === 'warning' || workers?.workers?.some((w) => !w.online)}>
        {workers?.workers?.some((w) => !w.online) ? 'Ordinateur d’analyse hors ligne' : worst === 'ok' ? 'Services principaux disponibles' : `${attention} point${attention > 1 ? 's' : ''} à voir`}
      </span>
    {/if}
  </header>

  <nav class="systemTabs" aria-label="Sections du système">
    {#each [['status', 'État'], ['automation', 'Analyses auto'], ['discord', 'Discord'], ['performance', 'Performance'], ['maintenance', 'Maintenance']] as [key, label]}
      <button type="button" class="btn" class:active={section === key} aria-pressed={section === key} onclick={() => section = key}>{label}</button>
    {/each}
  </nav>
  {#if problem}<p class="banner" role="alert">{problem}</p>{/if}

  {#if !info}
    <p class="muted">Chargement…</p>
  {:else}
    {#if section === 'status'}
    {#if info.checks.length}
      <section class="panel checks" aria-label="Points à voir">
        <div class="toolbar">
          <h2 class="eyebrow">À voir</h2>
          <select class="select" bind:value={level} aria-label="Filtrer les points à voir">
            <option value="all">Tous ({info.checks.length})</option>
            <option value="error">Erreurs ({info.checks.filter((c) => c.level === 'error').length})</option>
            <option value="warning">Avertissements ({info.checks.filter((c) => c.level === 'warning').length})</option>
            <option value="info">Informations ({info.checks.filter((c) => c.level === 'info').length})</option>
          </select>
        </div>
        <ul>
          {#each checks as check}
            <li class={check.level}><span class="dot"></span><span>{check.text}</span></li>
          {/each}
        </ul>
      </section>
    {/if}

    <div class="grid">
      <section class="panel card" aria-label="Bot Discord">
        <header><h2 class="eyebrow">Bot Discord</h2>
          {#if info.wants_bot}<span class="badge" class:success={BOT[info.bot.state][1] === 'success'} class:danger={BOT[info.bot.state][1] === 'danger'}>{BOT[info.bot.state][0]}</span>
          {:else}<span class="badge">Non configuré</span>{/if}
        </header>
        {#if info.bot.state === 'unknown'}
          <p class="muted">Aucun signe de vie reçu.</p>
        {:else}
          <dl>
            <div><dt>Dernier signe de vie</dt><dd>{ago(info.bot.updated_at)}</dd></div>
            <div><dt>Démarré</dt><dd>{ago(info.bot.data.started_at)}</dd></div>
            <div><dt>Sessions · reconnexions avec perte possible</dt><dd>{fmt.format(info.bot.data.sessions ?? 0)} · {fmt.format(info.bot.data.gaps ?? 0)}</dd></div>
            <div><dt>Messages reçus · enregistrés</dt><dd>{fmt.format(info.bot.data.received ?? 0)} · {fmt.format(info.bot.data.new ?? 0)}</dd></div>
            <div><dt>Dernier nouveau message</dt><dd>{ago(info.bot.data.last_new_at)}</dd></div>
            <div><dt>Modifications · suppressions appliquées</dt><dd>{fmt.format(info.bot.data.edited ?? 0)} · {fmt.format(info.bot.data.deleted ?? 0)}</dd></div>
          </dl>
        {/if}
      </section>

      <section class="panel card" aria-label="Collecte">
        <header><h2 class="eyebrow">Collecte et rattrapage</h2>
          <span class="badge" class:success={info.collector.enabled}>{info.collector.enabled ? (info.collector.mode === 'catchup' ? 'Rattrapage nocturne' : 'Surveillance') : 'Coupée'}</span>
        </header>
        {#if info.collector.enabled}
          <dl>
            {#if info.collector.mode !== 'catchup'}<div><dt>Dernier relevé</dt><dd>{ago(info.collector.last_poll_at)}</dd></div>{/if}
            <div><dt>Dernier rattrapage</dt><dd>{info.collector.last_catchup_at ? ago(info.collector.last_catchup_at) : 'pas encore fait'}</dd></div>
            <div><dt>Exports faits</dt><dd>{fmt.format(info.collector.exports ?? 0)}</dd></div>
            <div><dt>Salons en échec</dt><dd>{fmt.format(info.collector.failing_channels ?? 0)}</dd></div>
          </dl>
        {:else}
          <p class="muted">Rien n’est relu sur Discord : seuls le bot (le direct) et les exports déposés dans <code>inbox/</code> alimentent la base.</p>
        {/if}
      </section>

      <section class="panel card" aria-label="Base de données">
        <header><h2 class="eyebrow">Base de données</h2><span class="badge success">En ligne</span></header>
        <dl>
          <div><dt>Messages</dt><dd>{info.database.messages_approximate ? '≈ ' : ''}{fmt.format(info.database.messages)}</dd></div>
          <div><dt>Personnes</dt><dd>{fmt.format(info.database.people)}</dd></div>
          <div><dt>Salons · serveurs</dt><dd>{fmt.format(info.database.channels)} · {fmt.format(info.database.servers)}</dd></div>
          <div><dt>Taille</dt><dd>{size(info.database.bytes)}</dd></div>
          <div><dt>Dernier import</dt><dd>{ago(info.database.last_import_at)}</dd></div>
          <div><dt>Migrations</dt><dd>{info.database.migrations}</dd></div>
        </dl>
      </section>

      <section class="panel card" aria-label="IA locale">
        <header><h2 class="eyebrow">IA locale</h2>
          <span class="badge" class:success={info.ollama.reachable} class:danger={!info.ollama.reachable}>{info.ollama.reachable ? 'Ollama prêt' : 'Ollama ne répond pas'}</span>
        </header>
        <dl>
          {#each Object.entries(info.ollama.models_ready) as [name, there]}
            <div><dt><code>{name}</code></dt><dd>{there ? 'installé' : 'à installer'}</dd></div>
          {/each}
        </dl>
      </section>
    </div>

      <section class="panel card" aria-label="Vérification des débats">
        <header><h2>Vérification des débats</h2><button type="button" class="btn" onclick={loadDebateStatus}>Actualiser</button></header>
        {#if debateChecks}<p class="muted small">{debateChecks.mode === 'off' ? 'Désactivée' : debateChecks.mode === 'live' ? 'Réponses avec vérification des sources' : debateChecks.mode === 'answer' ? 'Réponses sans recherche Internet' : 'Observation'} · {debateChecks.model}</p>{#if debateChecks.why_not}<p class="banner">{debateChecks.why_not}</p>{/if}{/if}
        {#if debateFleet?.computers?.length}
          {#if !debateFleet.fresh}<p class="muted small">Dernier état connu · {duration(debateFleet.age_seconds)}</p>{/if}
          <ul class="workerList">{#each debateFleet.computers as machine (machine.url)}<li>
            <strong>{machine.local ? 'Serveur' : machine.url}</strong>
            <span class="badge" class:danger={!machine.online || !machine.has_model}>{!machine.online ? 'Hors ligne' : !machine.has_model ? 'Modèle absent' : machine.active ? 'En cours' : 'Disponible'}</span>
            <span class="muted small">{machine.calls} vérifications · {duration(machine.average)} en moyenne · {machine.observed} % · {machine.errors} erreurs</span>
            {#if machine.last_error}<span class="muted small">{machine.last_error}</span>{/if}
          </li>{/each}</ul>
        {:else}<p class="muted small">Aucune activité de vérification disponible.</p>{/if}
      </section>
    {/if}
    {#if section === 'automation'}
    <section class="panel card wide" aria-label="Lecture automatique">
      <header><h2 class="eyebrow">Lecture automatique</h2>{#if auto}<span class="badge" class:success={auto.settings.enabled}>{auto.settings.enabled ? 'Activée' : 'Éteinte'}</span>{/if}</header>
      <p class="muted small">L’IA lit d’elle-même ce que le bot enregistre, <strong>un peu à la fois</strong>, sans que vous ayez à lancer quoi que ce soit. Elle respecte les limites de performance ci-dessous et ne démarre jamais pendant qu’une autre analyse tourne.</p>
      {#if autoForm}
        <label class="switch"><input type="checkbox" bind:checked={autoForm.enabled} aria-label="Activer la lecture automatique" /> <span>Activer la lecture automatique</span></label>
        <fieldset class="what" disabled={!autoForm.enabled}>
          <legend class="muted small">Ce qui est lu</legend>
          <label class="check"><input type="checkbox" bind:checked={autoForm.vectors} /> <span><strong>Conversations et vecteurs</strong> : les nouveaux messages deviennent des conversations. Sans regard sur les personnes.</span></label>
          <label class="check"><input type="checkbox" bind:checked={autoForm.themes} /> <span><strong>Thèmes</strong> : nouvelle recherche quand 25 conversations ne sont dans aucun thème. Remplace les propositions que personne n’a touchées.</span></label>
          <label class="check"><input type="checkbox" bind:checked={autoForm.positions} /> <span><strong>Positions des personnes</strong> : ce que chacun pense, avec citations, puis les axes et la cohérence des rôles. <em>Regarde les opinions des gens.</em></span></label>
          {#if autoForm.positions}
            <label class="check ack" class:missing={!autoForm.positions_acknowledged}><input type="checkbox" bind:checked={autoForm.positions_acknowledged} aria-label="Les personnes sont informées" /> <span>Je confirme que les personnes de ce serveur <strong>sont informées</strong> et que le cadre juridique est validé (le cadre de traitement des données). Les messages d’une personne qui a demandé à ne plus être enregistrée ne sont jamais lus.</span></label>
          {/if}
        </fieldset>
        <div class="knobs">
          <label class="knob"><span class="knobHead"><span>Tous les</span></span>
            <select class="select" bind:value={autoForm.interval_minutes} aria-label="Fréquence de la lecture automatique">
              {#each auto.intervals as m}<option value={m}>{m >= 60 && m < 1440 ? `${m / 60} ${m === 60 ? 'heure' : 'heures'}` : m === 1440 ? 'jour' : `${m} minutes`}</option>{/each}
            </select>
            <span class="muted small">Un cycle ne fait que ce qu’il y a à faire : s’il n’y a rien de nouveau, il ne demande rien aux modèles.</span>
          </label>
          <label class="knob"><span class="knobHead"><span>Conversations lues par cycle (positions)</span><output>{autoForm.batch}</output></span>
            <input type="range" min="1" max="200" step="1" bind:value={autoForm.batch} aria-label="Conversations lues par cycle" />
            <span class="muted small">Un gros retard se résorbe sur plusieurs cycles. Les plus importantes passent d’abord.</span>
          </label>
          <div class="knob"><span class="knobHead"><span>Heures de lecture</span></span>
            <div class="hours">
              <select class="select" bind:value={autoForm.window_from} aria-label="Lire à partir de">{#each hours as h}<option value={h}>{h} h</option>{/each}</select>
              <span class="muted small">à</span>
              <select class="select" bind:value={autoForm.window_to} aria-label="Lire jusqu’à">{#each hours as h}{#if h > 0}<option value={h}>{h} h</option>{/if}{/each}<option value={24}>24 h</option></select>
            </div>
            <span class="muted small">{everyday ? 'Toute la journée.' : `De ${autoForm.window_from} h à ${autoForm.window_to} h`} ({auto.timezone}). 0 h → 24 h : à toute heure ; 22 h → 6 h : la nuit.</span>
          </div>
        </div>
        <div class="actions">
          <button type="button" class="btn btn-primary" onclick={saveAuto} disabled={!autoChanged || (autoForm.positions && !autoForm.positions_acknowledged)}>Enregistrer</button>
          {#if autoChanged}<button type="button" class="btn" onclick={() => { autoForm = { ...auto.settings }; autoNote = ''; }}>Annuler</button>{/if}
          <button type="button" class="btn" onclick={runNow} disabled={auto.running || autoChanged}>Lancer un cycle maintenant</button>
          {#if autoNote}<span class="muted small" role="status">{autoNote}</span>{/if}
        </div>
        <dl class="status">
          <div><dt>À lire</dt><dd>{auto.pending.new_messages} messages nouveaux · {auto.pending.without_vector} conversations sans vecteur · {auto.pending.unread} à lire pour les positions · {auto.pending.unplaced} hors thème</dd></div>
          <div><dt>Dernier cycle</dt><dd>{ago2(auto.state.last_cycle_at)}{#if auto.state.last_result} · {summary(auto.state.last_result)}{/if}</dd></div>
          <div><dt>Prochain</dt><dd>{auto.settings.enabled ? (auto.in_window ? (auto.next_at ? `à partir de ${planned(auto.next_at)}` : '—') : 'en dehors des heures de lecture') : 'éteint'}</dd></div>
        </dl>
      {:else}
        <p class="muted">Chargement…</p>
      {/if}
    </section>

    {/if}
    {#if section === 'discord'}
    <section class="panel card wide" aria-label="Carte sur Discord">
      <header><h2 class="eyebrow">Carte sur Discord</h2>{#if dmap}<span class="badge" class:success={dmap.enabled}>{dmap.enabled ? 'Activée' : 'Éteinte'}</span>{/if}</header>
      <p class="muted small">La commande <code>/dindon map</code> poste dans le salon une image de la carte, <strong>visible par tout le salon</strong>. Elle ne montre que ce que vous réglez ici, jamais un message, et jamais une personne qui a demandé à ne plus être enregistrée.</p>
      {#if dmap}
        <label class="switch"><input type="checkbox" bind:checked={dmap.enabled} aria-label="Activer la carte sur Discord" /> <span>Activer <code>/dindon map</code></span></label>
        <fieldset class="what" disabled={!dmap.enabled}>
          <legend class="muted small">Types d’échanges montrés</legend>
          {#each Object.entries(DMAP_KINDS) as [kind, label]}
            <label class="check"><input type="checkbox" value={kind} bind:group={dmap.kinds} /> <span>{label}</span></label>
          {/each}
        </fieldset>
        <fieldset class="what" disabled={!dmap.enabled}>
          <legend class="muted small">Fiche de la personne (Activité en salon vocal, à droite de la carte)</legend>
          {#each Object.entries(DMAP_SECTIONS) as [section, label]}
            <label class="check"><input type="checkbox" value={section} bind:group={dmap.sections} /> <span>{label}</span></label>
          {/each}
          <label class="check"><input type="checkbox" value="roles" bind:group={dmap.sections} /> <span><strong>Rôles</strong> que la personne s’est donnés. <em>Lecture de ce qu’elle dit d’elle-même.</em></span></label>
          <label class="check"><input type="checkbox" value="axes" bind:group={dmap.sections} /> <span><strong>Positions sur les axes</strong> (les 5 plus nettes, sans citation). <em>Lecture de l’IA : regarde les opinions des gens.</em></span></label>
          {#if dmapSensitive}
            <label class="check ack" class:missing={!dmap.acknowledged}><input type="checkbox" bind:checked={dmap.acknowledged} aria-label="Les personnes sont informées" /> <span>Je confirme que les personnes de ce serveur <strong>sont informées</strong> et que le cadre juridique est validé (le cadre de traitement des données). Cette fiche est visible de tous ceux qui sont dans le salon vocal.</span></label>
          {/if}
          <span class="muted small">Seules les personnes dont le nom est affiché sur la carte ont une fiche. Jamais un message, jamais un salon.</span>
        </fieldset>
        <fieldset class="what" disabled={!dmap.enabled}>
          <legend class="muted small">Filtres proposés dans l’Activité</legend>
          {#each Object.entries(DMAP_FILTERS) as [filter, label]}
            <label class="check"><input type="checkbox" value={filter} bind:group={dmap.filters} /> <span>{label}</span></label>
          {/each}
          <label class="check"><input type="checkbox" value="theme" bind:group={dmap.filters} /> <span><strong>Thème</strong> des conversations. <em>Lecture de l’IA : montre qui parle de quoi.</em></span></label>
          <label class="check"><input type="checkbox" value="ideology" bind:group={dmap.filters} /> <span><strong>Rôle d’idées</strong>. <em>Montre qui s’est donné ce rôle.</em></span></label>
          <span class="muted small">Jamais de filtre par salon : l’Activité ne montre aucun salon, et un salon que la personne ne peut pas lire ne doit pas se deviner par ses échanges.</span>
        </fieldset>
        <div class="knobs">
          <label class="knob"><span class="knobHead"><span>Personnes sur l’image</span><output>{dmap.max_people}</output></span>
            <input type="range" min="5" max="350" step="1" bind:value={dmap.max_people} oninput={limitDmapNames} aria-label="Personnes sur l’image" />
            <span class="muted small">Les plus connectées. Quand quelqu’un est demandé : cette personne et ses liens les plus forts.</span>
          </label>
          <label class="knob"><span class="knobHead"><span>Noms affichés</span><output>{dmap.names}</output></span>
            <input type="range" min="0" max={dmap.max_people} step="1" bind:value={dmap.names} aria-label="Noms affichés" />
            <span class="muted small">Les plus connectées portent leur nom ; 0 : aucun nom (la personne demandée garde le sien).</span>
          </label>
        </div>
        <div class="actions">
          <button type="button" class="btn btn-primary" onclick={saveDmap} disabled={!dmapChanged || (dmapSensitive && !dmap.acknowledged)}>Enregistrer</button>
          {#if dmapChanged}<button type="button" class="btn" onclick={() => { dmap = { ...dmapSaved, kinds: [...dmapSaved.kinds], sections: [...dmapSaved.sections] }; dmapNote = ''; }}>Annuler</button>{/if}
          {#if dmapNote}<span class="muted small" role="status">{dmapNote}</span>{/if}
        </div>
      {:else}
        <p class="muted">Chargement…</p>
      {/if}
    </section>

    <section class="panel card wide" aria-label="Fiche sur Discord">
      <header><h2 class="eyebrow">Fiche sur Discord</h2></header>
      <p class="muted small">La commande <code>/dindon card</code> poste la fiche d’une personne, <strong>visible par tout le salon</strong>. Vous choisissez ici les pages et ce que chacune montre : seul l’administrateur change ces réglages, personne ne reçoit de message à ce sujet.</p>
      {#if dcard}
        {#each Object.entries(DCARD_PAGES) as [page, title]}
          <fieldset class="what">
            <legend class="muted small"><label class="check"><input type="checkbox" value={page} bind:group={dcard.pages} /> <span><strong>Page {title}</strong></span></label></legend>
            {#each dcard.available[page] as block}
              <label class="check"><input type="checkbox" value={block} bind:group={dcard.blocks[page]} disabled={!dcard.pages.includes(page)} /> <span>{DCARD_BLOCKS[block]}</span></label>
            {/each}
          </fieldset>
        {/each}
        <div class="actions">
          <button type="button" class="btn btn-primary" onclick={saveDcard} disabled={!dcardChanged || dcard.pages.length === 0}>Enregistrer</button>
          {#if dcardChanged}<button type="button" class="btn" onclick={() => { dcard = cloneCard(dcardSaved); dcardNote = ''; }}>Annuler</button>{/if}
          {#if dcard.pages.length === 0}<span class="muted small" role="status">Gardez au moins une page.</span>{:else if dcardNote}<span class="muted small" role="status">{dcardNote}</span>{/if}
        </div>
      {:else}
        <p class="muted">Chargement…</p>
      {/if}
    </section>

    {/if}
    {#if section === 'performance'}
    <section class="panel card wide" aria-label="Performance">
      <header><h2 class="eyebrow">Performance</h2>{#if perf}<span class="badge" class:accent={perf.settings.preset !== 'full'}>{PRESET_NAMES[perf.settings.preset]}</span>{/if}</header>
      <p class="muted small">Limitez ce que le bot et l’IA prennent de la machine, <strong>au prix de leur vitesse</strong>. Rien n’est perdu : l’IA est plus lente, les messages du bot apparaissent un peu plus tard sur la carte.</p>
      {#if form}
        <div class="presets" role="radiogroup" aria-label="Profil de performance">
          {#each Object.keys(PRESET_NAMES) as name}
            <button type="button" class="preset" class:on={form.preset === name} role="radio" aria-checked={form.preset === name} onclick={() => pickPreset(name)}>
              <strong>{PRESET_NAMES[name]}</strong><span class="muted small">{PRESET_HELP[name]}</span>
            </button>
          {/each}
        </div>

        <details bind:open={performanceOpen}><summary>Réglages personnalisés</summary>        <div class="knobs">
          <label class="knob">
            <span class="knobHead"><span>IA : part du temps où elle travaille</span><output>{form.ai_max_load} %</output></span>
            <input type="range" min="10" max="100" step="5" bind:value={form.ai_max_load} oninput={edited} aria-label="Part du temps où l’IA travaille" />
            <span class="muted small">{form.ai_max_load >= 100 ? 'Sans pause entre deux appels.' : `Elle fait une pause après chaque appel : environ ${slower} fois plus lente, et la machine souffle le reste du temps.`}</span>
          </label>
          <label class="knob">
            <span class="knobHead"><span>IA : fils de calcul</span><output>{Number(form.ai_threads) === 0 ? 'automatique' : form.ai_threads}</output></span>
            <input type="range" min="0" max={perf.cpu_count ?? 8} step="1" bind:value={form.ai_threads} oninput={edited} aria-label="Fils de calcul de l’IA" />
            <span class="muted small">Moins de fils : moins de processeur pris, plus lent (0 : Ollama choisit ; sur un Mac, le GPU fait l’essentiel).</span>
          </label>
          <label class="knob">
            <span class="knobHead"><span>IA : modèles gardés en mémoire</span></span>
            <select class="select" bind:value={form.ai_keep_alive} onchange={edited} aria-label="Durée de garde des modèles en mémoire">
              {#each perf.keep_alive as v}<option value={v}>{v === '0' ? 'libérés tout de suite' : v === '30s' ? '30 secondes' : v.replace('m', ' minutes')}</option>{/each}
            </select>
            <span class="muted small">Plus court : de la mémoire rendue plus vite, mais le modèle se recharge à chaque reprise.</span>
          </label>
          <label class="knob">
            <span class="knobHead"><span>IA : conversations traitées à la fois (vecteurs)</span><output>{form.ai_batch}</output></span>
            <input type="range" min="1" max="32" step="1" bind:value={form.ai_batch} oninput={edited} aria-label="Taille des lots de vecteurs" />
            <span class="muted small">Des lots plus petits demandent moins de mémoire.</span>
          </label>
          <label class="knob">
            <span class="knobHead"><span>Bot : regroupement des écritures</span><output>{Number(form.bot_batch_seconds).toLocaleString('fr-FR')} s</output></span>
            <input type="range" min="0.1" max="10" step="0.1" bind:value={form.bot_batch_seconds} oninput={edited} aria-label="Regroupement des écritures du bot" />
            <span class="muted small">Les messages d’un salon attendent ce temps puis sont écrits ensemble : moins de travail pour la base, un message qui apparaît jusqu’à {Number(form.bot_batch_seconds).toLocaleString('fr-FR')} s plus tard.</span>
          </label>
        </div>

        </details>
        <div class="actions">
          <button type="button" class="btn btn-primary" onclick={savePerf} disabled={!changed}>Enregistrer</button>
          {#if changed}<button type="button" class="btn" onclick={() => { form = { ...perf.settings }; saved = ''; }}>Annuler</button>{/if}
          {#if saved}<span class="muted small" role="status">{saved}</span>{/if}
        </div>
        <div class="workerPanel">
          <h3>Ordinateurs d’analyse</h3>
          <p class="muted small">Le serveur garde les données et répartit les calculs de vecteurs avec les ordinateurs reliés par Tailscale. Installez les mêmes modèles Ollama sur chacun.</p>
          {#if workers?.workers?.length}
            <ul class="workerList">
              {#each workers.workers as worker}
                <li><span class="badge" class:success={worker.online} class:danger={!worker.online}>{worker.online ? 'Connecté' : 'Hors ligne'}</span>
                  <code>{worker.local ? 'Serveur' : worker.url}</code>
                  {#if worker.online}<span class="muted small">{worker.usable?.length ? `Utilisé pour : ${worker.usable.join(', ')}` : 'Aucun modèle compatible avec le serveur'}</span>{/if}
                  {#if !worker.local}<button type="button" class="btn" onclick={() => saveWorkers(workers.configured.filter((url) => url !== worker.url))}>Retirer</button>{/if}
                  {#if shareForm && workers.workers.length > 1}
                    <label class="shareRow">
                      <span class="muted small">Part initiale du travail</span>
                      <input type="range" min="0" max="100" step="1" value={shareForm[shareKey(worker)] ?? 0} oninput={(e) => setShare(shareKey(worker), e.currentTarget.value)} aria-label={`Part du travail de ${worker.local ? 'le serveur' : worker.url}, en pourcentage`} />
                      <input class="field-input shareNumber" type="number" min="0" max="100" value={shareForm[shareKey(worker)] ?? 0} oninput={(e) => setShare(shareKey(worker), e.currentTarget.value)} aria-label="Pourcentage" /> %
                    </label>
                  {/if}
                </li>
              {/each}
            </ul>
            {#if shareForm && workers.workers.length > 1}
              <div class="actions">
                <button type="button" class="btn" onclick={equalShares}>Répartir également</button>
                <button type="button" class="btn" disabled={!sharesChanged} onclick={saveShares}>Enregistrer la répartition</button>
              </div>
              <p class="muted small">Les parts s’ajustent après chaque étape selon les performances. Un ordinateur à 0 % reste en réserve.</p>
            {/if}
          {:else}<p class="muted small">Le serveur travaille seul pour le moment.</p>{/if}
          <div class="actions">
            <input class="field-input" type="url" placeholder="http://100.x.y.z:11434" aria-label="Adresse Tailscale de l’ordinateur" bind:value={workerUrl} />
            <button type="button" class="btn" disabled={!workerUrl.trim()} onclick={() => saveWorkers([...(workers?.configured ?? []), workerUrl.trim()])}>Ajouter un ordinateur</button>
            <button type="button" class="btn" onclick={loadWorkers}>Actualiser l’état</button>
          </div>
          {#if workerNote}<span class="muted small" role="status">{workerNote}</span>{/if}
        </div>
      {:else}
        <p class="muted">Chargement…</p>
      {/if}
    </section>

    {/if}
    {#if section === 'maintenance'}
    <section class="panel card wide" aria-label="Résultats de l’analyse">
      <header><h2 class="eyebrow">Résultats de l’analyse</h2></header>
      <p class="muted small">Supprime ce que l’analyse a déduit du serveur affiché sur la carte. Les messages et les liens de la carte ne sont jamais touchés ; l’analyse peut les refaire.</p>
      <div class="actions">
        {#each Object.entries(RESULTS) as [what, [label]] (what)}
          <button type="button" class="btn btn-danger" disabled={!guild || resetting !== ''} onclick={() => resetResults(what)}>Supprimer les {label.toLowerCase()}</button>
        {/each}
      </div>
      {#if resetNote}<p class="muted small" role="status">{resetNote}</p>{/if}
    </section>

    <section class="panel card wide" aria-label="Serveurs suivis">
      <header><h2 class="eyebrow">Serveurs suivis</h2><span class="muted small">liste <code>DINDON_GUILD_IDS</code> du fichier <code>.env</code></span></header>
      {#if info.followed.length > 4}
        <div class="toolbar" role="search" aria-label="Chercher un serveur">
          <input class="field-input" type="search" placeholder="Chercher un serveur… (/)" bind:value={q} aria-label="Chercher un serveur suivi" use:slash />
          <span class="found" aria-live="polite">{servers.length} sur {info.followed.length}</span>
        </div>
      {/if}
      {#if info.followed.length}
        <ul class="servers">
          {#each servers as server (server.id)}
            <li>
              <span class="name">{server.name ?? 'Serveur sans message enregistré'}</span>
              <code>{server.id}</code>
              <span class="badge small" class:success={server.seen_by_bot}>{server.seen_by_bot ? 'vu par le bot' : 'pas vu par le bot'}</span>
              <span class="badge small" class:success={server.in_database}>{server.in_database ? `${fmt.format(server.messages)} messages` : 'rien en base'}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="muted">Aucun serveur n’est suivi par le bot. Voir « Inviter le bot ».</p>
      {/if}
    </section>

    {/if}
    <p class="muted small footnote">Dindon {info.version} · fichiers illisibles dans <code>inbox/failed</code> : {info.inbox.failed}</p>
  {/if}
</div>

<style>
  .systemTabs { display: flex; flex-wrap: wrap; gap: .375rem; position: sticky; top: 0; z-index: 3; background: var(--bg-primary); padding-block: .5rem; }
  .systemTabs .active { border-color: var(--accent); background: var(--bg-active); }
  .ack.missing { border-color: var(--danger); }
  .page {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 1.5rem clamp(1rem, 3vw, 2.5rem) 2.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    animation: fadeIn var(--transition-slow) both;
  }

  .page > header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
  }

  h1 {
    font-size: clamp(1.5rem, 2vw, 1.9rem);
    line-height: 1.1;
    font-weight: 700;
    color: var(--text-primary);
  }


  .checks {
    padding: 1rem 1.25rem;
  }

  .checks h2 {
    margin-bottom: 0.625rem;
  }

  .checks ul {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .checks li {
    display: flex;
    align-items: flex-start;
    gap: 0.625rem;
    font-size: 0.875rem;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  .checks .dot {
    flex-shrink: 0;
    width: 0.5rem;
    height: 0.5rem;
    margin-top: 0.4375rem;
    border-radius: 50%;
    background: var(--text-muted);
  }

  .checks li.error .dot {
    background: var(--danger);
  }

  .checks li.warning .dot {
    background: #f0b232;
  }

  .checks li.error {
    color: #ffb3b8;
  }

  .grid {
    align-items: start;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
    gap: 1rem;
  }

  .card {
    padding: 1rem 1.125rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    box-shadow: var(--shadow-sm);
  }

  .card > header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }

  dl {
    display: flex;
    flex-direction: column;
  }

  dl div {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.4375rem 0;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 0.8125rem;
  }

  dl div:last-child {
    border-bottom: none;
  }

  dt {
    min-width: 0;
    flex: 1;
    color: var(--text-muted);
  }

  dd {
    min-width: 0;
    max-width: 65%;
    color: var(--text-primary);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    text-align: right;
  }

  .servers {
    list-style: none;
    display: flex;
    flex-direction: column;
  }

  .servers li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.625rem;
    padding: 0.5rem 0.25rem;
    border-bottom: 1px solid var(--border-subtle);
  }

  .servers li:last-child {
    border-bottom: none;
  }

  .name {
    flex: 1 1 10rem;
    min-width: 0;
    color: var(--text-primary);
    font-weight: 500;
  }

  .small {
    font-size: 0.75rem;
  }

  .switch { display: flex; align-items: center; gap: 0.5rem; font-weight: 600; color: var(--text-primary); }
  .what { display: flex; flex-direction: column; gap: 0.5rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); padding: 0.75rem 1rem; }
  .what:disabled { opacity: 0.55; }
  .check { display: flex; align-items: flex-start; gap: 0.5rem; font-size: 0.8125rem; color: var(--text-secondary); }
  .check input { margin-top: 0.25rem; }
  .check strong { color: var(--text-primary); }
  .ack { padding: 0.5rem 0.625rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); }
  .hours { display: flex; align-items: center; gap: 0.5rem; }
  .status { display: flex; flex-direction: column; }
  .status div { display: flex; gap: 1rem; padding: 0.375rem 0; border-top: 1px solid var(--border-subtle); font-size: 0.8125rem; }
  .status dt { flex: 0 0 7rem; color: var(--text-muted); }
  .status dd { color: var(--text-primary); }
  .presets { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 10rem), 1fr)); gap: 0.5rem; }
  .preset { display: flex; flex-direction: column; gap: 0.25rem; align-items: flex-start; padding: 0.625rem 0.75rem; border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); background: var(--surface-control); color: var(--text-primary); font: inherit; text-align: left; cursor: pointer; }
  .preset.on { border-color: var(--accent, #5865f2); box-shadow: 0 0 0 1px var(--accent, #5865f2) inset; }
  .knobs { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr)); gap: 1rem 1.5rem; }
  .knob { display: flex; flex-direction: column; gap: 0.375rem; }
  .knobHead { display: flex; justify-content: space-between; gap: 0.5rem; font-size: 0.8125rem; color: var(--text-primary); font-weight: 600; }
  .knobHead output { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
  .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; }
  .workerPanel { border-top: 1px solid var(--border-subtle); padding-top: 0.875rem; display: flex; flex-direction: column; gap: 0.5rem; }
  .workerPanel h3 { font-size: 0.95rem; color: var(--text-primary); }
  .workerPanel .field-input { flex: 1 1 16rem; max-width: 25rem; }
  .workerList { list-style: none; display: flex; flex-direction: column; gap: 0.5rem; }
  .workerList li { display: flex; flex-wrap: wrap; align-items: center; gap: 0.625rem; }
  .shareRow { display: flex; align-items: center; gap: 0.5rem; flex: 1 1 100%; }
  .shareRow input[type="range"] { flex: 1 1 8rem; max-width: 18rem; }
  .shareNumber { width: 4.5rem; flex: 0 0 auto; }
  .workerList code { overflow-wrap: anywhere; }

  .badge.small {
    min-height: 1.5rem;
    font-size: 0.6875rem;
  }

  .footnote {
    text-align: center;
  }

  @media (max-width: 720px) {
    .page {
      padding: 1rem 1rem 2rem;
    }
  }
</style>
