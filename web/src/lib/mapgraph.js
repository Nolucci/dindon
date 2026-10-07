// The map: one point per person, one line per pair of people who talk. Sigma draws it with WebGL, ForceAtlas2 places
// the points in a worker thread (so that the page stays smooth), and a new exchange makes its line light up.
import Graph from 'graphology';
import Sigma from 'sigma';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import FA2Layout from 'graphology-layout-forceatlas2/worker';

// How much each kind of exchange says about a tie (the same numbers as the API, which sends them in `meta.kind_factor`)
const DEFAULT_FACTOR = { reply: 1, mention: 0.6, reaction: 0.25 };
const FLASH_MS = 3200;
const PULSE_MS = 2200;                // a message travelling from one person to the other, then the ripple where it lands
const TRAVEL = 0.42;                  // the part of PULSE_MS that the message spends on its way
// The color of a new exchange follows its kind: a reply is a conversation (yellow), a mention calls someone (blurple), a reaction is a nod (pink)
const KIND_COLOR = { reply: [240, 178, 50], mention: [153, 160, 255], reaction: [255, 128, 176] };
const CALM = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;   // no travelling light: the line and the points still glow
const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2);
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

// --- grouping by role and by resemblance of names (instead of by exchanges) -------------------------------------
const NO_GROUP = 'Sans rôle';
// A name reduced to its letters and digits (no case, accents or fancy letters), so that « Jean_Dupont » and « jean dupont 2 » look alike
const nameKey = (label) => String(label ?? '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
const trigrams = (key) => {
  const padded = `  ${key} `;
  const set = new Set();
  for (let i = 0; i + 3 <= padded.length; i++) set.add(padded.slice(i, i + 3));
  return set;
};
function similar(a, b) {
  if (a.key.length >= 4 && b.key.length >= 4 && (a.key.startsWith(b.key.slice(0, 4)) || a.key.includes(b.key) || b.key.includes(a.key))) return true;
  let shared = 0;
  for (const t of a.grams) if (b.grams.has(t)) shared++;
  return shared / (a.grams.size + b.grams.size - shared || 1) >= 0.4;
}

/** The places of the points when grouped: one island per role, and inside it the names that look alike side by side (a sunflower spiral,
 * filled one family of names after the other). Returns { positions: id -> {x, y}, islands: [{name, x, y, radius, count}] } */
export function groupedLayout(people) {
  const byGroup = new Map();
  for (const person of people) {
    const name = person.group || NO_GROUP;
    if (!byGroup.has(name)) byGroup.set(name, []);
    const key = nameKey(person.label);
    byGroup.get(name).push({ id: person.id, influence: person.influence ?? 0, key, grams: trigrams(key) });
  }
  const positions = new Map();
  const islands = [];
  const SPACING = 3;
  for (const [name, members] of byGroup) {
    members.sort((a, b) => b.influence - a.influence || (a.key < b.key ? -1 : 1));
    const families = [];
    for (const member of members) {
      const family = families.find((f) => similar(f[0], member));
      if (family) family.push(member);
      else families.push([member]);
    }
    families.sort((a, b) => b.length - a.length || (a[0].key < b[0].key ? -1 : 1));
    const ordered = families.flat();
    const radius = SPACING * Math.sqrt(ordered.length) + SPACING * 2;
    const local = ordered.map((member, i) => {
      const r = SPACING * Math.sqrt(i + 0.5);
      const angle = i * 2.399963229728653;               // the golden angle
      return [member.id, r * Math.cos(angle), r * Math.sin(angle)];
    });
    islands.push({ name, radius, count: ordered.length, local, x: 0, y: 0 });
  }
  // The biggest island in the middle, the others around it along a spiral, each as close as it can be without touching
  islands.sort((a, b) => b.count - a.count || (a.name === NO_GROUP ? 1 : -1));
  const placed = [];
  for (const island of islands) {
    for (let t = 0; ; t += 0.05) {
      const distance = placed.length ? 4 * t * (islands[0].radius / 6) : 0;
      const x = distance * Math.cos(t * 3.2);
      const y = distance * Math.sin(t * 3.2);
      if (placed.every((o) => Math.hypot(o.x - x, o.y - y) >= o.radius + island.radius + SPACING * 2)) {
        island.x = x;
        island.y = y;
        break;
      }
    }
    placed.push(island);
    for (const [id, dx, dy] of island.local) positions.set(id, { x: island.x + dx, y: island.y + dy });
  }
  return { positions, islands: islands.map(({ name, x, y, radius, count }) => ({ name, x, y, radius, count })) };
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
    this.nodeKinds = new Map();   // person -> color of their last exchange
    this.flashKinds = new Map();  // key of an edge -> kind of its last exchange
    this.pulses = [];             // the exchanges on their way: { from, to, kind, since }
    this.maxInfluence = 1;
    this.maxWeight = 1;
    this.edgeCount = 0;
    this.layout = null;
    this.layoutTimer = null;
    this.grouped = false;     // placed by role and by resemblance of names, not by exchanges
    this.islands = [];
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
    this.renderer.on('afterRender', () => { this.drawIslandNames(); this.drawPulses(); });
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
      result.color = css(mix(data.rgb, this.nodeKinds.get(node) ?? FLASH_COLOR, light));
      result.size = result.size * (1 + 0.9 * light);
      result.zIndex = 4;
    }
    return result;
  }

  reduceEdge(edge, data) {
    this.updateFocus();
    const result = { ...data };
    if (this.grouped) result.hidden = true;                  // the lines would cross the islands: they show for the person in focus and for a new exchange
    if (this.inFocus) {
      if (this.graph.hasExtremity(edge, this.inFocus)) {
        result.hidden = false;
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
      result.hidden = false;
      result.color = faded(KIND_COLOR[this.flashKinds.get(edge)] ?? FLASH_COLOR, 0.55 + 0.45 * light);
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
    const newcomers = [];
    const spread = 60 + 9 * Math.sqrt(data.nodes.length);
    for (const node of data.nodes) {
      const look = this.nodeLook(node);
      const attributes = { id: node.id, label: node.label, size: look.size, color: look.color, rgb: look.rgb, influence: node.influence,
                           messages: node.messages, last_message_at: node.last_message_at, group: node.group ?? null };
      if (graph.hasNode(node.id)) {
        graph.mergeNodeAttributes(node.id, attributes);
      } else {
        graph.addNode(node.id, { ...attributes, x: (Math.random() - 0.5) * spread, y: (Math.random() - 0.5) * spread });
        newcomers.push(node.id);
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
    if (known === 0 || this.layout) this.settle(known === 0 ? 6000 : 2500);     // the first placement (or one still running) is done over
    else if (newcomers.length) this.placeNewcomers(newcomers);                   // afterwards nobody moves, except the people who just appeared
  }

  // Once the map is placed, the points stay where they are: a new person goes to the center of the people they talk to (or of the map if they talk to
  // nobody yet), then to the nearest free spot along a spiral, so that they sit with their group, never on top of a point or a name. The spot only depends
  // on the map and on the person (no randomness): the same newcomer always lands at the same place. In the grouped mode, where the islands depend on
  // who is there, everything is placed again.
  placeNewcomers(ids) {
    if (this.grouped) {
      this.placeGroups();
      return;
    }
    const graph = this.graph;
    const fresh = new Set(ids);
    const placed = [];
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    graph.forEachNode((id, a) => {
      if (fresh.has(id)) return;
      placed.push(a);
      minX = Math.min(minX, a.x); maxX = Math.max(maxX, a.x);
      minY = Math.min(minY, a.y); maxY = Math.max(maxY, a.y);
    });
    const center = placed.length ? { x: (minX + maxX) / 2, y: (minY + maxY) / 2 } : { x: 0, y: 0 };
    // The room a point has on this map: what the first placement left between neighbors
    const gap = placed.length > 1 ? 0.7 * Math.sqrt(Math.max((maxX - minX) * (maxY - minY), 1) / placed.length) : 10;
    const free = (x, y) => placed.every((a) => Math.hypot(a.x - x, a.y - y) >= gap);
    for (const id of ids) {
      let x = 0, y = 0, near = 0;
      graph.forEachNeighbor(id, (other, a) => { if (!fresh.has(other) || placed.includes(a)) { x += a.x; y += a.y; near++; } });
      const base = near ? { x: x / near, y: y / near } : center;
      let turn = 0;
      for (const ch of String(id)) turn = (turn * 31 + ch.charCodeAt(0)) % 360;
      let spot = base;
      for (let i = 0; i < 400; i++) {
        const r = gap * 0.35 * Math.sqrt(i);                                       // an even spiral out of the base
        const angle = (turn * Math.PI) / 180 + i * 2.399963229728653;               // the golden angle
        spot = { x: base.x + r * Math.cos(angle), y: base.y + r * Math.sin(angle) };
        if (free(spot.x, spot.y)) break;
      }
      graph.mergeNodeAttributes(id, spot);
      placed.push(graph.getNodeAttributes(id));
    }
    this.renderer.refresh();
  }

  // Places the points: a few seconds of ForceAtlas2 in a worker, then it stops (the points keep their places)
  settle(milliseconds) {
    this.layout?.kill();
    this.layout = null;
    clearTimeout(this.layoutTimer);
    if (this.grouped) {
      this.placeGroups();
      return;
    }
    this.islands = [];
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
    this.layoutTimer = setTimeout(() => {
      this.layout?.kill();                                          // a worker that is gone cannot write over the next step
      this.layout = null;
      this.spread();
    }, milliseconds);
  }

  // ForceAtlas2 piles the people up in the middle and leaves the edges empty. Once it has placed them, each one keeps their direction from the
  // center and their order (the most central stays central) but the distances are evened out, and the whole is stretched to the shape of the
  // panel: the space is used, and nothing goes past its edge (the camera fits the box of the points).
  spread() {
    const graph = this.graph;
    const n = graph.order;
    if (n < 3 || this.grouped) return;
    let cx = 0, cy = 0;
    graph.forEachNode((id, a) => { cx += a.x; cy += a.y; });
    cx /= n;
    cy /= n;
    const rows = [];
    graph.forEachNode((id, a) => rows.push({ id, angle: Math.atan2(a.y - cy, a.x - cx), r: Math.hypot(a.x - cx, a.y - cy) }));
    rows.sort((a, b) => a.r - b.r);
    const rMax = Math.max(rows[Math.floor(0.97 * (n - 1))].r, 1e-9);      // a few far strays do not set the scale
    const box = this.container.getBoundingClientRect();
    const aspect = box.width > 0 && box.height > 0 ? Math.min(Math.max(box.width / box.height, 0.6), 2.2) : 1;
    rows.forEach((row, rank) => {
      const even = Math.sqrt((rank + 0.5) / n);                          // evenly filled disc
      const kept = Math.min(row.r / rMax, 1);                             // what the layout said
      const r = 0.6 * even + 0.4 * kept;
      graph.mergeNodeAttributes(row.id, { x: r * Math.cos(row.angle) * aspect * 100, y: r * Math.sin(row.angle) * 100 });
    });
    this.renderer.refresh();
  }



  // Grouped by role and by names that look alike: the points go to their islands, with no regard for who talks to whom
  placeGroups(resetView = false) {
    const people = [];
    this.graph.forEachNode((id, a) => people.push({ id, label: a.label, group: a.group, influence: a.influence }));
    const { positions, islands } = groupedLayout(people);
    this.islands = islands;
    for (const [id, { x, y }] of positions) this.graph.mergeNodeAttributes(id, { x, y });
    this.renderer.refresh();
    if (resetView) this.renderer.getCamera().animatedReset({ duration: 400 });
  }

  setGrouped(on) {
    if (on === this.grouped) return;
    this.grouped = on;
    this.focusStale = true;
    this.settle(2500);
    if (on) this.placeGroups(true);
    this.renderer.refresh();
  }

  // The name of each island, above it (in grouped mode only)
  drawIslandNames() {
    if (!this.grouped || !this.islands.length) return;
    const context = this.renderer.getCanvases().labels.getContext('2d');
    const ratio = Math.max(this.renderer.getCamera().ratio, 1e-6);
    context.save();
    context.textAlign = 'center';
    context.font = `700 ${13 * UI}px ${FONT}`;
    for (const island of this.islands) {
      const point = this.renderer.graphToViewport({ x: island.x, y: island.y - island.radius });
      const edge = this.renderer.graphToViewport({ x: island.x, y: island.y });
      const reach = Math.abs(point.y - edge.y);
      if (!Number.isFinite(reach) || reach < 6 * UI && ratio > 1) continue;
      const text = `${island.name} · ${island.count}`;
      context.lineJoin = 'round';
      context.lineWidth = 4 * UI;
      context.strokeStyle = 'rgba(49, 51, 56, 0.95)';
      context.strokeText(text, point.x, point.y - 6 * UI);
      context.fillStyle = '#f2f3f5';
      context.fillText(text, point.x, point.y - 6 * UI);
    }
    context.restore();
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
    this.flashKinds.set(key, kind);
    this.nodeFlashes.set(from, now);
    this.nodeFlashes.set(to, now);
    this.nodeKinds.set(from, KIND_COLOR[kind] ?? FLASH_COLOR);
    this.nodeKinds.set(to, KIND_COLOR[kind] ?? FLASH_COLOR);
    this.pulses.push({ from, to, kind, since: now });
    if (this.pulses.length > 80) this.pulses.splice(0, this.pulses.length - 80);   // a flood of messages: the oldest lights go out first
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
      this.pulses = this.pulses.filter((p) => now - p.since < PULSE_MS);
      this.renderer.refresh({ skipIndexation: true });
      this.frame = this.flashes.size || this.nodeFlashes.size || this.pulses.length ? requestAnimationFrame(tick) : null;
    };
    this.frame = requestAnimationFrame(tick);
  }

  // The exchanges on their way, drawn over the map: a comet from the one who wrote to the one who is answered, a ring where it lands, and a halo
  // around everyone who is in a conversation right now (the more exchanges at once, the wider the halo: three people talking light up together)
  drawPulses() {
    if (!this.pulses.length) return;
    const context = this.renderer.getCanvases().labels.getContext('2d');
    const now = performance.now();
    const where = (id) => {
      if (!this.graph.hasNode(id)) return null;
      const data = this.renderer.getNodeDisplayData(id);
      const at = this.graph.getNodeAttributes(id);
      return data ? { ...this.renderer.graphToViewport({ x: at.x, y: at.y }), size: data.size } : null;
    };
    const active = new Map();                                 // person -> how many exchanges are going on around them
    context.save();
    context.globalCompositeOperation = 'lighter';
    for (const pulse of this.pulses) {
      const t = (now - pulse.since) / PULSE_MS;
      if (t < 0 || t >= 1) continue;
      const a = where(pulse.from);
      const b = where(pulse.to);
      if (!a || !b) continue;
      const rgb = KIND_COLOR[pulse.kind] ?? FLASH_COLOR;
      active.set(pulse.from, (active.get(pulse.from) ?? 0) + (1 - t));
      active.set(pulse.to, (active.get(pulse.to) ?? 0) + (1 - t));
      if (CALM) continue;
      const travel = Math.min(t / TRAVEL, 1);
      if (travel < 1) {
        const head = ease(travel);
        const tail = Math.max(0, head - 0.22);               // the trail of the comet, along the line
        const hx = a.x + (b.x - a.x) * head, hy = a.y + (b.y - a.y) * head;
        const tx = a.x + (b.x - a.x) * tail, ty = a.y + (b.y - a.y) * tail;
        const gradient = context.createLinearGradient(tx, ty, hx, hy);
        gradient.addColorStop(0, css(rgb, 0));
        gradient.addColorStop(1, css(rgb, 0.95));
        context.strokeStyle = gradient;
        context.lineWidth = 3 * UI;
        context.lineCap = 'round';
        context.beginPath();
        context.moveTo(tx, ty);
        context.lineTo(hx, hy);
        context.stroke();
        const glow = context.createRadialGradient(hx, hy, 0, hx, hy, 9 * UI);
        glow.addColorStop(0, css([255, 255, 255], 0.95));
        glow.addColorStop(0.35, css(rgb, 0.8));
        glow.addColorStop(1, css(rgb, 0));
        context.fillStyle = glow;
        context.beginPath();
        context.arc(hx, hy, 9 * UI, 0, Math.PI * 2);
        context.fill();
      }
      const ring = (point, from, to, strength) => {          // a ring that widens and fades
        const u = (t - from) / (to - from);
        if (u <= 0 || u >= 1) return;
        context.strokeStyle = css(rgb, strength * (1 - u) ** 1.5);
        context.lineWidth = (2.5 - 1.5 * u) * UI;
        context.beginPath();
        context.arc(point.x, point.y, point.size + (6 + 26 * ease(u)) * UI, 0, Math.PI * 2);
        context.stroke();
      };
      ring(a, 0, 0.3, 0.55);                                 // where it leaves: a small one
      ring(b, TRAVEL, 0.95, 0.9);                            // where it lands: a wide one
      ring(b, TRAVEL + 0.12, 1, 0.5);                        // and its echo
    }
    for (const [id, amount] of active) {
      const point = where(id);
      if (!point) continue;
      const strength = Math.min(1, 0.25 + 0.3 * amount);
      const reach = point.size + (10 + 8 * Math.min(amount, 3)) * UI;
      const rgb = this.nodeKinds.get(id) ?? FLASH_COLOR;
      const halo = context.createRadialGradient(point.x, point.y, point.size * 0.8, point.x, point.y, reach);
      halo.addColorStop(0, css(rgb, 0.45 * strength));
      halo.addColorStop(1, css(rgb, 0));
      context.fillStyle = halo;
      context.beginPath();
      context.arc(point.x, point.y, reach, 0, Math.PI * 2);
      context.fill();
    }
    context.restore();
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
