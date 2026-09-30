MatchUI.renderHero = function(match, model) {
    const hero = document.getElementById('match-hero');
    const status = model?.status || matchStatus(match);
    hero.dataset.matchState = status;
    hero.dataset.balance = model?.balance || 'unknown';
    const labels = {upcoming: '경기 예정', live: '진행 중', final: '최종 결과', unknown: '경기 정보'};
    MatchUI.text('hero-phase', labels[status] || labels.unknown);
    MatchUI.text('hero-data-note', status === 'final' ? '확정 스코어 · 과거 기록과 구분해 확인하세요'
        : status === 'live' ? '라이브 스코어 · 최근 조회 기준'
        : '맵 승률은 수집된 과거 기록입니다. 이 경기의 예측 확률이 아닙니다.');
};
