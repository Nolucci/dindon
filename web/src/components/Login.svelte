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

<!-- The login page of Poulet (app/login/LoginPage.module.css), with a password instead of Discord's OAuth -->
<main>
  <form class="panel card" onsubmit={submit}>
    <span class="eyebrow-brand">Dindon</span>
    <h1>Connexion</h1>
    <p class="text">La carte vivante de votre serveur, en local. Entrez le mot de passe pour l’ouvrir.</p>
    <div class="field">
      <label for="password">Mot de passe</label>
      <!-- svelte-ignore a11y_autofocus -->
      <input id="password" class="field-input" type="password" autocomplete="current-password" bind:value={password} autofocus required />
    </div>
    {#if error}<p class="banner" role="alert">{error}</p>{/if}
    <button class="button" type="submit" disabled={busy || !password}>Entrer</button>
    <div class="meta">
      <span>Accès protégé par mot de passe</span>
      <span class="badge accent">Local</span>
    </div>
  </form>
</main>

<style>
  main {
    min-height: 100%;
    display: grid;
    place-items: center;
    padding: 2rem;
    background: radial-gradient(circle at top, rgba(88, 101, 242, 0.26), transparent 30%),
      radial-gradient(circle at bottom right, rgba(35, 165, 90, 0.18), transparent 26%),
      linear-gradient(180deg, #1a1b1f 0%, #111216 100%);
    overflow-y: auto;
  }

  .card {
    width: min(100%, 28.75rem);
    padding: var(--space-5);
    border-radius: 1.5rem;
    box-shadow: 0 1.875rem 5rem rgba(0, 0, 0, 0.45);
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .eyebrow-brand {
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: none;
    color: #99a0ff;
  }

  h1 {
    font-size: clamp(1.75rem, 5vw, 2.5rem);
    line-height: 1.05;
    font-weight: 700;
    color: #f2f3f5;
  }

  .text {
    color: var(--text-secondary);
    line-height: 1.65;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  label {
    color: var(--text-primary);
    font-weight: 600;
    font-size: 0.8125rem;
  }

  .field-input {
    min-height: 2.75rem;
    border-radius: var(--radius-md);
    background: var(--bg-tertiary);
    font-size: 0.9375rem;
    padding: 0 var(--space-3);
  }

  .button {
    min-height: 3.25rem;
    border-radius: 0.875rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.625rem;
    background: linear-gradient(135deg, #5865f2, #7289da);
    color: white;
    font-weight: 700;
    transition: transform var(--transition-fast), box-shadow var(--transition-fast);
    box-shadow: 0 0.875rem 2.25rem rgba(88, 101, 242, 0.28);
  }

  .button:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 1.125rem 2.5rem rgba(88, 101, 242, 0.34);
  }

  .button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    color: var(--text-muted);
    font-size: 0.8125rem;
  }
</style>
