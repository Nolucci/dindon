// The map inside a Discord voice channel (an Activity): the same map as the interface (lib/mapgraph.js), fed by /activity/map, which only a member of the
// server can read. No password, no other page: Discord's SDK says who the person is, the server checks it with Discord.
import { DiscordSDK } from '@discord/embedded-app-sdk';
import './fonts.css';
import './app.css';
import { MapGraph } from './lib/mapgraph.js';
import { matches } from './lib/text.js';
import { imageProgram, pictureLoader } from './lib/pictures.js';


const PERIODS = { 7: '7 derniers jours', 30: '30 derniers jours', 90: '90 derniers jours', all: 'Depuis le début' };
// Inside Discord every request goes through its proxy, under /.proxy (the address of the page is the one of Discord, not ours)
const BASE = new URLSearchParams(location.search).has('frame_id') ? '/.proxy' : '';
const $ = (id) => document.getElementById(id);
const note = (text) => ($('note').textContent = text);

const GOLD = '#d6a55a';       // the gold of the frame of the background

// The background is the page's own (CSS, behind everything): zooming the map moves points and lines, never the background. It stretches to the window so that the golden frame
// always sits on the edges; the map, the bar and the card are panels inside it, dark enough that names stay readable over the ornaments.
const style = document.createElement('style');
style.textContent = `
  html, body { height: 100%; margin: 0; }
  body { display: flex; flex-direction: column; gap: .5rem; box-sizing: border-box; padding: clamp(16px, 4.2vmin, 52px); color: var(--text-primary);
         background: #050b1d url(/activity-background.webp) center / 100% 100% no-repeat; }
  .panel { background: rgba(5, 10, 28, .68); border: 1px solid rgba(214, 165, 90, .28); border-radius: 10px; }
  #bar { display: flex; align-items: center; gap: .6rem; padding: .5rem .75rem; flex-wrap: wrap; }
  #bar select, #bar button { font: inherit; color: inherit; background: rgba(30, 31, 34, .85); border: 1px solid #4e5058; border-radius: 6px; padding: .25rem .5rem; }
  #bar button { cursor: pointer; }
  #note { color: var(--text-secondary, #b5bac1); margin-left: auto; }
  #search { position: relative; flex: 1 1 14rem; max-width: 22rem; }
  #q { width: 100%; box-sizing: border-box; font: inherit; color: inherit; background: rgba(30, 31, 34, .85); border: 1px solid #4e5058; border-radius: 6px; padding: .3rem .6rem; }
  #q:focus { outline: 2px solid ${GOLD}; outline-offset: 1px; }
  #suggest { position: absolute; z-index: 10; left: 0; right: 0; top: calc(100% + 4px); margin: 0; padding: .25rem; list-style: none; max-height: 18rem; overflow-y: auto;
             background: rgba(14, 16, 30, .97); border: 1px solid rgba(214, 165, 90, .4); border-radius: 8px; box-shadow: 0 8px 24px rgba(0, 0, 0, .5); }
  #suggest button { display: flex; align-items: center; gap: .55rem; width: 100%; font: inherit; color: inherit; background: none; border: 0; border-radius: 6px; padding: .3rem .4rem; cursor: pointer; text-align: left; }
  #suggest button:hover, #suggest button:focus-visible { background: rgba(88, 101, 242, .3); outline: none; }
  #suggest .none { padding: .4rem .5rem; color: var(--text-secondary, #b5bac1); }
  #suggest mark { background: none; color: ${GOLD}; font-weight: 700; }
  #kinds, #filters { display: flex; gap: .3rem; flex-wrap: wrap; }
  #kinds button { font: inherit; font-size: .8rem; padding: .2rem .6rem; border-radius: 999px; cursor: pointer; color: var(--text-secondary, #b5bac1); background: transparent; border: 1px solid #4e5058; }
  #kinds button[aria-pressed="true"] { color: #fff; background: rgba(88, 101, 242, .55); border-color: #5865f2; }
  #main { flex: 1; min-height: 0; display: flex; gap: .5rem; }
  #canvas { flex: 1; min-width: 0; overflow: hidden; }
  #card { width: 22rem; max-width: 46%; overflow-y: auto; padding: 1.1rem 1.1rem 1.25rem; position: relative; background: rgba(5, 10, 28, .86); scrollbar-width: thin; }
  #card .close { position: absolute; top: .5rem; right: .6rem; border: 0; background: none; color: var(--text-secondary, #b5bac1); font-size: 1.4rem; line-height: 1; cursor: pointer; }
  #card .head { display: flex; align-items: center; gap: .85rem; margin-bottom: 1rem; padding-right: 1.2rem; }
  #card .who { min-width: 0; display: flex; flex-direction: column; gap: .2rem; align-items: flex-start; }
  #card h2 { margin: 0; font-size: 1.3rem; line-height: 1.2; overflow-wrap: anywhere; }
  #card .rank { font-size: .72rem; font-weight: 700; color: #1b1405; background: ${GOLD}; border-radius: 999px; padding: .1rem .55rem; }
  #card .muted { color: var(--text-secondary, #b5bac1); font-size: .76rem; margin: 0; line-height: 1.35; }
  .portrait { flex: none; display: inline-flex; align-items: center; justify-content: center; border: 3px solid; border-radius: 50%; overflow: hidden; box-sizing: border-box;
                    background: #1e1f22; font-weight: 700; color: var(--text-secondary, #b5bac1); }
  .portrait img { width: 100%; height: 100%; object-fit: cover; display: block; }
  #card .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
  #card .tile { display: flex; flex-direction: column; gap: .1rem; padding: .6rem .7rem; border-radius: 8px; background: rgba(88, 101, 242, .12); border: 1px solid rgba(88, 101, 242, .25); }
  #card .tile strong { font-size: 1.4rem; line-height: 1.1; font-variant-numeric: tabular-nums; }
  #card .tile span { font-size: .72rem; text-transform: uppercase; letter-spacing: .04em; color: var(--text-secondary, #b5bac1); }
  #card .tile em { font-style: normal; font-size: .72rem; color: ${GOLD}; margin-top: .15rem; }
  #card .block { margin-top: 1.1rem; padding-top: .9rem; border-top: 1px solid rgba(214, 165, 90, .22); display: flex; flex-direction: column; gap: .45rem; }
  #card .block h3 { margin: 0; font-size: .72rem; letter-spacing: .09em; text-transform: uppercase; color: ${GOLD}; }
  #card .bars { width: 100%; height: auto; display: block; }
  #card .bars text { fill: var(--text-secondary, #b5bac1); font-size: 8px; }
  #card ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .5rem; }
  #card .links button { display: flex; align-items: center; gap: .6rem; width: 100%; font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; text-align: left; }
  #card .links button:hover .name { text-decoration: underline; }
  #card .linkText { display: flex; flex-direction: column; min-width: 0; }
  #card .name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #card .meter { height: 3px; margin: .3rem 0 0 2.4rem; border-radius: 2px; background: rgba(255, 255, 255, .08); }
  #card .meter div { height: 100%; border-radius: 2px; background: linear-gradient(90deg, #5865f2, ${GOLD}); }
  #card .tags { display: flex; flex-wrap: wrap; gap: .35rem; margin: 0; }
  #card .tags span { padding: .15rem .6rem; border-radius: 999px; background: rgba(255, 255, 255, .08); font-size: .8rem; }
  #card .axes li { display: flex; flex-direction: column; }
  `;
document.head.append(style);

let token = null;
let guild = null;
let map = null;
let shown = null;          // the person whose card is open
let focused = null;        // the person whose links and name the server is showing
let loadNumber = 0;
const nodeColors = new Map();   // person -> color of their name (ring of their picture)
const KIND_NAMES = { reply: 'Réponses', mention: 'Mentions', reaction: 'Réactions' };
let kinds = null;               // the kinds of exchange ticked (null: not known yet, the server sends them all that the admins allow)
let people = [];                // the people of the map whose name is shown: the ones that can be searched
const fmt = new Intl.NumberFormat('fr-FR');
const dateFr = (iso) => new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });

const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const WEEKDAYS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'];
const el = (tag, className, text) => Object.assign(document.createElement(tag), { className: className ?? '', textContent: text ?? '' });   // text only: a name comes from Discord, never HTML
const NS = 'http://www.w3.org/2000/svg';

// Bars drawn as SVG, no library: `values` with a label under some of them; the tallest one is lit
function bars(values, { labels = [], height = 56, tip = () => '' } = {}) {
  const top = Math.max(...values, 1);
  const width = 240;
  const slot = width / values.length;
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height + 14}`);
  svg.setAttribute('class', 'bars');
  svg.setAttribute('role', 'img');
  values.forEach((value, i) => {
    const h = Math.max(value ? 2 : 0.5, (value / top) * height);
    const bar = document.createElementNS(NS, 'rect');
    bar.setAttribute('x', i * slot + slot * 0.14);
    bar.setAttribute('y', height - h);
    bar.setAttribute('width', slot * 0.72);
    bar.setAttribute('height', h);
    bar.setAttribute('rx', 1.5);
    bar.setAttribute('fill', value === top ? GOLD : '#5865f2');
    bar.setAttribute('opacity', value === top ? 1 : 0.75);
    const title = document.createElementNS(NS, 'title');
    title.textContent = tip(i, value);
    bar.append(title);
    svg.append(bar);
    if (labels[i]) {
      const text = document.createElementNS(NS, 'text');
      text.setAttribute('x', i === 0 ? 0 : i * slot + slot / 2);                 // the first label starts at the edge, so that it is not cut
      text.setAttribute('y', height + 11);
      text.setAttribute('text-anchor', i === 0 ? 'start' : 'middle');
      text.textContent = labels[i];
      svg.append(text);
    }
  });
  return svg;
}

function daypart(hour) {
  return hour >= 5 && hour < 12 ? 'le matin' : hour < 18 && hour >= 12 ? 'l’après-midi' : hour >= 18 && hour < 23 ? 'le soir' : 'la nuit';
}

function section(title, ...content) {
  const block = el('section', 'block');
  block.append(el('h3', '', title), ...content);
  return block;
}

// The photo of a person, or their initial, in a ring of the color of their name
function portrait(id, label, color, size) {
  const holder = el('span', 'portrait');
  holder.style.cssText = `width:${size}px;height:${size}px;border-color:${color || '#dbdee1'}`;
  if (pictures.get(id)) holder.append(Object.assign(document.createElement('img'), { src: pictures.get(id), alt: '' }));
  else holder.textContent = (label || '?').trim().charAt(0).toUpperCase();
  return holder;
}

function tile(value, label, note) {
  const box = el('div', 'tile');
  box.append(el('strong', '', value), el('span', '', label));
  if (note) box.append(el('em', '', note));
  return box;
}

function closeCard() {
  shown = null;
  focused = null;
  $('card').hidden = true;
  map.select(null);
  map.resized();
  void load();
}

function openCard(card) {
  const a = card.activity;
  const root = $('card');
  root.replaceChildren();
  const color = nodeColors.get(card.id);
  const close = el('button', 'close', '×');
  close.type = 'button';
  close.setAttribute('aria-label', 'Fermer la fiche');
  close.onclick = closeCard;

  const head = el('header', 'head');
  const who = el('div', 'who');
  who.append(el('h2', '', card.label));
  if (a) {
    who.append(el('p', 'muted', `Depuis le ${dateFr(a.first_message_at)} · dernier message le ${dateFr(a.last_message_at)}`));
    if (a.rank) who.append(el('span', 'rank', `n° ${fmt.format(a.rank)} sur ${fmt.format(a.writers)} auteurs`));
  }
  head.append(portrait(card.id, card.label, color, 64), who);
  root.append(close, head);

  if (a) {
    const grid = el('div', 'tiles');
    grid.append(
      tile(fmt.format(a.messages), 'messages', `${fmt.format(a.recent)} sur 30 jours`),
      tile(fmt.format(a.active_days), 'jours actifs', `${a.messages_per_active_day} par jour`),
      tile(`${Math.round(a.share_of_replies * 100)} %`, 'de réponses', `${fmt.format(a.average_length)} car. en moyenne`),
      tile(fmt.format(a.contacts), 'contacts', `${fmt.format(a.reactions_received)} réactions reçues`),
    );
    root.append(grid);
  }
  if (card.by_month?.length) {
    const labels = card.by_month.map((m, i) => (i === 0 || i === card.by_month.length - 1 || card.by_month.length <= 6 ? MONTHS[Number(m.month.slice(5)) - 1] : ''));
    root.append(section('Messages par mois', bars(card.by_month.map((m) => m.messages), { labels, tip: (i, v) => `${MONTHS[Number(card.by_month[i].month.slice(5)) - 1]} ${card.by_month[i].month.slice(0, 4)} : ${fmt.format(v)}` })));
  }
  if (card.habits) {
    const { hours, weekdays } = card.habits;
    const peakHour = hours.indexOf(Math.max(...hours));
    const peakDay = weekdays.indexOf(Math.max(...weekdays));
    root.append(section('Rythme',
      bars(hours, { height: 44, labels: hours.map((_, h) => (h % 6 === 0 ? `${h} h` : '')), tip: (h, v) => `${h} h : ${fmt.format(v)}` }),
      bars(weekdays, { height: 34, labels: ['L', 'M', 'M', 'J', 'V', 'S', 'D'], tip: (d, v) => `${WEEKDAYS[d]} : ${fmt.format(v)}` }),
      el('p', 'muted', `Plutôt ${daypart(peakHour)} (vers ${peakHour} h), surtout le ${WEEKDAYS[peakDay]}. Heure de Paris.`)));
  }
  if (card.roles?.length) {
    const tags = el('p', 'tags');
    for (const role of card.roles) tags.append(el('span', '', role));
    root.append(section('Rôles qu’elle s’est donnés', tags, el('p', 'muted', 'Ce que la personne dit d’elle-même : non vérifié.')));
  }
  if (card.axes?.length) {
    const list = el('ul', 'axes');
    for (const axis of card.axes) {
      const item = el('li');
      item.append(el('span', 'muted', axis.name), el('strong', '', axis.pole));
      list.append(item);
    }
    root.append(section('Où elle se situe', list, el('p', 'muted', 'Lecture automatique des propos, pas un verdict.')));
  }
  if (card.top_links?.length) {
    const strongest = Math.max(...card.top_links.map((l) => l.weight)) || 1;
    const list = el('ul', 'links');
    for (const link of card.top_links) {
      const item = el('li');
      const button = el('button');
      button.type = 'button';
      const text = el('span', 'linkText');
      text.append(el('span', 'name', link.label), el('span', 'muted', `${fmt.format(link.n)} échanges`));
      button.append(portrait(link.id, link.label, nodeColors.get(link.id), 30), text);
      button.onclick = () => { void choosePerson(link.id); };
      const bar = el('div', 'meter');
      bar.append(Object.assign(el('div'), { style: `width:${Math.max(6, (link.weight / strongest) * 100)}%` }));
      item.append(button, bar);
      list.append(item);
    }
    root.append(section('Liens principaux', list));
  }
  root.hidden = false;
  map.resized();
}

async function showCard(id) {
  shown = id;
  try {
    const card = await get(`/activity/person/${id}?${mapQuery()}`);
    if (shown === id) openCard(card);
  } catch (error) {
    if (shown !== id) return;
    $('card').replaceChildren(Object.assign(document.createElement('p'), { className: 'muted', textContent: error.message }));
    $('card').hidden = false;
    map.resized();
  }
}

async function get(path) {
  const response = await fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || 'Erreur');
  return body;
}

// The photos come through the server (the page may only load what the application serves), with the token: they are fetched here and shown as local pictures
// The photos come through the server (the page may only load what the application serves), with the token
let pictures = new Map();   // person -> local address of their photo, or null
let loader = null;

// What the map asked for: the same words for the map and for a card, so that a card is read in the map that is on the screen
const mapQuery = () => `guild=${guild}&period=${$('period').value}${kinds ? `&kinds=${[...kinds].join(',')}` : ''}${focused ? `&focus=${focused}` : ''}`
  + `${narrowed.weight !== '0' ? `&weight=${narrowed.weight}` : ''}${narrowed.theme ? `&theme=${narrowed.theme}` : ''}${narrowed.ideology ? `&ideology=${narrowed.ideology}` : ''}`;

// What the person narrowed the map to, among the filters that the admins offer (the server ignores any other)
const narrowed = { weight: '0', theme: '', ideology: '' };
const WEIGHT_CHOICES = [['0', 'Force : tous'], ['0.5', 'Force : ≥ 0,5'], ['1', 'Force : ≥ 1'], ['3', 'Force : ≥ 3'], ['10', 'Force : ≥ 10']];
let filtersDrawn = '';

function drawFilters(meta) {
  const allowed = meta.filters_allowed ?? [];
  const choices = meta.choices ?? {};
  const signature = JSON.stringify([allowed, choices]);
  if (signature === filtersDrawn) return;                    // the same choices: the selects keep what the person picked
  filtersDrawn = signature;
  const select = (key, label, options) => {
    const box = el('select');
    box.setAttribute('aria-label', label);
    for (const [value, text] of options) box.add(new Option(text, value, false, value === narrowed[key]));
    box.onchange = () => { narrowed[key] = box.value; void load().then((loaded) => { if (loaded && shown) showCard(shown); }); };
    return box;
  };
  const boxes = [];
  if (allowed.includes('weight')) boxes.push(select('weight', 'Force minimale des liens', WEIGHT_CHOICES));
  if (allowed.includes('theme') && choices.themes?.length) boxes.push(select('theme', 'Thème', [['', 'Thème : tous'], ...choices.themes.map((t) => [String(t.id), t.label])]));
  if (allowed.includes('ideology') && choices.ideologies?.length) boxes.push(select('ideology', 'Rôle d’idées', [['', 'Rôle : tous'], ...choices.ideologies.map((i) => [String(i.id), i.name])]));
  $('filters').replaceChildren(...boxes);
}

function drawKinds(allowed) {
  const box = $('kinds');
  if (!kinds) kinds = new Set(allowed);
  box.hidden = allowed.length < 2;                 // one kind allowed: nothing to choose
  box.replaceChildren(...allowed.map((kind) => {
    const chip = el('button', '', KIND_NAMES[kind] || kind);
    chip.type = 'button';
    chip.setAttribute('aria-pressed', String(kinds.has(kind)));
    chip.onclick = () => {
      if (kinds.has(kind) && kinds.size === 1) return;       // at least one stays ticked
      kinds.has(kind) ? kinds.delete(kind) : kinds.add(kind);
      void load().then((loaded) => { if (loaded && shown) showCard(shown); });
    };
    return chip;
  }));
}

// --- the search: among the people that the map names (nobody whose name the admins hide can be found), ignoring case and accents, every word in any order ---------------------
function highlight(label, query) {
  const out = document.createDocumentFragment();
  const words = query.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().split(/\s+/).filter(Boolean);
  const plain = label.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  if (plain.length !== label.length || !words.length) { out.append(label); return out; }        // letters that change length: no marks, the name is still right
  const marked = new Array(label.length).fill(false);
  for (const word of words) for (let at = plain.indexOf(word); at !== -1; at = plain.indexOf(word, at + 1)) for (let i = at; i < at + word.length; i++) marked[i] = true;
  for (let i = 0; i < label.length;) {
    let j = i;
    while (j < label.length && marked[j] === marked[i]) j++;
    out.append(marked[i] ? Object.assign(document.createElement('mark'), { textContent: label.slice(i, j) }) : label.slice(i, j));
    i = j;
  }
  return out;
}

function chooseFromSearch(person) {
  $('suggest').hidden = true;
  $('q').setAttribute('aria-expanded', 'false');
  $('q').value = '';
  void choosePerson(person.id);
}

async function choosePerson(id) {
  shown = id;
  focused = id;
  if (!await load() || shown !== id) return;
  map.select(id);
  map.focus(id);
  await showCard(id);
}

function suggest() {
  const query = $('q').value.trim();
  const list = $('suggest');
  list.replaceChildren();
  $('q').setAttribute('aria-expanded', String(Boolean(query)));
  list.hidden = !query;
  if (!query) return;
  const found = people.filter((p) => matches(query, p.label)).slice(0, 8);
  if (!found.length) {
    list.append(el('li', 'none', 'Personne ne correspond (seules les personnes nommées sur la carte sont cherchables).'));
    return;
  }
  for (const person of found) {
    const item = el('li');
    item.setAttribute('role', 'option');
    const button = el('button');
    button.type = 'button';
    const name = el('span', 'name');
    name.append(highlight(person.label, query));
    button.append(portrait(person.id, person.label, nodeColors.get(person.id), 26), name);
    button.onclick = () => chooseFromSearch(person);
    item.append(button);
    list.append(item);
  }
}

function searchKeys(event) {
  const buttons = [...$('suggest').querySelectorAll('button')];
  const at = buttons.indexOf(document.activeElement);
  if (event.key === 'ArrowDown') { event.preventDefault(); buttons[Math.min(at + 1, buttons.length - 1)]?.focus(); }
  else if (event.key === 'ArrowUp') { event.preventDefault(); if (at <= 0) $('q').focus(); else buttons[at - 1].focus(); }
  else if (event.key === 'Enter' && document.activeElement === $('q') && buttons[0]) { event.preventDefault(); buttons[0].click(); }
  else if (event.key === 'Escape' && !$('suggest').hidden) { event.preventDefault(); event.stopPropagation(); $('suggest').hidden = true; $('q').focus(); }
}

async function load() {
  const number = ++loadNumber;
  note('Chargement…');
  try {
    const data = await get(`/activity/map?${mapQuery()}`);
    if (number !== loadNumber) return false;
    map.load(data);
    drawKinds(data.meta.kinds_allowed ?? []);
    drawFilters(data.meta);
    people = data.nodes.filter((n) => n.label).sort((a, b) => b.influence - a.influence);
    for (const node of data.nodes) nodeColors.set(node.id, node.color || '#dbdee1');
    loader.show(data.nodes);
    $('reset').hidden = !($('period').value !== '30' || (kinds && kinds.size < (data.meta.kinds_allowed ?? []).length) || narrowed.weight !== '0' || narrowed.theme || narrowed.ideology);
    note(data.nodes.length ? `${data.nodes.length} personnes, ${data.edges.length} liens` : 'Rien à montrer pour cette période.');
    return true;
  } catch (error) {
    if (number === loadNumber) note(error.message);
    return false;
  }
}

async function start() {
  for (const [value, label] of Object.entries(PERIODS)) $('period').add(new Option(label, value, false, value === '30'));
  map = new MapGraph($('canvas'), {
    onSelect: (id) => (id ? void choosePerson(id) : closeCard()),
    onHover: () => {},
    imageProgram,
  });
  loader = pictureLoader(map, (path) => fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } }));
  pictures = loader.urls;
  $('q').addEventListener('input', suggest);
  $('q').addEventListener('focus', suggest);
  $('search').addEventListener('keydown', searchKeys);
  document.addEventListener('click', (event) => { if (!$('search').contains(event.target)) $('suggest').hidden = true; });
  document.addEventListener('keydown', (event) => {            // "/" goes to the search, as on the page of the interface
    if (event.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) { event.preventDefault(); $('q').focus(); }
  });
  $('fit').onclick = () => map.resetView();
  $('reset').onclick = () => {
    $('period').value = '30';
    kinds = null;
    Object.assign(narrowed, { weight: '0', theme: '', ideology: '' });
    filtersDrawn = '';
    shown = focused = null;
    $('card').hidden = true;
    map.select(null);
    void load().then(() => map.resetView());
  };
  $('period').onchange = () => { void load().then((loaded) => { if (loaded && shown) showCard(shown); }); };

  const { client_id: clientId } = await get('/activity/config');
  const sdk = new DiscordSDK(clientId);
  await sdk.ready();
  if (!sdk.guildId) return note('Lancez l’Activité depuis un salon vocal d’un serveur.');
  guild = sdk.guildId;
  const { code } = await sdk.commands.authorize({ client_id: clientId, response_type: 'code', state: '', prompt: 'none', scope: ['identify', 'guilds'] });
  const answer = await fetch(`${BASE}/activity/token`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
  if (!answer.ok) return note('Connexion à Discord refusée.');
  token = (await answer.json()).access_token;
  await sdk.commands.authenticate({ access_token: token });
  await load();
}

start().catch((error) => note(error?.message || 'Erreur'));
