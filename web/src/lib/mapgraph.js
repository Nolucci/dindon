// The map: one point per person, one line per pair of people who talk. Sigma draws it with WebGL, ForceAtlas2 places
// the points in a worker thread (so that the page stays smooth), and a new exchange makes its line light up.
import Graph from 'graphology';
import Sigma from 'sigma';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import FA2Layout from 'graphology-layout-forceatlas2/worker';

// How much each kind of exchange says about a tie (the same numbers as the API, which sends them in `meta.kind_factor`)
const DEFAULT_FACTOR = { reply: 1, mention: 0.6, reaction: 0.25 };
const FLASH_MS = 3200;
// The colors of the Poulet dashboard (its tokens, see app.css): the map is drawn on --bg-primary, with the blurple accent
const FLASH_COLOR = [240, 178, 50];   // Discord's yellow: a new exchange
const BACKGROUND = [49, 51, 56];      // --bg-primary
const FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
const DIM = 'rgb(66, 68, 76)';        // people who are not linked to the one in focus
const EDGE = [181, 186, 193];         // --text-secondary: the faint web that is always there
const EDGE_FOCUS = [153, 160, 255];   // the lines of the person under the mouse or selected (the light blurple of Poulet's eyebrows)
const ACCENT = '#5865f2';             // --accent
const NODE_DEFAULT = [219, 222, 225]; // Discord's color for a name without a colored role
const MIN_CONTRAST = 2;               // a color darker than this against the background is lightened (a black role would vanish)
const NAMED_NEIGHBORS = 14;         // when someone is in focus, their strongest links show a name
// The page is drawn at 80% of the browser's size (`html { font-size: 80% }`, see app.css): the sizes of the map follow it
const UI = (parseFloat(getComputedStyle(document.documentElement).fontSize) || 16) / 16;
const LABEL_PILL_EXTRA = 28 * UI;      // how far the pill of a hovered name goes beyond the name

// The person under the mouse, or selected: a glow in their own color and a white ring around the point, and their name in a
// blurple pill (the accent of the dashboard) with white letters, so that it stands out from every other name on the map
function drawHover(context, data, settings) {
  const size = settings.labelSize + 1.5 * UI;
  const [r, g, b] = data.rgb ?? NODE_DEFAULT;
  const photo = data.type === 'image';                  // a photo: only rings around it, a disc would cover the face
  const reach = data.size * 3 + 8 * UI;
  const glow = context.createRadialGradient(data.x, data.y, data.size, data.x, data.y, reach);
  glow.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.5)`);
  glow.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
  context.beginPath();
  context.arc(data.x, data.y, reach, 0, Math.PI * 2);
  context.fillStyle = glow;
  context.fill();
  if (photo) {
    context.beginPath();
    context.arc(data.x, data.y, data.size + 3 * UI, 0, Math.PI * 2);
    context.lineWidth = 2.5 * UI;
    context.strokeStyle = '#f2f3f5';
    context.stroke();
  } else {
    for (const [radius, fill] of [[data.size + 4.5 * UI, '#f2f3f5'], [data.size + 2.5 * UI, 'rgb(49, 51, 56)'], [data.size, data.color]]) {
      context.beginPath();
      context.arc(data.x, data.y, radius, 0, Math.PI * 2);
      context.fillStyle = fill;
      context.fill();
    }
  }
  if (!data.label) return;
  context.font = `700 ${size}px ${settings.labelFont}`;
  const width = context.measureText(data.label).width;
  const x = data.x + data.size + 3 * UI;                // against the ring, and over the start of the ordinary name
  const height = size + 12 * UI;
  context.save();
  context.shadowColor = 'rgba(0, 0, 0, 0.45)';
  context.shadowBlur = 10 * UI;
  context.shadowOffsetY = 2 * UI;
  context.fillStyle = ACCENT;
  context.beginPath();
  context.roundRect(x, data.y - height / 2, width + 22 * UI, height, 6 * UI);
  context.fill();
  context.restore();
  context.fillStyle = '#ffffff';
  context.fillText(data.label, x + 11 * UI, data.y + size / 3);
}

const bigger = (a, b) => (BigInt(a) > BigInt(b) ? 1 : -1); // ids are 18-digit numbers, kept as text
export const edgeKey = (a, b) => (bigger(a, b) > 0 ? `${b}|${a}` : `${a}|${b}`);

const css = ([r, g, b], a = 1) => `rgba(${r}, ${g}, ${b}, ${a})`;
const mix = (from, to, t) => from.map((v, i) => Math.round(v + (to[i] - v) * t));
// Sigma writes colors without multiplying them by their transparency, so that a line at 7% opacity is drawn as a nearly
// solid one. Transparency is therefore never asked of it: the color of a line is mixed with the background here instead.
const faded = (rgb, opacity) => css(mix(BACKGROUND, rgb, Math.min(1, Math.max(0, opacity))));

const luminance = ([r, g, b]) => {
  const linear = (v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
};
const MIN_LUMINANCE = MIN_CONTRAST * (luminance(BACKGROUND) + 0.05) - 0.05;

// The color of a person in Discord, from the API (#RRGGBB, or nothing when they have no colored role). Only that format is read.
function discordColor(hex) {
  const match = typeof hex === 'string' ? /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex) : null;
  if (!match) return NODE_DEFAULT;
  let rgb = [1, 2, 3].map((i) => parseInt(match[i], 16));
  for (let t = 0.05; luminance(rgb) < MIN_LUMINANCE && t <= 1; t += 0.05) rgb = mix([1, 2, 3].map((i) => parseInt(match[i], 16)), [255, 255, 255], t);
  return rgb;
}

export class MapGraph {
  // `imageProgram`: Sigma's program that draws a picture in a point (the Activity gives one: the people's photos in the color of their name)
  constructor(container, { onSelect, onHover, imageProgram }) {
    this.container = container;
    container.__map = this; // so that a test in a browser can ask where the names are
    this.flashCount = 0;
    this.graph = new Graph({ type: 'undirected', multi: false });
    this.onSelect = onSelect;
    this.onHover = onHover;
    this.factor = DEFAULT_FACTOR;
    this.selected = null;
    this.hovered = null;        // the person whose point is under the mouse
    this.labelHovered = null;   // the person whose name is under the mouse (when no point is)
    this.labelBox = null;
    this.labelBoxes = [];       // where the names were drawn the last time
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
      stagePadding: 64 * UI,           // room around the points for the photos and the names, which would be cut at the edge of the panel otherwise
      allowInvalidContainer: true,     // the map is hidden (not destroyed) while another page is shown: its container then has no size
      labelColor: { color: '#dcdee1' },
      labelFont: FONT,
      labelSize: 12 * UI,
      labelWeight: '500',
      labelRenderedSizeThreshold: 0,   // any size: a crowded area still only shows what fits (see labelGridCellSize)
      labelDensity: 1.3,
      labelGridCellSize: 64 * UI,
      defaultDrawNodeLabel: (context, data, settings) => this.drawLabel(context, data, settings),
      defaultDrawNodeHover: drawHover,
      defaultNodeColor: '#5865f2',
      ...(imageProgram ? { nodeProgramClasses: { image: imageProgram } } : {}),
      zIndex: true,
      minCameraRatio: 0.03,
      maxCameraRatio: 14,
      nodeReducer: (node, data) => this.reduceNode(node, data),
      edgeReducer: (edge, data) => this.reduceEdge(edge, data),
    });
    // The names are drawn on a canvas, which does not wait for a font: draw them again once Inter has arrived
    Promise.all([document.fonts?.load(`500 12px ${FONT}`), document.fonts?.load(`700 13px ${FONT}`)])
      .then(() => this.renderer?.refresh({ skipIndexation: true }))
      .catch(() => {});
    this.renderer.on('beforeRender', () => (this.labelBoxes = []));
    this.renderer.on('clickNode', ({ node }) => this.select(node, true));
    this.renderer.on('clickStage', () => this.select(this.labelHovered, true)); // a click on a name is a click on its point
    this.renderer.on('enterNode', ({ node }) => {
      this.hovered = node;
      this.applyCursor();
      this.onHover?.(node);
      this.renderer.refresh({ skipIndexation: true });
    });
    this.renderer.on('leaveNode', () => {
      this.hovered = null;
      this.applyCursor();
      this.onHover?.(this.labelHovered);
      this.renderer.refresh({ skipIndexation: true });
    });
    this.onPointer = (event) => {
      const box = container.getBoundingClientRect();
      const hit = this.hovered ? null : this.labelAt(event.clientX - box.left, event.clientY - box.top);
      this.labelBox = hit;
      this.setLabelHovered(hit?.id ?? null);
    };
    this.onLeave = () => {
      this.labelBox = null;
      this.setLabelHovered(null);
    };
    container.addEventListener('mousemove', this.onPointer);
    container.addEventListener('mouseleave', this.onLeave);
  }

  setLabelHovered(id) {
    if (id === this.labelHovered) return;
    this.labelHovered = id;
    this.applyCursor();
    this.onHover?.(this.hoveredNow());
    this.renderer.refresh({ skipIndexation: true });
  }

  // Names are drawn with a dark halo so that they stay readable on top of the lines. Where each one is drawn is remembered:
  // a name can be hovered and clicked like its point.
  drawLabel(context, data, settings) {
    if (!data.label) return;
    const size = settings.labelSize;
    context.font = `${settings.labelWeight} ${size}px ${settings.labelFont}`;
    const x = data.x + data.size + 4 * UI;
    const y = data.y + size / 3;
    context.lineJoin = 'round';
    context.lineWidth = 4 * UI;
    context.strokeStyle = 'rgba(49, 51, 56, 0.95)';
    context.strokeText(data.label, x, y);
    context.fillStyle = '#dcdee1';
    context.fillText(data.label, x, y);
    if (data.id) {
      this.labelBoxes.push({ id: data.id, left: data.x, right: x + context.measureText(data.label).width, top: data.y - size * 0.8, bottom: data.y + size * 0.8 });
    }
  }

  // The name under the pointer (x, y in pixels of the map), if any. Once a name is hovered it keeps the hover while the pointer stays
  // on it or on the pill that opens around it, which is wider than the name.
  labelAt(x, y) {
    const inside = (b, extra = 0) => x >= b.left && x <= b.right + extra && y >= b.top && y <= b.bottom;
    if (this.labelBox && inside(this.labelBox, LABEL_PILL_EXTRA)) return this.labelBox;
    for (let i = this.labelBoxes.length - 1; i >= 0; i--) if (inside(this.labelBoxes[i])) return this.labelBoxes[i];
    return null;
  }

  // The person under the mouse: their point, otherwise their name
  hoveredNow() {
    return this.hovered ?? this.labelHovered;
  }

  applyCursor() {
    this.container.style.cursor = this.hoveredNow() ? 'pointer' : 'default';
  }

  // --- what each point and line looks like ---------------------------------------------------------

  // A point is the color of the person in Discord; its size is the weight of their exchanges
  nodeLook(node) {
    const size = (3.5 + 13 * Math.sqrt(node.influence / this.maxInfluence)) * UI;
    const rgb = discordColor(node.color);
    return { size, rgb, color: css(rgb) };
  }

  // Lines are only a faint web: they show the shape of the groups without hiding the names
  edgeLook(weight) {
    const crowd = Math.min(1, 900 / Math.max(this.edgeCount, 1));
    const strength = Math.pow(weight / this.maxWeight, 0.5);
    return { size: (0.5 + 1.5 * strength) * UI, color: faded(EDGE, (0.13 + 0.20 * strength) * (0.6 + 0.4 * crowd)) };
  }

  // Who is in focus, and with whom they talk (computed once when the focus changes, not for every point drawn)
  updateFocus() {
    const wanted = this.selected ?? this.hoveredNow();
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
    if (data.type === 'image') result.size = Math.max(data.size * 2.1, 13 * UI);    // a face needs more room than a dot
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
        if (data.type === 'image') { result.type = 'circle'; result.size = data.size; }   // those out of focus go back to dim dots
      }
    }
    // The person under the mouse is always lit and named, whoever is selected (a selected person dims everybody else)
    if (node === this.hoveredNow()) {
      result.highlighted = true;
      result.forceLabel = true;
      result.color = data.color;
      result.label = data.label;
      result.size = result.size * 1.25;
      result.zIndex = 5;
    }
    const light = this.light(this.nodeFlashes.get(node));
    if (light > 0) {
      result.color = css(mix(data.rgb, FLASH_COLOR, light));
      result.size = result.size * (1 + 0.9 * light);
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
        result.size = (0.8 + 3.6 * strength) * UI;
        result.zIndex = 2;
      } else {
        result.color = faded(EDGE, 0.07);
        result.zIndex = 0;
      }
    }
    const light = this.light(this.flashes.get(edge));
    if (light > 0) {
      result.color = faded(FLASH_COLOR, 0.55 + 0.45 * light);
      result.size = Math.max(result.size, data.size) + 3.5 * UI * light;
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
      const look = this.nodeLook(node);
      const attributes = { id: node.id, label: node.label, size: look.size, color: look.color, rgb: look.rgb, influence: node.influence,
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
    this.renderer.setSetting('labelGridCellSize', (64 + 56 * (1 - crowd)) * UI);
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

  // A person's photo in their point: the ring around it keeps the color of their name
  setPicture(id, url) {
    if (!this.graph.hasNode(id)) return;
    this.graph.mergeNodeAttributes(id, { type: 'image', image: url });
    this.renderer.refresh();
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
    this.container.removeEventListener('mousemove', this.onPointer);
    this.container.removeEventListener('mouseleave', this.onLeave);
    clearTimeout(this.layoutTimer);
    if (this.frame) cancelAnimationFrame(this.frame);
    this.layout?.kill();
    this.renderer.kill();
  }
}
