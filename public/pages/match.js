MatchUI.reorder = function(status) {
    const container = document.getElementById('report-modules');
    if (container.dataset.phase === status) return;
    const order = status === 'upcoming' || status === 'unknown'
        ? ['map-preview-card', 'veto-card', 'player-impact-card', 'live-scoreboard-panel']
        : status === 'live' ? ['live-scoreboard-panel', 'map-preview-card', 'player-impact-card', 'veto-card']
        : ['live-scoreboard-panel', 'veto-card', 'map-preview-card', 'player-impact-card'];
    for (const id of order) container.appendChild(document.getElementById(id));
    container.dataset.phase = status;
};

MatchUI.refresh = function(match = selectedMatch) {
    if (!match) return;
    const data = MatchUI.matchId === match.id ? MatchUI.analysis : null;
    const model = data ? MatchUI.buildMatchSummary(data, match) : null;
    MatchUI.renderHero(match, model);
    if (data) MatchUI.renderInsights(data, match, model);
    MatchUI.reorder(model?.status || matchStatus(match));
    MatchUI.text('live-heading-title', matchStatus(match) === 'final' ? '맵별 결과' : '라이브 스코어');
    MatchUI.text('live-caption', matchStatus(match) === 'final' ? '확정된 경기 스코어' : '최근 조회한 스코어 · 기록 통계와 별도로 갱신됩니다');
    MatchUI.text('veto-phase', matchStatus(match) === 'final' ? '공개된 실제 밴픽과 기록 기반 참고를 구분합니다' : '밴·픽 참고 · 현재 맵 풀의 과거 기록 기준');
};

MatchUI.render = function(data, match) {
    MatchUI.analysis = data;
    MatchUI.matchId = match.id;
    const model = MatchUI.buildMatchSummary(data, match);
    MatchUI.renderMapCard(data, match, model);
    MatchUI.renderPlayerCard(data, match);
    MatchUI.refresh(match);
};

MatchUI.onReportState = function(state) {
    document.getElementById('match-report').dataset.reportState = state;
    if (state !== 'ready') { MatchUI.analysis = null; MatchUI.matchId = null; }
    const button = document.getElementById('hero-analyze-btn');
    button.disabled = state === 'loading' || !selectedMatch?.details_ready;
    button.textContent = state === 'loading' ? '기록을 비교하는 중…' : state === 'ready' ? '다시 분석' : state === 'error' ? '분석 다시 시도' : '매치업 분석';
    MatchUI.text('hero-action-note', state === 'loading' ? '저장된 맵·선수·최근 기록을 한 번에 불러옵니다.'
        : state === 'ready' ? '대회 범위는 위의 경기 선택 메뉴에서 변경할 수 있습니다.'
        : state === 'error' ? '통계를 불러오지 못했습니다. 다시 시도하거나 경기를 변경하세요.'
        : '선택한 경기의 맵·선수·최근 기록을 비교합니다.');
};

MatchUI.preview = function(match) {
    document.getElementById('selection-caption').textContent = `${match.team_a} vs ${match.team_b}`;
    document.getElementById('report-event').textContent = tournamentDisplayName(cleanTournamentName(match));
    for (const side of ['a', 'b']) MatchUI.text(`summary-${side}-rate`, '—');
    renderFixtureContext(match);
    renderTeamLogos({}, match);
    setReportState('preview');
    MatchUI.refresh(match);
    document.getElementById('match-selection-panel').open = false;
};
