<script>
  import { onMount } from 'svelte';
  import { api } from './lib/api.js';
  import Login from './components/Login.svelte';
  import Dashboard from './components/Dashboard.svelte';

  let state = $state('checking'); // checking | out | in

  onMount(async () => {
    try {
      state = (await api.session()).authenticated ? 'in' : 'out';
    } catch {
      state = 'out';
    }
  });
</script>

{#if state === 'in'}
  <Dashboard onLogout={() => (state = 'out')} />
{:else if state === 'out'}
  <Login onLogin={() => (state = 'in')} />
{/if}
