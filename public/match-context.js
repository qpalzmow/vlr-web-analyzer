const KST = 'Asia/Seoul';
const MATCH_STATUSES = { live: '진행 중', upcoming: '예정', final: '종료', unknown: '상태 확인 중' };

function vlrLink(kind, id) {
    return /^\d{1,12}$/.test(String(id || '')) ? `https://www.vlr.gg/${kind ? kind + '/' : ''}${id}${kind === 'player' ? '/?timespan=all' : ''}` : '';
}

function sourceAnchor(text, url) {
    let valid = false;
    try {
        const parsed = new URL(url);
        valid = parsed.protocol === 'https:' && ['www.vlr.gg', 'vlr.gg'].includes(parsed.hostname) &&
            /^\/(?:\d+|(?:team|player|event)\/\d+)(?:\/|$)/.test(parsed.pathname) && !parsed.username && !parsed.password;
    } catch { /* Legacy records may not contain source links. */ }
    return valid ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(text)}</a>` : escapeHTML(text);
}

function setSourceLink(id, url) {
    const element = document.getElementById(id);
    if (url) element.setAttribute('href', url);
    else element.removeAttribute('href');
}

function matchTimestamp(match) {
    const value = match.live_score?.scheduled_at || match.scheduled_at || match.selection_data?.details?.scheduled_at;
    if (!value || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date : null;
}

function kstDay(date) {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: KST, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date);
    return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type).value).join('-');
}

function matchDay(match) {
    const stamp = matchTimestamp(match);
    if (stamp) return kstDay(stamp);
    // Legacy dates identify a day only; never infer a timezone from an AM/PM clock.
    const old = String(match.date || '').match(/\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(20\d{2})\b/i);
    if (!old) return '';
    const months = ['january','february','march','april','may','june','july','august','september','october','november','december'];
    return `${old[3]}-${String(months.indexOf(old[1].toLowerCase()) + 1).padStart(2, '0')}-${old[2].padStart(2, '0')}`;
}

function formatDay(day, relative = false) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day || '')) return '날짜 확인 중';
    const stamp = new Date(day + 'T12:00:00Z');
    if (!Number.isFinite(stamp.getTime())) return '날짜 확인 중';
    const label = new Intl.DateTimeFormat('ko-KR', {timeZone: KST, year: 'numeric', month: 'short', day: 'numeric', weekday: 'short'}).format(stamp);
    const today = kstDay(new Date());
    const yesterday = kstDay(new Date(Date.now() - 86400000));
    return label + (relative && day === today ? ' · 오늘' : relative && day === yesterday ? ' · 어제' : '');
}

function matchClock(match) {
    const stamp = matchTimestamp(match);
    return stamp ? new Intl.DateTimeFormat('ko-KR', { timeZone: KST, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(stamp) : '시간 확인 중';
}

function formatMatchSchedule(match) {
    return `${formatDay(matchDay(match))} · ${matchClock(match)}${matchTimestamp(match) ? ' KST' : ''}`;
}

function matchStatus(match) {
    const status = match.live_score?.status || match.status_code || match.selection_data?.live_score?.status;
    if (['live', 'final', 'upcoming'].includes(status)) return status;
    const text = String(match.status || '').toLowerCase();
    if (/\blive\b/.test(text)) return 'live';
    if (/\b(completed|final)\b/.test(text)) return 'final';
    if (/\b(upcoming|pending)\b|\d+\s*[dhms]/.test(text)) return 'upcoming';
    return 'unknown';
}

function matchesSearch(match) {
    const text = `${match.team_a} ${match.team_b} ${cleanTournamentName(match)} ${tournamentDisplayName(cleanTournamentName(match))}`.toLowerCase();
    return matchSearchQuery.toLowerCase().trim().split(/\s+/).filter(Boolean).every(word => text.includes(word));
}

function renderMatchBrowser() {
    const filters = document.getElementById('match-status-filters');
    filters.innerHTML = '';
    for (const [status, label] of [['all', '전체'], ['live', '진행 중'], ['upcoming', '예정'], ['final', '종료']]) {
        const count = status === 'all' ? filteredMatches.length : filteredMatches.filter(m => matchStatus(m) === status).length;
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = `${label} ${count}`;
        button.setAttribute('aria-pressed', String(selectedMatchStatus === status));
        button.addEventListener('click', () => { selectedMatchStatus = status; renderMatchBrowser(); });
        filters.appendChild(button);
    }
    const body = document.getElementById('match-browser');
    const scrollTop = body.scrollTop;
    body.innerHTML = '';
    const matches = filteredMatches.filter(m => selectedMatchStatus === 'all' || matchStatus(m) === selectedMatchStatus);
    const priority = { live: 0, upcoming: 1, final: 2, unknown: 3 };
    matches.sort((a, b) => priority[matchStatus(a)] - priority[matchStatus(b)] ||
        (matchStatus(a) === 'final' ? (matchTimestamp(b)?.getTime() || 0) - (matchTimestamp(a)?.getTime() || 0) :
            (matchTimestamp(a)?.getTime() || 0) - (matchTimestamp(b)?.getTime() || 0)) || String(a.id).localeCompare(String(b.id), 'en', {numeric:true}));
    let lastHeading = '';
    for (const match of matches) {
        const headingText = `${MATCH_STATUSES[matchStatus(match)]} · ${formatDay(matchDay(match), true)}`;
        if (lastHeading !== headingText) {
            const heading = document.createElement('h3');
            heading.className = 'match-date-heading';
            heading.textContent = headingText;
            body.appendChild(heading);
            lastHeading = headingText;
        }
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'match-row';
        row.setAttribute('aria-pressed', String(selectedMatch?.id === match.id));
        row.disabled = !match.selection_data;
        const score = match.live_score || match.selection_data?.live_score;
        const state = row.disabled ? match.selection_status === 'unassigned' ? '대진 미정' : '업데이트 대기' : MATCH_STATUSES[matchStatus(match)];
        const scoreText = ['live', 'final'].includes(score?.status) ? `${score.series_score_a} : ${score.series_score_b}` : 'vs';
        row.innerHTML = `<span class="match-row-time">${escapeHTML(matchClock(match))}</span><span class="match-row-teams"><span>${escapeHTML(match.team_a)} <span class="muted">${escapeHTML(scoreText)}</span> ${escapeHTML(match.team_b)}</span><small>${escapeHTML(matchRoundLabel(match) || tournamentDisplayName(cleanTournamentName(match)))}</small></span><span class="match-row-state${matchStatus(match) === 'live' ? ' positive' : ''}">${escapeHTML(state)}</span>`;
        row.addEventListener('click', () => {
            matchSelect.value = String(filteredMatches.findIndex(item => item.id === match.id));
            void handleMatchSelection();
        });
        body.appendChild(row);
    }
    document.getElementById('match-results-count').textContent = `${matches.length}경기 · KST`;
    if (!matches.length) body.innerHTML = '<p class="empty-row">조건에 맞는 경기가 없습니다. 검색어나 상태 필터를 변경해 주세요.</p>';
    body.scrollTop = scrollTop || 0;
}

function renderFixtureContext(match = selectedMatch) {
    if (!match) return;
    const details = match.selection_data?.details || {};
    const score = match.live_score || match.selection_data?.live_score;
    const state = matchStatus(match);
    document.getElementById('report-fixture').textContent = [matchRoundLabel(match), formatMatchSchedule(match)].filter(Boolean).join(' · ');
    document.getElementById('match-summary-score').textContent = ['live', 'final'].includes(state) && score ? `${score.series_score_a} : ${score.series_score_b}` : 'vs';
    document.getElementById('match-summary-status').textContent = MATCH_STATUSES[state];
    document.getElementById('match-summary-status').dataset.live = String(state === 'live');
    document.getElementById('match-summary-format').textContent = score?.match_format || details.match_format || '';
    setSourceLink('match-source', vlrLink('', match.id));
    setSourceLink('report-event', vlrLink('event', details.event_id));
    for (const side of ['a', 'b']) setSourceLink(`team-${side}-source`, vlrLink('team', details[`team_${side}_id`]));
    const veto = score?.actual_veto?.length ? score.actual_veto : details.actual_veto || [];
    const panel = document.getElementById('confirmed-veto');
    panel.hidden = !veto.length && state !== 'final';
    const list = document.getElementById('confirmed-veto-list');
    list.innerHTML = '';
    for (const item of veto) {
        if (!['ban','pick','remaining'].includes(item.action)) continue;
        const row = document.createElement('li');
        row.className = 'veto-entry';
        row.innerHTML = `<span>${escapeHTML(item.team || '')}</span><span class="veto-action">${{ban:'밴',pick:'픽',remaining:'남은 맵'}[item.action]}</span><strong>${escapeHTML(item.map)}</strong>`;
        list.appendChild(row);
    }
    document.getElementById('confirmed-veto-note').textContent = veto.length ? 'VLR에 공개된 실제 밴·픽 순서입니다.' : '공개된 확정 밴·픽 기록이 없습니다.';
    const outlook = document.getElementById('map-outlook');
    const key = `${match.id}:${Boolean(veto.length)}:${state}`;
    if (outlook.dataset.context !== key) outlook.open = !veto.length && state !== 'final';
    outlook.dataset.context = key;
}

function renderTeamLogos(data, match) {
    for (const side of ['a', 'b']) {
        const image = document.getElementById(`team-${side}-logo`);
        const details = match.selection_data?.details || {};
        const tid = details[`team_${side}_id`];
        const available = Boolean(data[`logo_${side}`] || details[`team_${side}_logo`]) && /^\d{1,12}$/.test(tid || '');
        image.hidden = !available;
        image.alt = `${match[`team_${side}`]} 로고`;
        image.onerror = () => { image.hidden = true; };
        if (available) image.setAttribute('src', `/api/team-logo/${tid}`);
        else image.removeAttribute('src');
    }
}

function renderCareerRoster(rosterA, rosterB) {
    careerRows = [];
    for (const [side, roster] of [['a', rosterA], ['b', rosterB]]) {
        if (Array.isArray(roster) && roster.length) careerRows.push(...roster.map(player => ({...player, side})));
        else careerRows.push({nickname: reportTeamName(side), side, available: false, rosterUnavailable: true});
    }
    renderRosterTable();
}

function renderRosterTable() {
    const body = document.getElementById('career-roster-body');
    body.innerHTML = '';
    const rows = [...careerRows].sort((a,b) => (careerSort === 'team' ? a.side.localeCompare(b.side) : 0) ||
        Number(b.available) - Number(a.available) || (b.acs || 0) - (a.acs || 0) || (b.rounds || 0) - (a.rounds || 0) || a.nickname.localeCompare(b.nickname));
    let previousSide = '';
    for (const player of rows) {
        const row = document.createElement('tr');
        if (careerSort === 'team' && previousSide && previousSide !== player.side) row.className = 'roster-team-divider';
        previousSide = player.side;
        const available = hasCareerPlayerStats(player);
        const number = (value, digits) => available && Number.isFinite(value) ? value.toLocaleString('ko-KR', digits === undefined ? {} : {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '—';
        const name = sourceAnchor(player.nickname, vlrLink('player', player.player_id));
        const team = sourceAnchor(reportTeamName(player.side), vlrLink('team', selectedMatch?.selection_data?.details?.[`team_${player.side}_id`]));
        const status = player.rosterUnavailable ? '현역 명단 수집 대기' : !available ? '커리어 기록 없음' : '';
        row.innerHTML = `<th scope="row">${name}${status ? `<small class="map-note">${status}</small>` : ''}</th><td class="team-${player.side}">${team}</td><td class="number">${number(player.acs,1)}</td><td class="number">${number(player.kd_ratio,2)}</td><td class="number">${available && Number.isFinite(player.kd_margin) && player.kd_margin > 0 ? '+' : ''}${number(player.kd_margin)}</td><td class="number">${number(player.rounds)}</td><td class="roster-agents">${escapeHTML(available && player.agents?.length ? player.agents.join(', ') : '—')}</td>`;
        body.appendChild(row);
    }
    if (!rows.length) body.innerHTML = '<tr><td colspan="7" class="empty-row">전력 분석 후 현역 선수 명단을 표시합니다.</td></tr>';
    document.querySelectorAll('#roster-sort button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.sort === careerSort)));
}
