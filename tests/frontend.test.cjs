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

test('preloaded teams wait for details and use new pool and restored filters exactly once', async () => {
    const h = setup();
    let resolveDetails;
    h.context.fetch = () => new Promise(resolve => { resolveDetails = resolve; });
    h.run(`
        selectedEvents.add('old');
        filteredMatches = [{id:'1',url:'/1',team_a:'A',team_b:'B',team_a_id:'1',team_b_id:'2'}];
        matchSelect.value='0';
        globalThis.analyses=[];
        runAnalysis=async()=>analyses.push({events:[...selectedEvents],pool:selectedMatch.map_pool});
        startLiveScorePolling=()=>{};
    `);
    const pending = h.run("handleMatchSelection(['8'])");
    assert.deepEqual(h.read('[...selectedEvents]'), []);
    assert.equal(h.read('analyses.length'), 0);
    resolveDetails(response({
        details: { team_a_id: '1', team_b_id: '2', team_a_name: 'A', team_b_name: 'B' },
        map_pool: ['Bind', 'Icebox'], team_a_events: [], team_b_events: [],
    }));
    await pending;
    assert.deepEqual(h.read('analyses'), [{ events: ['8'], pool: ['Bind', 'Icebox'] }]);
    assert.equal(h.read('selectedMatch.details_ready'), true);
    assert.equal(h.elements.get('tournament-checklist').querySelectorAll()[0].checked, true);
});

test('failed details keep analysis disabled even when IDs were preloaded', async () => {
    const h = setup();
    h.context.fetch = async () => ({ ok: false, status: 500 });
    h.run("filteredMatches=[{id:'1',url:'/1',team_a_id:'1',team_b_id:'2'}];matchSelect.value='0'");
    await h.run('handleMatchSelection()');
    assert.equal(h.read('analyzeBtn.disabled'), true);
    assert.equal(h.read('matchSelect.disabled'), false);
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
    h.run("selectedEvents.add('old');filteredMatches=[{id:'1',url:'/1',team_a_id:'1',team_b_id:'2'}];matchSelect.value='0'");
    await h.run("handleMatchSelection(['8'])");
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

test('shared match missing from current catalog is selected with its event filters', async () => {
    const h = setup('?match=123456&events=8,9');
    h.run("globalThis.restored=null;handleMatchSelection=async ids=>{restored={id:filteredMatches[matchSelect.value].id,ids};}");
    await h.run('restoreSharedSelection()');
    assert.deepEqual(h.read('restored'), { id: '123456', ids: ['8', '9'] });
    assert.equal(h.read('allMatches[0].url'), 'https://www.vlr.gg/123456');
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
