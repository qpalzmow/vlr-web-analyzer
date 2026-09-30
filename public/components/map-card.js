MatchUI.renderMapCard = function(data, match, model) {
    for (const side of ['a', 'b']) MatchUI.text(`map-preview-team-${side}`, match[`team_${side}`]);
    const list = document.getElementById('map-preview-list');
    list.innerHTML = '';
    const rows = [...model.maps].sort((a, b) => Number(b.comparable) - Number(a.comparable) ||
        Math.abs(b.delta || 0) - Math.abs(a.delta || 0) || (b.a?.played || 0) + (b.b?.played || 0) - (a.a?.played || 0) - (a.b?.played || 0)).slice(0, 3);
    const rate = (record, value, side) => {
        const available = value !== null;
        const sample = available ? `${record.w}–${record.l} · ${record.played}맵${record.played < MIN_MAP_SAMPLE ? ' · 표본 부족' : ''}` : '기록 없음';
        return `<div class="forecast-line team-${side}"><span>${escapeHTML(match[`team_${side}`])}</span><span class="forecast-track" aria-hidden="true"><i style="left:${available ? Math.max(0, Math.min(100, value)) : 0}%"${available ? '' : ' hidden'}></i></span><b>${available ? Math.round(value) + '%' : '—'}</b><small>${escapeHTML(sample)}</small></div>`;
    };
    for (const row of rows) {
        const block = document.createElement('li');
        block.className = 'forecast-map';
        const difference = kind => {
            const a = row.a, b = row.b;
            if (!row.comparable || !(a?.[`${kind}_total`] > 0) || !(b?.[`${kind}_total`] > 0) ||
                !Number.isFinite(a[`${kind}_won`]) || !Number.isFinite(b[`${kind}_won`])) return '비교 표본 부족';
            const delta = a[`${kind}_won`] / a[`${kind}_total`] * 100 - b[`${kind}_won`] / b[`${kind}_total`] * 100;
            return Math.abs(delta) < 0.05 ? '동률' : `${match[`team_${delta > 0 ? 'a' : 'b'}`]} +${MatchUI.number(Math.abs(delta), 1)}%p`;
        };
        block.innerHTML = `<h4>${escapeHTML(row.name)}</h4>${rate(row.a, row.rateA, 'a')}${rate(row.b, row.rateB, 'b')}<p class="map-differences"><span>공격 ${escapeHTML(difference('atk'))}</span><span>수비 ${escapeHTML(difference('def'))}</span></p>`;
        list.appendChild(block);
    }
    if (!rows.length) list.innerHTML = '<li class="empty-row">현재 맵 풀에 수집된 기록이 없습니다. 상세 표에서 과거 맵 기록을 확인할 수 있습니다.</li>';
    MatchUI.text('map-preview-sample', `현재 맵 풀 기준 · 비교 가능한 표본 ${model.comparable.length}개 맵 · 5맵 미만은 우위 비교에서 제외`);
};
