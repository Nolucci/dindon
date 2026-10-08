<script>
  // One axis: from its negative pole (red) to its positive pole (green), a dot where the person stands, how sure (a bracket under the bar),
  // and, as a band, what each ideology that the person gave themselves expects on this axis. No score: the bar says it.
  let { axis, compact = false } = $props();

  const at = (v) => `${Math.max(0, Math.min(100, ((v + 1) / 2) * 100))}%`;
  const has = $derived(axis.score !== null && axis.score !== undefined);
  const lo = $derived(has ? Math.max(-1, axis.score - (axis.uncertainty ?? 0)) : 0);
  const hi = $derived(has ? Math.min(1, axis.score + (axis.uncertainty ?? 0)) : 0);
</script>

<div class="axis" class:compact>
  <div class="poles"><span>{axis.negative_pole}</span><span>{axis.positive_pole}</span></div>
  <div class="track" class:empty={!has} role="img"
       aria-label={has ? `${axis.name} : entre ${axis.negative_pole} et ${axis.positive_pole}, à ${axis.score.toFixed(2)}` : `${axis.name} : pas assez de propos`}>
    {#if has}<span class="dot" style="left: {at(axis.score)}"></span>{/if}
  </div>
  <!-- How sure: a thin bracket under the bar (the colours of the bar never change; a wide bracket means that little was said) -->
  <div class="sure" aria-hidden="true">
    {#if has}<span class="whisker" style="left: {at(lo)}; width: calc({at(hi)} - {at(lo)})" title="marge d’incertitude : de {lo.toFixed(2)} à {hi.toFixed(2)}"></span>{/if}
  </div>
  <!-- What each role of the person expects: one line per role, under the bar, with its name (never a frame over the bar) -->
  {#each axis.expected ?? [] as e}
    <div class="role" class:bad={e.verdict === 'incompatible'} title="{e.role} attend entre {e.min} et {e.max}">
      <span class="range" style="left: {at(e.min)}; width: calc({at(e.max)} - {at(e.min)})"></span>
      <span class="name">{e.role}{e.verdict === 'incompatible' ? ' · incompatible' : ''}</span>
    </div>
  {/each}
</div>

<style>
  .axis { display: flex; flex-direction: column; gap: 0.1875rem; }
  .poles { display: flex; gap: .75rem; justify-content: space-between; font-size: 0.6875rem; color: var(--text-muted); }
  .poles span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .poles span:last-child { text-align: right; }
  .track { position: relative; height: 0.625rem; border-radius: 999px; background: linear-gradient(90deg, #ed4245 0%, #c9a227 50%, #3ba55d 100%); }
  .track.empty { background: var(--bg-tertiary); }
  .compact .track { height: 0.5rem; }
  .sure { position: relative; height: 0.5rem; }
  .whisker { position: absolute; top: 0.1875rem; height: 2px; background: var(--text-secondary); border-radius: 1px; }
  .whisker::before, .whisker::after { content: ''; position: absolute; top: -0.1875rem; width: 2px; height: 0.5rem; background: var(--text-secondary); border-radius: 1px; }
  .whisker::before { left: 0; }
  .whisker::after { right: 0; }
  .dot { position: absolute; top: 50%; width: 0.875rem; height: 0.875rem; margin: -0.4375rem 0 0 -0.4375rem; border-radius: 50%; background: #fff; border: 2px solid var(--bg-primary, #1e1f22); box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.4); }
  /* what a role expects: a segment under the bar where the role would put someone, then its name */
  .role { position: relative; padding-top: .5rem; min-height: 1.125rem; font-size: 0.625rem; color: var(--text-muted); }
  .role .range { position: absolute; top: 0.125rem; height: 0.25rem; min-width: 0.25rem; border-radius: 999px; background: var(--text-secondary); opacity: 0.7; }
  .role .name { display: block; line-height: 1.3; overflow-wrap: anywhere; }
  .role.bad .range { background: #ed4245; opacity: 0.9; }
  .role.bad .name { color: #ed4245; }
</style>
