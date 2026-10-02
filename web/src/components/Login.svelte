<script>
  import { api } from '../lib/api.js';

  let { onLogin } = $props();
  let password = $state('');
  let error = $state('');
  let busy = $state(false);

  async function submit(event) {
    event.preventDefault();
    busy = true;
    error = '';
    try {
      await api.login(password);
      onLogin();
    } catch (e) {
      error = e.status === 429 ? 'Trop d’essais : attendez un instant.' : e.status === 401 ? 'Mot de passe incorrect.' : 'Connexion impossible.';
      password = '';
    } finally {
      busy = false;
    }
  }
</script>

<main>
  <form onsubmit={submit}>
    <h1>Dindon</h1>
    <p class="muted">La carte vivante de votre serveur, en local.</p>
    <label for="password">Mot de passe</label>
    <!-- svelte-ignore a11y_autofocus -->
    <input id="password" type="password" autocomplete="current-password" bind:value={password} autofocus required />
    <button type="submit" disabled={busy || !password}>Entrer</button>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </form>
</main>

<style>
  main { height: 100%; display: grid; place-items: center; }
  form { width: min(340px, calc(100vw - 32px)); display: grid; gap: 10px; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 26px; }
  h1 { margin: 0; font-size: 26px; letter-spacing: 0.5px; }
  p { margin: 0 0 8px; }
  label { font-size: 13px; color: var(--muted); }
  .error { color: var(--warn); margin: 0; }
</style>
