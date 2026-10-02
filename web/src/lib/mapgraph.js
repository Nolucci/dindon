// The map: one point per person, one line per pair of people who talk. Sigma draws it with WebGL, ForceAtlas2 places
// the points in a worker thread (so that the page stays smooth), and a new exchange makes its line light up.
import Graph from 'graphology';
import Sigma from 'sigma';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import FA2Layout from 'graphology-layout-forceatlas2/worker';

// How much each kind of exchange says about a tie (the same numbers as the API, which sends them in `meta.kind_factor`)
const DEFAULT_FACTOR = { reply: 1, mention: 0.6, reaction: 0.25 };
const FLASH_MS = 3200;
const FLASH_COLOR = [255, 226, 138];
const BACKGROUND = [11, 15, 20];
const DIM = 'rgb(38, 47, 59)';      // people who are not linked to the one in focus
const EDGE = [138, 154, 176];       // the faint web that is always there
const EDGE_FOCUS = [118, 178, 235]; // the lines of the person under the mouse or selected
const MS_PER_DAY = 86400000;
const NAMED_NEIGHBORS = 14;         // when someone is in focus, their strongest links show a name

// Names are drawn with a dark halo so that they stay readable on top of the lines
function drawLabel(context, data, settings) {
  if (!data.label) return;
  const size = settings.labelSize;
  context.font = `${settings.labelWeight} ${size}px ${settings.labelFont}`;
  const x = data.x + data.size + 4;
  const y = data.y + size / 3;
  context.lineJoin = 'round';
  context.lineWidth = 4;
  context.strokeStyle = 'rgba(11, 15, 20, 0.95)';
  context.strokeText(data.label, x, y);
  context.fillStyle = '#e6edf5';
  context.fillText(data.label, x, y);
}

// The person under the mouse or selected: a dark pill with a light name (Sigma's own is white with grey text)
function drawHover(context, data, settings) {
  const size = settings.labelSize + 1;
  context.font = `600 ${size}px ${settings.labelFont}`;
  context.beginPath();
  context.arc(data.x, data.y, data.size + 3, 0, Math.PI * 2);
  context.fillStyle = 'rgba(11, 15, 20, 0.9)';
  context.fill();
  context.beginPath();
  context.arc(data.x, data.y, data.size, 0, Math.PI * 2);
  context.fillStyle = data.color;
  context.fill();
  if (!data.label) return;
  const width = context.measureText(data.label).width;
  const x = data.x + data.size + 7;
  const height = size + 10;
  context.fillStyle = 'rgba(18, 24, 33, 0.97)';
  context.strokeStyle = 'rgba(118, 178, 235, 0.9)';
  context.lineWidth = 1;
  context.beginPath();
  context.roundRect(x, data.y - height / 2, width + 14, height, 6);
  context.fill();
  context.stroke();
  context.fillStyle = '#ffffff';
  context.fillText(data.label, x + 7, data.y + size / 3);
}

const bigger = (a, b) => (BigInt(a) > BigInt(b) ? 1 : -1); // ids are 18-digit numbers, kept as text
export const edgeKey = (a, b) => (bigger(a, b) > 0 ? `${b}|${a}` : `${a}|${b}`);

function hslToRgb(h, s, l) {
  s /= 100;
  l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(255 * f(0)), Math.round(255 * f(8)), Math.round(255 * f(4))];
}
const css = ([r, g, b], a = 1) => `rgba(${r}, ${g}, ${b}, ${a})`;
const mix = (from, to, t) => from.map((v, i) => Math.round(v + (to[i] - v) * t));
// Sigma writes colors without multiplying them by their transparency, so that a line at 7% opacity is drawn as a nearly
// solid one. Transparency is therefore never asked of it: the color of a line is mixed with the background here instead.
const faded = (rgb, opacity) => css(mix(BACKGROUND, rgb, Math.min(1, Math.max(0, opacity))));

export class MapGraph {
  constructor(container, { onSelect, onHover }) {
    this.container = container;
    this.flashCount = 0;
    this.graph = new Graph({ type: 'undirected', multi: false });
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.factor = DEFAULT_FACTOR;
    this.selected = null;
    this.hovered = null;
    this.flashes = new Map(); // key of an edge -> when its light went on
    this.nodeFlashes = new Map();
    this.maxInfluence = 1;
    this.maxWeight = 1;
    this.edgeCount = 0;
    this.layout = null;
    this.layoutTimer = null;
    this.frame = null;
    this.inFocus = null;      // the person whose links are shown: selected, otherwise under the mouse
    this.neighbors = new Map(); // their links: other person -> weight
    this.focusMax = 1;
    this.named = new Set();     // the ones of them whose name is always shown

    this.renderer = new Sigma(this.graph, container, {
      renderEdgeLabels: false,
      labelColor: { color: '#d8e0ea' },
      labelFont: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
      labelSize: 12,
      labelWeight: '500',
      labelRenderedSizeThreshold: 0,   // any size: a crowded area still only shows what fits (see labelGridCellSize)
      labelDensity: 1.3,
      labelGridCellSize: 64,
      defaultDrawNodeLabel: drawLabel,
      defaultDrawNodeHover: drawHover,
      defaultNodeColor: '#6aa3d8',
      zIndex: true,
      minCameraRatio: 0.03,
      maxCameraRatio: 14,
      nodeReducer: (node, data) => this.reduceNode(node, data),
      edgeReducer: (edge, data) => this.reduceEdge(edge, data),
    });
    this.renderer.on('clickNode', ({ node }) => this.select(node, true));
    this.renderer.on('clickStage', () => this.select(null, true));
    this.renderer.on('enterNode', ({ node }) => {
      this.hovered = node;
      container.style.cursor = 'pointer';
      this.onHover?.(node);
      this.renderer.refresh({ skipIndexation: true });
    });
    this.renderer.on('leaveNode', () => {
      this.hovered = null;
      container.style.cursor = 'default';
      this.onHover?.(null);
      this.renderer.refresh({ skipIndexation: true });
    });
  }

  // --- what each point and line looks like ---------------------------------------------------------

  nodeLook(node, now) {
    const size = 3.5 + 13 * Math.sqrt(node.influence / this.maxInfluence);
    // The color says how recently the person wrote: bright when recent, dim when long ago
    const last = node.last_message_at ? Date.parse(node.last_message_at) : null;
    const recency = last ? Math.exp(-(now - last) / (30 * MS_PER_DAY)) : 0;
    const rgb = last ? hslToRgb(208, 62, 34 + 36 * recency) : [90, 100, 114];
    return { size, rgb, color: css(rgb) };
  }

  // Lines are only a faint web: they show the shape of the groups without hiding the names
  edgeLook(weight) {
    const crowd = Math.min(1, 900 / Math.max(this.edgeCount, 1));
    const strength = Math.pow(weight / this.maxWeight, 0.5);
    return { size: 0.5 + 1.5 * strength, color: faded(EDGE, (0.13 + 0.20 * strength) * (0.6 + 0.4 * crowd)) };
  }

  // Who is in focus, and with whom they talk (computed once when the focus changes, not for every point drawn)
  updateFocus() {
    const wanted = this.selected ?? this.hovered;
    const focus = wanted && this.graph.hasNode(wanted) ? wanted : null;
    if (focus === this.inFocus && !this.focusStale) return;
    this.inFocus = focus;
    this.focusStale = false;
    this.neighbors = new Map();
    this.named = new Set();
    this.focusMax = 1e-9;
    if (!focus) return;
    this.graph.forEachEdge(focus, (edge, attributes, source, target) => {
      this.neighbors.set(source === focus ? target : source, attributes.weight);
      this.focusMax = Math.max(this.focusMax, attributes.weight);
    });
    this.named = new Set([...this.neighbors].sort((a, b) => b[1] - a[1]).slice(0, NAMED_NEIGHBORS).map(([id]) => id));
  }

  reduceNode(node, data) {
    this.updateFocus();
    const result = { ...data };
    if (this.inFocus) {
      if (node === this.inFocus) {
        result.highlighted = true;
        result.forceLabel = true;
        result.zIndex = 3;
      } else if (this.neighbors.has(node)) {
        result.zIndex = 2;
        result.forceLabel = this.named.has(node);
      } else {
        result.color = DIM;
        result.label = '';
        result.zIndex = 0;
      }
    }
    const light = this.light(this.nodeFlashes.get(node));
    if (light > 0) {
      result.color = css(mix(data.rgb, FLASH_COLOR, light));
      result.size = data.size * (1 + 0.9 * light);
      result.zIndex = 4;
    }
    return result;
  }

  reduceEdge(edge, data) {
    this.updateFocus();
    const result = { ...data };
    if (this.inFocus) {
      if (this.graph.hasExtremity(edge, this.inFocus)) {
        // The links of the person in focus: clear, and as thick as they are strong (among theirs)
        const strength = Math.pow(data.weight / this.focusMax, 0.6);
        result.color = faded(EDGE_FOCUS, 0.40 + 0.60 * strength);
        result.size = 0.8 + 3.6 * strength;
        result.zIndex = 2;
      } else {
        result.color = faded(EDGE, 0.07);
        result.zIndex = 0;
      }
    }
    const light = this.light(this.flashes.get(edge));
    if (light > 0) {
      result.color = faded(FLASH_COLOR, 0.55 + 0.45 * light);
      result.size = Math.max(result.size, data.size) + 3.5 * light;
      result.zIndex = 4;
    }
    return result;
  }

  light(since) {
    if (since === undefined) return 0;
    const t = (performance.now() - since) / FLASH_MS;
    return t >= 1 ? 0 : (1 - t) * (1 - t);
  }

  // --- loading what the API sends ----------------------------------------------------------------

  load(data) {
    if (data.meta?.kind_factor) this.factor = data.meta.kind_factor;
    const now = Date.now();
    const graph = this.graph;
    const incoming = new Set(data.nodes.map((n) => n.id));
    graph.forEachNode((id) => {
      if (!incoming.has(id)) graph.dropNode(id);
    });
    graph.clearEdges();
    this.maxInfluence = Math.max(1e-9, ...data.nodes.map((n) => n.influence));
    this.maxWeight = Math.max(1e-9, ...data.edges.map((e) => e.weight));
    this.edgeCount = data.edges.length;
    const known = graph.order;
    const spread = 60 + 9 * Math.sqrt(data.nodes.length);
    for (const node of data.nodes) {
      const look = this.nodeLook(node, now);
      const attributes = { label: node.label, size: look.size, color: look.color, rgb: look.rgb, influence: node.influence,
                           messages: node.messages, last_message_at: node.last_message_at };
      if (graph.hasNode(node.id)) {
        graph.mergeNodeAttributes(node.id, attributes);
      } else {
        graph.addNode(node.id, { ...attributes, x: (Math.random() - 0.5) * spread, y: (Math.random() - 0.5) * spread });
      }
    }
    for (const edge of data.edges) {
      if (edge.source === edge.target || !graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
      const look = this.edgeLook(edge.weight);
      graph.addUndirectedEdgeWithKey(edgeKey(edge.source, edge.target), edge.source, edge.target,
        { ...look, weight: edge.weight, n: edge.n, kinds: edge.kinds, last_at: edge.last_at, layoutWeight: 1 + Math.log1p(edge.weight) });
    }
    if (this.selected && !graph.hasNode(this.selected)) this.selected = null;
    this.focusStale = true;
    // Few people: every name. Many people: only the names that fit (zooming in shows more)
    const crowd = Math.min(1, 90 / Math.max(data.nodes.length, 1));
    this.renderer.setSetting('labelDensity', 0.45 + 0.9 * crowd);
    this.renderer.setSetting('labelGridCellSize', 64 + 56 * (1 - crowd));
    this.renderer.refresh();
    this.settle(known === 0 ? 6000 : 2500);
  }

  // Places the points: a few seconds of ForceAtlas2 in a worker, then it stops (the points keep their places)
  settle(milliseconds) {
    this.layout?.kill();
    clearTimeout(this.layoutTimer);
    if (this.graph.order < 2) return;
    const inferred = forceAtlas2.inferSettings(this.graph);
    const settings = {
      ...inferred,
      scalingRatio: Math.max(inferred.scalingRatio ?? 10, 8) * 1.8, // more repulsion: names need room
      slowDown: 3,
      gravity: 0.35,
      edgeWeightInfluence: 0.7,
      adjustSizes: true,                                            // points do not overlap
      getEdgeWeight: 'layoutWeight',
      barnesHutOptimize: this.graph.order > 400,
    };
    this.layout = new FA2Layout(this.graph, { settings });
    this.layout.start();
    this.layoutTimer = setTimeout(() => this.layout?.stop(), milliseconds);
  }

  // --- live ----------------------------------------------------------------------------------------

  /** A new exchange: light the line up. Returns false if someone is not on the map yet (the page then reloads it). */
  flash(event) {
    const { from, to, kind } = event;
    if (!this.graph.hasNode(from) || !this.graph.hasNode(to)) return false;
    const key = edgeKey(from, to);
    const added = this.factor[kind] ?? 0.25;
    if (this.graph.hasEdge(key)) {
      const weight = this.graph.getEdgeAttribute(key, 'weight') + added;
      this.maxWeight = Math.max(this.maxWeight, weight);
      this.graph.mergeEdgeAttributes(key, { weight, ...this.edgeLook(weight) });
    } else {
      this.graph.addUndirectedEdgeWithKey(key, from, to, { ...this.edgeLook(added), weight: added, n: 1, kinds: { [kind]: added }, layoutWeight: 1 });
    }
    this.focusStale = true;
    const now = performance.now();
    this.flashes.set(key, now);
    this.nodeFlashes.set(from, now);
    this.nodeFlashes.set(to, now);
    this.container.dataset.flashes = String(++this.flashCount); // a counter, so that the page can be tested from outside
    this.animate();
    return true;
  }

  animate() {
    if (this.frame) return;
    const tick = () => {
      const now = performance.now();
      for (const map of [this.flashes, this.nodeFlashes]) {
        for (const [key, since] of map) if (now - since >= FLASH_MS) map.delete(key);
      }
      this.renderer.refresh({ skipIndexation: true });
      this.frame = this.flashes.size || this.nodeFlashes.size ? requestAnimationFrame(tick) : null;
    };
    this.frame = requestAnimationFrame(tick);
  }

  // --- selecting -----------------------------------------------------------------------------------

  select(id, fromClick = false) {
    this.selected = id;
    this.renderer.refresh({ skipIndexation: true });
    if (fromClick) this.onSelect?.(id);
  }

  focus(id) {
    if (!this.graph.hasNode(id)) return false;
    const { x, y } = this.renderer.getNodeDisplayData(id);
    this.renderer.getCamera().animate({ x, y, ratio: 0.25 }, { duration: 600 });
    return true;
  }

  has(id) {
    return this.graph.hasNode(id);
  }

  labelOf(id) {
    return this.graph.hasNode(id) ? this.graph.getNodeAttribute(id, 'label') : id;
  }

  // The page changed the size of the map (the person's card opens or closes)
  resized() {
    this.renderer.resize();
    this.renderer.refresh();
  }

  resetView() {
    this.renderer.getCamera().animatedReset({ duration: 500 });
  }

  destroy() {
    clearTimeout(this.layoutTimer);
    if (this.frame) cancelAnimationFrame(this.frame);
    this.layout?.kill();
    this.renderer.kill();
  }
}
