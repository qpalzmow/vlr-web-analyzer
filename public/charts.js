// Legacy entry points retained for the analysis pipeline; all values are now tables.
function hasCareerPlayerStats(ace) {
    return ace?.available === true && ace.acs_available !== false && Number.isFinite(ace.rounds) && ace.rounds > 0 &&
        typeof ace.nickname === 'string' && ace.nickname && ace.nickname !== 'N/A' &&
        Number.isFinite(ace.acs) && ace.acs >= 0;
}
function hasCareerRosterStats(player) {
    return player?.available === true && Number.isFinite(player.rounds) && player.rounds > 0;
}
function careerUnavailableMessage(player) {
    const reasons = {
        career_not_ready: '현역 선수 커리어 수집 대기 중',
        roster_unverified: '현역 선수 명단을 확인할 수 없어 비교 불가',
        no_roster: '확인 가능한 현역 선수 명단 없음',
        no_player_stats: '확인 가능한 현역 선수 기록 없음',
        source_acs_missing: 'ACS 원본 미제공 · 라운드·K/D는 전체 선수 표에서 확인'
    };
    return reasons[player?.unavailable_reason || player?.acs_unavailable_reason] || '확인 가능한 현역 선수 기록 없음';
}
function careerCoverageText(ace) {
    const count = value => Number.isInteger(value) && value >= 0;
    const names = value => Array.isArray(value) ? value.filter(name => typeof name === 'string' && name) : [];
    const hasStats = count(ace?.players_with_stats) && ace.players_with_stats > 0 && count(ace?.roster_size);
    if (!hasCareerPlayerStats(ace) && !hasStats) return careerUnavailableMessage(ace);
    const parts = [];
    if (hasStats) parts.push(`기록 있는 현역 ${ace.players_with_stats}/${ace.roster_size}명 기준`);
    if (count(ace?.players_with_acs) && count(ace?.roster_size)) parts.push(`ACS 확인 ${ace.players_with_acs}/${ace.roster_size}명`);
    const missing = names(ace?.missing_players), missingAcs = names(ace?.players_missing_acs);
    if (missing.length) parts.push(`기록 없음: ${missing.join(', ')}`);
    if (missingAcs.length) parts.push(`ACS 미제공: ${missingAcs.join(', ')}`);
    if (!hasCareerPlayerStats(ace)) parts.push(careerUnavailableMessage(ace));
    return parts.join(' · ') || '확인된 전체 커리어 기록 기준';
}
function destroyCharts() {
    document.getElementById('acs-trend-chart').innerHTML = '';
}
function renderCareerAcsChart(aceA, aceB, emptyMessage = '확인 가능한 현역 선수 기록 없음') {
    const available = [aceA, aceB].some(hasCareerPlayerStats);
    const empty = document.getElementById('career-acs-empty');
    empty.hidden = available;
    const statsOnly = [aceA, aceB].some(ace => ace?.players_with_stats > 0 && ace.unavailable_reason === 'source_acs_missing');
    empty.textContent = !available && statsOnly
        ? 'ACS를 확인할 수 없어 대표 선수 비교를 표시하지 않습니다. 라운드·K/D는 전체 선수 표에서 확인할 수 있습니다.' : emptyMessage;
    // Keep both rows visible so unavailable values and coverage stay inspectable.
    document.getElementById('career-acs-chart').hidden = false;
}
function parseFormResult(item) {
    if (item && typeof item === 'object') {
        const result = ['W','L','D'].includes(item.result) ? item.result : '—';
        const raw = [result, item.score, item.opponent, item.date ? formatDay(item.date) : '', item.event].filter(Boolean).join(' · ');
        return {...item, result, raw};
    }
    const text = String(item || '');
    const result = text.match(/^([WL])\b/i)?.[1].toUpperCase() || '—';
    return { result, score: text.match(/\(([^)]*)\)/)?.[1] || '',
        opponent: text.match(/\bvs\s+(.+)$/i)?.[1] || '', raw: text };
}
function formDetailCell(item) {
    if (!item) return '<td class="muted">기록 없음</td>';
    const f = parseFormResult(item);
    const context = `<small class="form-context">${escapeHTML(f.date ? formatDay(f.date) : '날짜 미수집')}${f.event ? `<br>${escapeHTML(f.event)}` : ''}</small>`;
    return `<td><div class="form-detail"><b class="${f.result === 'W' ? 'win' : f.result === 'L' ? 'loss' : ''}">${f.result}</b><span>${sourceAnchor(f.opponent || f.raw, f.url)}<small class="form-score">${escapeHTML(f.score)}</small>${context}</span></div></td>`;
}
function renderAcsTrendChart(formA, formB) {
    const a = (formA || []).slice(0, 5), b = (formB || []).slice(0, 5);
    const body = document.getElementById('acs-trend-chart');
    body.innerHTML = '';
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
        const row = document.createElement('tr');
        row.innerHTML = `<th scope="row">${i === 0 ? '최근' : i + 1}</th>${formDetailCell(a[i])}${formDetailCell(b[i])}`;
        body.appendChild(row);
    }
    if (!a.length && !b.length) body.innerHTML = '<tr><td colspan="3" class="empty-row">수집된 최근 경기 기록이 없습니다.</td></tr>';
}
