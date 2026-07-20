// State variables
let allMatches = [];
let filteredMatches = [];
let selectedMatch = null;
let teamAEvents = [];
let teamBEvents = [];
let selectedEvents = new Set();
let analysisRunning = false;
let matchDetailsAbortController = null;
let analysisAbortController = null;
let liveScoreInterval = null;

// Agent badge Tailwind colors mapping
const agentColors = {
    jett: { bg: 'bg-sky-500/10 border-sky-500/20', text: 'text-sky-400' },
    raze: { bg: 'bg-orange-500/10 border-orange-500/20', text: 'text-orange-400' },
    phoenix: { bg: 'bg-red-500/10 border-red-500/20', text: 'text-red-400' },
    sage: { bg: 'bg-teal-500/10 border-teal-500/20', text: 'text-teal-400' },
    sova: { bg: 'bg-blue-500/10 border-blue-500/20', text: 'text-blue-400' },
    breach: { bg: 'bg-amber-500/10 border-amber-500/20', text: 'text-amber-400' },
    omen: { bg: 'bg-indigo-500/10 border-indigo-500/20', text: 'text-indigo-400' },
    brimstone: { bg: 'bg-yellow-800/10 border-yellow-800/20', text: 'text-yellow-600' },
    cypher: { bg: 'bg-slate-500/10 border-slate-500/20', text: 'text-slate-400' },
    reyna: { bg: 'bg-purple-500/10 border-purple-500/20', text: 'text-purple-400' },
    killjoy: { bg: 'bg-yellow-500/10 border-yellow-500/20', text: 'text-yellow-500' },
    viper: { bg: 'bg-emerald-500/10 border-emerald-500/20', text: 'text-emerald-400' },
    skye: { bg: 'bg-green-600/10 border-green-600/20', text: 'text-green-500' },
    yoru: { bg: 'bg-blue-700/10 border-blue-700/20', text: 'text-blue-500' },
    astra: { bg: 'bg-purple-700/10 border-purple-700/20', text: 'text-purple-500' },
    kayo: { bg: 'bg-sky-600/10 border-sky-600/20', text: 'text-sky-400' },
    chamber: { bg: 'bg-slate-700/10 border-slate-700/20', text: 'text-slate-300' },
    neon: { bg: 'bg-cyan-500/10 border-cyan-500/20', text: 'text-cyan-400' },
    fade: { bg: 'bg-slate-600/10 border-slate-600/20', text: 'text-slate-400' },
    harbor: { bg: 'bg-sky-600/10 border-sky-600/20', text: 'text-sky-500' },
    gekko: { bg: 'bg-lime-500/10 border-lime-500/20', text: 'text-lime-400' },
    deadlock: { bg: 'bg-cyan-600/10 border-cyan-600/20', text: 'text-cyan-500' },
    iso: { bg: 'bg-indigo-500/10 border-indigo-500/20', text: 'text-indigo-400' },
    clove: { bg: 'bg-pink-500/10 border-pink-500/20', text: 'text-pink-400' }
};

// UI Elements
const tierSelect = document.getElementById('tier-select');
const eventSelect = document.getElementById('event-select');
const matchSelect = document.getElementById('match-select');
const tournamentChecklistContainer = document.getElementById('tournament-checklist-container');
const tournamentChecklist = document.getElementById('tournament-checklist');

const statusIcon = document.getElementById('status-icon');
const statusText = document.getElementById('status-text');
const subStatusText = document.getElementById('sub-status-text');
const statusIconContainer = document.getElementById('status-icon-container');

const analyzeBtn = document.getElementById('analyze-btn');
const progressBarContainer = document.getElementById('progress-bar-container');
const progressBar = document.getElementById('progress-bar');

// App Initialization
document.addEventListener('DOMContentLoaded', () => {
    fetchMatches();
    
    // Wire up events
    tierSelect.addEventListener('change', () => {
        populateEventsDropdown();
    });
    
    eventSelect.addEventListener('change', () => {
        populateMatchesDropdown();
    });
    
    matchSelect.addEventListener('change', () => {
        handleMatchSelection();
    });
    
    analyzeBtn.addEventListener('click', () => {
        runAnalysis();
    });
});

// 1. Fetch matches from server
async function fetchMatches() {
    updateStatus('info', 'VLR.gg에서 일정을 불러오는 중입니다...', '전체 매치를 실시간 수집하고 있습니다.', 0);
    try {
        const response = await fetch('/api/matches');
        if (!response.ok) {
            throw new Error(`서버 에러: ${response.status}`);
        }
        allMatches = await response.json();
        
        if (allMatches.length === 0) {
            updateStatus('alert', '진행 중이거나 예정된 경기가 없습니다.', 'vlr.gg 페이지를 확인해보세요.', 0);
            return;
        }
        
        updateStatus('success', '경기 일정 로드 성공.', `${allMatches.length}개의 일정을 성공적으로 확인했습니다.`, 0);
        populateEventsDropdown();
    } catch (err) {
        updateStatus('error', '경기 일정을 불러오는 데 실패했습니다.', err.message, 0);
    }
}

// 2. Populate Events Dropdown (filtered by selected Tier)
function populateEventsDropdown() {
    const tier = tierSelect.value;
    
    // Filter matches by tier
    const tempMatches = allMatches.filter(m => {
        if (tier === 'All') return true;
        return m.tier === tier;
    });
    
    // Extract unique event names
    const uniqueEvents = [...new Set(tempMatches.map(m => m.event))];
    
    eventSelect.innerHTML = '';
    
    if (uniqueEvents.length === 0) {
        eventSelect.innerHTML = '<option>대회가 없습니다.</option>';
        eventSelect.disabled = true;
        matchSelect.innerHTML = '<option>매치가 없습니다.</option>';
        matchSelect.disabled = true;
        analyzeBtn.disabled = true;
        return;
    }
    
    uniqueEvents.forEach(evt => {
        const opt = document.createElement('option');
        opt.value = evt;
        opt.textContent = evt;
        eventSelect.appendChild(opt);
    });
    
    eventSelect.disabled = false;
    populateMatchesDropdown();
}

// 3. Populate Matches Dropdown (filtered by selected Event and Tier)
function populateMatchesDropdown() {
    const tier = tierSelect.value;
    const selectedEvent = eventSelect.value;
    
    filteredMatches = allMatches.filter(m => {
        const tierMatch = (tier === 'All' || m.tier === tier);
        const eventMatch = (m.event === selectedEvent);
        return tierMatch && eventMatch;
    });
    
    matchSelect.innerHTML = '';
    
    if (filteredMatches.length === 0) {
        matchSelect.innerHTML = '<option>매치가 없습니다.</option>';
        matchSelect.disabled = true;
        analyzeBtn.disabled = true;
        return;
    }
    
    filteredMatches.forEach((m, idx) => {
        const opt = document.createElement('option');
        opt.value = idx;
        opt.textContent = `${m.team_a} vs ${m.team_b} (${m.time} | ${m.date})`;
        matchSelect.appendChild(opt);
    });
    
    matchSelect.disabled = false;
    analyzeBtn.disabled = false;
    
    // Trigger initial match detail fetch
    handleMatchSelection();
}

// 4. Handle Match Selection (Fetch Team IDs and Recent Tournaments list)
async function handleMatchSelection() {
    const idx = parseInt(matchSelect.value, 10);
    if (isNaN(idx)) return;
    
    selectedMatch = filteredMatches[idx];
    
    // Stop any active live polling
    stopLiveScorePolling();
    
    // Clear display cards to show loading
    document.getElementById('team-a-name').textContent = selectedMatch.team_a;
    document.getElementById('team-b-name').textContent = selectedMatch.team_b;
    document.getElementById('team-a-form').innerHTML = '<span class="text-xs text-slate-500 italic">조회 대기 중..</span>';
    document.getElementById('team-b-form').innerHTML = '<span class="text-xs text-slate-500 italic">조회 대기 중..</span>';
    document.getElementById('team-a-agents').innerHTML = '<span class="text-xs text-slate-500 italic">조회 대기 중..</span>';
    document.getElementById('team-b-agents').innerHTML = '<span class="text-xs text-slate-500 italic">조회 대기 중..</span>';
    
    renderEmptyTable('team-a-maps-table');
    renderEmptyTable('team-b-maps-table');
    
    document.getElementById('ai-ban-list').innerHTML = '<p class="text-slate-500">- Team A: N/A</p><p class="text-slate-500">- Team B: N/A</p>';
    document.getElementById('ai-pick-list').innerHTML = '<p class="text-slate-500">- Team A: N/A</p><p class="text-slate-500">- Team B: N/A</p>';
    
    clearAceCompare();
    
    // Abort previous request if it is still running
    if (matchDetailsAbortController) {
        matchDetailsAbortController.abort();
    }
    matchDetailsAbortController = new AbortController();
    const signal = matchDetailsAbortController.signal;
    
    // Lock UI to prevent premature clicks
    analyzeBtn.disabled = true;
    matchSelect.disabled = true;
    updateStatus('info', '매치 세부 정보 수집 중...', '선수 및 대회 정보를 실시간으로 수집 중입니다 (약 5~10초 소요). 잠시만 기다려주세요.', 0);
    progressBarContainer.classList.remove('hidden');
    
    try {
        const matchUrl = selectedMatch.url;
        const response = await fetch(`/api/match-details?url=${encodeURIComponent(matchUrl)}`, { signal });
        if (!response.ok) {
            throw new Error(`상세 로드 실패: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Save details inside selectedMatch object
        selectedMatch.team_a_id = data.details.team_a_id;
        selectedMatch.team_a_name = data.details.team_a_name;
        selectedMatch.team_b_id = data.details.team_b_id;
        selectedMatch.team_b_name = data.details.team_b_name;
        selectedMatch.map_pool = data.map_pool || [];
        selectedMatch.live_score = data.live_score || null;
        
        teamAEvents = data.team_a_events;
        teamBEvents = data.team_b_events;
        
        updateStatus('success', '매치 정보 로드 완료.', '대회 필터를 선택하고 전력 분석 시작을 클릭하세요.', 40);
        
        // Draw checklists
        drawTournamentChecklist();
        
        // Start Live Scoreboard Polling / Display
        startLiveScorePolling();
        
        // Auto trigger full analysis
        runAnalysis();
    } catch (err) {
        if (err.name === 'AbortError') {
            console.log('Match details request aborted.');
            return;
        }
        updateStatus('error', '매치 세부 정보를 불러오지 못했습니다.', err.message, 0);
    } finally {
        // Unlock UI only if this request wasn't aborted
        if (!signal.aborted) {
            analyzeBtn.disabled = false;
            matchSelect.disabled = false;
        }
    }
}

// 5. Draw Tournament Checklist (Limit 12 events total, checking top 3 by default)
function drawTournamentChecklist() {
    tournamentChecklist.innerHTML = '';
    selectedEvents.clear();
    
    // Merge event lists from Team A and Team B
    const seenEvents = {};
    [...teamAEvents, ...teamBEvents].forEach(evt => {
        seenEvents[evt.id] = evt.name;
    });
    
    // Convert to array and sort by numeric ID descending (newest tournaments have larger IDs)
    const sortedEvents = Object.entries(seenEvents)
        .map(([id, name]) => ({ id: parseInt(id, 10), name }))
        .sort((a, b) => b.id - a.id);
        
    if (sortedEvents.length === 0) {
        tournamentChecklistContainer.classList.add('hidden');
        return;
    }
    
    tournamentChecklistContainer.classList.remove('hidden');
    
    sortedEvents.forEach((evt, idx) => {
        const evId = evt.id.toString();
        const evName = evt.name;
        const shortName = evName.length > 25 ? evName.substring(0, 25) + '..' : evName;
        
        const label = document.createElement('label');
        label.className = 'flex items-center space-x-2 bg-zinc-900 border border-slate-800 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-300 hover:border-slate-600 transition-colors cursor-pointer';
        
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'rounded border-slate-700 bg-zinc-950 text-emerald-500 focus:ring-emerald-500 focus:ring-offset-zinc-950 cursor-pointer';
        cb.value = evId;
        
        // Check only top 3 (most recent) by default
        if (idx < 3) {
            cb.checked = true;
            selectedEvents.add(evId);
        } else {
            cb.checked = false;
        }
        
        cb.addEventListener('change', () => {
            if (cb.checked) {
                selectedEvents.add(evId);
            } else {
                selectedEvents.delete(evId);
            }
        });
        
        label.appendChild(cb);
        label.appendChild(document.createTextNode(` ${shortName}`));
        tournamentChecklist.appendChild(label);
    });
}

// 6. Run Analysis Pipeline (POST to server)
async function runAnalysis() {
    if (!selectedMatch) return;
    
    // Prevent analysis if match details (team IDs) are not fully loaded yet
    if (!selectedMatch.team_a_id || !selectedMatch.team_b_id) {
        updateStatus('error', '매치 상세 정보 미로딩', '매치 세부 정보가 아직 로드되지 않았습니다. 잠시 후 다시 시도하세요.', 0);
        return;
    }
    
    // Abort previous analysis if it is running
    if (analysisAbortController) {
        analysisAbortController.abort();
    }
    analysisAbortController = new AbortController();
    const signal = analysisAbortController.signal;
    
    analysisRunning = true;
    analyzeBtn.disabled = true;
    progressBarContainer.classList.remove('hidden');
    
    // Set individual loading indicators (with spinner SVG)
    const spinnerHtml = `<span class="flex items-center gap-1 text-slate-500 italic"><svg class="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> 분석 중...</span>`;
    
    document.getElementById('team-a-form').innerHTML = spinnerHtml;
    document.getElementById('team-b-form').innerHTML = spinnerHtml;
    
    document.getElementById('team-a-maps-table').innerHTML = `<tr><td colspan="5" class="py-4 text-center">${spinnerHtml}</td></tr>`;
    document.getElementById('team-b-maps-table').innerHTML = `<tr><td colspan="5" class="py-4 text-center">${spinnerHtml}</td></tr>`;
    
    document.getElementById('ai-ban-list').innerHTML = `<p>${spinnerHtml}</p>`;
    document.getElementById('ai-pick-list').innerHTML = `<p>${spinnerHtml}</p>`;
    
    document.getElementById('team-a-agents').innerHTML = spinnerHtml;
    document.getElementById('team-b-agents').innerHTML = spinnerHtml;
    
    document.getElementById('ace-a-nickname').textContent = '분석 중...';
    document.getElementById('ace-a-acs').textContent = '0.0';
    document.getElementById('ace-a-kd').textContent = '0';
    document.getElementById('ace-a-agents').innerHTML = '<span class="text-[10px] text-slate-500">N/A</span>';
    
    document.getElementById('ace-b-nickname').textContent = '분석 중...';
    document.getElementById('ace-b-acs').textContent = '0.0';
    document.getElementById('ace-b-kd').textContent = '0';
    document.getElementById('ace-b-agents').innerHTML = '<span class="text-[10px] text-slate-500">N/A</span>';

    updateStatus('info', '전력 분석을 시작합니다...', '경기 흐름, 맵 전적, 에이스 데이터를 요청 중입니다.', 10);
    
    const payload = {
        team_a_id: selectedMatch.team_a_id,
        team_b_id: selectedMatch.team_b_id,
        event_ids: selectedEvents.size > 0 ? Array.from(selectedEvents) : null
    };
    
    let completedSteps = 0;
    const totalSteps = 3;
    
    function updateProgress(stepName) {
        completedSteps++;
        const progressPercent = 10 + Math.floor((completedSteps / totalSteps) * 90);
        updateStatus('info', `데이터 수집 및 매핑 중... [${progressPercent}%]`, `${stepName} 데이터를 성공적으로 로드했습니다.`, progressPercent);
    }

    // 1. Fetch Form (W/L Flow)
    const formPromise = fetch('/api/analyze/form', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal
    }).then(async res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderFormBadges('team-a-form', data.form_a);
        renderFormBadges('team-b-form', data.form_b);
        lucide.createIcons();
        updateProgress('경기 흐름');
    }).catch(err => {
        if (err.name === 'AbortError') return;
        document.getElementById('team-a-form').innerHTML = '<span class="text-xs text-red-400">로드 실패</span>';
        document.getElementById('team-b-form').innerHTML = '<span class="text-xs text-red-400">로드 실패</span>';
        console.error('Form fetch error:', err);
    });

    // 2. Fetch Maps & AI Simulation
    const mapsPromise = fetch('/api/analyze/maps', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal
    }).then(async res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderMapsTable('team-a-maps-table', data.maps_a);
        renderMapsTable('team-b-maps-table', data.maps_b);
        calculateAISimulation(data.maps_a, data.maps_b);
        lucide.createIcons();
        updateProgress('진영별 맵 승률');
    }).catch(err => {
        if (err.name === 'AbortError') return;
        document.getElementById('team-a-maps-table').innerHTML = '<tr><td colspan="5" class="py-4 text-center text-red-400">로드 실패</td></tr>';
        document.getElementById('team-b-maps-table').innerHTML = '<tr><td colspan="5" class="py-4 text-center text-red-400">로드 실패</td></tr>';
        document.getElementById('ai-ban-list').innerHTML = '<p class="text-red-400">시뮬레이션 실패</p>';
        document.getElementById('ai-pick-list').innerHTML = '<p class="text-red-400">시뮬레이션 실패</p>';
        console.error('Maps fetch error:', err);
    });

    // 3. Fetch Aces
    const acesPromise = fetch('/api/analyze/aces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal
    }).then(async res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderAgentBadges('team-a-agents', data.ace_a.agents);
        renderAgentBadges('team-b-agents', data.ace_b.agents);
        populateAceCard('a', data.ace_a);
        populateAceCard('b', data.ace_b);
        lucide.createIcons();
        updateProgress('에이스 통계');
    }).catch(err => {
        if (err.name === 'AbortError') return;
        document.getElementById('team-a-agents').innerHTML = '<span class="text-xs text-red-400">로드 실패</span>';
        document.getElementById('team-b-agents').innerHTML = '<span class="text-xs text-red-400">로드 실패</span>';
        document.getElementById('ace-a-nickname').textContent = 'N/A';
        document.getElementById('ace-b-nickname').textContent = 'N/A';
        console.error('Aces fetch error:', err);
    });

    try {
        await Promise.all([formPromise, mapsPromise, acesPromise]);
        
        if (!signal.aborted) {
            updateStatus('success', '전력 분석 완료.', '양 팀의 최신 경기 데이터 융합 분석이 무결하게 완료되었습니다.', 100);
        }
    } catch (err) {
        if (err.name !== 'AbortError') {
            updateStatus('error', '일부 전력 분석 실패', '일부 데이터를 불러오는 중 에러가 발생했습니다.', 0);
        }
    } finally {
        if (!signal.aborted) {
            analysisRunning = false;
            analyzeBtn.disabled = false;
            setTimeout(() => {
                if (!analysisRunning) progressBarContainer.classList.add('hidden');
            }, 3000);
        }
    }
}

// Helper: Render Form Badges
function renderFormBadges(containerId, formList) {
    const el = document.getElementById(containerId);
    el.innerHTML = '';
    
    if (!formList || formList.length === 0) {
        el.innerHTML = '<span class="text-xs text-slate-500 italic">경기 기록 없음 (N/A)</span>';
        return;
    }
    
    formList.forEach(f => {
        const isWin = f.startsWith('W');
        const outcomeText = isWin ? '승' : '패';
        
        let score = '';
        const scoreMatch = f.match(/\((.*?)\)/);
        if (scoreMatch) {
            score = scoreMatch[1];
        }
        
        let opponent = '';
        const vsIdx = f.indexOf('vs ');
        if (vsIdx !== -1) {
            opponent = f.substring(vsIdx + 3).trim();
        }
        
        const badge = document.createElement('span');
        badge.className = isWin 
            ? 'bg-emerald-950/40 text-emerald-400 border border-emerald-800/40 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-lg text-[10px] sm:text-xs font-bold'
            : 'bg-red-950/40 text-red-400 border border-red-800/40 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-lg text-[10px] sm:text-xs font-bold';
            
        let displayText = score ? `${outcomeText} ${score}` : outcomeText;
        if (opponent) {
            // Capitalize opponent name for professional clean display
            displayText += ` vs ${opponent.toUpperCase()}`;
        }
        
        badge.textContent = displayText;
        el.appendChild(badge);
    });
}

// Helper: Render Agent Badges
function renderAgentBadges(containerId, agentList) {
    const el = document.getElementById(containerId);
    el.innerHTML = '';
    
    if (!agentList || agentList.length === 0 || agentList[0] === 'N/A') {
        el.innerHTML = '<span class="text-xs text-slate-500 italic">기록 없음 (N/A)</span>';
        return;
    }
    
    agentList.forEach(agent => {
        const key = agent.trim().toLowerCase();
        let classes = { bg: 'bg-slate-800/40 border-slate-700/30', text: 'text-slate-300' };
        
        if (agentColors[key]) {
            classes = agentColors[key];
        }
        
        const badge = document.createElement('span');
        badge.className = `${classes.bg} ${classes.text} border px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-lg text-[10px] sm:text-xs font-bold`;
        badge.textContent = agent;
        el.appendChild(badge);
    });
}

// Helper: Render Maps Table
function renderMapsTable(tableId, mapsData) {
    const el = document.getElementById(tableId);
    el.innerHTML = '';
    
    const mapNames = Object.keys(mapsData || {});
    if (mapNames.length === 0) {
        el.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-slate-500 italic">기록된 맵 데이터가 없습니다.</td></tr>';
        return;
    }
    
    // Active tournament map pool: Dynamically scraped from VLR event page, fallbacks to VCT 2026 Competitive pool
    const fallbackMapPool = ['Ascent', 'Breeze', 'Haven', 'Lotus', 'Split', 'Summit', 'Sunset'];
    const activeMapPool = (selectedMatch && selectedMatch.map_pool && selectedMatch.map_pool.length > 0)
        ? selectedMatch.map_pool
        : fallbackMapPool;
    
    // Sort by: (1) active map first, (2) play count descending
    const sortedMaps = Object.entries(mapsData).sort((a, b) => {
        const aActive = activeMapPool.includes(a[0]);
        const bActive = activeMapPool.includes(b[0]);
        if (aActive && !bActive) return -1;
        if (!aActive && bActive) return 1;
        return b[1].played - a[1].played;
    });
    
    sortedMaps.forEach(([mapName, s]) => {
        const isActive = activeMapPool.includes(mapName);
        const tr = document.createElement('tr');
        
        if (isActive) {
            // High contrast emerald left-border highlight for active pool
            tr.className = 'border-b border-slate-800/60 hover:bg-emerald-950/15 bg-emerald-950/5 transition-colors font-medium border-l-4 border-l-emerald-500/80';
        } else {
            // Dimmed/translucent look for inactive/retired maps
            tr.className = 'border-b border-slate-900/40 hover:bg-slate-900/5 bg-zinc-950/10 opacity-30 transition-colors font-medium';
        }
        
        const atkPct = s.atk_total > 0 ? Math.round((s.atk_won / s.atk_total) * 100) + '%' : '0%';
        const defPct = s.def_total > 0 ? Math.round((s.def_won / s.def_total) * 100) + '%' : '0%';
        
        const badgeHtml = isActive 
            ? `<span class="ml-1 sm:ml-2 text-[8px] sm:text-[9px] font-bold text-emerald-400 bg-emerald-950/80 border border-emerald-500/30 px-1 py-0.5 rounded uppercase tracking-wider">Active</span>`
            : `<span class="ml-1 sm:ml-2 text-[8px] sm:text-[9px] font-bold text-slate-500 bg-zinc-800/40 border border-slate-700/20 px-1 py-0.5 rounded uppercase tracking-wider">Legacy</span>`;
            
        tr.innerHTML = `
            <td class="py-2 sm:py-3 pl-2 text-slate-100 font-bold text-[11px] sm:text-sm flex items-center">${mapName} ${badgeHtml}</td>
            <td class="py-2 sm:py-3 text-center text-slate-300">${s.played}</td>
            <td class="py-2 sm:py-3 text-center text-sky-400 font-bold">${atkPct}</td>
            <td class="py-2 sm:py-3 text-center text-orange-400 font-bold">${defPct}</td>
            <td class="py-2 sm:py-3 text-center text-slate-400 text-[10px] sm:text-xs">${s.w}승 - ${s.l}패</td>
        `;
        el.appendChild(tr);
    });
}

// Helper: Populate Ace Player Card
function populateAceCard(teamLetter, aceData) {
    document.getElementById(`ace-${teamLetter}-nickname`).textContent = aceData.nickname;
    document.getElementById(`ace-${teamLetter}-acs`).textContent = aceData.acs.toFixed(1);
    
    const kdEl = document.getElementById(`ace-${teamLetter}-kd`);
    const kd = aceData.kd_margin;
    kdEl.textContent = kd > 0 ? `+${kd}` : kd;
    kdEl.className = kd > 0 ? 'text-emerald-400 font-bold' : (kd < 0 ? 'text-red-400 font-bold' : 'text-slate-200');
    
    const agentsContainer = document.getElementById(`ace-${teamLetter}-agents`);
    agentsContainer.innerHTML = '';
    
    if (!aceData.agents || aceData.agents.length === 0 || aceData.agents[0] === 'N/A') {
        agentsContainer.innerHTML = '<span class="text-[10px] text-slate-500">N/A</span>';
        return;
    }
    
    aceData.agents.forEach(agent => {
        const key = agent.trim().toLowerCase();
        let classes = { bg: 'bg-slate-800/40 border-slate-700/30', text: 'text-slate-300' };
        
        if (agentColors[key]) {
            classes = agentColors[key];
        }
        
        const chip = document.createElement('span');
        chip.className = `${classes.bg} ${classes.text} border px-1.5 py-0.5 sm:px-2 rounded text-[9px] sm:text-[10px] font-bold`;
        chip.textContent = agent;
        agentsContainer.appendChild(chip);
    });
}

// Helper: Clear Ace compare
function clearAceCompare() {
    document.getElementById('ace-a-nickname').textContent = 'N/A';
    document.getElementById('ace-a-acs').textContent = '0.0';
    document.getElementById('ace-a-kd').textContent = '0';
    document.getElementById('ace-a-kd').className = 'text-slate-200';
    document.getElementById('ace-a-agents').innerHTML = '<span class="text-[10px] text-slate-500">N/A</span>';
    
    document.getElementById('ace-b-nickname').textContent = 'N/A';
    document.getElementById('ace-b-acs').textContent = '0.0';
    document.getElementById('ace-b-kd').textContent = '0';
    document.getElementById('ace-b-kd').className = 'text-slate-200';
    document.getElementById('ace-b-agents').innerHTML = '<span class="text-[10px] text-slate-500">N/A</span>';
}

// Helper: Render Empty Table row
function renderEmptyTable(tableId) {
    const el = document.getElementById(tableId);
    el.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-slate-500 italic">데이터가 없습니다.</td></tr>';
}

// Helper: Calculate AI Simulation (Bans and Picks)
function calculateAISimulation(mapsA, mapsB) {
    const banList = document.getElementById('ai-ban-list');
    const pickList = document.getElementById('ai-pick-list');
    
    const allMaps = Array.from(new Set([...Object.keys(mapsA || {}), ...Object.keys(mapsB || {})]));
    
    // Active competitive tournament map pool: Dynamically scraped from VLR event page, fallbacks to VCT 2026 Competitive pool
    const fallbackMapPool = ['Ascent', 'Breeze', 'Haven', 'Lotus', 'Split', 'Summit', 'Sunset'];
    const activeMapPool = (selectedMatch && selectedMatch.map_pool && selectedMatch.map_pool.length > 0)
        ? selectedMatch.map_pool
        : fallbackMapPool;
    const activeMaps = allMaps.filter(m => activeMapPool.includes(m));
    
    if (activeMaps.length === 0) {
        banList.innerHTML = '<p class="text-slate-500">- Team A: N/A</p><p class="text-slate-500">- Team B: N/A</p>';
        pickList.innerHTML = '<p class="text-slate-500">- Team A: N/A</p><p class="text-slate-500">- Team B: N/A</p>';
        return;
    }
    
    function getWinrate(mapsDict, mapName) {
        if (!mapsDict[mapName]) return -1;
        const total = mapsDict[mapName].w + mapsDict[mapName].l;
        return total > 0 ? mapsDict[mapName].w / total : -1;
    }
    
    function getPlayed(mapsDict, mapName) {
        if (!mapsDict[mapName]) return 0;
        return mapsDict[mapName].played;
    }
    
    // Sort for picks (highest winrate, highest play count) using active map pool only
    const sortedA = activeMaps.map(m => ({ name: m, wr: getWinrate(mapsA, m), p: getPlayed(mapsA, m) })).sort((x, y) => y.wr - x.wr || y.p - x.p);
    const sortedB = activeMaps.map(m => ({ name: m, wr: getWinrate(mapsB, m), p: getPlayed(mapsB, m) })).sort((x, y) => y.wr - x.wr || y.p - x.p);
    
    const pickA = sortedA[0]?.name || 'N/A';
    const pickB = sortedB[0]?.name || 'N/A';
    
    // Smart tactical bans:
    // Team A wants to block Team B's best map.
    // Team B wants to block Team A's best map.
    
    // Team A Ban (targeting Team B's maps, but don't ban our own pick)
    let banA = 'N/A';
    let banReasonA = '낮은 승률 밴';
    const candidateBansForA = sortedB.filter(item => item.name !== pickA);
    const highestOpponentMapForA = candidateBansForA[0];
    const ourWinrateOnOpponentMapForA = getWinrate(mapsA, highestOpponentMapForA?.name);
    
    if (highestOpponentMapForA && highestOpponentMapForA.wr > 0.60 && highestOpponentMapForA.wr > ourWinrateOnOpponentMapForA) {
        banA = highestOpponentMapForA.name;
        banReasonA = '상대 핵심 카드 견제 밴';
    } else {
        // Fallback to Team A's lowest winrate map
        const sortedSelfBanA = activeMaps.map(m => ({ name: m, wr: getWinrate(mapsA, m), p: getPlayed(mapsA, m) })).sort((x, y) => x.wr - y.wr || x.p - y.p);
        banA = sortedSelfBanA[0]?.name || 'N/A';
    }
    
    // Team B Ban (targeting Team A's maps, but don't ban our own pick)
    let banB = 'N/A';
    let banReasonB = '낮은 승률 밴';
    const candidateBansForB = sortedA.filter(item => item.name !== pickB);
    const highestOpponentMapForB = candidateBansForB[0];
    const ourWinrateOnOpponentMapForB = getWinrate(mapsB, highestOpponentMapForB?.name);
    
    if (highestOpponentMapForB && highestOpponentMapForB.wr > 0.60 && highestOpponentMapForB.wr > ourWinrateOnOpponentMapForB) {
        banB = highestOpponentMapForB.name;
        banReasonB = '상대 핵심 카드 견제 밴';
    } else {
        // Fallback to Team B's lowest winrate map
        const sortedSelfBanB = activeMaps.map(m => ({ name: m, wr: getWinrate(mapsB, m), p: getPlayed(mapsB, m) })).sort((x, y) => x.wr - y.wr || x.p - y.p);
        banB = sortedSelfBanB[0]?.name || 'N/A';
    }
    
    banList.innerHTML = `
        <p class="text-slate-200 font-semibold"><span class="text-xs text-slate-500">Team A:</span> ${banA} <span class="text-[10px] text-red-400 bg-red-950/40 px-1.5 py-0.5 rounded border border-red-900/30">${banReasonA}</span></p>
        <p class="text-slate-200 font-semibold"><span class="text-xs text-slate-500">Team B:</span> ${banB} <span class="text-[10px] text-red-400 bg-red-950/40 px-1.5 py-0.5 rounded border border-red-900/30">${banReasonB}</span></p>
    `;
    
    pickList.innerHTML = `
        <p class="text-slate-200 font-semibold"><span class="text-xs text-slate-500">Team A:</span> ${pickA} <span class="text-[10px] text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-900/30">핵심 카드 픽</span></p>
        <p class="text-slate-200 font-semibold"><span class="text-xs text-slate-500">Team B:</span> ${pickB} <span class="text-[10px] text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-900/30">핵심 카드 픽</span></p>
    `;
}

// 8. Update UI status display
function updateStatus(type, title, desc, progressVal) {
    statusText.textContent = title;
    subStatusText.textContent = desc;
    
    // Status style mapping
    if (type === 'success') {
        statusIconContainer.className = 'p-2 bg-emerald-500/10 border border-emerald-500/20 rounded-xl';
        statusIcon.className = 'w-5 h-5 text-emerald-400';
        statusIcon.setAttribute('data-lucide', 'check-circle');
    } else if (type === 'error') {
        statusIconContainer.className = 'p-2 bg-red-500/10 border border-red-500/20 rounded-xl';
        statusIcon.className = 'w-5 h-5 text-red-400';
        statusIcon.setAttribute('data-lucide', 'x-circle');
    } else if (type === 'info') {
        statusIconContainer.className = 'p-2 bg-sky-500/10 border border-sky-500/20 rounded-xl';
        statusIcon.className = 'w-5 h-5 text-sky-400';
        statusIcon.setAttribute('data-lucide', 'loader-2');
        statusIcon.classList.add('animate-spin');
    } else {
        statusIconContainer.className = 'p-2 bg-slate-800/50 rounded-xl';
        statusIcon.className = 'w-5 h-5 text-slate-400';
        statusIcon.setAttribute('data-lucide', 'info');
    }
    
    if (type !== 'info') {
        statusIcon.classList.remove('animate-spin');
    }
    
    // Update progress bar
    if (progressVal > 0) {
        progressBar.style.width = `${progressVal}%`;
    } else {
        progressBar.style.width = '0%';
    }
    
    // Trigger icons refresh
    lucide.createIcons();
}

// 9. Live Scoreboard Polling & Rendering Logic
function startLiveScorePolling() {
    stopLiveScorePolling();
    
    // Render initial live score from match details payload
    updateLiveScoreboard();
    
    if (!selectedMatch || !selectedMatch.live_score) return;
    
    // Only poll if the match is live (or status is live)
    // Even if upcoming or completed, we show it, but only poll if live!
    if (selectedMatch.live_score.status !== 'live') return;
    
    console.log("Starting live score polling interval...");
    liveScoreInterval = setInterval(async () => {
        if (!selectedMatch || !selectedMatch.url) return;
        const targetUrl = selectedMatch.url;
        try {
            const response = await fetch(`/api/live-score?url=${encodeURIComponent(targetUrl)}`);
            if (!response.ok) throw new Error("Status: " + response.status);
            
            const liveData = await response.json();
            
            // Prevent race condition if user changed the match while fetch was in-flight
            if (!selectedMatch || selectedMatch.url !== targetUrl) return;
            
            selectedMatch.live_score = liveData;
            updateLiveScoreboard();
            
            // If match is no longer live, stop polling
            if (liveData.status !== 'live') {
                console.log("Match finished or not live anymore. Stopping polling.");
                stopLiveScorePolling();
            }
        } catch (err) {
            console.error("Live scoreboard polling failed:", err);
        }
    }, 25000); // 25 seconds interval (safe with 20s server cache)
}

function stopLiveScorePolling() {
    if (liveScoreInterval) {
        clearInterval(liveScoreInterval);
        liveScoreInterval = null;
        console.log("Live score polling stopped.");
    }
}

function updateLiveScoreboard() {
    const panel = document.getElementById('live-scoreboard-panel');
    if (!selectedMatch || !selectedMatch.live_score) {
        panel.classList.add('hidden');
        return;
    }
    
    const scoreData = selectedMatch.live_score;
    const maps = scoreData.maps || [];
    
    // If no maps exist and series score is 0-0 and not live, hide panel
    if (maps.length === 0 && scoreData.series_score_a === "0" && scoreData.series_score_b === "0" && scoreData.status !== 'live') {
        panel.classList.add('hidden');
        return;
    }
    
    panel.classList.remove('hidden');
    
    // Render series score
    const seriesScoreEl = document.getElementById('live-series-score');
    const teamA = selectedMatch.team_a;
    const teamB = selectedMatch.team_b;
    seriesScoreEl.innerHTML = `${teamA} <span class="text-emerald-400 font-extrabold">${scoreData.series_score_a}</span> : <span class="text-emerald-400 font-extrabold">${scoreData.series_score_b}</span> ${teamB}`;
    
    // Render status badge
    const badge = document.getElementById('live-status-badge');
    if (scoreData.status === 'live') {
        badge.className = 'text-[10px] font-bold uppercase tracking-wider px-3 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-xl animate-pulse';
        badge.textContent = 'LIVE';
    } else if (scoreData.status === 'final') {
        badge.className = 'text-[10px] font-bold uppercase tracking-wider px-3 py-1 bg-slate-800 text-slate-300 border border-slate-700/60 rounded-xl';
        badge.textContent = 'FINAL';
    } else {
        badge.className = 'text-[10px] font-bold uppercase tracking-wider px-3 py-1 bg-zinc-950 text-slate-400 border border-slate-800 rounded-xl';
        badge.textContent = 'UPCOMING';
    }
    
    // Render maps
    const mapsContainer = document.getElementById('live-maps-container');
    const mapsGrid = document.getElementById('live-maps-grid');
    mapsGrid.innerHTML = '';
    
    if (maps.length > 0) {
        mapsContainer.classList.remove('hidden');
        maps.forEach(m => {
            const card = document.createElement('div');
            card.className = 'bg-zinc-950/80 border border-slate-800/80 rounded-xl p-3 flex flex-col items-center justify-center space-y-1';
            
            const mapNameEl = document.createElement('span');
            mapNameEl.className = 'text-[10px] font-bold text-slate-400 uppercase tracking-wider';
            mapNameEl.textContent = m.map;
            
            const scoreEl = document.createElement('span');
            scoreEl.className = 'text-sm font-extrabold text-white';
            scoreEl.textContent = `${m.score_a} - ${m.score_b}`;
            
            card.appendChild(mapNameEl);
            card.appendChild(scoreEl);
            mapsGrid.appendChild(card);
        });
    } else {
        mapsContainer.classList.add('hidden');
    }
    
    // Refresh icons inside the panel if any
    lucide.createIcons();
}
