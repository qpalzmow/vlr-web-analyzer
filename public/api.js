// 1. Fetch matches from server
function renderCatalogStatus(data) {
    const badge = document.getElementById('sync-badge-text');
    const updated = data.updated_at ? new Date(data.updated_at).toLocaleString('ko-KR', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
    const refreshing = data.sync_status === 'running' ? ' · 갱신 중' : '';
    const failed = data.sync_status === 'error' ? ' · 이전 데이터 유지' : '';
    const analytics = data.analytics_status?.stale_teams ? ` · 분석 갱신 대기 ${data.analytics_status.stale_teams}팀` : '';
    if (badge) badge.title = data.updated_at || '';
    if (badge) badge.textContent = updated
        ? `1시간마다 업데이트 · ${updated} 기준${refreshing}${failed}${analytics}`
        : '첫 경기 목록을 준비하고 있습니다';
}

async function fetchMatches(background = false) {
    if (catalogFetchRunning) return;
    catalogFetchRunning = true;
    if (!background) updateStatus('info', '저장된 경기 목록을 불러오는 중...', '1시간마다 업데이트됩니다.', 0);
    try {
        const response = await fetch('/api/catalog', { cache: 'no-store' });
        if (!response.ok) throw new Error(`서버 에러: ${response.status}`);
        const data = await response.json();
        renderCatalogStatus(data);
        if (data.generation !== catalogGeneration || !allMatches.length) {
            catalogGeneration = data.generation;
            allMatches = data.matches || [];
            // An ongoing analysis stays tied to its chosen generation.
            if (background && selectedMatch && !allMatches.some(m => m.id === selectedMatch.id)) {
                allMatches.push(selectedMatch);
            }
            populateEventsDropdown(background);
            if (!allMatches.length) {
                updateStatus('info', '첫 경기 목록을 준비하고 있습니다.', '서버에서 수집이 끝나면 자동으로 표시됩니다.', 0);
            } else if (!sharedSelectionRestored) {
                await restoreSharedSelection();
            }
        }
    } catch (err) {
        if (!background || !allMatches.length) updateStatus('error', '경기 목록을 불러오지 못했습니다.', err.message, 0);
    } finally {
        catalogFetchRunning = false;
        clearTimeout(catalogRefreshTimer);
        // This read cannot start an upstream scrape.
        catalogRefreshTimer = setTimeout(() => fetchMatches(true), 60000);
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
    if (!match || !match.selection_data) {
        updateStatus('info', '공유된 경기는 업데이트 대기 중입니다.', '다음 경기 목록에 준비되면 자동으로 표시됩니다.', 0);
        return;
    }
    sharedSelectionRestored = true;
    tierSelect.value = 'All';
    regionSelect.value = 'All';
    selectedTournamentCategory = 'all';
    populateEventsDropdown();
    eventSelect.value = getTournamentKey(match);
    populateMatchesDropdown();
    matchSelect.value = String(filteredMatches.indexOf(match));
    await handleMatchSelection(eventIds, true);
}

// Selection is entirely local: no details, menus, pool, or score request.
async function handleMatchSelection(restoredEventIds = [], autoAnalyze = false) {
    const value = matchSelect.value;
    const requestMatch = value === '' ? null : filteredMatches[Number(value)];
    clearDashboard();
    selectedEvents.clear();
    teamAEvents = [];
    teamBEvents = [];
    selectedMatch = requestMatch || null;
    analyzeBtn.disabled = true;
    if (!requestMatch) return;
    requestMatch.details_ready = false;
    const data = requestMatch.selection_data;
    if (!data?.details?.team_a_id || !data?.details?.team_b_id) {
        updateStatus('info', '이 경기는 업데이트 대기 중입니다.', '다음 정기 업데이트에서 준비됩니다.', 0);
        return;
    }
    const d = data.details;
    requestMatch.team_a_id = d.team_a_id;
    requestMatch.team_b_id = d.team_b_id;
    requestMatch.event_id = d.event_id;
    requestMatch.team_a = d.team_a_name || requestMatch.team_a;
    requestMatch.team_b = d.team_b_name || requestMatch.team_b;
    requestMatch.url = requestMatch.url || requestMatch.match_url || `https://www.vlr.gg/${requestMatch.id}`;
    requestMatch.map_pool = [...(data.map_pool || [])];
    requestMatch.live_score = data.live_score || null;
    requestMatch.live_updates_started = false;
    document.getElementById('team-a-name').textContent = requestMatch.team_a;
    document.getElementById('team-b-name').textContent = requestMatch.team_b;
    syncReportTeamNames();
    teamAEvents = [...(data.team_a_events || [])];
    teamBEvents = [...(data.team_b_events || [])];
    const available = new Set([...teamAEvents, ...teamBEvents].map(e => e.id));
    restoredEventIds.forEach(id => {
        if (!available.has(id)) teamAEvents.push({ id, name: '선택한 대회 #' + id });
    });
    drawTournamentChecklist();
    setTournamentSelection(restoredEventIds);
    requestMatch.details_ready = true;
    analyzeBtn.disabled = false;
    progressBarContainer.classList.add('hidden');
    updateStatus('success', '분석 준비 완료.', data.stale
        ? '이 경기의 최신 수집이 지연되어 이전 데이터를 표시합니다.'
        : '경기 분석을 누르면 모든 결과를 한 번에 표시합니다.', 0);
    if (autoAnalyze) await runAnalysis();
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

    beginReport();

    updateStatus('info', '전력 분석을 시작합니다...', '미리 수집한 통계를 한 번에 불러오고 있습니다.', 10);

    const payload = {
        team_a_id: analysisMatch.team_a_id,
        team_b_id: analysisMatch.team_b_id,
        event_ids: selectedEvents.size > 0 ? Array.from(selectedEvents) : null
    };

    payload.map_pool = analysisMatch.map_pool?.length ? analysisMatch.map_pool : FALLBACK_MAP_POOL;
    try {
        const response = await fetch('/api/analyze', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload), signal
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `분석 조회 실패: ${response.status}`);
        if (signal.aborted || selectedMatch !== analysisMatch) return;
        // Paint one consistent response in the same task; no per-panel requests.
        renderFormBadges('team-a-form', data.form_a);
        renderFormBadges('team-b-form', data.form_b);
        renderAcsTrendChart(data.form_a, data.form_b);
        renderMapsTable('team-a-maps-table', data.maps_a);
        renderMapsTable('team-b-maps-table', data.maps_b);
        renderBanPickResults(data.simulation);
        renderAgentBadges('team-a-agents', data.ace_a.agents);
        renderAgentBadges('team-b-agents', data.ace_b.agents);
        populateAceCard('a', data.ace_a);
        populateAceCard('b', data.ace_b);
        renderCareerAcsChart(data.ace_a, data.ace_b);
        if (data.probability) {
            updateWinProbabilityBar(data.probability.a, data.probability.b);
        } else {
            document.getElementById('win-probability-section').classList.add('hidden');
        }
        renderReportSummary(data, analysisMatch, payload.event_ids);
        const timestamp = new Date(data.updated_at).toLocaleString('ko-KR');
        const unavailableTeams = [
            [analysisMatch.team_a, data.ace_a], [analysisMatch.team_b, data.ace_b]
        ].filter(([, ace]) => !hasCareerPlayerStats(ace)).map(([name]) => name);
        const partial = data.ace_a.partial || data.ace_b.partial;
        const notice = (data.stale ? ' · 갱신 지연: 이전 데이터 사용' : '') +
            (unavailableTeams.length ? ` · ${unavailableTeams.join(', ')}: 커리어 비교 불가 (선수 표의 안내 확인)` : '') +
            (partial ? ' · 기록 없는 선수는 커리어 대표 선정에서 제외' : '') +
            ' · 커리어 비교는 대회 필터와 무관 · 팀 FK·FD 및 예측 승률 미표시';
        document.getElementById('report-integrity-note').textContent = notice.replace(/^ · /, '');
        updateStatus(data.stale || unavailableTeams.length || partial ? 'alert' : 'success', '전력 분석 완료.', `${timestamp} 기준${data.stale ? ' · 갱신 지연: 이전 데이터 사용' : ''}${unavailableTeams.length || partial ? ' · 선수별 표본 안내 확인' : ''}`, 100);
        // Live score is independent and does not delay any analysis panel.
        if (!analysisMatch.live_updates_started) {
            analysisMatch.live_updates_started = true;
            startLiveScorePolling();
        }
    } catch (err) {
        if (err.name !== 'AbortError' && !signal.aborted && selectedMatch === analysisMatch) {
            setReportState('error');
            document.getElementById('match-selection-panel').open = true;
            renderEmptyTable('team-a-maps-table');
            renderEmptyTable('team-b-maps-table');
            renderFormBadges('team-a-form', []);
            renderFormBadges('team-b-form', []);
            renderAcsTrendChart([], []);
            clearAceCompare('커리어를 불러오지 못했습니다. 다시 분석해 주세요.');
            renderAgentBadges('team-a-agents', []);
            renderAgentBadges('team-b-agents', []);
            renderBanPickResults({bans:[],picks:[]});
            document.getElementById('win-probability-section').classList.add('hidden');
            updateStatus('alert', '전력 분석을 표시하지 못했습니다.', err.message, 0);
        }
    } finally {
        if (!signal.aborted && selectedMatch === analysisMatch) {
            analysisRunning = false;
            analyzeBtn.disabled = false;
            progressBarContainer.classList.add('hidden');
        }
    }
}

// Win Probability Gauge Bar Manager
function updateWinProbabilityBar(probA, probB) {
    const sec = document.getElementById('win-probability-section');
    if (!sec) return;
    if (![probA, probB].every(value => Number.isFinite(value) && value >= 0 && value <= 100)) {
        sec.classList.add('hidden');
        return;
    }
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
        barA.textContent = '';
        barB.style.width = `${probB}%`;
        barB.textContent = '';
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
