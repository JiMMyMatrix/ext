#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


PET_NAMES = [
    ("Mochi", "Corgi"),
    ("Nimbus", "Cat"),
    ("Bento", "Rabbit"),
    ("Pixel", "Parrot"),
    ("Maple", "Corgi"),
    ("Juniper", "Cat"),
    ("Pebble", "Hamster"),
    ("Soba", "Turtle"),
    ("Kumo", "Corgi"),
    ("Lychee", "Cat"),
    ("Taro", "Rabbit"),
    ("Fig", "Dog"),
]

MOODS = ["calm", "playful", "sleepy", "curious", "brave", "clingy", "proud"]
TAGS = [
    "walk",
    "meal",
    "training",
    "medicine",
    "grooming",
    "memory",
    "vet",
    "social",
    "sleep",
    "play",
]


def write_file(root: Path, rel_path: str, content: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def pet_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index, (name, species) in enumerate(PET_NAMES, start=1):
        records.append(
            {
                "id": f"pet-{index:02d}",
                "name": name,
                "species": species,
                "age": 1 + (index % 9),
                "favorite": TAGS[index % len(TAGS)],
                "color": ["sable", "cream", "tabby", "white", "black", "golden"][index % 6],
                "carePlan": [
                    f"Morning check-in for {name}",
                    f"Track food, mood, and energy for {name}",
                    f"Save one memory note for {name}",
                ],
            }
        )
    return records


def entry_records(count: int = 190) -> list[dict[str, object]]:
    pets = pet_records()
    records: list[dict[str, object]] = []
    for index in range(1, count + 1):
        pet = pets[(index - 1) % len(pets)]
        tag_a = TAGS[index % len(TAGS)]
        tag_b = TAGS[(index + 3) % len(TAGS)]
        mood = MOODS[index % len(MOODS)]
        records.append(
            {
                "id": f"entry-{index:03d}",
                "petId": pet["id"],
                "petName": pet["name"],
                "species": pet["species"],
                "date": f"2026-05-{((index - 1) % 28) + 1:02d}",
                "mood": mood,
                "tags": [tag_a, tag_b],
                "title": f"{pet['name']} {mood} diary note {index}",
                "body": (
                    f"{pet['name']} had a {mood} day with a focus on {tag_a}. "
                    f"The caregiver added a follow-up reminder for {tag_b}."
                ),
                "energy": (index % 5) + 1,
                "careMinutes": 10 + (index % 45),
            }
        )
    return records


def js_object_lines(name: str, rows: list[dict[str, object]]) -> list[str]:
    lines = [f"export const {name} = ["]
    for row in rows:
        lines.append("\t{")
        for key, value in row.items():
            lines.append(f"\t\t{key}: {json.dumps(value, ensure_ascii=True)},")
        lines.append("\t},")
    lines.append("];")
    return lines


def render_index() -> str:
    return """<!doctype html>
<html lang="en">
<head>
\t<meta charset="utf-8">
\t<meta name="viewport" content="width=device-width, initial-scale=1">
\t<title>Pet Life Diary</title>
\t<link rel="stylesheet" href="src/styles.css">
</head>
<body>
\t<div class="app-shell" data-app-shell>
\t\t<header class="hero-panel">
\t\t\t<p class="eyebrow">Pet Life Diary</p>
\t\t\t<h1>Remember the small care moments that make a pet's life visible.</h1>
\t\t\t<p class="hero-copy">A polished static demo for logging routines, moods, care tasks, and memories across multiple pets.</p>
\t\t\t<div class="hero-actions">
\t\t\t\t<button data-action="open-editor">Add diary entry</button>
\t\t\t\t<button class="secondary" data-action="export-data">Export data</button>
\t\t\t</div>
\t\t</header>

\t\t<nav class="tab-bar" aria-label="Diary sections">
\t\t\t<button class="tab is-active" data-view-target="dashboard">Dashboard</button>
\t\t\t<button class="tab" data-view-target="timeline">Timeline</button>
\t\t\t<button class="tab" data-view-target="pets">Pets</button>
\t\t\t<button class="tab" data-view-target="insights">Insights</button>
\t\t</nav>

\t\t<main>
\t\t\t<section id="view-dashboard" class="view is-active" data-view="dashboard">
\t\t\t\t<div class="section-heading">
\t\t\t\t\t<h2>Today at a glance</h2>
\t\t\t\t\t<p>Care rhythm, recent moods, and reminders collected in one quiet surface.</p>
\t\t\t\t</div>
\t\t\t\t<div class="metric-grid" data-metric-grid></div>
\t\t\t\t<div class="focus-grid">
\t\t\t\t\t<section class="panel">
\t\t\t\t\t\t<h3>Care reminders</h3>
\t\t\t\t\t\t<ul data-reminder-list></ul>
\t\t\t\t\t</section>
\t\t\t\t\t<section class="panel">
\t\t\t\t\t\t<h3>Favorite moments</h3>
\t\t\t\t\t\t<div data-highlight-list></div>
\t\t\t\t\t</section>
\t\t\t\t</div>
\t\t\t</section>

\t\t\t<section id="view-timeline" class="view" data-view="timeline">
\t\t\t\t<div class="section-heading inline">
\t\t\t\t\t<div>
\t\t\t\t\t\t<h2>Diary timeline</h2>
\t\t\t\t\t\t<p>Search, filter, and add entries without leaving the page.</p>
\t\t\t\t\t</div>
\t\t\t\t\t<div class="filter-row">
\t\t\t\t\t\t<label for="species-filter">Species</label>
\t\t\t\t\t\t<select id="species-filter" data-filter-species></select>
\t\t\t\t\t\t<label for="tag-filter">Tag</label>
\t\t\t\t\t\t<select id="tag-filter" data-filter-tag></select>
\t\t\t\t\t\t<input data-search placeholder="Search diary entries">
\t\t\t\t\t</div>
\t\t\t\t</div>
\t\t\t\t<div class="timeline-layout">
\t\t\t\t\t<section class="panel entry-composer" data-entry-composer>
\t\t\t\t\t\t<h3>Add entry</h3>
\t\t\t\t\t\t<form data-entry-form>
\t\t\t\t\t\t\t<label>Pet <select name="petId" data-pet-select></select></label>
\t\t\t\t\t\t\t<label>Title <input name="title" required></label>
\t\t\t\t\t\t\t<label>Mood <select name="mood" data-mood-select></select></label>
\t\t\t\t\t\t\t<label>Tags <input name="tags" placeholder="walk, meal"></label>
\t\t\t\t\t\t\t<label>Entry <textarea name="body" rows="5" required></textarea></label>
\t\t\t\t\t\t\t<button type="submit">Save diary entry</button>
\t\t\t\t\t\t</form>
\t\t\t\t\t</section>
\t\t\t\t\t<section class="entry-list" data-entry-list></section>
\t\t\t\t</div>
\t\t\t</section>

\t\t\t<section id="view-pets" class="view" data-view="pets">
\t\t\t\t<div class="section-heading">
\t\t\t\t\t<h2>Pet profiles</h2>
\t\t\t\t\t<p>Each profile keeps care habits, favorites, and recent diary notes together.</p>
\t\t\t\t</div>
\t\t\t\t<div class="pet-grid" data-pet-grid></div>
\t\t\t</section>

\t\t\t<section id="view-insights" class="view" data-view="insights">
\t\t\t\t<div class="section-heading">
\t\t\t\t\t<h2>Care insights</h2>
\t\t\t\t\t<p>Lightweight summaries show patterns without turning the diary into a dashboard.</p>
\t\t\t\t</div>
\t\t\t\t<div class="insight-grid" data-insight-grid></div>
\t\t\t\t<section class="panel import-export-panel">
\t\t\t\t\t<h3>Import and export</h3>
\t\t\t\t\t<p>Keep a local backup, restore sample data, or copy the current diary as JSON.</p>
\t\t\t\t\t<div class="button-row">
\t\t\t\t\t\t<button data-action="copy-json">Copy JSON</button>
\t\t\t\t\t\t<button class="secondary" data-action="reset-demo">Reset demo</button>
\t\t\t\t\t</div>
\t\t\t\t\t<textarea readonly data-json-preview></textarea>
\t\t\t\t</section>
\t\t\t</section>
\t\t</main>
\t</div>
\t<script type="module" src="src/app.js"></script>
</body>
</html>"""


def render_state_js() -> str:
    return """import { sampleEntries, samplePets } from './fixtures.js';

const STORAGE_KEY = 'pet-life-diary.product-demo.v1';

function clone(value) {
\treturn JSON.parse(JSON.stringify(value));
}

function initialState() {
\treturn {
\t\tpets: clone(samplePets),
\t\tentries: clone(sampleEntries),
\t\tfilters: {
\t\t\tspecies: 'all',
\t\t\ttag: 'all',
\t\t\tquery: '',
\t\t},
\t\tlastSavedAt: new Date().toISOString(),
\t};
}

export function loadState() {
\ttry {
\t\tconst raw = window.localStorage.getItem(STORAGE_KEY);
\t\tif (!raw) {
\t\t\treturn initialState();
\t\t}
\t\tconst parsed = JSON.parse(raw);
\t\treturn {
\t\t\t...initialState(),
\t\t\t...parsed,
\t\t\tfilters: {
\t\t\t\t...initialState().filters,
\t\t\t\t...(parsed.filters || {}),
\t\t\t},
\t\t};
\t} catch {
\t\treturn initialState();
\t}
}

export function saveState(state) {
\tstate.lastSavedAt = new Date().toISOString();
\twindow.localStorage.setItem(STORAGE_KEY, JSON.stringify(state, null, 2));
}

export function resetState() {
\tconst state = initialState();
\tsaveState(state);
\treturn state;
}

export function exportState(state) {
\treturn JSON.stringify(
\t\t{
\t\t\tschema: 'pet-life-diary.product-demo.v1',
\t\t\texportedAt: new Date().toISOString(),
\t\t\tpets: state.pets,
\t\t\tentries: state.entries,
\t\t},
\t\tnull,
\t\t2
\t);
}

export function createEntryId(entries) {
\tconst nextNumber = entries.length + 1;
\treturn `entry-user-${String(nextNumber).padStart(3, '0')}`;
}
"""


def render_entries_js() -> str:
    return """export const moods = ['calm', 'playful', 'sleepy', 'curious', 'brave', 'clingy', 'proud'];

export function normalizeTags(value) {
\treturn String(value || '')
\t\t.split(',')
\t\t.map((tag) => tag.trim().toLowerCase())
\t\t.filter(Boolean);
}

export function createEntryFromForm(form, pets, entries) {
\tconst formData = new FormData(form);
\tconst petId = String(formData.get('petId') || '');
\tconst pet = pets.find((candidate) => candidate.id === petId) || pets[0];
\tconst title = String(formData.get('title') || '').trim();
\tconst body = String(formData.get('body') || '').trim();
\tconst mood = String(formData.get('mood') || 'calm');
\tconst tags = normalizeTags(formData.get('tags'));
\tif (!title || !body) {
\t\tthrow new Error('Title and entry body are required.');
\t}
\treturn {
\t\tid: `entry-user-${String(entries.length + 1).padStart(3, '0')}`,
\t\tpetId: pet.id,
\t\tpetName: pet.name,
\t\tspecies: pet.species,
\t\tdate: new Date().toISOString().slice(0, 10),
\t\tmood,
\t\ttags: tags.length ? tags : ['memory'],
\t\ttitle,
\t\tbody,
\t\tenergy: 3,
\t\tcareMinutes: 15,
\t};
}

export function entryMatchesFilters(entry, filters) {
\tconst query = filters.query.trim().toLowerCase();
\tconst matchesSpecies = filters.species === 'all' || entry.species === filters.species;
\tconst matchesTag = filters.tag === 'all' || entry.tags.includes(filters.tag);
\tconst matchesQuery =
\t\t!query ||
\t\tentry.title.toLowerCase().includes(query) ||
\t\tentry.body.toLowerCase().includes(query) ||
\t\tentry.petName.toLowerCase().includes(query);
\treturn matchesSpecies && matchesTag && matchesQuery;
}

export function visibleEntries(state) {
\treturn state.entries
\t\t.filter((entry) => entryMatchesFilters(entry, state.filters))
\t\t.sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id));
}

export function uniqueTags(entries) {
\treturn [...new Set(entries.flatMap((entry) => entry.tags))].sort();
}
"""


def render_pets_js() -> str:
    return """export function entriesForPet(entries, petId) {
\treturn entries.filter((entry) => entry.petId === petId);
}

export function petSummary(pet, entries) {
\tconst petEntries = entriesForPet(entries, pet.id);
\tconst totalCareMinutes = petEntries.reduce((sum, entry) => sum + Number(entry.careMinutes || 0), 0);
\tconst favoriteTags = [...new Set(petEntries.flatMap((entry) => entry.tags))].slice(0, 4);
\tconst latestEntry = [...petEntries].sort((a, b) => b.date.localeCompare(a.date))[0];
\treturn {
\t\t...pet,
\t\tentryCount: petEntries.length,
\t\ttotalCareMinutes,
\t\tfavoriteTags,
\t\tlatestEntry,
\t};
}

export function speciesOptions(pets) {
\treturn ['all', ...new Set(pets.map((pet) => pet.species))];
}
"""


def render_analytics_js() -> str:
    return """export function calculateMetrics(state) {
\tconst entries = state.entries;
\tconst pets = state.pets;
\tconst careMinutes = entries.reduce((sum, entry) => sum + Number(entry.careMinutes || 0), 0);
\tconst averageEnergy =
\t\tentries.length === 0
\t\t\t? 0
\t\t\t: entries.reduce((sum, entry) => sum + Number(entry.energy || 0), 0) / entries.length;
\tconst moodCounts = entries.reduce((counts, entry) => {
\t\tcounts[entry.mood] = (counts[entry.mood] || 0) + 1;
\t\treturn counts;
\t}, {});
\tconst topMood = Object.entries(moodCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || 'calm';
\treturn [
\t\t{ label: 'Pets tracked', value: pets.length, detail: 'Active profiles' },
\t\t{ label: 'Diary entries', value: entries.length, detail: 'Saved memories' },
\t\t{ label: 'Care minutes', value: careMinutes, detail: 'Across sample data' },
\t\t{ label: 'Average energy', value: averageEnergy.toFixed(1), detail: `Most common mood: ${topMood}` },
\t];
}

export function insightsForState(state) {
\tconst bySpecies = state.entries.reduce((counts, entry) => {
\t\tcounts[entry.species] = (counts[entry.species] || 0) + 1;
\t\treturn counts;
\t}, {});
\tconst byTag = state.entries.reduce((counts, entry) => {
\t\tfor (const tag of entry.tags) {
\t\t\tcounts[tag] = (counts[tag] || 0) + 1;
\t\t}
\t\treturn counts;
\t}, {});
\treturn [
\t\t{
\t\t\ttitle: 'Species coverage',
\t\t\tbody: Object.entries(bySpecies)
\t\t\t\t.map(([species, count]) => `${species}: ${count}`)
\t\t\t\t.join(' | '),
\t\t},
\t\t{
\t\t\ttitle: 'Common care themes',
\t\t\tbody: Object.entries(byTag)
\t\t\t\t.sort((a, b) => b[1] - a[1])
\t\t\t\t.slice(0, 6)
\t\t\t\t.map(([tag, count]) => `${tag}: ${count}`)
\t\t\t\t.join(' | '),
\t\t},
\t\t{
\t\t\ttitle: 'Readiness',
\t\t\tbody: 'The demo is fully static, uses local storage, and can be shown without a build step.',
\t\t},
\t];
}
"""


def render_storage_js() -> str:
    return """export async function copyText(value) {
\tif (navigator.clipboard?.writeText) {
\t\tawait navigator.clipboard.writeText(value);
\t\treturn true;
\t}
\treturn false;
}

export function downloadJson(filename, value) {
\tconst blob = new Blob([value], { type: 'application/json' });
\tconst url = URL.createObjectURL(blob);
\tconst link = document.createElement('a');
\tlink.href = url;
\tlink.download = filename;
\tdocument.body.appendChild(link);
\tlink.click();
\tlink.remove();
\tURL.revokeObjectURL(url);
}
"""


def render_ui_js() -> str:
    return """import { calculateMetrics, insightsForState } from './analytics.js';
import { createEntryFromForm, moods, uniqueTags, visibleEntries } from './entries.js';
import { entriesForPet, petSummary, speciesOptions } from './pets.js';
import { copyText, downloadJson } from './storage.js';
import { exportState, resetState, saveState } from './state.js';

function text(value) {
\treturn document.createTextNode(String(value));
}

function clear(node) {
\tnode.replaceChildren();
}

function el(tagName, className, children = []) {
\tconst node = document.createElement(tagName);
\tif (className) {
\t\tnode.className = className;
\t}
\tfor (const child of children) {
\t\tnode.append(child instanceof Node ? child : text(child));
\t}
\treturn node;
}

function option(value, label = value) {
\tconst node = document.createElement('option');
\tnode.value = value;
\tnode.textContent = label;
\treturn node;
}

export function bindNavigation(render) {
\tdocument.querySelectorAll('[data-view-target]').forEach((button) => {
\t\tbutton.addEventListener('click', () => {
\t\t\tconst target = button.dataset.viewTarget;
\t\t\tdocument.querySelectorAll('[data-view]').forEach((view) => {
\t\t\t\tview.classList.toggle('is-active', view.dataset.view === target);
\t\t\t});
\t\t\tdocument.querySelectorAll('[data-view-target]').forEach((tab) => {
\t\t\t\ttab.classList.toggle('is-active', tab === button);
\t\t\t});
\t\t\trender();
\t\t});
\t});
}

export function renderMetrics(state) {
\tconst grid = document.querySelector('[data-metric-grid]');
\tif (!grid) return;
\tclear(grid);
\tfor (const metric of calculateMetrics(state)) {
\t\tgrid.append(
\t\t\tel('article', 'metric-card', [
\t\t\t\tel('span', 'metric-label', [metric.label]),
\t\t\t\tel('strong', 'metric-value', [metric.value]),
\t\t\t\tel('small', 'metric-detail', [metric.detail]),
\t\t\t])
\t\t);
\t}
}

export function renderTimeline(state) {
\tconst list = document.querySelector('[data-entry-list]');
\tif (!list) return;
\tclear(list);
\tconst entries = visibleEntries(state);
\tfor (const entry of entries.slice(0, 60)) {
\t\tconst card = el('article', 'entry-card');
\t\tcard.append(el('p', 'entry-meta', [`${entry.date} | ${entry.petName} | ${entry.mood}`]));
\t\tcard.append(el('h3', '', [entry.title]));
\t\tcard.append(el('p', '', [entry.body]));
\t\tcard.append(el('div', 'tag-row', entry.tags.map((tag) => el('span', 'tag', [tag]))));
\t\tlist.append(card);
\t}
\tif (entries.length === 0) {
\t\tlist.append(el('p', 'empty-state', ['No entries match the current filters.']));
\t}
}

export function renderPets(state) {
\tconst grid = document.querySelector('[data-pet-grid]');
\tif (!grid) return;
\tclear(grid);
\tfor (const pet of state.pets.map((candidate) => petSummary(candidate, state.entries))) {
\t\tconst card = el('article', 'pet-card');
\t\tcard.append(el('p', 'entry-meta', [pet.species]));
\t\tcard.append(el('h3', '', [pet.name]));
\t\tcard.append(el('p', '', [`${pet.entryCount} entries | ${pet.totalCareMinutes} care minutes`]));
\t\tcard.append(el('p', '', [`Favorite: ${pet.favorite} | Color: ${pet.color}`]));
\t\tcard.append(el('div', 'tag-row', pet.favoriteTags.map((tag) => el('span', 'tag', [tag]))));
\t\tif (pet.latestEntry) {
\t\t\tcard.append(el('p', 'latest-note', [`Latest: ${pet.latestEntry.title}`]));
\t\t}
\t\tgrid.append(card);
\t}
}

export function renderInsights(state) {
\tconst grid = document.querySelector('[data-insight-grid]');
\tconst preview = document.querySelector('[data-json-preview]');
\tif (grid) {
\t\tclear(grid);
\t\tfor (const insight of insightsForState(state)) {
\t\t\tgrid.append(el('article', 'insight-card', [el('h3', '', [insight.title]), el('p', '', [insight.body])]));
\t\t}
\t}
\tif (preview) {
\t\tpreview.value = exportState(state);
\t}
}

export function renderReminders(state) {
\tconst list = document.querySelector('[data-reminder-list]');
\tconst highlights = document.querySelector('[data-highlight-list]');
\tif (list) {
\t\tclear(list);
\t\tfor (const pet of state.pets.slice(0, 8)) {
\t\t\tlist.append(el('li', '', [`${pet.name}: ${pet.carePlan[0]}`]));
\t\t}
\t}
\tif (highlights) {
\t\tclear(highlights);
\t\tfor (const entry of state.entries.slice(0, 5)) {
\t\t\thighlights.append(el('p', 'highlight-line', [`${entry.petName}: ${entry.title}`]));
\t\t}
\t}
}

export function renderFilters(state, render) {
\tconst species = document.querySelector('[data-filter-species]');
\tconst tag = document.querySelector('[data-filter-tag]');
\tconst search = document.querySelector('[data-search]');
\tif (species && species.childElementCount === 0) {
\t\tfor (const value of speciesOptions(state.pets)) {
\t\t\tspecies.append(option(value, value === 'all' ? 'All species' : value));
\t\t}
\t\tspecies.addEventListener('change', () => {
\t\t\tstate.filters.species = species.value;
\t\t\tsaveState(state);
\t\t\trender();
\t\t});
\t}
\tif (tag && tag.childElementCount === 0) {
\t\tfor (const value of ['all', ...uniqueTags(state.entries)]) {
\t\t\ttag.append(option(value, value === 'all' ? 'All tags' : value));
\t\t}
\t\ttag.addEventListener('change', () => {
\t\t\tstate.filters.tag = tag.value;
\t\t\tsaveState(state);
\t\t\trender();
\t\t});
\t}
\tif (search && !search.dataset.bound) {
\t\tsearch.dataset.bound = 'true';
\t\tsearch.addEventListener('input', () => {
\t\t\tstate.filters.query = search.value;
\t\t\tsaveState(state);
\t\t\trender();
\t\t});
\t}
\tif (species) species.value = state.filters.species;
\tif (tag) tag.value = state.filters.tag;
\tif (search) search.value = state.filters.query;
}

export function renderComposer(state, render) {
\tconst petSelect = document.querySelector('[data-pet-select]');
\tconst moodSelect = document.querySelector('[data-mood-select]');
\tconst form = document.querySelector('[data-entry-form]');
\tif (petSelect && petSelect.childElementCount === 0) {
\t\tfor (const pet of state.pets) {
\t\t\tpetSelect.append(option(pet.id, `${pet.name} (${pet.species})`));
\t\t}
\t}
\tif (moodSelect && moodSelect.childElementCount === 0) {
\t\tfor (const mood of moods) {
\t\t\tmoodSelect.append(option(mood));
\t\t}
\t}
\tif (form && !form.dataset.bound) {
\t\tform.dataset.bound = 'true';
\t\tform.addEventListener('submit', (event) => {
\t\t\tevent.preventDefault();
\t\t\ttry {
\t\t\t\tconst entry = createEntryFromForm(form, state.pets, state.entries);
\t\t\t\tstate.entries.unshift(entry);
\t\t\t\tsaveState(state);
\t\t\t\tform.reset();
\t\t\t\trender();
\t\t\t} catch (error) {
\t\t\t\twindow.alert(error instanceof Error ? error.message : 'Could not save entry.');
\t\t\t}
\t\t});
\t}
}

export function bindActions(state, render) {
\tdocument.querySelector('[data-action="open-editor"]')?.addEventListener('click', () => {
\t\tdocument.querySelector('[data-view-target="timeline"]')?.click();
\t\tdocument.querySelector('[data-entry-form] input[name="title"]')?.focus();
\t});
\tdocument.querySelector('[data-action="export-data"]')?.addEventListener('click', () => {
\t\tdownloadJson('pet-life-diary-export.json', exportState(state));
\t});
\tdocument.querySelector('[data-action="copy-json"]')?.addEventListener('click', async () => {
\t\tawait copyText(exportState(state));
\t});
\tdocument.querySelector('[data-action="reset-demo"]')?.addEventListener('click', () => {
\t\tconst reset = resetState();
\t\tObject.assign(state, reset);
\t\trender();
\t});
}

export function renderAll(state) {
\trenderMetrics(state);
\trenderTimeline(state);
\trenderPets(state);
\trenderInsights(state);
\trenderReminders(state);
}
"""


def render_app_js() -> str:
    return """import { loadState } from './state.js';
import {
\tbindActions,
\tbindNavigation,
\trenderAll,
\trenderComposer,
\trenderFilters,
} from './ui.js';

const state = loadState();

function render() {
\trenderFilters(state, render);
\trenderComposer(state, render);
\trenderAll(state);
}

bindNavigation(render);
bindActions(state, render);
render();
"""


def render_styles() -> str:
    lines = [
        ":root {",
        "\t--bg: #f7f2ea;",
        "\t--ink: #28231f;",
        "\t--muted: #756c63;",
        "\t--card: #fffaf2;",
        "\t--line: #e2d6c6;",
        "\t--accent: #bb6b3d;",
        "\t--accent-strong: #8b3f24;",
        "\t--shadow: 0 20px 60px rgba(61, 44, 28, 0.14);",
        "}",
        "* { box-sizing: border-box; }",
        "body { margin: 0; font-family: ui-rounded, Georgia, serif; background: var(--bg); color: var(--ink); }",
        "button, input, select, textarea { font: inherit; }",
        "button { border: 0; border-radius: 999px; padding: 0.8rem 1.15rem; background: var(--accent); color: white; cursor: pointer; }",
        "button.secondary { background: transparent; color: var(--accent-strong); border: 1px solid var(--line); }",
        ".app-shell { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 56px; }",
        ".hero-panel { padding: 56px; border-radius: 40px; background: linear-gradient(135deg, #fffaf2, #f4dfc6); box-shadow: var(--shadow); }",
        ".hero-panel h1 { max-width: 780px; font-size: clamp(2.3rem, 6vw, 5rem); line-height: 0.95; margin: 0; }",
        ".hero-copy { max-width: 650px; color: var(--muted); font-size: 1.15rem; }",
        ".eyebrow { letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent-strong); font-weight: 700; }",
        ".hero-actions, .button-row, .filter-row, .tag-row { display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: center; }",
        ".tab-bar { display: flex; gap: 0.5rem; margin: 28px 0; padding: 8px; border: 1px solid var(--line); border-radius: 999px; background: rgba(255,255,255,0.45); }",
        ".tab { background: transparent; color: var(--muted); }",
        ".tab.is-active { background: var(--ink); color: white; }",
        ".view { display: none; }",
        ".view.is-active { display: block; }",
        ".section-heading { margin: 32px 0 18px; }",
        ".section-heading.inline { display: flex; justify-content: space-between; gap: 1rem; align-items: end; }",
        ".metric-grid, .focus-grid, .pet-grid, .insight-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }",
        ".timeline-layout { display: grid; grid-template-columns: minmax(260px, 360px) 1fr; gap: 18px; align-items: start; }",
        ".panel, .metric-card, .entry-card, .pet-card, .insight-card { background: var(--card); border: 1px solid var(--line); border-radius: 28px; padding: 22px; box-shadow: 0 10px 28px rgba(61,44,28,0.07); }",
        ".metric-label, .entry-meta, .metric-detail { color: var(--muted); }",
        ".metric-value { display: block; font-size: 2rem; margin: 0.35rem 0; }",
        ".entry-list { display: grid; gap: 14px; }",
        ".entry-card h3, .pet-card h3, .insight-card h3 { margin-top: 0; }",
        ".tag { display: inline-flex; padding: 0.35rem 0.65rem; border-radius: 999px; background: #f1e2cf; color: var(--accent-strong); }",
        "form { display: grid; gap: 0.9rem; }",
        "label { display: grid; gap: 0.35rem; color: var(--muted); }",
        "input, select, textarea { width: 100%; border: 1px solid var(--line); border-radius: 16px; padding: 0.8rem; background: white; color: var(--ink); }",
        "textarea[data-json-preview] { min-height: 200px; font-family: ui-monospace, SFMono-Regular, monospace; font-size: 0.82rem; }",
        ".empty-state, .latest-note, .highlight-line { color: var(--muted); }",
        "@media (max-width: 800px) {",
        "\t.hero-panel { padding: 30px; }",
        "\t.timeline-layout { grid-template-columns: 1fr; }",
        "\t.section-heading.inline { align-items: stretch; flex-direction: column; }",
        "\t.tab-bar { overflow-x: auto; border-radius: 26px; }",
        "}",
    ]
    for index in range(1, 121):
        tone = index % 8
        lines.extend(
            [
                f".mood-tone-{index:03d} {{",
                f"\t--tone-hue: {24 + tone * 18};",
                f"\tbackground: hsl(var(--tone-hue) 72% {92 - (tone % 4)}%);",
                f"\tborder-color: hsl(var(--tone-hue) 38% {78 - (tone % 5)}%);",
                "}",
            ]
        )
    return "\n".join(lines)


def render_readme() -> str:
    return """# Pet Life Diary Product Demo

Pet Life Diary is a static, dependency-free care journal demo. It is intentionally larger than the smoke-test app so Corgi can prove that Executor work, Reviewer validation, and Governor acceptance still behave correctly when a project resembles a small real product.

## Product surface

- Dashboard with care metrics, reminders, and highlighted memories.
- Timeline with species, tag, and search filters.
- Entry composer that appends new diary notes and persists them to local storage.
- Pet profiles with care-plan summaries.
- Insights view with simple analytics and local JSON export.

## Files

- `index.html` defines the product shell and views.
- `src/app.js` boots the demo.
- `src/state.js` owns local persistence.
- `src/ui.js` renders the main interface and input flows.
- `src/entries.js`, `src/pets.js`, `src/analytics.js`, and `src/storage.js` keep product logic separate.
- `src/fixtures.js` and `data/*.json` provide a substantial sample dataset.
- `tests/product-validation.js` documents the behavioral checks used by the benchmark.

## Run

Open `index.html` in a browser. No build step is required.
"""


def render_product_validation_js() -> str:
    return """// Static validation notes for the Corgi product benchmark.
// The Python validator checks these surfaces after Executor writes files.
export const expectedSurfaces = [
\t'app shell',
\t'local storage',
\t'entry creation',
\t'species filtering',
\t'tag filtering',
\t'search',
\t'analytics',
\t'import export',
];

export function validationChecklist() {
\treturn expectedSurfaces.map((surface) => ({
\t\tsurface,
\t\tstatus: 'covered',
\t}));
}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--dispatch-ref", required=True)
    parser.add_argument("--objective", default="")
    parser.add_argument("--accepted-intake", default="")
    args = parser.parse_args()

    root = Path(args.repo_root)
    pets = pet_records()
    entries = entry_records()

    fixture_lines = [
        "// Product-scale sample data for the Pet Life Diary benchmark.",
        "// Generated by the Executor helper so authorship evidence can prove file creation.",
        "",
        *js_object_lines("samplePets", pets),
        "",
        *js_object_lines("sampleEntries", entries),
    ]

    write_file(root, "README.md", render_readme())
    write_file(root, "index.html", render_index())
    write_file(root, "src/app.js", render_app_js())
    write_file(root, "src/state.js", render_state_js())
    write_file(root, "src/entries.js", render_entries_js())
    write_file(root, "src/pets.js", render_pets_js())
    write_file(root, "src/analytics.js", render_analytics_js())
    write_file(root, "src/storage.js", render_storage_js())
    write_file(root, "src/ui.js", render_ui_js())
    write_file(root, "src/fixtures.js", "\n".join(fixture_lines))
    write_file(root, "src/styles.css", render_styles())
    write_file(root, "data/sample-pets.json", json.dumps(pets, indent=2, ensure_ascii=True))
    write_file(root, "data/sample-entries.json", json.dumps(entries, indent=2, ensure_ascii=True))
    write_file(root, "tests/product-validation.js", render_product_validation_js())


if __name__ == "__main__":
    main()
