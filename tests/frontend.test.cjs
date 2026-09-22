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
    context.chartDestroyCount = 0;
    context.Chart = function (_canvas, config) {
        context.lastChart = config;
        this.destroy = () => { context.chartDestroyCount++; };
    };
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

test('reselecting a match uses the newest pool while the active report keeps its snapshot', async () => {
    const h=setup();
    h.run("tierSelect.value='All';regionSelect.value='All'");
    h.context.fetch=async()=>response({generation:'old',matches:[readyMatch()]});
    await h.run('fetchMatches()');
    h.run("matchSelect.value='0'");await h.run('handleMatchSelection()');
    h.run('globalThis.prior=selectedMatch;analysisRunning=true');
    const fresh=readyMatch();fresh.selection_data.map_pool=['Abyss'];
    fresh.selection_data.team_a_events=[{id:'10',name:'New'}];
    h.context.fetch=async()=>response({generation:'new',matches:[fresh]});
    await h.run('fetchMatches(true)');
    assert.equal(h.read('selectedMatch===prior'),true);
    assert.deepEqual(h.read('selectedMatch.map_pool'),['Bind','Icebox']);
    h.run("matchSelect.value='0'");await h.run('handleMatchSelection()');
    assert.deepEqual(h.read('selectedMatch.map_pool'),['Abyss']);
    assert.equal(h.read('teamAEvents[0].id'),'10');
});

test('career ACS chart preserves raw values and a zero baseline without saturation', () => {
    const h=setup();
    h.run("renderCareerAcsChart({nickname:'GSR',acs:238.8,kd_margin:773,available:true},{nickname:'Jinggg',acs:239.0,kd_margin:1631,available:true})");
    const chart = h.context.lastChart;
    assert.equal(chart.type, 'bar');
    assert.equal(chart.options.indexAxis, 'y');
    assert.equal(chart.options.scales.x.beginAtZero, true);
    assert.equal(chart.options.scales.x.min, 0);
    assert.equal(chart.options.scales.x.max, undefined);
    assert.deepEqual(h.read('lastChart.data.datasets[0].data'), [238.8, 239.0]);
    assert.deepEqual(h.read('lastChart.data.labels'), ['Team A · GSR', 'Team B · Jinggg']);
    assert.equal(chart.options.plugins.tooltip.callbacks.label({raw:239}), '커리어 ACS: 239.0');
    assert.equal(h.elements.get('career-acs-empty').hidden, true);
});

test('missing player data clears the prior chart and cannot become a synthetic zero bar', () => {
    const h=setup();
    h.run("renderCareerAcsChart({nickname:'Player',acs:200,available:true},{nickname:'N/A',acs:0,available:false})");
    assert.deepEqual(h.read('lastChart.data.datasets[0].data'), [200]);
    h.run("renderCareerAcsChart({nickname:'N/A',acs:null,available:false},null)");
    assert.equal(h.read('careerAcsChartInstance'), null);
    assert.equal(h.context.chartDestroyCount, 1);
    assert.equal(h.elements.get('career-acs-chart').hidden, true);
    assert.equal(h.elements.get('career-acs-empty').hidden, false);
    assert.equal(h.elements.get('career-acs-empty').textContent, '확인 가능한 현역 선수 기록 없음');
});

test('unavailable player cards show missing values instead of zero', () => {
    const h=setup();
    h.run("populateAceCard('a',{nickname:'N/A',acs:null,kd_margin:null,agents:[],available:false})");
    assert.equal(h.elements.get('ace-a-acs').textContent,'—');
    assert.equal(h.elements.get('ace-a-kd').textContent,'—');
    assert.equal(h.elements.get('ace-a-kd-ratio').textContent,'—');
    assert.equal(h.elements.get('ace-a-rounds').textContent,'—');
    assert.equal(h.elements.get('ace-a-coverage').textContent,'확인 가능한 현역 선수 기록 없음');
});

test('partial roster comparison displays actual statistics, coverage, and missing names', () => {
    const h=setup();
    h.context.ace = {...careerPlayer('Rb'), acs:219.3, kd_margin:753, kd_ratio:1.1648,
        rounds:9012, partial:true, roster_size:6, players_with_stats:5, missing_players:['WoohyuN']};
    h.run("populateAceCard('a',ace)");
    assert.equal(h.elements.get('ace-a-acs').textContent, '219.3');
    assert.equal(h.elements.get('ace-a-kd').textContent, '+753');
    assert.equal(h.elements.get('ace-a-kd-ratio').textContent, '1.16');
    assert.equal(h.elements.get('ace-a-rounds').textContent, '9,012');
    assert.equal(h.elements.get('ace-a-coverage').textContent, '기록 있는 현역 5/6명 기준 · 기록 없음: WoohyuN');
    assert.match(h.elements.get('ace-a-collected').textContent, /수집 기준/);
});

test('clearing comparison removes old metrics, coverage, timestamp, agents, and chart', () => {
    const h=setup();
    h.context.ace=careerPlayer('Previous');
    h.run("populateAceCard('a',ace);renderCareerAcsChart(ace,null);clearAceCompare()");
    for (const field of ['nickname','acs','kd','kd-ratio','rounds']) {
        assert.equal(h.elements.get(`ace-a-${field}`).textContent,'—');
    }
    assert.equal(h.elements.get('ace-a-coverage').textContent,'전력 분석 후 커리어를 표시합니다.');
    assert.equal(h.elements.get('ace-a-collected').textContent,'');
    assert.equal(h.elements.get('ace-a-agents').children.length,0);
    assert.equal(h.read('careerAcsChartInstance'),null);
    assert.equal(h.elements.get('career-acs-chart').hidden,true);
});

test('stale and unavailable statistics are both explained', async () => {
    const h=setup();h.context.match=readyMatch();
    h.run("filteredMatches=[match];matchSelect.value='0';startLiveScorePolling=()=>{}");
    h.context.fetch=async()=>response({...analysisResult(),stale:true,players_available:false,probability:null,
        ace_b:{nickname:'N/A',acs:null,available:false,agents:[],unavailable_reason:'roster_unverified'}});
    await h.run("handleMatchSelection(['8'],true)");
    assert.match(h.elements.get('sub-status-text').textContent,/갱신 지연/);
    assert.match(h.elements.get('sub-status-text').textContent,/미표시/);
    assert.match(h.elements.get('sub-status-text').textContent,/Two:/);
    assert.doesNotMatch(h.elements.get('sub-status-text').textContent,/One:/);
    assert.equal(h.elements.get('ace-a-nickname').textContent,'Player A');
    assert.equal(h.elements.get('ace-b-coverage').textContent,'현역 선수 명단을 확인할 수 없어 비교 불가');
    assert.deepEqual(h.read('lastChart.data.datasets[0].data'),[220]);
});

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

const careerPlayer = (nickname, acs=220) => ({
    nickname, acs, kd_margin:5, kd_ratio:1.25, rounds:100, kills:25, deaths:20,
    agents:['Jett'], available:true, partial:false, roster_size:5, players_with_stats:5,
    missing_players:[], unavailable_reason:null, scope:'career', collected_at:'2026-09-15T00:00:00Z'
});
const analysisResult = () => ({
    form_a:['W (2-0)'],form_b:['L (0-2)'],maps_a:{},maps_b:{},
    ace_a:careerPlayer('Player A'),
    ace_b:careerPlayer('Player B',200),
    adv_a:{},adv_b:{},simulation:{bans:[],picks:[]},probability:{a:55,b:45},
    updated_at:'2026-09-15T00:00:00Z',stale:false,players_available:true
});

test('one analysis request sends filters and pool and paints every panel together', async () => {
    const h=setup();
    const calls=[];
    h.context.match=readyMatch();
    h.run("filteredMatches=[match];matchSelect.value='0';startLiveScorePolling=()=>{}");
    h.context.fetch=async (url,options)=>{calls.push({url,body:JSON.parse(options.body)});return response(analysisResult());};
    await h.run("handleMatchSelection(['8'],true)");
    assert.equal(calls.length,1);
    assert.equal(calls[0].url,'/api/analyze');
    assert.deepEqual(calls[0].body.event_ids,['8']);
    assert.deepEqual(calls[0].body.map_pool,['Bind','Icebox']);
    assert.equal(h.elements.get('ace-a-nickname').textContent,'Player A');
    assert.equal(h.elements.get('ace-b-nickname').textContent,'Player B');
    assert.equal(h.elements.get('ace-a-rounds').textContent,'100');
    assert.deepEqual(h.read('lastChart.data.datasets[0].data'),[220,200]);
    assert.match(h.elements.get('sub-status-text').textContent,/커리어 비교는 대회 필터와 무관/);
    assert.equal(h.elements.get('status-text').textContent,'전력 분석 완료.');
    assert.equal(h.read('analysisRunning'),false);
    assert.equal(h.read('analyzeBtn.disabled'),false);
});

test('switching matches before analysis resolves cannot paint stale results', async () => {
    const h=setup();let finish;
    h.context.matches=[readyMatch(),readyMatch('2')];
    h.run("filteredMatches=matches;matchSelect.value='0';startLiveScorePolling=()=>{}");
    await h.run('handleMatchSelection()');
    h.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
    const pending=h.run('runAnalysis()');
    h.run("matchSelect.value='1'");await h.run('handleMatchSelection()');
    finish(response(analysisResult()));await pending;
    assert.equal(h.elements.get('ace-a-nickname').textContent,'—');
    assert.equal(h.elements.get('status-text').textContent,'대회 선택 준비 완료.');
    assert.equal(h.read('selectedMatch.id'),'2');
});

test('unprepared scope reports the reason without per-panel fallback requests', async () => {
    const h=setup();let calls=0;
    h.context.match=readyMatch();h.run("filteredMatches=[match];matchSelect.value='0'");
    await h.run('handleMatchSelection()');
    h.context.fetch=async()=>{calls++;return {ok:false,status:409,json:async()=>({detail:'선택한 대회 통계를 준비 중입니다.'})};};
    await h.run('runAnalysis()');
    assert.equal(calls,1);
    assert.match(h.elements.get('sub-status-text').textContent,/선택한 대회 통계/);
    assert.equal(h.read('analyzeBtn.disabled'),false);
    assert.equal(h.elements.get('ace-a-nickname').textContent,'—');
    assert.equal(h.elements.get('career-acs-chart').hidden,true);
});

test('re-analysis clears prior career statistics and chart while the new request is pending', async () => {
    const h=setup();let finish;
    h.context.match=readyMatch();
    h.run("filteredMatches=[match];matchSelect.value='0';startLiveScorePolling=()=>{}");
    h.context.fetch=async()=>response(analysisResult());
    await h.run('handleMatchSelection([],true)');
    h.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
    const pending=h.run('runAnalysis()');
    for (const field of ['nickname','acs','kd','kd-ratio','rounds']) {
        assert.equal(h.elements.get(`ace-a-${field}`).textContent,'—');
    }
    assert.equal(h.elements.get('ace-a-collected').textContent,'');
    assert.equal(h.elements.get('career-acs-chart').hidden,true);
    assert.equal(h.read('careerAcsChartInstance'),null);
    assert.match(h.elements.get('career-acs-empty').textContent,/불러오는 중/);
    finish(response(analysisResult()));await pending;
    assert.equal(h.elements.get('ace-a-nickname').textContent,'Player A');
    assert.equal(h.elements.get('career-acs-chart').hidden,false);
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
