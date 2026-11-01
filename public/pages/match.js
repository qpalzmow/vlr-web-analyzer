MatchUI.reorder = function(status) {
    const container = document.getElementById('report-modules');
    if (container.dataset.phase === status) return;
    // Keep the two half-width map modules together; full-width cards cannot split their row.
    const order = status === 'upcoming' || status === 'unknown'
        ? ['map-preview-card', 'veto-card', 'player-impact-card', 'live-scoreboard-panel']
        : ['live-scoreboard-panel', 'map-preview-card', 'veto-card', 'player-impact-card'];
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
    if (!['ready', 'refreshing', 'refresh-error'].includes(state)) {
        MatchUI.analysis = null;
        MatchUI.matchId = null;
    }
};

MatchUI.preview = function(match) {
    document.getElementById('selection-caption').textContent = `${match.team_a} vs ${match.team_b}`;
    document.getElementById('report-event').textContent = tournamentDisplayName(cleanTournamentName(match));
    for (const side of ['a', 'b']) MatchUI.text(`summary-${side}-rate`, '—');
    renderFixtureContext(match);
    renderTeamLogos({}, match);
    setReportState('preview');
    MatchUI.refresh(match);
};
