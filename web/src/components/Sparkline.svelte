<script>
  // Messages per month, as small bars. No library: a few rectangles.
  let { points } = $props(); // [{ month: '2026-03', messages: 12 }, ...]
  const width = 260;
  const height = 44;
  let max = $derived(Math.max(1, ...points.map((p) => p.messages)));
  let bar = $derived(Math.min(16, Math.max(2, (width - (points.length - 1) * 2) / Math.max(points.length, 1))));
</script>

<svg viewBox="0 0 {width} {height}" role="img" aria-label="Messages par mois" class="spark">
  {#each points as p, i}
    {@const h = Math.max(2, (p.messages / max) * (height - 4))}
    <rect x={i * (bar + 2)} y={height - h} width={bar} height={h} rx="1.5"><title>{p.month} : {p.messages} messages</title></rect>
  {/each}
</svg>

<style>
  .spark { width: 100%; height: 2.75rem; display: block; }
  rect { fill: var(--accent); opacity: 0.8; transition: opacity var(--transition-fast); }
  rect:hover { opacity: 1; }
</style>
