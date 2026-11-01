MatchUI.buildMatchSummary = function(data, match) {
    const status = matchStatus(match), score = MatchUI.series(match);
    const maps = MatchUI.mapRecords(data, match);
    const comparable = maps.filter(row => row.comparable);
    const advantage = comparable.filter(row => Math.abs(row.delta) >= 10).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
    const meanDelta = comparable.length >= 2 ? comparable.reduce((sum, row) => sum + row.delta, 0) / comparable.length : null;
    const balance = meanDelta === null ? 'unknown' : Math.abs(meanDelta) <= 5 ? 'close' : meanDelta > 10 ? 'a' : meanDelta < -10 ? 'b' : 'balanced';
    const model = {status, balance, maps, comparable, score, kicker: '기록 비교', title: '', detail: ''};
    const formA = MatchUI.recent(data, 'a'), formB = MatchUI.recent(data, 'b');
    const formLeader = formA.count >= 3 && formA.count === formB.count && formA.wins !== formB.wins
        ? formA.wins > formB.wins ? 'a' : 'b' : null;
    // Match status and the actual score belong to the hero. This paragraph
    // adds historical context using the same minimum samples for every phase.
    if (advantage.length) {
        const top = advantage[0];
        const side = top.delta > 0 ? 'a' : 'b', team = match[`team_${side}`];
        model.title = `${team}는 ${top.name}의 과거 맵 승률에서 앞섭니다.`;
        model.detail = `${top.name}에서 ${MatchUI.number(Math.abs(top.delta), 1)}%p 차이 · 양 팀 각각 ${top.a.played}맵 / ${top.b.played}맵 기록.`;
        if (formLeader && formLeader !== side) {
            model.detail += ` 최근 ${formA.count}경기에서는 ${match[`team_${formLeader}`]}의 승수가 더 많습니다.`;
        }
    } else if (comparable.length) {
        model.title = '비교 가능한 맵의 기록 차이가 크지 않습니다.';
        model.detail = `양 팀 모두 ${MIN_MAP_SAMPLE}맵 이상 기록이 있는 ${comparable.length}개 맵의 승률 차이가 10%p 미만입니다.`;
        if (formLeader && Math.abs(formA.wins - formB.wins) >= 2) {
            model.detail += ` 최근 ${formA.count}경기에서는 ${match[`team_${formLeader}`]}의 승수가 더 많습니다.`;
        }
    } else {
        model.title = '맵별 표본을 먼저 확인하세요.';
        model.detail = `양 팀 모두 ${MIN_MAP_SAMPLE}맵 이상 기록이 있는 공통 맵이 없습니다. 작은 표본의 승률은 우위 비교에서 제외합니다.`;
    }
    return model;
};

MatchUI.renderInsights = function(data, match, model) {
    MatchUI.text('insight-kicker', model.kicker);
    MatchUI.text('insight-title', model.title);
    MatchUI.text('insight-detail', model.detail);
    for (const side of ['a', 'b']) {
        const form = MatchUI.recent(data, side);
        MatchUI.text(`insight-form-${side}`, match[`team_${side}`]);
        MatchUI.text(`insight-form-note-${side}`, form.count ? `최근 ${form.count}경기 · ${form.wins}승` : '최근 기록 없음');
    }
    const note = document.getElementById('insight-freshness');
    note.hidden = !data.stale;
    note.textContent = data.stale ? '일부 기록의 갱신이 지연되어 이전 수집본을 사용합니다.' : '';
};
