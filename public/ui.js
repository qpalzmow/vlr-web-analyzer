// Theme Manager (Original eSports Dark vs Apple iOS 27 Glass UI Kit)
function setUITheme(theme) {
    const htmlEl = document.documentElement;
    const btnOriginal = document.getElementById('theme-btn-original');
    const btnIos = document.getElementById('theme-btn-ios');
    
    htmlEl.setAttribute('data-theme', theme);

    if (theme === 'ios') {
        htmlEl.classList.add('theme-ios');
        if (btnOriginal && btnIos) {
            btnOriginal.className = 'px-2.5 py-1.5 sm:px-3 rounded-lg text-slate-400 hover:text-white transition-all duration-200 flex items-center gap-1.5';
            btnIos.className = 'px-2.5 py-1.5 sm:px-3 rounded-lg transition-all duration-200 flex items-center gap-1.5 bg-blue-600/30 text-sky-300 border border-sky-400/30 font-bold shadow-sm backdrop-blur-md';
        }
        localStorage.setItem('vlr_ui_theme', 'ios');
    } else {
        htmlEl.classList.remove('theme-ios');
        if (btnOriginal && btnIos) {
            btnOriginal.className = 'px-2.5 py-1.5 sm:px-3 rounded-lg transition-all duration-200 flex items-center gap-1.5 bg-emerald-500/20 text-emerald-400 font-bold shadow-sm';
            btnIos.className = 'px-2.5 py-1.5 sm:px-3 rounded-lg text-slate-400 hover:text-white transition-all duration-200 flex items-center gap-1.5';
        }
        localStorage.setItem('vlr_ui_theme', 'original');
    }
    if (window.lucide) {
        lucide.createIcons();
    }
}

function initUITheme() {
    const savedTheme = localStorage.getItem('vlr_ui_theme') || 'original';
    setUITheme(savedTheme);
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
        label.className = 'flex items-center space-x-1.5 sm:space-x-2 bg-zinc-900 border border-slate-800 px-2 py-1 sm:px-3 sm:py-1.5 rounded-lg text-[10px] sm:text-xs font-semibold text-slate-300 hover:border-slate-600 transition-colors cursor-pointer';
        
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

// Toast & Export Utilities
function showToast(message, type = 'success') {
    let toast = document.getElementById('app-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'app-toast';
        toast.className = 'fixed bottom-5 right-5 px-4 py-3 rounded-xl shadow-2xl z-50 transition-all duration-300 transform translate-y-4 opacity-0 text-xs font-bold flex items-center gap-2 border';
        document.body.appendChild(toast);
    }
    
    if (type === 'success') {
        toast.style.background = 'rgba(16, 185, 129, 0.92)';
        toast.style.borderColor = 'rgba(52, 211, 153, 0.4)';
        toast.style.color = '#ffffff';
    } else {
        toast.style.background = 'rgba(239, 68, 68, 0.92)';
        toast.style.borderColor = 'rgba(248, 113, 113, 0.4)';
        toast.style.color = '#ffffff';
    }
    
    toast.textContent = message;
    toast.classList.remove('translate-y-4', 'opacity-0');
    
    setTimeout(() => {
        toast.classList.add('translate-y-4', 'opacity-0');
    }, 3000);
}

function exportReportImage() {
    if (typeof html2canvas === 'undefined') {
        showToast('html2canvas 라이브러리가 로드되지 않았습니다.', 'error');
        return;
    }
    
    showToast('리포트 이미지를 생성 중입니다...', 'success');
    
    const target = document.querySelector('main');
    html2canvas(target, {
        backgroundColor: '#05070c',
        scale: 1.5,
        useCORS: true
    }).then(canvas => {
        const link = document.createElement('a');
        const matchName = selectedMatch ? `${selectedMatch.team_a}-vs-${selectedMatch.team_b}` : 'vlr-analysis';
        link.download = `${matchName}-report.png`;
        link.href = canvas.toDataURL('image/png');
        link.click();
        showToast('리포트 이미지가 저장되었습니다! 📸', 'success');
    }).catch(err => {
        console.error('Export error:', err);
        showToast('이미지 저장 중 오류가 발생했습니다.', 'error');
    });
}

function generateShareableLink() {
    if (!selectedMatch) {
        showToast('선택된 매치가 없습니다.', 'error');
        return;
    }
    
    const url = new URL(window.location.href);
    url.searchParams.set('match', selectedMatch.id);
    url.searchParams.set('url', selectedMatch.url);
    if (selectedEvents.size > 0) {
        url.searchParams.set('events', Array.from(selectedEvents).join(','));
    }
    
    navigator.clipboard.writeText(url.toString()).then(() => {
        showToast('분석 공유 링크가 클립보드에 복사되었습니다! 🔗', 'success');
    }).catch(() => {
        showToast('클립보드 복사 실패. 주소창의 URL을 공유해 주세요.', 'error');
    });
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
        <p class="text-slate-200 font-semibold text-xs sm:text-sm"><span class="text-[10px] sm:text-xs text-slate-500">Team A:</span> ${banA} <span class="text-[9px] sm:text-[10px] text-red-400 bg-red-950/40 px-1.5 py-0.5 rounded border border-red-900/30">${banReasonA}</span></p>
        <p class="text-slate-200 font-semibold text-xs sm:text-sm"><span class="text-[10px] sm:text-xs text-slate-500">Team B:</span> ${banB} <span class="text-[9px] sm:text-[10px] text-red-400 bg-red-950/40 px-1.5 py-0.5 rounded border border-red-900/30">${banReasonB}</span></p>
    `;
    
    pickList.innerHTML = `
        <p class="text-slate-200 font-semibold text-xs sm:text-sm"><span class="text-[10px] sm:text-xs text-slate-500">Team A:</span> ${pickA} <span class="text-[9px] sm:text-[10px] text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-900/30">핵심 카드 픽</span></p>
        <p class="text-slate-200 font-semibold text-xs sm:text-sm"><span class="text-[10px] sm:text-xs text-slate-500">Team B:</span> ${pickB} <span class="text-[9px] sm:text-[10px] text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-900/30">핵심 카드 픽</span></p>
    `;
}

// 8. Update UI status display
function updateStatus(type, title, desc, progressVal) {
    statusText.textContent = title;
    subStatusText.textContent = desc;
    
    // Status style mapping
    if (type === 'success') {
        statusIconContainer.className = 'p-1.5 sm:p-2 bg-emerald-500/10 border border-emerald-500/20 rounded-xl';
        statusIcon.setAttribute('data-lucide', 'check-circle');
    } else if (type === 'error') {
        statusIconContainer.className = 'p-1.5 sm:p-2 bg-red-500/10 border border-red-500/20 rounded-xl';
        statusIcon.setAttribute('data-lucide', 'x-circle');
    } else if (type === 'info') {
        statusIconContainer.className = 'p-1.5 sm:p-2 bg-sky-500/10 border border-sky-500/20 rounded-xl';
        statusIcon.setAttribute('data-lucide', 'loader-2');
    } else {
        statusIconContainer.className = 'p-1.5 sm:p-2 bg-slate-800/50 rounded-xl';
        statusIcon.setAttribute('data-lucide', 'info');
    }
    
    // Update progress bar
    if (progressVal > 0) {
        progressBar.style.width = `${progressVal}%`;
    } else {
        progressBar.style.width = '0%';
    }
    
    // Trigger icons refresh — Lucide replaces the element with a new SVG,
    // so we must query the fresh element afterwards to add/remove spin class.
    lucide.createIcons();
    
    // Re-query the icon after Lucide replaces it
    const freshIcon = statusIconContainer.querySelector('svg');
    if (freshIcon) {
        const wClass = type === 'info' ? 'w-4 h-4 sm:w-5 sm:h-5' : 'w-4 h-4 sm:w-5 sm:h-5';
        let colorClass = 'text-slate-400';
        if (type === 'success') colorClass = 'text-emerald-400';
        else if (type === 'error') colorClass = 'text-red-400';
        else if (type === 'info') colorClass = 'text-sky-400';
        
        freshIcon.setAttribute('class', `${wClass} ${colorClass}`);
        
        // Only spin during 'info' (loading) state
        if (type === 'info') {
            freshIcon.classList.add('animate-spin');
        }
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
    seriesScoreEl.innerHTML = `<span class="break-all">${teamA}</span> <span class="text-emerald-400 font-extrabold">${scoreData.series_score_a}</span> : <span class="text-emerald-400 font-extrabold">${scoreData.series_score_b}</span> <span class="break-all">${teamB}</span>`;
    
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
            card.className = 'bg-zinc-950/80 border border-slate-800/80 rounded-xl p-2 sm:p-3 flex flex-col items-center justify-center space-y-1';
            
            const mapNameEl = document.createElement('span');
            mapNameEl.className = 'text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider';
            mapNameEl.textContent = m.map;
            
            const scoreEl = document.createElement('span');
            scoreEl.className = 'text-xs sm:text-sm font-extrabold text-white';
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
