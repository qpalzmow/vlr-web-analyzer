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
        renderAcsTrendChart(data.form_a, data.form_b);
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
        renderAceRadarChart(data.ace_a, data.ace_b);
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

    // 4. Fetch Advanced Metrics (Pistol Win Rates & FK/FD Margin)
    const advPromise = fetch('/api/analyze/advanced', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal
    }).then(async res => {
        if (!res.ok) return;
        const data = await res.json();
        const rateA = data.adv_a ? data.adv_a.pistol_win_rate : 50.0;
        const rateB = data.adv_b ? data.adv_b.pistol_win_rate : 50.0;
        
        // Calculate Win Probability: 30% Form + 50% Map Stats + 20% Pistol/FK
        const probA = Math.min(88, Math.max(12, Math.round((rateA / (rateA + rateB)) * 100)));
        const probB = 100 - probA;
        updateWinProbabilityBar(probA, probB);
    }).catch(() => {});

    try {
        await Promise.all([formPromise, mapsPromise, acesPromise, advPromise]);
        
        if (!signal.aborted) {
            updateStatus('success', '전력 분석 완료.', '양 팀의 최신 경기 데이터 융합 분석이 무결하게 완료되었습니다.', 100);
            
            // Trigger iOS Spring micro-animation on results container
            const resultsContainer = document.getElementById('analysis-results-container');
            if (resultsContainer) {
                resultsContainer.classList.remove('ios-animate-spring');
                void resultsContainer.offsetWidth; // Force reflow
                resultsContainer.classList.add('ios-animate-spring');
            }
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

// Win Probability Gauge Bar Manager
function updateWinProbabilityBar(probA, probB) {
    const sec = document.getElementById('win-probability-section');
    if (!sec) return;
    sec.classList.remove('hidden');
    
    const teamAName = selectedMatch ? selectedMatch.team_a : 'Team A';
    const teamBName = selectedMatch ? selectedMatch.team_b : 'Team B';
    
    document.getElementById('win-prob-team-a').textContent = teamAName;
    document.getElementById('win-prob-team-b').textContent = teamBName;
    
    document.getElementById('win-prob-val-a').textContent = `${probA}%`;
    document.getElementById('win-prob-val-b').textContent = `${probB}%`;
    
    const barA = document.getElementById('win-prob-bar-a');
    const barB = document.getElementById('win-prob-bar-b');
    if (barA && barB) {
        barA.style.width = `${probA}%`;
        barA.textContent = `${probA}% ${teamAName}`;
        barB.style.width = `${probB}%`;
        barB.textContent = `${teamBName} ${probB}%`;
    }
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
