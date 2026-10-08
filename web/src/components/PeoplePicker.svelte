<script>
  import { onDestroy } from 'svelte';
  import { api, AuthError } from '../lib/api.js';
  let { guild, label, value = $bindable(''), onAuthLost } = $props();
  let query = $state('');
  let found = $state([]);
  let names = $state({});
  let problem = $state('');
  let timer;
  let request = 0;
  const ids = $derived(value.split(/[\s,;]+/).filter(Boolean));
  function add(person) {
    if (!ids.includes(person.id)) value = [...ids, person.id].join(' ');
    names = { ...names, [person.id]: person.label };
    query = ''; found = []; request++;
  }
  function search() {
    const current = ++request;
    clearTimeout(timer);
    found = []; problem = '';
    if (query.trim().length < 2) return;
    timer = setTimeout(async () => {
      try {
        const answer = await api.people(query.trim(), guild);
        if (current === request) found = answer.filter((p) => !ids.includes(p.id));
      } catch (error) {
        if (error instanceof AuthError) onAuthLost();
        else if (current === request) problem = 'Recherche indisponible. Vous pouvez saisir un identifiant Discord.';
      }
    }, 200);
  }
  $effect(() => { guild; query = ''; found = []; request++; clearTimeout(timer); });
  onDestroy(() => { clearTimeout(timer); request++; });
</script>
<div class="picker">
  <label class="field">{label}<input class="field-input" type="search" placeholder="Nom ou identifiant Discord" aria-label={label} bind:value={query} oninput={search} /></label>
  {#if ids.length}<div class="selected">{#each ids as id}<button type="button" class="btn" aria-label={`Retirer ${names[id] || id}`} onclick={() => value = ids.filter((other) => other !== id).join(' ')}>{names[id] || id} ×</button>{/each}</div>{/if}
  {#if problem}<p class="muted small">{problem}</p>{/if}
  {#if found.length}<ul>{#each found as person (person.id)}<li><button type="button" class="result" onclick={() => add(person)}>{person.label}</button></li>{/each}</ul>{/if}
  {#if /^\d{15,22}$/.test(query.trim()) && !ids.includes(query.trim())}<button type="button" class="btn" onclick={() => add({ id: query.trim(), label: query.trim() })}>Ajouter cet identifiant</button>{/if}
</div>
<style>
  .picker { display: flex; flex-direction: column; gap: .375rem; margin-top: .625rem; }
  .field { display: flex; flex-direction: column; gap: .375rem; }
  .selected { display: flex; flex-wrap: wrap; gap: .25rem; }
  ul { list-style: none; max-height: 10rem; overflow-y: auto; border: 1px solid var(--border-subtle); border-radius: .5rem; }
  .result { width: 100%; text-align: left; padding: .625rem; }
  .result:hover { background: var(--bg-hover); }
  .small { font-size: .75rem; }
</style>
