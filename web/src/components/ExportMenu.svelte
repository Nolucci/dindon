<script>
  import { api } from '../lib/api.js';
  let { guild, part } = $props();
</script>
<details class="exportMenu">
  <summary class="btn">Exporter</summary>
  <div class="formats"><a class="btn" href={api.digestUrl(guild, 'md', part)} download>Markdown (.md)</a><a class="btn" href={api.digestUrl(guild, 'json', part)} download>JSON</a></div>
</details>
<style>
  .exportMenu { position: relative; }
  summary { list-style: none; }
  summary::-webkit-details-marker { display: none; }
  .formats { position: absolute; right: 0; top: calc(100% + .25rem); z-index: 4; display: flex; flex-direction: column; gap: .25rem; min-width: 11rem; padding: .5rem; border: 1px solid var(--border-strong); border-radius: .5rem; background: var(--bg-tertiary); box-shadow: var(--shadow-md); }
  @media (max-width: 720px) {
    .exportMenu[open] { flex-basis: 100%; }
    summary { width: fit-content; }
    .formats { position: static; width: min(11rem, 100%); min-width: 0; margin-top: .25rem; }
  }
</style>
