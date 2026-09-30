MatchUI.buildMatchSummary = function(data, match) {
    const status = matchStatus(match), score = MatchUI.series(match);
    const maps = MatchUI.mapRecords(data, match);
    const comparable = maps.filter(row => row.comparable);
    const advantage = comparable.filter(row => Math.abs(row.delta) >= 10).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
    const meanDelta = comparable.length >= 2 ? comparable.reduce((sum, row) => sum + row.delta, 0) / comparable.length : null;
    const balance = meanDelta === null ? 'unknown' : Math.abs(meanDelta) <= 5 ? 'close' : meanDelta > 10 ? 'a' : meanDelta < -10 ? 'b' : 'balanced';
    const model = {status, balance, maps, comparable, score, kicker: '기록을 보는 관점', title: '', detail: ''};
    if (status === 'final') {
        model.kicker = '확정 결과';
        model.title = !score || score.a + score.b === 0 ? '최종 스코어를 확인하고 있습니다.' : score.a === score.b
            ? `${match.team_a}와 ${match.team_b}, ${score.a} : ${score.b}로 종료.`
            : `${score.a > score.b ? match.team_a : match.team_b} 승리. 최종 스코어는 ${Math.max(score.a, score.b)} : ${Math.min(score.a, score.b)}입니다.`;
        model.detail = '맵별 결과와 공개된 밴픽을 먼저 확인하세요. 아래 맵 승률과 선수 ACS는 과거 기록·전체 커리어 기준입니다.';
    } else if (status === 'live') {
        model.kicker = '현재 스코어';
        model.title = !score ? '경기가 진행 중입니다.' : score.a === score.b ? `현재 ${score.a} : ${score.b}, 동률입니다.`
            : `현재 스코어 ${score.a} : ${score.b}. ${score.a > score.b ? match.team_a : match.team_b} 우세입니다.`;
        model.detail = '라이브 스코어를 먼저 표시합니다. 맵 기록과 커리어 수치는 이 경기의 실시간 선수 성적이 아닙니다.';
    } else if (advantage.length) {
        const top = advantage[0];
        const team = top.delta > 0 ? match.team_a : match.team_b;
        model.title = `${team}는 ${top.name}의 과거 맵 승률에서 앞섭니다.`;
        model.detail = `${top.name}의 기록 차이는 ${MatchUI.number(Math.abs(top.delta), 1)}%p입니다. 양 팀 모두 5맵 이상 기록이 있는 맵만 비교합니다.`;
    } else if (comparable.length) {
        model.title = '비교 가능한 맵의 기록 차이가 크지 않습니다.';
        model.detail = `${comparable.length}개 맵에서 양 팀 표본을 확인했습니다. 공수 기록과 최근 상대팀을 함께 살펴보세요.`;
    } else {
        model.title = '맵별 표본을 먼저 확인하세요.';
        model.detail = '양 팀 모두 5맵 이상 기록이 있는 공통 맵이 부족합니다. 수집된 기록을 표시하되 우세팀이나 승부를 추정하지 않습니다.';
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
