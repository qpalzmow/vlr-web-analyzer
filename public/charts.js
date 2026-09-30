// Legacy entry points retained for the analysis pipeline; all values are now tables.
function hasCareerPlayerStats(ace) {
    return ace?.available === true && ace.nickname && ace.nickname !== 'N/A' && Number.isFinite(ace.acs);
}
function destroyCharts() {
    document.getElementById('acs-trend-chart').innerHTML = '';
}
function renderCareerAcsChart(aceA, aceB, emptyMessage = '확인 가능한 현역 선수 기록 없음') {
    const available = [aceA, aceB].some(hasCareerPlayerStats);
    const empty = document.getElementById('career-acs-empty');
    empty.hidden = available;
    empty.textContent = emptyMessage;
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
