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
            await restoreSharedSelection();
            return;
        }

        updateStatus('success', '경기 일정 로드 성공.', `${allMatches.length}개의 일정을 성공적으로 확인했습니다.`, 0);
        populateEventsDropdown();
        await restoreSharedSelection();
    } catch (err) {
        updateStatus('error', '경기 일정을 불러오는 데 실패했습니다.', err.message, 0);
    }
}

async function restoreSharedSelection() {
    const params = new URLSearchParams(window.location.search);
    if (!params.has('match') && !params.has('url')) return;
    let matchId = params.get('match') || '';
    if (!matchId && params.has('url')) {
        try {
            const url = new URL(params.get('url'), 'https://www.vlr.gg');
            if (!['www.vlr.gg', 'vlr.gg'].includes(url.hostname)) throw new Error('Invalid host');
            matchId = url.pathname.split('/')[1];
        } catch {
            showToast('공유 링크의 경기 주소가 올바르지 않습니다.', 'error');
            return;
        }
    }
    const eventIds = [...new Set((params.get('events') || '').split(',').filter(Boolean))];
    if (!/^\d{1,12}$/.test(matchId) || eventIds.length > MAX_SELECTED_EVENTS ||
            eventIds.some(id => !/^\d{1,12}$/.test(id))) {
        showToast('공유 링크의 경기 또는 대회 선택이 올바르지 않습니다.', 'error');
        return;
    }
    let match = allMatches.find(item => item.id === matchId);
    if (!match) {
        match = { id: matchId, url: 'https://www.vlr.gg/' + matchId,
            team_a: 'Team A', team_b: 'Team B', tournament: '공유된 경기', tier: 'Other', region: 'Other' };
        allMatches.push(match);
    }
    tierSelect.value = 'All';
    regionSelect.value = 'All';
    populateEventsDropdown();
    eventSelect.value = match.tournament || match.event || '기타 대회';
    populateMatchesDropdown();
    matchSelect.value = String(filteredMatches.indexOf(match));
    await handleMatchSelection(eventIds);
}

// 4. Handle Match Selection (Fetch Team IDs and Recent Tournaments list)
async function handleMatchSelection(restoredEventIds = []) {
    if (!matchSelect.value || matchSelect.value === '') {
        analyzeBtn.disabled = true;
        selectedMatch = null;
        clearDashboard();
        return;
    }
    const idx = parseInt(matchSelect.value, 10);
    if (isNaN(idx)) return;

    const requestMatch = filteredMatches[idx];
    if (!requestMatch) return;
    clearDashboard();
    selectedEvents.clear();
    teamAEvents = [];
    teamBEvents = [];
    selectedMatch = requestMatch;
    requestMatch.details_ready = false;

    // Stop any active live polling
    stopLiveScorePolling();

    // Clear display cards to show loading
    document.getElementById('team-a-name').textContent = requestMatch.team_a;
    document.getElementById('team-b-name').textContent = requestMatch.team_b;
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
    const isSTier = requestMatch.tier === 'S-Tier';
    updateStatus('info', isSTier ? '경기 정보 불러오는 중...' : '매치 세부 정보 수집 중...', '대회와 맵 정보를 확인하고 있습니다.', 10);
    progressBarContainer.classList.remove('hidden');

    try {
        const matchUrl = requestMatch.url || requestMatch.match_url || (requestMatch.id ? `https://www.vlr.gg/${requestMatch.id}` : '');
        if (!matchUrl) {
            throw new Error('매치 URL 정보를 찾을 수 없습니다.');
        }
        const response = await fetch(`/api/match-details?url=${encodeURIComponent(matchUrl)}`, { signal });
        if (!response.ok) {
            throw new Error(`상세 로드 실패: ${response.status}`);
        }

        const data = await response.json();

        // Guard against race condition: ignore response if user switched match or aborted
        if (signal.aborted || selectedMatch !== requestMatch) return;

        // Save details inside requestMatch object
        requestMatch.team_a_id = data.details.team_a_id;
        requestMatch.team_a_name = data.details.team_a_name;
        requestMatch.team_b_id = data.details.team_b_id;
        requestMatch.team_b_name = data.details.team_b_name;
        requestMatch.map_pool = data.map_pool || [];
        requestMatch.live_score = data.live_score || null;
        requestMatch.url = matchUrl;
        requestMatch.team_a = data.details.team_a_name || requestMatch.team_a;
        requestMatch.team_b = data.details.team_b_name || requestMatch.team_b;
        document.getElementById('team-a-name').textContent = requestMatch.team_a;
        document.getElementById('team-b-name').textContent = requestMatch.team_b;

        teamAEvents = data.team_a_events || [];
        teamBEvents = data.team_b_events || [];
        // Shared filters may refer to events older than the recent dropdown.
        const availableIds = new Set([...teamAEvents, ...teamBEvents].map(e => e.id));
        restoredEventIds.forEach(id => {
            if (!availableIds.has(id)) teamAEvents.push({ id, name: '공유된 대회 #' + id });
        });

        // Draw checklists
        drawTournamentChecklist();
        setTournamentSelection(restoredEventIds);
        requestMatch.details_ready = true;
        matchSelect.disabled = false;

        // Start Live Scoreboard Polling / Display
        startLiveScorePolling();

        await runAnalysis();
    } catch (err) {
        if (err.name === 'AbortError') {
            console.log('Match details request aborted.');
            return;
        }
        if (selectedMatch === requestMatch) {
            updateStatus('error', '매치 세부 정보를 불러오지 못했습니다.', err.message, 0);
        }
    } finally {
        // Unlock UI only if this request wasn't aborted and is still active
        if (!signal.aborted && selectedMatch === requestMatch) {
            analyzeBtn.disabled = !requestMatch.details_ready || !requestMatch.team_a_id || !requestMatch.team_b_id || analysisRunning;
            matchSelect.disabled = false;
        }
    }
}

// 6. Run Analysis Pipeline (POST to server)
async function runAnalysis() {
    const analysisMatch = selectedMatch;
    if (!analysisMatch) return;

    // Prevent analysis if match details (team IDs) are not fully loaded yet
    if (!analysisMatch.details_ready || !analysisMatch.team_a_id || !analysisMatch.team_b_id) {
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

    document.getElementById('team-a-maps-table').innerHTML = `<tr><td colspan="4" class="py-4 text-center">${spinnerHtml}</td></tr>`;
    document.getElementById('team-b-maps-table').innerHTML = `<tr><td colspan="4" class="py-4 text-center">${spinnerHtml}</td></tr>`;

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
        team_a_id: analysisMatch.team_a_id,
        team_b_id: analysisMatch.team_b_id,
        event_ids: selectedEvents.size > 0 ? Array.from(selectedEvents) : null
    };

    let completedSteps = 0;
    const totalSteps = 4;
    let failedSteps = 0;

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
        if (signal.aborted || selectedMatch !== analysisMatch) return;
        renderFormBadges('team-a-form', data.form_a);
        renderFormBadges('team-b-form', data.form_b);
        renderAcsTrendChart(data.form_a, data.form_b);
        lucide.createIcons();
        updateProgress('경기 흐름');
    }).catch(err => {
        if (err.name === 'AbortError') return;
        failedSteps++;
        if (selectedMatch === analysisMatch) {
            document.getElementById('team-a-form').innerHTML = '<span class="text-xs text-red-400">로드 실패</span>';
            document.getElementById('team-b-form').innerHTML = '<span class="text-xs text-red-400">로드 실패</span>';
        }
        console.error('Form fetch error:', err);
    });

    // 2. Fetch Maps & Server AI Ban/Pick Simulation
    const mapsPromise = fetch('/api/analyze/maps', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal
    }).then(async res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (signal.aborted || selectedMatch !== analysisMatch) return;
        renderMapsTable('team-a-maps-table', data.maps_a);
        renderMapsTable('team-b-maps-table', data.maps_b);

        // Single Source of Truth: Call server banpick endpoint
        const pool = (analysisMatch.map_pool && analysisMatch.map_pool.length > 0)
            ? analysisMatch.map_pool
            : FALLBACK_MAP_POOL;

        try {
            const simRes = await fetch('/api/simulate/banpick', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ maps_a: data.maps_a || {}, maps_b: data.maps_b || {}, map_pool: pool }),
                signal
            });
            if (simRes.ok) {
                const simData = await simRes.json();
                if (!signal.aborted && selectedMatch === analysisMatch) {
                    renderBanPickResults(simData);
                }
            } else {
                if (!signal.aborted && selectedMatch === analysisMatch) {
                    calculateAISimulation(data.maps_a, data.maps_b);
                }
            }
        } catch (simErr) {
            if (simErr.name !== 'AbortError' && selectedMatch === analysisMatch) {
                calculateAISimulation(data.maps_a, data.maps_b);
            }
        }

        lucide.createIcons();
        updateProgress('진영별 맵 승률');
    }).catch(err => {
        if (err.name === 'AbortError') return;
        failedSteps++;
        if (selectedMatch === analysisMatch) {
            document.getElementById('team-a-maps-table').innerHTML = '<tr><td colspan="4" class="py-4 text-center text-red-400">로드 실패</td></tr>';
            document.getElementById('team-b-maps-table').innerHTML = '<tr><td colspan="4" class="py-4 text-center text-red-400">로드 실패</td></tr>';
            document.getElementById('ai-ban-list').innerHTML = '<p class="text-red-400">시뮬레이션 실패</p>';
            document.getElementById('ai-pick-list').innerHTML = '<p class="text-red-400">시뮬레이션 실패</p>';
        }
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
        if (signal.aborted || selectedMatch !== analysisMatch) return;
        renderAgentBadges('team-a-agents', data.ace_a.agents);
        renderAgentBadges('team-b-agents', data.ace_b.agents);
        populateAceCard('a', data.ace_a);
        populateAceCard('b', data.ace_b);
        renderAceRadarChart(data.ace_a, data.ace_b);
        lucide.createIcons();
        updateProgress('에이스 통계');
    }).catch(err => {
        if (err.name === 'AbortError') return;
        failedSteps++;
        if (selectedMatch === analysisMatch) {
            document.getElementById('team-a-agents').innerHTML = '<span class="text-xs text-red-400">로드 실패</span>';
            document.getElementById('team-b-agents').innerHTML = '<span class="text-xs text-red-400">로드 실패</span>';
            document.getElementById('ace-a-nickname').textContent = 'N/A';
            document.getElementById('ace-b-nickname').textContent = 'N/A';
        }
        console.error('Aces fetch error:', err);
    });

    // 4. Fetch Advanced Metrics (FK/FD Margin & Map Stats)
    const advPromise = fetch('/api/analyze/advanced', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal
    }).then(async res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (signal.aborted || selectedMatch !== analysisMatch) return;

        // Calculate Win Probability using legitimate weighted metrics:
        // 60% Map Win Rate + 40% First Kill/Death Margin
        const mapWinA = (data.adv_a && typeof data.adv_a.map_win_rate === 'number') ? data.adv_a.map_win_rate : 50.0;
        const mapWinB = (data.adv_b && typeof data.adv_b.map_win_rate === 'number') ? data.adv_b.map_win_rate : 50.0;
        const fkMarginA = (data.adv_a && typeof data.adv_a.fk_fd_margin === 'number') ? data.adv_a.fk_fd_margin : 0.0;
        const fkMarginB = (data.adv_b && typeof data.adv_b.fk_fd_margin === 'number') ? data.adv_b.fk_fd_margin : 0.0;

        const scoreA = Math.max(10, (mapWinA * 0.6) + Math.max(0, (50 + fkMarginA * 5) * 0.4));
        const scoreB = Math.max(10, (mapWinB * 0.6) + Math.max(0, (50 + fkMarginB * 5) * 0.4));
        const total = (scoreA + scoreB) > 0 ? (scoreA + scoreB) : 100;

        const probA = Math.min(85, Math.max(15, Math.round((scoreA / total) * 100)));
        const probB = 100 - probA;
        updateWinProbabilityBar(probA, probB);
        updateProgress('고급 지표');
    }).catch(err => {
        if (err.name === 'AbortError') return;
        failedSteps++;
        console.error('Advanced metrics error:', err);
    });

    try {
        await Promise.all([formPromise, mapsPromise, acesPromise, advPromise]);

        if (!signal.aborted && selectedMatch === analysisMatch) {
            if (failedSteps === 0) {
                updateStatus('success', '전력 분석 완료.', '양 팀의 최신 경기 데이터 융합 분석이 무결하게 완료되었습니다.', 100);
            } else if (failedSteps < totalSteps) {
                updateStatus('alert', '전력 분석 일부 완료.', `${failedSteps}개 항목의 데이터를 불러오지 못했습니다. 일부 결과가 정확하지 않을 수 있습니다.`, 100);
            } else {
                updateStatus('error', '전력 분석 실패.', '모든 데이터를 불러오는 데 실패했습니다. 잠시 후 다시 시도해 주세요.', 0);
            }
        }
    } catch (err) {
        if (err.name !== 'AbortError' && selectedMatch === analysisMatch) {
            updateStatus('error', '일부 전력 분석 실패', '일부 데이터를 불러오는 중 에러가 발생했습니다.', 0);
        }
    } finally {
        if (!signal.aborted && selectedMatch === analysisMatch) {
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
    updateLiveScoreboard();
    const match = selectedMatch;
    if (!match || !match.url || document.hidden) return;
    liveScoreAbortController = new AbortController();
    const signal = liveScoreAbortController.signal;

    async function poll() {
        if (signal.aborted || selectedMatch !== match || document.hidden) return;
        try {
            const response = await fetch(`/api/live-score?url=${encodeURIComponent(match.url)}`, { signal });
            if (!response.ok) throw new Error("Status: " + response.status);
            const liveData = await response.json();
            if (signal.aborted || selectedMatch !== match) return;
            if (!liveData || liveData.status === 'error') throw new Error('Score temporarily unavailable');
            match.live_score = liveData;
            updateLiveScoreboard();
        } catch (err) {
            if (err.name !== 'AbortError') console.error("Live scoreboard polling failed:", err);
        } finally {
            if (!signal.aborted && selectedMatch === match && !document.hidden && match.live_score?.status !== 'final') {
                const delay = match.live_score?.status === 'upcoming' ? 60000 : 25000;
                liveScoreTimeout = setTimeout(poll, delay);
            }
        }
    }
    // A cached match may not contain a score. Always discover its current state.
    void poll();
}

function stopLiveScorePolling() {
    if (liveScoreAbortController) {
        liveScoreAbortController.abort();
        liveScoreAbortController = null;
    }
    if (liveScoreTimeout) {
        clearTimeout(liveScoreTimeout);
        liveScoreTimeout = null;
    }
}
