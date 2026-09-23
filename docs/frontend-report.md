# Frontend report layout

## Dependency review

Before redesigning the markup, `index.html`, `constants.js`, `ui.js`, `api.js`,
`charts.js`, `app.js`, the theme overrides and frontend regression tests were read.
The catalog and analysis response schemas were checked for available fields.
There are no team logos in those contracts; the report therefore uses team names.

`constants.js` owns selection state and captures filter/status DOM references.
`app.js` binds user interactions. `api.js` restores shared URLs, reads the stored
catalog, submits the single analysis request, and polls live scores. `ui.js`
groups tournaments and renders response data. These responsibilities and API
contracts remain unchanged.

The existing control, status, player and live-score IDs are retained. Theme
switch IDs are removed with the old theme. The following destinations changed
element type intentionally; their API-facing rendering functions were adapted:

| ID | Old element | New destination |
| --- | --- | --- |
| `team-a-maps-table`, `team-b-maps-table` | Separate table bodies | Team column-group headings in a shared table |
| `career-acs-chart` | Canvas | Career player table |
| `acs-trend-chart` | Canvas | Latest-first recent-match table body |
| `match-selection-panel` | Section | Native details disclosure |

`renderMapsTable` now updates a pair of map datasets and renders one union of map
names; absent team/round records stay missing instead of becoming 0%.
`charts.js` retains its entry-point names for the existing analysis pipeline but
has no Chart.js dependency. Exact ACS values belong in the player table. Recent
results preserve actual outcomes, opponents and scores rather than inventing a
numeric momentum scale. A short form history is not padded with fake matches.

## Design and interaction

One graphite palette, off-white text, muted gray metadata, two desaturated team
colors, and win/loss colors. `report.css` replaces Tailwind and all iOS overrides;
there is no persisted theme preference or theme switch. System fonts, 12px
minimum metadata, 14px body/table text, 18px section headings, 24–32px team names.
Separators and whitespace establish sections; backgrounds belong to controls.

The initial view prioritizes tournament, match, then analysis. Tournament family,
tier and region sit in a secondary disclosure; record checkboxes and quick
filters are in a separate, initially closed disclosure. Native labeled selects
preserve optgroups and unavailable-match options.

Successful analysis collapses the chooser and moves keyboard focus to the report.
Overview, Maps, Players and Form are anchor sections, so all data is available to
keyboard navigation and image export without hidden tabs. Share/export actions
are visible only for a completed report. The header summary shows **historical
map win rates**, not predictions. The optional reference indicator still accepts
API-provided values; null/invalid values remain hidden.

Map-filter labels and share URLs use the completed request's filter snapshot.
Editing filters before reanalysis therefore cannot silently change the meaning
of an existing report or its shared link. Stale/partial/unavailable data remains
explicit in status, player coverage and exported notes. Unknown event map pools
are labeled as using the default pool.

Tables scroll within their regions on small screens; the team summary remains
side by side. Controls/links have 44px targets. Focus-visible outlines, table
headers, live status announcements, reduced-motion support, wrap-safe names and
native disclosures replace decorative icon controls.

Image export captures only the report at 1120px, restores full table columns in
the cloned document, and excludes selection/navigation controls. The export
library loads asynchronously and does not block application initialization.
Export failure restores the button and supports retry.

## Verification

- 40 frontend regression tests: selection, tournament grouping, filters, shared
  restore, one analysis request, stale response rejection, live polling, career
  values/coverage, comparison rows, missing data, escaping, report states and
  export clone/error handling.
- 122 Python tests, including real HTML ID contracts, label/anchor destinations
  and static asset delivery.
- Local jsdom integration against the preview API and real HTML: Nongshim
  RedForce vs NRG, 13 aligned map rows, five recent matches, Dambi ACS 229.8 and
  5,771 rounds, 5/6 roster coverage, one analysis request, actual checkbox quick
  filters, keyboard focus transfer and no DOM errors. The live-score response
  was stubbed in this integration check to avoid upstream scraping; polling has
  separate regression coverage.
- Second source cleanup removed repeated status prose from the top of the
  report, fixed long player/team header wrapping and documented fallback pools.

**Outstanding visual verification:** the browser-control environment returned no
available browsers, including the in-app and Chrome entry points. Actual
390/768/1280/1440px screenshots, 320px overflow inspection, and the rendered PNG
have not been inspected. DOM tests and CSS review are not substitutes for those
checks. The local preview is at `http://127.0.0.1:8770` while the preview process
is running.
