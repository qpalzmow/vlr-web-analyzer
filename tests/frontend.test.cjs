const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(search = '') {
    class Element {
        constructor(tag = 'div') {
            this.tag = tag;
            this.children = [];
            this.value = '';
            this.dataset = {};
            this.style = {};
            this.classList = { add() {}, remove() {} };
        }
        set innerHTML(value) {
            this.html = value;
            this.children = [];
            if (this.tag === 'select') this.value = '';
        }
        get innerHTML() { return this.html || ''; }
        appendChild(child) {
            this.children.push(child);
            if (this.tag === 'select' && child.tag === 'option' && !this.value) this.value = child.value;
        }
        addEventListener(name, callback) { this[name] = callback; }
        setAttribute() {}
        querySelector() { return null; }
        querySelectorAll() {
            const found = [];
            for (const child of this.children) {
                if (child.tag === 'input') found.push(child);
                if (child.querySelectorAll) found.push(...child.querySelectorAll());
            }
            return found;
        }
        replaceChildren(...children) { this.children = children; }
    }
    const elements = new Map();
    const timers = new Map();
    let nextTimer = 0;
    const context = {
        console: { log() {}, error() {} }, AbortController, URL, URLSearchParams,
        window: { location: { search, href: 'https://analyzer.test/' + search }, isSecureContext: true },
        navigator: { clipboard: { async writeText(text) { context.copied = text; } } },
        document: {
            hidden: false, body: new Element(),
            getElementById(id) {
                if (!elements.has(id)) elements.set(id, new Element(id.endsWith('-select') ? 'select' : 'div'));
                return elements.get(id);
            },
            createElement(tag) { return new Element(tag); },
            createTextNode(text) { return { text }; },
        },
        lucide: { createIcons() {} },
        setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
        clearTimeout(id) { timers.delete(id); },
        fetch: async () => { throw new Error('Unexpected fetch'); },
    };
    context.Chart = function (_canvas, config) { context.lastChart = config; this.destroy = () => {}; };
    vm.createContext(context);
    for (const file of ['constants.js', 'charts.js', 'ui.js', 'api.js']) {
        vm.runInContext(fs.readFileSync(path.join(__dirname, '../public', file), 'utf8'), context);
    }
    return {
        context, elements, timers,
        run: source => vm.runInContext(source, context),
        read: source => JSON.parse(vm.runInContext('JSON.stringify(' + source + ')', context)),
    };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const response = data => ({ ok: true, json: async () => data });

const readyMatch = (id = '1') => ({id, url: '/' + id, team_a: 'One', team_b: 'Two',
    tier: 'S-Tier', region: 'Global', tournament: 'Event',
    selection_data: {details: {team_a_id: '1', team_b_id: '2', event_id: '20'},
        team_a_events: [{id:'8',name:'Event Eight'}], team_b_events: [], map_pool: ['Bind','Icebox']}});

test('selection renders synchronously with zero network requests even with an old snapshot or missing pool', async () => {
    const h = setup();
    const match = readyMatch();
    match.selection_data.collected_at = '2020-01-01T00:00:00Z';
    match.selection_data.map_pool = [];
    h.context.match = match;
    h.run("filteredMatches=[match];matchSelect.value='0'");
    let requests = 0;
    h.context.fetch = async () => { requests++; throw new Error('Network forbidden'); };
    const task = h.run('handleMatchSelection()');
    assert.equal(h.read('selectedMatch.details_ready'), true);
    assert.equal(h.read('analyzeBtn.disabled'), false);
    assert.equal(h.elements.get('tournament-checklist').querySelectorAll().length, 1);
    await task;
    assert.equal(requests, 0);
    assert.equal(h.timers.size, 0);
});

test('a pending match never falls back to scraping even if legacy team IDs exist', async () => {
    const h = setup();
    h.run("filteredMatches=[{id:'1',url:'/1',team_a_id:'1',team_b_id:'2'}];matchSelect.value='0'");
    let requests = 0;
    h.context.fetch = async () => { requests++; throw new Error('Network forbidden'); };
    await h.run('handleMatchSelection()');
    assert.equal(requests, 0);
    assert.equal(h.read('analyzeBtn.disabled'), true);
    assert.match(h.elements.get('status-text').textContent, /업데이트 대기/);
});

test('manual selection does not analyze and switching matches clears old filters', async () => {
    const h = setup();
    h.context.matches = [readyMatch(),readyMatch('2')];
    h.run("filteredMatches=matches;matchSelect.value='0';globalThis.calls=0;runAnalysis=async()=>calls++");
    await h.run("handleMatchSelection(['8'])");
    assert.deepEqual(h.read('[...selectedEvents]'), ['8']);
    h.run("matchSelect.value='1'");
    await h.run('handleMatchSelection()');
    assert.deepEqual(h.read('[...selectedEvents]'), []);
    assert.equal(h.read('calls'), 0);
});

test('hourly snapshot refresh preserves active analysis and filters, updates other matches', async () => {
    const h = setup();
    h.run("tierSelect.value='All';regionSelect.value='All'");
    h.context.fetch = async () => response({generation:'one',updated_at:'2026-09-14T00:00:00Z',matches:[readyMatch(),readyMatch('2')]});
    await h.run('fetchMatches()');
    h.run("matchSelect.value='0'");
    await h.run("handleMatchSelection(['8'])");
    h.run('analysisRunning=true;analyzeBtn.disabled=true;globalThis.active=selectedMatch');
    const newer = readyMatch('2');
    newer.selection_data.team_a_events = [{id:'9',name:'New Event'}];
    h.context.fetch = async () => response({generation:'two',updated_at:'2026-09-14T01:00:00Z',matches:[readyMatch(),newer]});
    await h.run('fetchMatches(true)');
    assert.equal(h.read('selectedMatch===active'), true);
    assert.deepEqual(h.read('[...selectedEvents]'), ['8']);
    assert.equal(h.read('analysisRunning'), true);
    assert.equal(h.read('analyzeBtn.disabled'), true);
    h.run("matchSelect.value='1'");
    await h.run('handleMatchSelection()');
    assert.equal(h.read('teamAEvents[0].id'), '9');
});

test('first startup polls only the stored catalog until a generation is published', async () => {
    const h = setup();
    h.run("tierSelect.value='All';regionSelect.value='All'");
    const requests = [];
    h.context.fetch = async url => { requests.push(url); return response({generation:null,matches:[]}); };
    await h.run('fetchMatches()');
    assert.match(h.elements.get('status-text').textContent,/첫 경기 목록/);
    h.context.fetch = async url => { requests.push(url); return response({generation:'ready',matches:[readyMatch()]}); };
    const timer = [...h.timers.values()].find(t=>t.delay===60000);
    await timer.callback();
    assert.deepEqual(requests,['/api/catalog','/api/catalog']);
    assert.equal(h.read('allMatches.length'),1);
});

test('full selection pipeline sends the restored scope and actual map pool to analysis endpoints', async () => {
    const h = setup();
    const calls = [];
    const ace = { nickname: 'Player', acs: 200, kd_margin: 5, agents: ['Jett'] };
    h.context.fetch = async (url, options = {}) => {
        const body = options.body ? JSON.parse(options.body) : null;
        calls.push({ url, body });
        if (url.startsWith('/api/match-details')) return response({
            details: { team_a_id: '1', team_b_id: '2', team_a_name: 'One', team_b_name: 'Two' },
            map_pool: ['Bind', 'Icebox'], team_a_events: [{ id: '8', name: 'Event 8' }], team_b_events: [],
        });
        if (url.startsWith('/api/live-score')) return response({ status: 'final', series_score_a: '2', series_score_b: '1' });
        if (url === '/api/analyze/form') return response({ form_a: ['W (2-0)'], form_b: ['L (0-2)'] });
        if (url === '/api/analyze/maps') return response({ maps_a: {}, maps_b: {} });
        if (url === '/api/analyze/aces') return response({ ace_a: ace, ace_b: ace });
        if (url === '/api/analyze/advanced') return response({ adv_a: {}, adv_b: {} });
        if (url === '/api/simulate/banpick') return response({ bans: [], picks: [] });
        throw new Error('Unexpected request ' + url);
    };
    h.context.match = readyMatch();
    h.run("selectedEvents.add('old');filteredMatches=[match];matchSelect.value='0'");
    await h.run("handleMatchSelection(['8'], true)");
    const analysis = calls.filter(call => call.url.startsWith('/api/analyze/'));
    assert.equal(analysis.length, 4);
    for (const call of analysis) assert.deepEqual(call.body.event_ids, ['8']);
    assert.deepEqual(calls.find(call => call.url === '/api/simulate/banpick').body.map_pool, ['Bind', 'Icebox']);
    assert.equal(h.read('analysisRunning'), false);
    assert.equal(h.read('analyzeBtn.disabled'), false);
    assert.equal(h.elements.get('status-text').textContent, '전력 분석 완료.');
});

test('cache without score is fetched immediately and final score stops polling', async () => {
    const h = setup();
    let calls = 0;
    h.context.fetch = async () => { calls++; return response({ status: 'final', series_score_a: '2', series_score_b: '1', maps: [] }); };
    h.run("selectedMatch={url:'/1',live_score:null};startLiveScorePolling()");
    await flush();
    assert.equal(calls, 1);
    assert.equal(h.read('selectedMatch.live_score.status'), 'final');
    assert.equal(h.timers.size, 0);
});

test('upcoming transitions to live and retries errors without losing the last score', async () => {
    const h = setup();
    const scores = [
        { status: 'upcoming', series_score_a: '0', series_score_b: '0' },
        { status: 'live', series_score_a: '1', series_score_b: '0' },
        { status: 'error', series_score_a: '0', series_score_b: '0' },
    ];
    h.context.fetch = async () => response(scores.shift());
    h.run("selectedMatch={url:'/1',live_score:null};startLiveScorePolling()");
    await flush();
    let [id, timer] = [...h.timers][0];
    assert.equal(timer.delay, 60000);
    h.timers.delete(id);
    await timer.callback();
    assert.equal(h.read('selectedMatch.live_score.status'), 'live');
    [id, timer] = [...h.timers][0];
    h.timers.delete(id);
    await timer.callback();
    assert.equal(h.read('selectedMatch.live_score.series_score_a'), '1');
    assert.equal([...h.timers.values()][0].delay, 25000);
});

test('stopping an in-flight poll prevents a stale render and rescheduling', async () => {
    const h = setup();
    let finish;
    h.context.fetch = () => new Promise(resolve => { finish = resolve; });
    h.run("selectedMatch={url:'/1',live_score:null};startLiveScorePolling();stopLiveScorePolling()");
    finish(response({ status: 'live' }));
    await flush();
    assert.equal(h.read('selectedMatch.live_score'), null);
    assert.equal(h.timers.size, 0);
});

test('all-selection supports two disjoint twelve-event lists and caps longer shared lists', () => {
    const h = setup();
    h.run(`
        teamAEvents=Array.from({length:12},(_,i)=>({id:String(i+1),name:'Event '+i}));
        teamBEvents=Array.from({length:12},(_,i)=>({id:String(i+13),name:'Event '+i}));
        drawTournamentChecklist();
        document.getElementById('btn-filter-all').onclick();
    `);
    assert.equal(h.read('selectedEvents.size'), 24);
    h.run("setTournamentSelection(Array.from({length:25},(_,i)=>String(i+1)))");
    assert.equal(h.read('selectedEvents.size'), 24);
});

test('missing shared match waits for a published generation without a one-off scrape', async () => {
    const h = setup('?match=123456&events=8,9');
    h.run("globalThis.restored=null;handleMatchSelection=async ids=>{restored={id:filteredMatches[matchSelect.value].id,ids};}");
    await h.run('restoreSharedSelection()');
    assert.equal(h.read('restored'),null);
    assert.equal(h.read('allMatches.length'),0);
    h.context.match = readyMatch('123456');
    h.run('allMatches=[match]');
    await h.run('restoreSharedSelection()');
    assert.deepEqual(h.read('restored'), {id:'123456',ids:['8','9']});
});

test('invalid shared filters do not launch an analysis', async () => {
    const h = setup('?match=123456&events=oops');
    h.run("globalThis.calls=0;handleMatchSelection=async()=>calls++");
    await h.run('restoreSharedSelection()');
    assert.equal(h.read('calls'), 0);
});

test('sharing with no filters removes stale filters from the existing URL', async () => {
    const h = setup('?match=123&events=8');
    h.run("selectedMatch={id:'456',url:'/456'};selectedEvents.clear();generateShareableLink()");
    await flush();
    const url = new URL(h.context.copied);
    assert.equal(url.searchParams.get('match'), '456');
    assert.equal(url.searchParams.has('events'), false);
});

test('trend chart orders old to recent, aligns shorter histories, and does not invent missing form', () => {
    const h = setup();
    h.run("renderAcsTrendChart(['W (2-0)','L (0-2)'],['W (2-1)'])");
    const chart = h.context.lastChart;
    assert.deepEqual(JSON.parse(JSON.stringify(chart.data.labels)), ['2경기 전', '1경기 전']);
    assert.deepEqual(JSON.parse(JSON.stringify(chart.data.datasets[0].data)), [10, 100]);
    assert.deepEqual(JSON.parse(JSON.stringify(chart.data.datasets[1].data)), [null, 75]);
    h.run('renderAcsTrendChart([],[])');
    assert.equal(h.context.lastChart.data.datasets[0].data.length, 0);
});
