// Shared presentation helpers. All data still comes from the existing API.
const MatchUI = {
    analysis: null,
    matchId: null,
    text(id, value) { document.getElementById(id).textContent = value ?? ''; },
    number(value, digits = 0) {
        return Number.isFinite(value) ? value.toLocaleString('ko-KR', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '—';
    },
    mapRate(record) {
        return record && Number.isFinite(record.played) && record.played > 0 &&
            Number.isFinite(record.w) && record.w >= 0 && record.w <= record.played ? record.w / record.played * 100 : null;
    },
    series(match) {
        const score = match?.live_score || match?.selection_data?.live_score;
        if (!score || !['live', 'final'].includes(matchStatus(match))) return null;
        const values = [score.series_score_a, score.series_score_b];
        if (!values.every(value => /^\d{1,2}$/.test(String(value ?? '')))) return null;
        return {a: Number(values[0]), b: Number(values[1])};
    },
    mapRecords(data, match) {
        const pool = match?.map_pool?.length ? match.map_pool : FALLBACK_MAP_POOL;
        return pool.map(name => {
            const a = data?.maps_a?.[name], b = data?.maps_b?.[name];
            const rateA = MatchUI.mapRate(a), rateB = MatchUI.mapRate(b);
            const comparable = rateA !== null && rateB !== null && a.played >= MIN_MAP_SAMPLE && b.played >= MIN_MAP_SAMPLE;
            return {name, a, b, rateA, rateB, comparable, delta: comparable ? rateA - rateB : null};
        }).filter(row => row.rateA !== null || row.rateB !== null);
    },
    recent(data, side) {
        const items = data?.[`recent_${side}`]?.length ? data[`recent_${side}`] : data?.[`form_${side}`] || [];
        const results = items.slice(0, 5).map(parseFormResult).filter(item => ['W', 'L', 'D'].includes(item.result));
        return {count: results.length, wins: results.filter(item => item.result === 'W').length};
    }
};
