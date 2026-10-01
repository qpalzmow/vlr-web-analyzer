const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('catalog status exposes delayed data even when the last import completed', () => {
    const h = setup();
    h.context.data = {updated_at:'2020-01-01T00:00:00Z',sync_status:'completed',analytics_status:{stale_teams:2}};
    h.run('renderCatalogStatus(data)');
    assert.match(h.elements.get('sync-badge-text').textContent, /갱신 지연/);
    assert.match(h.elements.get('sync-badge-text').textContent, /분석 갱신 대기 2팀/);
    h.context.data.updated_at = new Date().toISOString();
    h.run('renderCatalogStatus(data)');
    assert.doesNotMatch(h.elements.get('sync-badge-text').textContent, /갱신 지연/);
});

function setup(search = '') {
    class Element {
        constructor(tag = 'div') {
            this.tag = tag;
            this.children = [];
            this.value = '';
            this.dataset = {};
            this.style = {};
            this.classes = new Set();
            this.classList = { add: (...names) => names.forEach(n => this.classes.add(n)),
                remove: (...names) => names.forEach(n => this.classes.delete(n)), contains: n => this.classes.has(n) };
            this.attributes = {};
        }
        set innerHTML(value) {
            this.html = value;
            this.children = [];
            if (this.tag === 'select') this.value = '';
        }
        get innerHTML() { return this.html || ''; }
        appendChild(child) {
            if (child.parent) child.parent.children = child.parent.children.filter(item => item !== child);
            child.parent = this;
            this.children.push(child);
            if (this.tag === 'select' && child.tag === 'option' && !this.value) this.value = child.value;
        }
        addEventListener(name, callback) { this[name] = callback; }
        setAttribute(key, value) { this.attributes[key] = value; }
        removeAttribute(key) { delete this.attributes[key]; }
        click() { this.clicked = true; }
        focus() { this.focused = true; }
        remove() { this.removed = true; }
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
            querySelectorAll() { return []; },
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
    vm.createContext(context);
    for (const file of ['constants.js', 'components/primitives.js', 'match-context.js', 'charts.js', 'components/insight-strip.js', 'components/matchup-hero.js', 'components/map-card.js', 'components/player-card.js', 'ui.js', 'api.js', 'pages/match.js']) {
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

test('career comparison preserves exact ACS in semantic table cells', () => {
    const h=setup();
    h.context.a=careerPlayer('GSR',238.8); h.context.b=careerPlayer('Jinggg',239);
    h.run("populateAceCard('a',a);populateAceCard('b',b);renderCareerAcsChart(a,b)");
    assert.equal(h.elements.get('ace-a-acs').textContent,'238.8');
    assert.equal(h.elements.get('ace-b-acs').textContent,'239.0');
    assert.equal(h.elements.get('career-acs-empty').hidden,true);
    assert.equal(h.elements.get('career-acs-chart').hidden,false);
});

test('missing players remain inspectable without synthetic zero values', () => {
    const h=setup();
    h.run("populateAceCard('a',{nickname:'N/A',acs:null,available:false});renderCareerAcsChart(null,null)");
    assert.equal(h.elements.get('ace-a-acs').textContent,'—');
    assert.equal(h.elements.get('career-acs-chart').hidden,false);
    assert.equal(h.elements.get('career-acs-empty').hidden,false);
    assert.equal(h.elements.get('career-acs-empty').textContent,'확인 가능한 현역 선수 기록 없음');
});

test('unavailable player rows show missing values instead of zero', () => {
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

test('clearing comparison removes old metrics, coverage, timestamp, agents, and comparison state', () => {
    const h=setup();
    h.context.ace=careerPlayer('Previous');
    h.run("populateAceCard('a',ace);renderCareerAcsChart(ace,null);clearAceCompare()");
    for (const field of ['nickname','acs','kd','kd-ratio','rounds']) {
        assert.equal(h.elements.get(`ace-a-${field}`).textContent,'—');
    }
    assert.equal(h.elements.get('ace-a-coverage').textContent,'전력 분석 후 커리어를 표시합니다.');
    assert.equal(h.elements.get('ace-a-collected').textContent,'');
    assert.equal(h.elements.get('ace-a-agents').children.length,0);
    assert.equal(h.elements.get('career-acs-empty').hidden,false);
    assert.equal(h.elements.get('career-acs-chart').hidden,false);
});

test('stale and unavailable statistics are both explained', async () => {
    const h=setup();h.context.match=readyMatch();
    h.run("filteredMatches=[match];matchSelect.value='0';startLiveScorePolling=()=>{}");
    h.context.fetch=async()=>response({...analysisResult(),stale:true,players_available:false,probability:null,
        ace_b:{nickname:'N/A',acs:null,available:false,agents:[],unavailable_reason:'roster_unverified'}});
    await h.run("handleMatchSelection(['8'],true)");
    assert.match(h.elements.get('sub-status-text').textContent,/갱신 지연/);
    assert.match(h.elements.get('report-integrity-note').textContent,/미표시/);
    assert.match(h.elements.get('report-integrity-note').textContent,/Two:/);
    assert.doesNotMatch(h.elements.get('report-integrity-note').textContent,/One:/);
    assert.equal(h.elements.get('ace-a-nickname').textContent,'Player A');
    assert.equal(h.elements.get('ace-b-coverage').textContent,'현역 선수 명단을 확인할 수 없어 비교 불가');
    assert.equal(h.elements.get('ace-a-acs').textContent,'220.0');
    assert.equal(h.elements.get('ace-b-acs').textContent,'—');
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
    assert.equal(h.elements.get('ace-a-acs').textContent,'220.0');
    assert.equal(h.elements.get('ace-b-acs').textContent,'200.0');
    assert.match(h.elements.get('report-integrity-note').textContent,/커리어 비교는 대회 필터와 무관/);
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
    assert.equal(h.elements.get('status-text').textContent,'분석 준비 완료.');
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
    assert.equal(h.elements.get('career-acs-chart').hidden,false);
});

test('re-analysis clears prior career statistics and comparison state while the new request is pending', async () => {
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
    assert.equal(h.elements.get('career-acs-chart').hidden,false);
    assert.equal(h.elements.get('career-acs-empty').hidden,false);
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

test('recent results retain newest-first order, scores and opponents without invented ratings', () => {
    const h=setup();
    h.run("renderAcsTrendChart(['W (2-0) vs Alpha','L (0-2) vs Beta'],['W (2-1) vs Gamma'])");
    const rows=h.elements.get('acs-trend-chart').children;
    assert.equal(rows.length,2);
    assert.match(rows[0].innerHTML,/Alpha/);
    assert.match(rows[0].innerHTML,/Gamma/);
    assert.match(rows[0].innerHTML,/2-0/);
    assert.match(rows[1].innerHTML,/Beta/);
    assert.match(rows[1].innerHTML,/기록 없음/);
    assert.equal(h.read("parseFormResult('Unknown').result"),'—');
    h.run('renderAcsTrendChart([],[])');
    assert.equal(h.elements.get('acs-trend-chart').children.length,0);
    assert.match(h.elements.get('acs-trend-chart').innerHTML,/기록이 없습니다/);
});

function tournamentMatch(id, name, eventId = null) {
    const match = { ...readyMatch(id), tournament: name, event: name,
        stage: '📅 그룹 스테이지 (Group Stage)', round_name: name };
    if (eventId) match.selection_data.details.event_id = eventId;
    else { match.selection_data = null; match.selection_status = 'unassigned'; }
    return match;
}

test('bundled stage fragments collapse into 14 tournaments without losing pending matches', () => {
    const h = setup();
    h.context.seedMatches = JSON.parse(fs.readFileSync(path.join(__dirname, '../data/catalog_seed.json'), 'utf8')).matches;
    h.run('allMatches=seedMatches;tierSelect.value="All";regionSelect.value="All";populateEventsDropdown()');
    const groups = h.read('tournamentGroups.map(g=>({key:g.key,category:g.category,name:g.name,count:g.matches.length}))');
    assert.equal(groups.length, 14);
    assert.equal(groups.reduce((sum,g)=>sum+g.count,0), h.context.seedMatches.length);
    assert.equal(groups.find(g=>g.key==='event:2766').count, 27);
    assert.equal(groups.find(g=>g.key==='event:2766').name, 'Valorant Champions 2026');
    assert.equal(groups.filter(g=>g.category==='game-changers').length, 6);
    const sections = h.elements.get('event-select').children;
    assert.deepEqual(sections.map(g=>g.label), ['챔피언스','VCT 지역 리그','게임 체인저스','기타 대회']);
    assert.equal(sections[0].children[0].textContent, '챔피언스 2026 · 27경기');
    assert.equal(h.read('filteredMatches.length'), 27);
    assert.match(h.elements.get('tournament-selection-summary').textContent, /분석 가능 8경기/);
});

test('category buttons show only that family and switching category clears the prior report', () => {
    const h = setup();
    h.context.matches = [
        tournamentMatch('1', 'Group Stage–Opening (C) Valorant Champions 2026', '2766'),
        tournamentMatch('2', 'Game Changers 2026: Pacific', '3065'),
        tournamentMatch('3', 'Game Changers 2026: China', '3129')];
    h.run('allMatches=matches;tierSelect.value="All";regionSelect.value="All";populateEventsDropdown();selectedMatch=matches[0];selectedEvents.add("8")');
    h.elements.get('tournament-category-filters').children.find(button=>button.dataset.category==='game-changers').click();
    assert.equal(h.read('selectedTournamentCategory'), 'game-changers');
    assert.deepEqual(h.elements.get('event-select').children.map(g=>g.label), ['게임 체인저스']);
    assert.equal(h.elements.get('event-select').children[0].children.length, 2);
    assert.equal(h.read('selectedMatch'), null);
    assert.equal(h.read('selectedEvents.size'), 0);
});

test('no-ID pending rows follow a unique full-name alias built before region and tier filters', () => {
    const h=setup();
    const known=tournamentMatch('1','Group Stage–Opening (A) Valorant Champions 2026','2766');
    const pending=tournamentMatch('2','Playoffs–Grand Final Valorant Champions 2026');
    pending.tier='Other';
    h.context.matches=[known,pending];
    h.run('allMatches=matches;tierSelect.value="Other";regionSelect.value="All";populateEventsDropdown()');
    assert.equal(h.read('eventSelect.value'),'event:2766');
    assert.deepEqual(h.read('filteredMatches.map(m=>m.id)'),['2']);
    const options=h.elements.get('match-select').children.flatMap(g=>g.children);
    assert.equal(options[0].disabled,true);
});

test('years, regions and qualifiers remain separate and Game Changers Championship is not Champions', () => {
    const h=setup();
    h.context.matches=[
        tournamentMatch('1','Valorant Champions 2025','11'),
        tournamentMatch('2','Valorant Champions 2026','12'),
        tournamentMatch('3','Game Changers 2026: Pacific','13'),
        tournamentMatch('4','Game Changers 2026: Pacific Open Qualifier','14'),
        tournamentMatch('5','Game Changers 2026: China','15'),
        tournamentMatch('6','Champions Tour Game Changers Championship','16'),
        tournamentMatch('7','Kaizen Valorant Championship Division 1 - Season 1','17')];
    assert.equal(h.read('buildTournamentGroups(matches).length'),7);
    assert.equal(h.read('tournamentCategory(matches[5].tournament)'),'game-changers');
    assert.equal(h.read('tournamentDisplayName(matches[5].tournament)'), 'Champions Tour 게임 체인저스 Championship');
    assert.equal(h.read("tournamentCategory('Champions Tour 2021: Europe Stage 2')"), 'vct');
    assert.equal(h.read('tournamentCategory(matches[6].tournament)'),'other');
    h.run('allMatches=matches;tierSelect.value="All";regionSelect.value="All";populateEventsDropdown()');
    assert.match(h.elements.get('event-select').children[0].children[0].textContent,/2026/);
});

test('ambiguous no-ID rows never merge two different events with the same title', () => {
    const h=setup();
    h.context.matches=[tournamentMatch('1','Same Event','11'),tournamentMatch('2','Same Event','12'),tournamentMatch('3','Same Event')];
    const groups=h.read('buildTournamentGroups(matches)');
    assert.equal(groups.length,3);
    assert.deepEqual(groups.map(g=>g.matches.length),[1,1,1]);
});

test('refresh preserves selected match and filters even when its tournament gains an event ID', async () => {
    const h=setup();
    const match=tournamentMatch('1','Group Stage–Opening (C) Valorant Champions 2026','2766');
    delete match.selection_data.details.event_id;
    h.context.match=match;
    h.run('allMatches=[match];tierSelect.value="All";regionSelect.value="All";populateEventsDropdown();matchSelect.value="0"');
    await h.run('handleMatchSelection(["8"])');
    h.run('globalThis.active=selectedMatch;selectedTournamentCategory="champions"');
    h.context.newMatch=tournamentMatch('1','Valorant Champions 2026','2766');
    h.run('allMatches=[newMatch];populateEventsDropdown(true)');
    assert.equal(h.read('selectedMatch===active'),true);
    assert.equal(h.read('eventSelect.value'),'event:2766');
    assert.deepEqual(h.read('[...selectedEvents]'),['8']);
    assert.equal(h.read('selectedTournamentCategory'),'champions');
});

test('shared links restore the canonical event and match across category filters', async () => {
    const h=setup('?match=123456&events=8');
    h.context.matches=[tournamentMatch('123456','Group Stage–Opening (C) Valorant Champions 2026','2766'),
        tournamentMatch('222222','Game Changers 2026: Pacific','3065')];
    h.run('allMatches=matches;selectedTournamentCategory="game-changers";globalThis.restored=null;handleMatchSelection=async ids=>{restored={id:filteredMatches[matchSelect.value].id,ids};}');
    await h.run('restoreSharedSelection()');
    assert.equal(h.read('eventSelect.value'),'event:2766');
    assert.equal(h.read('selectedTournamentCategory'),'all');
    assert.deepEqual(h.read('restored'),{id:'123456',ids:['8']});
});

test('empty category after changing region falls back to remaining events and empty results clear selection', () => {
    const h=setup();
    const champs=tournamentMatch('1','Valorant Champions 2026','11');
    const gc=tournamentMatch('2','Game Changers 2026: Pacific','12'); gc.region='Pacific';
    h.context.matches=[champs,gc];
    h.run('allMatches=matches;tierSelect.value="All";regionSelect.value="All";populateEventsDropdown();selectedTournamentCategory="champions";regionSelect.value="Pacific";populateEventsDropdown()');
    assert.equal(h.read('selectedTournamentCategory'),'all');
    assert.equal(h.read('eventSelect.value'),'event:12');
    h.run('selectedMatch=matches[1];regionSelect.value="EMEA";populateEventsDropdown()');
    assert.equal(h.read('selectedMatch'),null);
    assert.equal(h.read('eventSelect.disabled'),true);
    assert.match(h.elements.get('tournament-selection-summary').textContent,/대회가 없습니다/);
});

test('round labels retain group identity without repeating the tournament name', () => {
    const h=setup();
    h.context.match=tournamentMatch('1','Group Stage–Opening (C) Valorant Champions 2026','2766');
    assert.equal(h.read('matchRoundLabel(match)'),'C조 첫 경기');
    h.context.match=tournamentMatch('2',"Group Stage–Winner's (D) Valorant Champions 2026",'2766');
    assert.equal(h.read('matchRoundLabel(match)'),'D조 승자전');
    h.context.match=tournamentMatch('3','Playoffs–Grand Final THE POKAL 2026','3077');
    assert.equal(h.read('matchRoundLabel(match)'),'결승전');
});

test('map event checkboxes retain the full distinguishing regional suffix', () => {
    const h=setup();
    h.run("teamAEvents=[{id:'1',name:'Game Changers 2026: North America Stage 2'}];teamBEvents=[];drawTournamentChecklist()");
    const label=h.elements.get('tournament-checklist').children[0];
    assert.equal(label.children.at(-1).textContent,'게임 체인저스 2026: North America Stage 2');
    assert.equal(label.children[0].dataset.eventType,'game-changers');
});

test('map rows align both teams, distinguish missing rounds from losses, and escape names', () => {
    const h=setup();
    h.run("selectedMatch={map_pool:['Haven']};renderMapsTable('team-a-maps-table',{Haven:{played:4,w:3,l:1,atk_won:0,atk_total:0,def_won:0,def_total:10}});renderMapsTable('team-b-maps-table',{'<script>':{played:2,w:0,l:2,atk_won:0,atk_total:3,def_won:1,def_total:2},Haven:{played:2,w:1,l:1,atk_won:1,atk_total:2,def_won:1,def_total:2}})");
    const rows=h.elements.get('maps-comparison-body').children;
    assert.equal(rows.length,2);
    assert.match(rows[0].innerHTML,/Haven/);
    assert.match(rows[0].innerHTML,/75%/);
    assert.match(rows[0].innerHTML,/50%/);
    assert.match(rows[0].innerHTML,/<td>—<\/td><td>0%<\/td>/);
    assert.match(rows[1].innerHTML,/&lt;script&gt;/);
    assert.doesNotMatch(rows[1].innerHTML,/<script>/);
    assert.match(rows[1].innerHTML,/풀 외/);
    h.run("renderEmptyTable('team-a-maps-table');renderEmptyTable('team-b-maps-table')");
    assert.equal(h.elements.get('maps-comparison-body').children.length,0);
    assert.match(h.elements.get('maps-comparison-body').innerHTML,/기록이 없습니다/);
});

test('a complete report shows honest map rates and keeps the applied filter snapshot for sharing', async () => {
    const h=setup();h.context.match=readyMatch();
    h.run("filteredMatches=[match];matchSelect.value='0';startLiveScorePolling=()=>{}");
    const result={...analysisResult(),probability:null,maps_a:{Haven:{played:4,w:3,l:1}},maps_b:{}};
    h.context.fetch=async()=>response(result);
    await h.run("handleMatchSelection(['8'],true)");
    assert.equal(h.elements.get('summary-a-rate').textContent,'75%');
    assert.equal(h.elements.get('summary-b-rate').textContent,'—');
    assert.match(h.elements.get('report-scope').textContent,/Event Eight/);
    assert.match(h.elements.get('report-scope').textContent,/예측 승률이 아닙니다/);
    assert.equal(h.elements.get('win-probability-section').classList.contains('hidden'),true);
    assert.equal(h.elements.get('match-report').classList.contains('hidden'),false);
    assert.equal(h.elements.get('match-selection-panel').open,false);
    assert.equal(h.elements.get('overview').focused,true);
    h.run("setTournamentSelection(['9']);generateShareableLink()");await flush();
    assert.equal(new URL(h.context.copied).searchParams.get('events'),'8');
    assert.deepEqual(h.read('reportSnapshot.events'),['8']);
    h.run('clearDashboard()');
    assert.equal(h.read('reportSnapshot'),null);
    assert.equal(h.elements.get('report-toolbar').classList.contains('hidden'),true);
});

test('loading and failed analysis hide export and stale report then allow retry', async () => {
    const h=setup();h.context.match=readyMatch();let finish;
    h.run("filteredMatches=[match];matchSelect.value='0';startLiveScorePolling=()=>{}");
    await h.run('handleMatchSelection()');
    h.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
    const pending=h.run('runAnalysis()');
    assert.equal(h.elements.get('match-report').attributes['aria-busy'],'true');
    assert.equal(h.elements.get('analyze-btn').disabled,true);
    assert.equal(h.elements.get('report-toolbar').classList.contains('hidden'),true);
    finish({ok:false,status:409,json:async()=>({detail:'Not ready'})});await pending;
    assert.equal(h.elements.get('match-report').attributes['aria-busy'],'false');
    assert.equal(h.elements.get('analyze-btn').disabled,false);
    assert.equal(h.elements.get('match-selection-panel').open,true);
    assert.equal(h.read('reportSnapshot'),null);
    assert.equal(h.elements.get('analysis-status').dataset.state,'alert');
});

test('reference indicator rejects nonfinite or out-of-range values', () => {
    const h=setup();
    h.run('updateWinProbabilityBar(55,45)');
    assert.equal(h.elements.get('win-prob-val-a').textContent,'55%');
    assert.equal(h.elements.get('win-prob-bar-a').style.width,'55%');
    h.run('updateWinProbabilityBar(NaN,45)');
    assert.equal(h.elements.get('win-probability-section').classList.contains('hidden'),true);
    h.run('updateWinProbabilityBar(101,-1)');
    assert.equal(h.elements.get('win-probability-section').classList.contains('hidden'),true);
});

test('export captures only the full-width report and restores its button after errors', async () => {
    const h=setup();h.context.match=readyMatch();
    h.run("filteredMatches=[match];matchSelect.value='0';startLiveScorePolling=()=>{}");
    h.context.fetch=async()=>response(analysisResult());
    await h.run('handleMatchSelection([],true)');
    let options;
    const links=[];
    const create=h.context.document.createElement;
    h.context.document.createElement=tag=>{const el=create(tag);if(tag==='a') links.push(el);return el;};
    h.context.html2canvas=async(target,config)=>{
        assert.equal(target,h.elements.get('match-report'));options=config;
        return {toDataURL:()=> 'data:image/png;base64,test'};
    };
    await h.run('exportReportImage()');
    assert.equal(options.windowWidth,1280);
    assert.equal(options.scale,1.5);
    const report=create('article'),body=create('body');
    options.onclone({getElementById:id=>{assert.equal(id,'match-report');return report;},body});
    assert.deepEqual(body.children,[report]);
    assert.equal(report.classList.contains('export-report'),true);
    assert.equal(links[0].download,'One-vs-Two-report.png');
    assert.equal(links[0].clicked,true);
    assert.equal(links[0].removed,true);
    assert.equal(h.elements.get('export-img-btn').disabled,false);
    h.context.html2canvas=async()=>{throw Error('Canvas failure');};
    await h.run('exportReportImage()');
    assert.equal(h.elements.get('export-img-btn').disabled,false);
    assert.equal(h.read('exportRunning'),false);
    assert.equal(h.elements.get('app-toast').dataset.state,'error');
});

test('form and recommendation rendering never interpret team or opponent names as markup', () => {
    const h=setup();
    h.run("selectedMatch={team_a:'<img src=x>',team_b:'Two'};renderBanPickResults({bans:[{team:'Team A',map:'<svg>',reason:'<script>'}],picks:[]});renderAcsTrendChart(['W (2-0) vs <img>'],[])");
    const ban=h.elements.get('ai-ban-list').children[0].innerHTML;
    assert.match(ban,/&lt;img/);assert.doesNotMatch(ban,/<img/);
    assert.match(h.elements.get('acs-trend-chart').children[0].innerHTML,/&lt;img&gt;/);
});

test('unstarted placeholder maps do not become a scoreboard but live zero scores remain visible', () => {
    const h=setup();
    h.run("selectedMatch={team_a:'One',team_b:'Two',live_score:{status:'upcoming',series_score_a:'0',series_score_b:'0',maps:[{map:'Map',score_a:'0',score_b:'0'},{map:'TBD',score_a:'-',score_b:'-'}]}};updateLiveScoreboard()");
    assert.equal(h.elements.get('live-scoreboard-panel').classList.contains('hidden'),true);
    h.run("selectedMatch.live_score.status='live';updateLiveScoreboard()");
    assert.equal(h.elements.get('live-scoreboard-panel').classList.contains('hidden'),false);
    assert.match(h.elements.get('live-series-score').textContent,/0 : 0/);
    h.run("selectedMatch.live_score={status:'final',series_score_a:'2',series_score_b:'1',maps:[{map:'Haven',score_a:'13',score_b:'7'}]};updateLiveScoreboard()");
    assert.equal(h.elements.get('live-scoreboard-panel').classList.contains('hidden'),false);
    assert.match(h.elements.get('live-maps-grid').children[0].innerHTML,/13 – 7/);
});

test('match clocks use KST across midnight and never reuse unlabelled legacy clocks', () => {
    const h=setup();
    assert.equal(h.run("matchClock({scheduled_at:'2026-09-30T09:00:00Z'})"),'18:00');
    assert.equal(h.run("matchDay({scheduled_at:'2026-09-30T16:00:00Z'})"),'2026-10-01');
    assert.equal(h.run("matchClock({date:'Wed, September 30, 2026 Today',time:'3:00 AM'})"),'시간 확인 중');
    assert.doesNotMatch(h.run("formatMatchSchedule({date:'Wed, September 30, 2026 Today',time:'3:00 AM'})"), /3:00 AM|Today/);
});

test('international quick filters exclude regional Champions Tour and preserve Challengers stage identity', () => {
    const h=setup();
    assert.equal(h.run("categorizeTournament('Champions Tour 2024: Americas Stage 2').type"),'vct');
    assert.equal(h.run("categorizeTournament('Champions Tour 2024: Masters Madrid').type"),'global');
    assert.equal(h.run("categorizeTournament('Valorant Champions 2026').type"),'global');
    assert.equal(h.run("categorizeTournament('Challengers 2026: Korea Stage 2').type"),'challengers');
});

test('date groups stay chronological even when legacy clocks have no timezone', () => {
    const h=setup();
    const a=readyMatch('1'),b=readyMatch('2'),c=readyMatch('3');
    a.date='Wed, September 30, 2026';b.date='Thu, October 1, 2026';c.date=a.date;
    a.status_code=b.status_code=c.status_code='upcoming';
    h.context.matches=[b,a,c];
    h.run('filteredMatches=matches;renderMatchBrowser()');
    const dates=h.elements.get('match-browser').children.filter(e=>e.tag==='h3');
    assert.equal(dates.length,2);
    assert.match(dates[0].textContent,/9월 30일/);
    assert.match(dates[1].textContent,/10월 1일/);
});

test('search and status browsing stay local and selecting a row still requires Analyze', async () => {
    const h=setup();
    const a=readyMatch(),b=readyMatch('2');
    a.status_code='live'; b.status_code='final';
    a.scheduled_at=b.scheduled_at='2026-09-30T09:00:00Z';
    h.context.matches=[a,b];
    h.run("tierSelect.value='All';regionSelect.value='All';allMatches=matches;populateEventsDropdown();selectedMatchStatus='final';renderMatchBrowser()");
    let requests=0;
    h.context.fetch=async()=>{requests++;throw new Error('Network forbidden');};
    const rows=h.elements.get('match-browser').children.filter(e=>e.tag==='button');
    assert.equal(rows.length,1);
    await rows[0].click();
    assert.equal(requests,0);
    assert.equal(h.read('selectedMatch.id'),'2');
    assert.equal(h.read('analyzeBtn.disabled'),false);
    assert.match(rows[0].innerHTML,/종료/);
    h.run("matchSearchQuery='absent';populateEventsDropdown(true)");
    assert.equal(h.read('filteredMatches.length'),0);
    assert.equal(requests,0);
});

test('an unmatched search preserves a finished report, its filters and export snapshot', async () => {
    const h=setup();h.context.matches=[readyMatch()];
    h.run("tierSelect.value='All';regionSelect.value='All';allMatches=matches;populateEventsDropdown();matchSelect.value='0'");
    await h.run('handleMatchSelection()');
    h.context.result=analysisResult();
    h.run("renderReportSummary(result,selectedMatch,['8']);globalThis.original=reportSnapshot;matchSearchQuery='no such team';populateEventsDropdown(true)");
    assert.equal(h.read('reportSnapshot===original'),true);
    assert.equal(h.elements.get('match-report').classList.contains('hidden'),false);
    assert.equal(h.read('analyzeBtn.disabled'),false);
});

test('complete roster preserves all members, missing records, sorting and escaped source links', () => {
    const h=setup();h.context.match=readyMatch();
    h.context.a=[{...careerPlayer('Low <svg>',200),player_id:'7'},{...careerPlayer('High',250),player_id:'8'},
        {nickname:'Newcomer',available:false,player_id:'9',acs:null,rounds:null}];
    h.context.b=[{...careerPlayer('Other',240),player_id:'10'}];
    h.run("selectedMatch=match;renderCareerRoster(a,b)");
    const rows=h.elements.get('career-roster-body').children;
    assert.equal(rows.length,4);
    assert.match(rows[0].innerHTML,/High/);
    assert.match(rows[1].innerHTML,/&lt;svg&gt;/);
    assert.match(rows[2].innerHTML,/커리어 기록 없음/);
    assert.match(rows[2].innerHTML,/—/);
    h.run("careerSort='acs';renderRosterTable()");
    assert.match(h.elements.get('career-roster-body').children[1].innerHTML,/Other/);
    assert.doesNotMatch(h.run("sourceAnchor('<img>', 'javascript:alert(1)')"),/<a|<img/);
    assert.doesNotMatch(h.run("sourceAnchor('x', 'https://www.vlr.gg.evil.test/1')"),/<a/);
});

test('actual veto and final score take priority and polling respects an expanded recommendation', () => {
    const h=setup(); h.context.match=readyMatch();
    h.run("selectedMatch=match;selectedMatch.live_score={status:'final',series_score_a:'2',series_score_b:'0',match_format:'BO3',actual_veto:[{team:'ONE',action:'pick',map:'Ascent'}]};renderFixtureContext()");
    assert.equal(h.elements.get('match-summary-score').textContent,'2 : 0');
    assert.equal(h.elements.get('match-summary-format').textContent,'BO3');
    assert.equal(h.elements.get('confirmed-veto').hidden,false);
    assert.equal(h.elements.get('map-outlook').open,false);
    h.run("document.getElementById('map-outlook').open=true;renderFixtureContext()");
    assert.equal(h.elements.get('map-outlook').open,true);
});

test('three-map perfect results do not outrank established maps and stay labelled in the table', () => {
    const h=setup();h.context.match=readyMatch(); h.context.data=analysisResult();
    h.run("selectedMatch=match;selectedMatch.map_pool=['Ascent','Summit'];data.maps_a={Summit:{played:3,w:3,l:0},Ascent:{played:20,w:12,l:8}};renderMapsComparison(data.maps_a,{});renderReportSummary(data,selectedMatch,[])");
    assert.match(h.elements.get('summary-a-map').textContent,/Ascent/);
    const rows=h.elements.get('maps-comparison-body').children;
    assert.match(rows.find(row=>row.innerHTML.includes('Summit')).innerHTML,/표본 부족/);
});

const mapSample = (played, wins) => ({played,w:wins,l:played-wins,atk_won:50,atk_total:100,def_won:50,def_total:100});

test('match narrative excludes small samples and never turns map history into an odds prediction', () => {
    const h=setup();h.context.match=readyMatch();h.context.data=analysisResult();
    h.run("match.status_code='upcoming';match.map_pool=['Ascent','Summit'];data.maps_a={Ascent:{played:20,w:12},Summit:{played:3,w:3}};data.maps_b={Ascent:{played:20,w:10},Summit:{played:3,w:0}}");
    const result=h.read('MatchUI.buildMatchSummary(data,match)');
    assert.match(result.title,/One.*Ascent.*과거/);
    assert.doesNotMatch(result.title,/Summit|승리|예측|확률|55%/);
    assert.equal(result.comparable.length,1);
    assert.equal(result.balance,'unknown');
    h.run('data.maps_a={};data.maps_b={}');
    assert.match(h.read('MatchUI.buildMatchSummary(data,match)').title,/표본/);
});

test('final result uses the actual winner even when historical maps and reference indicator favor the loser', () => {
    const h=setup();h.context.match=readyMatch();h.context.data=analysisResult();
    h.run("match.live_score={status:'final',series_score_a:'0',series_score_b:'2'};data.maps_a={Bind:{played:20,w:20}};data.maps_b={Bind:{played:20,w:0}};data.probability={a:90,b:10}");
    const result=h.read('MatchUI.buildMatchSummary(data,match)');
    assert.equal(result.status,'final');
    assert.match(result.title,/Two 승리.*2 : 0/);
    assert.doesNotMatch(result.title,/역전|예측|90|One가/);
    h.run("match.live_score.series_score_b='unavailable'");
    assert.match(h.read('MatchUI.buildMatchSummary(data,match)').title,/확인/);
});

test('live zero scores and phase changes update insight without replacing modules or career data', () => {
    const h=setup();h.context.match=readyMatch();h.context.data=analysisResult();
    h.run("selectedMatch=match;match.live_score={status:'upcoming',series_score_a:'0',series_score_b:'0'};MatchUI.render(data,match)");
    const parent=h.elements.get('report-modules');
    const ids=()=>parent.children.map(child=>[...h.elements.entries()].find(([,value])=>value===child)[0]);
    assert.deepEqual(ids(),['map-preview-card','veto-card','player-impact-card','live-scoreboard-panel']);
    const nodes=[...parent.children];
    h.run("match.live_score.status='live';MatchUI.refresh()");
    assert.match(h.elements.get('insight-title').textContent,/0 : 0.*동률/);
    assert.deepEqual(ids(),['live-scoreboard-panel','map-preview-card','veto-card','player-impact-card']);
    h.run("match.live_score={status:'final',series_score_a:'2',series_score_b:'1'};MatchUI.refresh();MatchUI.refresh()");
    assert.deepEqual(ids(),['live-scoreboard-panel','map-preview-card','veto-card','player-impact-card']);
    assert.equal(new Set(parent.children).size,4);
    assert.ok(nodes.every(node=>parent.children.includes(node)));
    assert.equal(h.elements.get('impact-a-acs').textContent,'220.0');
    assert.match(h.elements.get('insight-title').textContent,/One 승리.*2 : 1/);
});

test('selecting a match previews its hero locally and clears old analysis before a new request', async () => {
    const h=setup();h.context.match=readyMatch();
    h.run("filteredMatches=[match];matchSelect.value='0';MatchUI.analysis={maps_a:{}};MatchUI.matchId='old'");
    await h.run('handleMatchSelection()');
    assert.equal(h.elements.get('match-report').dataset.reportState,'preview');
    assert.equal(h.elements.get('match-report').classList.contains('hidden'),false);
    assert.equal(h.elements.get('hero-analyze-btn').disabled,false);
    assert.equal(h.read('MatchUI.analysis'),null);
    h.run('beginReport()');
    assert.equal(h.elements.get('hero-analyze-btn').disabled,true);
    assert.equal(h.elements.get('match-report').dataset.reportState,'loading');
});

test('map preview preserves missing attack rounds, escapes names and labels low sample records', () => {
    const h=setup();h.context.match={...readyMatch(),team_a:'<img src=x>',map_pool:['<svg>']};
    h.context.data={...analysisResult(),maps_a:{'<svg>':mapSample(3,3)},maps_b:{'<svg>':mapSample(5,1)}};
    h.run('MatchUI.renderMapCard(data,match,MatchUI.buildMatchSummary(data,match))');
    const html=h.elements.get('map-preview-list').children[0].innerHTML;
    assert.match(html,/&lt;svg&gt;/);assert.match(html,/&lt;img/);
    assert.doesNotMatch(html,/<svg|<img/);
    assert.match(html,/표본 부족/);assert.match(html,/공격 비교 표본 부족/);
    h.context.match={...readyMatch(),map_pool:['Ascent']};
    h.context.data={...analysisResult(),maps_a:{Ascent:{...mapSample(10,6),atk_total:0}},maps_b:{Ascent:mapSample(10,5)}};
    h.run('MatchUI.renderMapCard(data,match,MatchUI.buildMatchSummary(data,match))');
    assert.match(h.elements.get('map-preview-list').children[0].innerHTML,/공격 비교 표본 부족/);
});
