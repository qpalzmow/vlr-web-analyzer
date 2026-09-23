const TOURNAMENT_CATEGORIES = [
    { id: 'champions', label: '챔피언스' },
    { id: 'masters', label: '마스터스' },
    { id: 'vct', label: 'VCT 지역 리그' },
    { id: 'game-changers', label: '게임 체인저스' },
    { id: 'challengers', label: '챌린저스 / 어센션' },
    { id: 'other', label: '기타 대회' }
];

function cleanTournamentName(match) {
    let name = String(match.tournament || match.event || '기타 대회').replace(/\s+/g, ' ').trim();
    // Older catalog rows include a stage/round before the actual event name.
    // Strip only a recognized prefix, preserving region, year and qualifiers.
    const prefix = /^(?:(?:Group Stage|Playoffs|Play[- ]?ins?|Main Event|Regional Final)\s*[–—-]?\s*)?(?:(?:Upper|Lower|Consolation)\s+)?(?:Grand Finals?|Quarterfinals?|Semifinals?|Finals?|Round(?: of)?\s+\d+|Opening|Winner['’]?s|Elimination|Decider)(?:\s*\([A-Z]\))?\s+/i;
    name = name.replace(prefix, '');
    return name || '기타 대회';
}

function tournamentCategory(name) {
    if (/\bgame\s+changers\b/i.test(name)) return 'game-changers';
    if (/^(?:valorant\s+)?champions\b(?!\s+tour\b)/i.test(name)) return 'champions';
    if (/^(?:valorant\s+)?masters\b/i.test(name)) return 'masters';
    if (/\b(challengers|ascension|vcl)\b/i.test(name)) return 'challengers';
    if (/\b(vct|champions tour)\b/i.test(name)) return 'vct';
    return 'other';
}

function tournamentDisplayName(name) {
    return name.replace(/^(?:valorant\s+)?champions\b(?!\s+tour\b)/i, '챔피언스')
        .replace(/^(?:valorant\s+)?masters\b/i, '마스터스')
        .replace(/\bGame Changers\b/i, '게임 체인저스');
}

function buildTournamentGroups(matches) {
    const aliases = new Map();
    const rows = matches.map(match => {
        const name = cleanTournamentName(match);
        const alias = name.toLowerCase();
        const id = String(match.selection_data?.details?.event_id || '');
        if (id) {
            if (!aliases.has(alias)) aliases.set(alias, new Set());
            aliases.get(alias).add(id);
        }
        return { match, name, alias, id };
    });
    const groups = new Map();
    tournamentKeyByMatch = new Map();
    for (const { match, name, alias, id } of rows) {
        const knownIds = aliases.get(alias);
        const resolvedId = id || (knownIds?.size === 1 ? [...knownIds][0] : '');
        const key = resolvedId ? `event:${resolvedId}` : `name:${alias}`;
        if (!groups.has(key)) groups.set(key, { key, name, category: tournamentCategory(name), matches: [] });
        groups.get(key).matches.push(match);
        tournamentKeyByMatch.set(match.id, key);
    }
    return [...groups.values()];
}

function getTournamentKey(match) {
    return tournamentKeyByMatch.get(match.id);
}

function matchesSelectionFilters(match) {
    return (tierSelect.value === 'All' || match.tier === tierSelect.value) &&
        (regionSelect.value === 'All' || match.region === regionSelect.value);
}

function renderTournamentCategories(groups) {
    const container = document.getElementById('tournament-category-filters');
    if (!container) return;
    container.innerHTML = '';
    for (const category of [{ id: 'all', label: '전체' }, ...TOURNAMENT_CATEGORIES]) {
        const count = category.id === 'all' ? groups.length : groups.filter(group => group.category === category.id).length;
        if (!count && category.id !== 'all') continue;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'tournament-category-button';
        button.dataset.category = category.id;
        button.setAttribute('aria-pressed', String(selectedTournamentCategory === category.id));
        button.textContent = `${category.label} · ${count}`;
        button.title = `${category.label} 대회 ${count}개`;
        button.disabled = !count;
        button.addEventListener('click', () => {
            selectedTournamentCategory = category.id;
            populateEventsDropdown();
        });
        container.appendChild(button);
    }
}

function updateTournamentSummary() {
    const summary = document.getElementById('tournament-selection-summary');
    if (!summary) return;
    const group = tournamentGroups.find(item => item.key === eventSelect.value);
    if (!group) {
        summary.textContent = '선택한 등급·지역에 해당하는 대회가 없습니다.';
        return;
    }
    const matches = group.matches.filter(matchesSelectionFilters);
    const ready = matches.filter(match => match.selection_data).length;
    summary.textContent = `${tournamentDisplayName(group.name)} · ${matches.length}경기 / 분석 가능 ${ready}경기`;
}

// 2. Tournament identity is built before filters, so pending matches stay with their event.
function populateEventsDropdown(preserveSelection = false) {
    const previousTournament = eventSelect.value;
    tournamentGroups = buildTournamentGroups(allMatches);
    const groups = tournamentGroups.map(group => ({ ...group, matches: group.matches.filter(matchesSelectionFilters) }))
        .filter(group => group.matches.length);
    const activeKey = preserveSelection && selectedMatch ? getTournamentKey(selectedMatch) : previousTournament;
    const activeGroup = groups.find(group => group.key === activeKey);
    if (preserveSelection && activeGroup && selectedTournamentCategory !== 'all') selectedTournamentCategory = activeGroup.category;
    if (!groups.some(group => group.category === selectedTournamentCategory)) selectedTournamentCategory = 'all';
    renderTournamentCategories(groups);
    eventSelect.innerHTML = '';
    if (!groups.length) {
        eventSelect.innerHTML = '<option>대회가 없습니다.</option>';
        eventSelect.disabled = true;
        matchSelect.innerHTML = '<option>매치가 없습니다.</option>';
        matchSelect.disabled = true;
        analyzeBtn.disabled = true;
        selectedMatch = null;
        clearDashboard();
        updateTournamentSummary();
        return;
    }
    const visibleGroups = [];
    for (const category of TOURNAMENT_CATEGORIES) {
        if (selectedTournamentCategory !== 'all' && selectedTournamentCategory !== category.id) continue;
        const categoryGroups = groups.filter(group => group.category === category.id).sort((a, b) =>
            Number((b.name.match(/\b20\d{2}\b/) || [0])[0]) - Number((a.name.match(/\b20\d{2}\b/) || [0])[0]) ||
            a.name.localeCompare(b.name, 'ko', { numeric: true }) || a.key.localeCompare(b.key));
        if (!categoryGroups.length) continue;
        const optgroup = document.createElement('optgroup');
        optgroup.label = category.label;
        for (const group of categoryGroups) {
            const opt = document.createElement('option');
            opt.value = group.key;
            opt.textContent = `${tournamentDisplayName(group.name)} · ${group.matches.length}경기`;
            optgroup.appendChild(opt);
            visibleGroups.push(group);
        }
        eventSelect.appendChild(optgroup);
    }
    eventSelect.disabled = false;
    eventSelect.value = preserveSelection && visibleGroups.some(group => group.key === activeKey)
        ? activeKey : visibleGroups[0].key;
    populateMatchesDropdown(preserveSelection);
}

function matchRoundLabel(match) {
    const name = cleanTournamentName(match);
    const event = String(match.event || '');
    const nameIndex = event.toLowerCase().lastIndexOf(name.toLowerCase());
    let round = nameIndex > 0 ? event.slice(0, nameIndex) : String(match.round_name || '');
    round = round.replace(/[–—]/g, ' ').replace(/\s+/g, ' ').trim()
        .replace(/^(Group Stage|Playoffs|Play[- ]?ins?|Main Event)\s*[-:]?\s*/i, '').trim();
    const grouped = round.match(/^(Opening|Winner['’]?s|Elimination|Decider)\s*\(([A-Z])\)$/i);
    if (grouped) {
        const labels = { opening: '첫 경기', winners: '승자전', elimination: '패자전', decider: '최종전' };
        return `${grouped[2]}조 ${labels[grouped[1].toLowerCase().replace(/['’]/g, '')]}`;
    }
    const rounds = { 'grand final': '결승전', 'upper final': '상위 결승', 'lower final': '하위 결승',
        'upper semifinals': '상위 4강', 'lower semifinals': '하위 4강', 'upper quarterfinals': '상위 8강',
        'quarterfinals': '8강', 'semifinals': '4강', 'consolation final': '3위 결정전' };
    return rounds[round.toLowerCase()] || round.replace(/^Lower Round (\d+)$/i, '하위 $1R')
        .replace(/^Upper Round of (\d+)$/i, '상위 $1강');
}

// 3. Populate Matches Dropdown (grouped by Stage optgroups: Playoffs, Play-Ins, Group Stage)
function populateMatchesDropdown(preserveSelection = false) {
    const activeMatch = preserveSelection ? selectedMatch : null;
    const selectedTournament = eventSelect.value;
    filteredMatches = allMatches.filter(m => matchesSelectionFilters(m) && getTournamentKey(m) === selectedTournament);
    updateTournamentSummary();
    const activeIndex = activeMatch ? filteredMatches.findIndex(m => m.id === activeMatch.id) : -1;
    // selectedMatch remains the displayed snapshot; dropdown entries always stay current.
    
    matchSelect.innerHTML = '';
    
    if (filteredMatches.length === 0) {
        matchSelect.innerHTML = '<option value="">매치가 없습니다.</option>';
        matchSelect.disabled = true;
        analyzeBtn.disabled = true;
        selectedMatch = null;
        clearDashboard();
        return;
    }
    
    // Default placeholder option: requires explicit user selection
    const placeholderOpt = document.createElement('option');
    placeholderOpt.value = '';
    placeholderOpt.textContent = '분석할 경기를 선택하세요';
    placeholderOpt.selected = true;
    matchSelect.appendChild(placeholderOpt);
    
    // Group filteredMatches by Stage
    const stageGroups = {};
    const stageOrder = [
        '⚔️ 플레이인 (Play-Ins)',
        '📅 그룹 스테이지 (Group Stage)',
        '기타 스테이지',
        '🏆 플레이오프 (Playoffs)'
    ];
    
    filteredMatches.forEach((m, idx) => {
        const stage = m.stage || '기타 스테이지';
        if (!stageGroups[stage]) {
            stageGroups[stage] = [];
        }
        stageGroups[stage].push({ match: m, globalIdx: idx });
    });
    
    // Render optgroup in logical stage order
    stageOrder.forEach(stageName => {
        if (stageGroups[stageName] && stageGroups[stageName].length > 0) {
            const optgroup = document.createElement('optgroup');
            optgroup.label = `${stageName.replace(/^[^A-Za-z가-힣]+/, '')} · ${stageGroups[stageName].length}경기`;
            
            stageGroups[stageName].forEach(({ match: m, globalIdx }) => {
                const opt = document.createElement('option');
                opt.value = globalIdx;
                const round = matchRoundLabel(m);
                const roundTag = round ? `[${round}] ` : '';
                const timeDate = m.time || m.date ? ` (${[m.time, m.date].filter(Boolean).join(' | ')})` : '';
                opt.textContent = `${roundTag}${m.team_a} vs ${m.team_b}${timeDate}`;
                opt.disabled = !m.selection_data;
                if (opt.disabled) opt.textContent += m.selection_status === 'unassigned' ? ' · 대진 미정' : ' · 업데이트 대기';
                optgroup.appendChild(opt);
            });
            
            matchSelect.appendChild(optgroup);
        }
    });
    
    // Any remaining stages not in stageOrder
    Object.keys(stageGroups).forEach(stageName => {
        if (!stageOrder.includes(stageName) && stageGroups[stageName].length > 0) {
            const optgroup = document.createElement('optgroup');
            optgroup.label = `${stageName.replace(/^[^A-Za-z가-힣]+/, '')} · ${stageGroups[stageName].length}경기`;
            
            stageGroups[stageName].forEach(({ match: m, globalIdx }) => {
                const opt = document.createElement('option');
                opt.value = globalIdx;
                const round = matchRoundLabel(m);
                const roundTag = round ? `[${round}] ` : '';
                const timeDate = m.time || m.date ? ` (${[m.time, m.date].filter(Boolean).join(' | ')})` : '';
                opt.textContent = `${roundTag}${m.team_a} vs ${m.team_b}${timeDate}`;
                opt.disabled = !m.selection_data;
                if (opt.disabled) opt.textContent += m.selection_status === 'unassigned' ? ' · 대진 미정' : ' · 업데이트 대기';
                optgroup.appendChild(opt);
            });
            
            matchSelect.appendChild(optgroup);
        }
    });
    
    matchSelect.disabled = false;
    if (activeIndex >= 0) {
        matchSelect.value = String(activeIndex);
        return;
    }
    analyzeBtn.disabled = true;
    selectedMatch = null;
    clearDashboard();
    updateStatus('info', '경기 준비 완료.', '분석을 진행할 매치를 선택해주세요.', 0);
}

function categorizeTournament(name) {
    const lower = (name || '').toLowerCase();
    if (/\bgame\s+changers\b/i.test(lower)) {
        return { type: 'game-changers', badgeText: '게임 체인저스',
            order: 1 };
    }
    if (/\b(champions|masters|world cup|ewc)\b/i.test(lower)) {
        return {
            type: 'global',
            badgeText: '국제대회',
            order: 1
        };
    }
    if (/\b(kickoff)\b/i.test(lower)) {
        return {
            type: 'vct',
            badgeText: '킥오프',
            order: 2
        };
    }
    if (/\b(stage\s*2|stage2)\b/i.test(lower)) {
        return {
            type: 'vct',
            badgeText: '스테이지 2',
            order: 3
        };
    }
    if (/\b(stage\s*1|stage1)\b/i.test(lower)) {
        return {
            type: 'vct',
            badgeText: '스테이지 1',
            order: 4
        };
    }
    if (/\b(vct\s*\d{4})\b/i.test(lower)) {
        return {
            type: 'vct',
            badgeText: 'VCT 정규',
            order: 5
        };
    }
    if (/\b(challengers|ascension|vcl)\b/i.test(lower)) {
        return {
            type: 'challengers',
            badgeText: '챌린저스',
            order: 6
        };
    }
    return {
        type: 'offseason',
        badgeText: '오프시즌',
        order: 7
    };
}

// 5. Draw Tournament Checklist (Categorized by Kickoff, Stage 1/2, International, Off-Season)
function drawTournamentChecklist() {
    tournamentChecklist.innerHTML = '';
    selectedEvents.clear();
    
    // Merge event lists from Team A and Team B
    const seenEvents = {};
    [...teamAEvents, ...teamBEvents].forEach(evt => {
        const name = evt.name ? evt.name.trim() : '';
        // Skip generic sub-stages
        if (!name || /^(playoffs|group stage|play-ins|main event|quarterfinals|semifinals|grand final|tournament)$/i.test(name)) {
            return;
        }
        seenEvents[evt.id] = name;
    });
    
    // Convert to array and sort by numeric ID descending
    const sortedEvents = Object.entries(seenEvents)
        .map(([id, name]) => {
            const cat = categorizeTournament(name);
            return { id: parseInt(id, 10), name, ...cat };
        })
        .sort((a, b) => b.id - a.id);
        
    if (sortedEvents.length === 0) {
        tournamentChecklistContainer.classList.add('hidden');
        return;
    }
    
    tournamentChecklistContainer.classList.remove('hidden');
    
    // Wire up quick filter buttons
    const btnAll = document.getElementById('btn-filter-all');
    const btnVct = document.getElementById('btn-filter-vct');
    const btnGlobal = document.getElementById('btn-filter-global');
    const btnOffseason = document.getElementById('btn-filter-offseason');
    const btnClear = document.getElementById('btn-filter-clear');

    const checkboxes = [];

    sortedEvents.forEach((evt, idx) => {
        const evId = evt.id.toString();
        const evName = evt.name;
        
        const label = document.createElement('label');
        label.title = evName;
        label.className = 'event-check';
        
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'event-checkbox';
        cb.value = evId;
        cb.dataset.eventType = evt.type;
        
        // Default unchecked on initial load to load full 100% verified DB cache instantly (0.01s)
        cb.checked = false;
        
        cb.addEventListener('change', () => {
            if (cb.checked) {
                if (selectedEvents.size >= MAX_SELECTED_EVENTS) {
                    cb.checked = false;
                    showToast('대회는 최대 ' + MAX_SELECTED_EVENTS + '개까지 선택할 수 있습니다.', 'error');
                    return;
                }
                selectedEvents.add(evId);
            } else {
                selectedEvents.delete(evId);
            }
            updateFilterCount();
        });
        
        checkboxes.push(cb);
        
        const badge = document.createElement('span');
        badge.className = 'event-kind';
        badge.textContent = evt.badgeText;
        
        label.appendChild(cb);
        label.appendChild(badge);
        const name = document.createElement('span');
        name.className = 'event-name';
        name.textContent = tournamentDisplayName(evName);
        label.appendChild(name);
        tournamentChecklist.appendChild(label);
    });

    if (btnAll) {
        btnAll.onclick = () => {
            setTournamentSelection(checkboxes.map(cb => cb.value));
        };
    }
    if (btnVct) {
        btnVct.onclick = () => {
            setTournamentSelection(checkboxes.filter(cb => cb.dataset.eventType === 'vct').map(cb => cb.value));
        };
    }
    if (btnGlobal) {
        btnGlobal.onclick = () => {
            setTournamentSelection(checkboxes.filter(cb => cb.dataset.eventType === 'global').map(cb => cb.value));
        };
    }
    if (btnOffseason) {
        btnOffseason.onclick = () => {
            setTournamentSelection(checkboxes.filter(cb => cb.dataset.eventType === 'offseason').map(cb => cb.value));
        };
    }
    if (btnClear) {
        btnClear.onclick = () => {
            setTournamentSelection([]);
        };
    }
}

function setTournamentSelection(ids) {
    const uniqueIds = [...new Set(ids)];
    selectedEvents = new Set(uniqueIds.slice(0, MAX_SELECTED_EVENTS));
    updateFilterCount();
    tournamentChecklist.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.checked = selectedEvents.has(cb.value);
    });
    if (uniqueIds.length > MAX_SELECTED_EVENTS) {
        showToast('대회는 최대 ' + MAX_SELECTED_EVENTS + '개까지 선택할 수 있습니다.', 'error');
    }
}

// Presentation state belongs to a completed response, never to edited filters.
let reportSnapshot = null;
let mapComparison = { a: {}, b: {} };
let toastTimer = null;
let exportRunning = false;

function showToast(message, type = 'success') {
    const toast = document.getElementById('app-toast');
    toast.textContent = message;
    toast.dataset.state = type;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
}

async function exportReportImage() {
    if (!reportSnapshot || analysisRunning || exportRunning) return;
    if (typeof html2canvas === 'undefined') {
        showToast('이미지 저장 도구를 불러오지 못했습니다. 페이지를 새로고침해 주세요.', 'error');
        return;
    }
    const snapshot = reportSnapshot;
    const button = document.getElementById('export-img-btn');
    const target = document.getElementById('match-report');
    exportRunning = true;
    button.disabled = true;
    button.textContent = '이미지 생성 중…';
    try {
        const canvas = await html2canvas(target, {
            backgroundColor: '#191b1e', scale: 1.5, useCORS: true,
            windowWidth: 1280, scrollX: 0, scrollY: 0,
            onclone: doc => {
                const report = doc.getElementById('match-report');
                report.classList.add('export-report');
                // Isolate the report from the mobile page and open every data column.
                doc.body.replaceChildren(report);
            }
        });
        const link = document.createElement('a');
        const filename = `${snapshot.match.team_a}-vs-${snapshot.match.team_b}`.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_');
        link.download = `${filename}-report.png`;
        link.href = canvas.toDataURL('image/png');
        document.body.appendChild(link);
        link.click();
        link.remove();
        showToast('리포트 이미지를 저장했습니다.');
    } catch (err) {
        console.error('Export error:', err);
        showToast('이미지를 저장하지 못했습니다. 다시 시도해 주세요.', 'error');
    } finally {
        exportRunning = false;
        button.disabled = false;
        button.textContent = '이미지 저장';
    }
}

function generateShareableLink() {
    const match = reportSnapshot?.match || selectedMatch;
    const events = reportSnapshot?.events || Array.from(selectedEvents);
    if (!match) { showToast('먼저 경기를 선택해 주세요.', 'error'); return; }
    const url = new URL(window.location.href);
    url.searchParams.set('match', match.id);
    url.searchParams.set('url', match.url);
    if (events.length) url.searchParams.set('events', events.join(','));
    else url.searchParams.delete('events');
    async function copy(text) {
        if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
        const field = document.createElement('textarea');
        field.value = text;
        field.style.position = 'fixed';
        field.style.opacity = '0';
        document.body.appendChild(field);
        field.select();
        try { if (!document.execCommand('copy')) throw new Error('Copy failed'); }
        finally { field.remove(); }
    }
    copy(url.toString()).then(() => showToast('분석 링크를 복사했습니다.'))
        .catch(() => showToast('링크를 복사하지 못했습니다. 브라우저의 클립보드 권한을 확인해 주세요.', 'error'));
}

function escapeHTML(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

function renderFormBadges(containerId, formList) {
    const el = document.getElementById(containerId);
    el.innerHTML = '';
    if (!formList?.length) { el.innerHTML = '<span class="meta">기록 없음</span>'; return; }
    formList.slice(0, 5).forEach(item => {
        const f = parseFormResult(item);
        const mark = document.createElement('span');
        mark.className = `form-result ${f.result === 'W' ? 'win' : f.result === 'L' ? 'loss' : ''}`;
        mark.textContent = f.result;
        mark.title = f.raw;
        mark.setAttribute('aria-label', f.raw);
        el.appendChild(mark);
    });
}

function renderAgentBadges(containerId, list) {
    const el = document.getElementById(containerId);
    el.innerHTML = '';
    el.textContent = list?.filter(agent => agent && agent !== 'N/A').join(', ') || '—';
}

function percent(won, total) {
    return Number.isFinite(won) && Number.isFinite(total) && total > 0
        ? `${Math.round(won / total * 100)}%` : '—';
}

// The legacy map IDs now label column groups in one direct comparison table.
function renderMapsTable(tableId, mapsData) {
    mapComparison[tableId === 'team-a-maps-table' ? 'a' : 'b'] = mapsData || {};
    renderMapComparison();
}

function renderEmptyTable(tableId) { renderMapsTable(tableId, {}); }

function renderMapComparison() {
    const body = document.getElementById('maps-comparison-body');
    body.innerHTML = '';
    const pool = selectedMatch?.map_pool?.length ? selectedMatch.map_pool : FALLBACK_MAP_POOL;
    const { a, b } = mapComparison;
    const names = [...new Set([...Object.keys(a), ...Object.keys(b)])].sort((x, y) =>
        Number(pool.includes(y)) - Number(pool.includes(x)) ||
        ((a[y]?.played || 0) + (b[y]?.played || 0)) - ((a[x]?.played || 0) + (b[x]?.played || 0)) || x.localeCompare(y));
    const cells = (s, team) => {
        if (!s || !(s.played > 0)) return '<td class="team-start muted">—</td><td class="muted">—</td><td class="muted">—</td>';
        const width = Math.max(0, Math.min(100, s.w / s.played * 100));
        return `<td class="team-start"><div class="map-record"><b>${percent(s.w, s.played)}</b><small>${escapeHTML(s.w)}–${escapeHTML(s.l)}</small></div><span class="map-rate team-${team}" aria-hidden="true"><span style="width:${width}%"></span></span></td><td>${percent(s.atk_won, s.atk_total)}</td><td>${percent(s.def_won, s.def_total)}</td>`;
    };
    names.forEach(name => {
        const row = document.createElement('tr');
        row.innerHTML = `<th scope="row">${escapeHTML(name)}${pool.includes(name) ? '' : '<span class="map-note">풀 외</span>'}</th>${cells(a[name], 'a')}${cells(b[name], 'b')}`;
        body.appendChild(row);
    });
    if (!names.length) body.innerHTML = '<tr><td colspan="7" class="empty-row">선택한 범위에 수집된 맵 기록이 없습니다.</td></tr>';
}

function populateAceCard(teamLetter, aceData) {
    const available = hasCareerPlayerStats(aceData);
    document.getElementById(`ace-${teamLetter}-nickname`).textContent = available ? aceData.nickname : '—';
    document.getElementById(`ace-${teamLetter}-acs`).textContent = available ? aceData.acs.toFixed(1) : '—';
    document.getElementById(`ace-${teamLetter}-kd-ratio`).textContent = available && Number.isFinite(aceData.kd_ratio) ? aceData.kd_ratio.toFixed(2) : '—';
    document.getElementById(`ace-${teamLetter}-rounds`).textContent = available && Number.isFinite(aceData.rounds) ? aceData.rounds.toLocaleString('ko-KR') : '—';
    const kd = available ? aceData.kd_margin : null;
    const kdEl = document.getElementById(`ace-${teamLetter}-kd`);
    kdEl.textContent = Number.isFinite(kd) ? (kd > 0 ? `+${kd}` : String(kd)) : '—';
    // Neutral text keeps team and result colors meaningful.
    kdEl.className = '';
    const coverage = document.getElementById(`ace-${teamLetter}-coverage`);
    if (available) {
        const missing = aceData.partial && aceData.missing_players?.length ? ` · 기록 없음: ${aceData.missing_players.join(', ')}` : '';
        coverage.textContent = `기록 있는 현역 ${aceData.players_with_stats}/${aceData.roster_size}명 기준${missing}`;
    } else {
        const reasons = {
            career_not_ready: '현역 선수 커리어 수집 대기 중',
            roster_unverified: '현역 선수 명단을 확인할 수 없어 비교 불가',
            no_roster: '확인 가능한 현역 선수 명단 없음',
            no_player_stats: '확인 가능한 현역 선수 기록 없음'
        };
        coverage.textContent = reasons[aceData?.unavailable_reason] || '확인 가능한 현역 선수 기록 없음';
    }
    coverage.className = 'meta';
    const collected = aceData?.collected_at ? new Date(aceData.collected_at) : null;
    document.getElementById(`ace-${teamLetter}-collected`).textContent = collected && Number.isFinite(collected.getTime())
        ? `${collected.toLocaleString('ko-KR')} 수집 기준` : '';
    renderAgentBadges(`ace-${teamLetter}-agents`, available ? aceData.agents : []);
}

function clearAceCompare(message = '전력 분석 후 커리어를 표시합니다.') {
    for (const team of ['a', 'b']) {
        for (const field of ['nickname', 'acs', 'kd', 'kd-ratio', 'rounds']) document.getElementById(`ace-${team}-${field}`).textContent = '—';
        document.getElementById(`ace-${team}-coverage`).textContent = message;
        document.getElementById(`ace-${team}-collected`).textContent = '';
        renderAgentBadges(`ace-${team}-agents`, []);
    }
    renderCareerAcsChart(null, null, message);
}

function reportTeamName(team) { return selectedMatch?.[`team_${team}`] || '—'; }

function syncReportTeamNames() {
    for (const team of ['a', 'b']) {
        for (const id of [`team-${team}-name`, `team-${team}-maps-table`, `ace-${team}-team`, `ace-${team}-note-team`, `form-${team}-team`]) {
            document.getElementById(id).textContent = reportTeamName(team);
        }
    }
}

function setReportState(state) {
    const ready = state === 'ready';
    document.getElementById('match-report').classList[ready ? 'remove' : 'add']('hidden');
    document.getElementById('report-toolbar').classList[ready ? 'remove' : 'add']('hidden');
    document.getElementById('match-report').setAttribute('aria-busy', String(state === 'loading'));
    analyzeBtn.textContent = state === 'loading' ? '분석 중…' : ready ? '다시 분석' : '경기 분석';
    if (!ready) reportSnapshot = null;
}

function beginReport() {
    setReportState('loading');
    destroyCharts();
    mapComparison = { a: {}, b: {} };
    renderMapComparison();
    renderFormBadges('team-a-form', []);
    renderFormBadges('team-b-form', []);
    renderBanPickResults(null);
    clearAceCompare('현역 선수 커리어를 불러오는 중...');
    document.getElementById('win-probability-section').classList.add('hidden');
}

function renderReportSummary(data, match, events) {
    syncReportTeamNames();
    reportSnapshot = { match: { ...match }, events: [...(events || [])] };
    document.getElementById('report-event').textContent = tournamentDisplayName(cleanTournamentName(match));
    document.getElementById('report-fixture').textContent = [matchRoundLabel(match), match.date, match.time].filter(Boolean).join(' · ');
    document.getElementById('selection-caption').textContent = `${match.team_a} vs ${match.team_b}`;
    const pool = match.map_pool?.length ? match.map_pool : FALLBACK_MAP_POOL;
    for (const team of ['a', 'b']) {
        const maps = Object.entries(data[`maps_${team}`] || {});
        const total = maps.reduce((sum, [, s]) => sum + (s.played || 0), 0);
        const wins = maps.reduce((sum, [, s]) => sum + (s.w || 0), 0);
        const losses = maps.reduce((sum, [, s]) => sum + (s.l || 0), 0);
        document.getElementById(`summary-${team}-rate`).textContent = percent(wins, total);
        document.getElementById(`summary-${team}-record`).textContent = total ? `${wins}승 ${losses}패` : '기록 없음';
        const strongest = maps.filter(([name, s]) => pool.includes(name) && s.played > 0)
            .sort(([, x], [, y]) => y.w / y.played - x.w / x.played || y.played - x.played)[0];
        document.getElementById(`summary-${team}-map`).textContent = strongest
            ? `${strongest[0]} · ${percent(strongest[1].w, strongest[1].played)} (${strongest[1].played}맵)` : '기록 없음';
        const ace = data[`ace_${team}`];
        document.getElementById(`summary-${team}-player`).textContent = hasCareerPlayerStats(ace)
            ? `${ace.nickname} · 커리어 ACS ${ace.acs.toFixed(1)}` : '현역 선수 커리어 확인 불가';
        document.getElementById(`summary-${team}-sample`).textContent = `맵 표본 ${total.toLocaleString('ko-KR')}개 · ${maps.filter(([, s]) => s.played > 0).length}종`;
    }
    const filterNames = (events || []).map(id => [...teamAEvents, ...teamBEvents].find(e => e.id === id)?.name || `대회 #${id}`);
    document.getElementById('report-scope').textContent = `맵 기록 범위: ${filterNames.length ? filterNames.join(' / ') : '수집된 전체 대회'}. 표시된 맵 승률은 과거 기록이며 이 경기의 예측 승률이 아닙니다.`;
    const date = new Date(data.updated_at);
    document.getElementById('report-updated').textContent = `통계 수집: ${Number.isFinite(date.getTime()) ? date.toLocaleString('ko-KR') : '시각 확인 불가'}${data.stale ? ' · 갱신 지연으로 이전 데이터 사용' : ''}`;
    document.getElementById('map-pool-note').textContent = `${match.map_pool?.length ? '확인된 대회 맵 풀' : '대회 맵 풀 미확인 · 기본 풀'}을 먼저 표시합니다. ‘풀 외’는 이 풀에 포함되지 않는 과거 맵입니다. 기록이 없는 값은 —로 표시합니다.`;
    setReportState('ready');
    document.getElementById('match-selection-panel').open = false;
    document.getElementById('advanced-filters').open = false;
    document.getElementById('tournament-explorer').open = false;
    document.getElementById('overview').focus({ preventScroll: true });
}

function updateFilterCount() {
    document.getElementById('filter-count').textContent = selectedEvents.size ? `· ${selectedEvents.size}개 선택` : '';
}

function clearDashboard() {
    analysisRunning = false;
    selectedEvents.clear();
    updateFilterCount();
    setReportState('idle');
    document.getElementById('match-selection-panel').open = true;
    document.getElementById('selection-caption').textContent = '';
    mapComparison = { a: {}, b: {} };
    renderMapComparison();
    renderFormBadges('team-a-form', []);
    renderFormBadges('team-b-form', []);
    renderAgentBadges('team-a-agents', []);
    renderAgentBadges('team-b-agents', []);
    renderBanPickResults(null);
    clearAceCompare();
    if (analysisAbortController) analysisAbortController.abort();
    if (typeof stopLiveScorePolling === 'function') stopLiveScorePolling();
    updateStatus('info', '대기 중', '경기를 선택해 주세요.', 0);
    for (const id of ['progress-bar-container', 'tournament-checklist-container', 'win-probability-section', 'live-scoreboard-panel']) document.getElementById(id).classList.add('hidden');
    destroyCharts();
}

function renderBanPickResults(simData) {
    const resolveTeam = value => value === 'Team A' ? reportTeamName('a') : value === 'Team B' ? reportTeamName('b') : value;
    const render = (id, entries, isPick) => {
        const el = document.getElementById(id);
        el.innerHTML = '';
        if (!entries?.length) { el.innerHTML = '<p class="meta">참고할 맵 기록이 없습니다.</p>'; return; }
        entries.forEach(item => {
            const row = document.createElement('div');
            row.className = 'outlook-row';
            const note = isPick ? (Number.isFinite(item.win_pct) ? `기록상 승률 ${item.win_pct}%` : '') : item.reason;
            row.innerHTML = `<span>${escapeHTML(resolveTeam(item.team))}</span><strong>${escapeHTML(item.map)}</strong><small>${escapeHTML(note)}</small>`;
            el.appendChild(row);
        });
    };
    render('ai-ban-list', simData?.bans, false);
    render('ai-pick-list', simData?.picks, true);
    if (simData?.remaining?.length) {
        const remaining = document.createElement('p');
        remaining.className = 'meta';
        remaining.textContent = `그 외 후보: ${simData.remaining.join(', ')}`;
        document.getElementById('ai-pick-list').appendChild(remaining);
    }
}

function updateStatus(type, title, desc, progressVal) {
    statusText.textContent = title;
    subStatusText.textContent = desc;
    document.getElementById('analysis-status').dataset.state = type;
    const progress = Math.max(0, Math.min(100, progressVal || 0));
    progressBar.style.width = `${progress}%`;
    progressBarContainer.setAttribute('aria-valuenow', String(progress));
}

function updateLiveScoreboard() {
    const panel = document.getElementById('live-scoreboard-panel');
    const score = selectedMatch?.live_score;
    const maps = score?.maps || [];
    if (!score || (!maps.length && String(score.series_score_a) === '0' && String(score.series_score_b) === '0' && score.status !== 'live')) {
        panel.classList.add('hidden'); return;
    }
    panel.classList.remove('hidden');
    document.getElementById('live-series-score').textContent = `${reportTeamName('a')}  ${score.series_score_a ?? '—'} : ${score.series_score_b ?? '—'}  ${reportTeamName('b')}`;
    const badge = document.getElementById('live-status-badge');
    badge.textContent = score.status === 'live' ? '진행 중' : score.status === 'final' ? '경기 종료' : '예정';
    badge.dataset.live = String(score.status === 'live');
    const grid = document.getElementById('live-maps-grid');
    grid.innerHTML = '';
    document.getElementById('live-maps-container').classList[maps.length ? 'remove' : 'add']('hidden');
    maps.forEach(map => {
        const row = document.createElement('div');
        row.className = 'live-map';
        row.innerHTML = `<span>${escapeHTML(map.map)}</span><span>${escapeHTML(map.score_a ?? '—')} – ${escapeHTML(map.score_b ?? '—')}</span>`;
        grid.appendChild(row);
    });
}
