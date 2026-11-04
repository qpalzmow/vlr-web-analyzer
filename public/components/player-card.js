MatchUI.renderPlayerCard = function(data, match) {
    for (const side of ['a', 'b']) {
        const ace = data[`ace_${side}`];
        const available = hasCareerPlayerStats(ace);
        MatchUI.text(`impact-${side}-team`, match[`team_${side}`]);
        MatchUI.text(`impact-${side}-acs`, available ? MatchUI.number(ace.acs, 1) : '—');
        const gaps = available && Array.isArray(ace.players_missing_acs) && ace.players_missing_acs.length
            ? ' · 일부 현역 ACS 미제공' : available && ace.partial ? ' · 일부 현역 기록 없음' : '';
        MatchUI.text(`impact-${side}-detail`, available
            ? `${MatchUI.number(ace.rounds)} 라운드 · K/D ${MatchUI.number(ace.kd_ratio, 2)}${gaps}` : careerCoverageText(ace));
        const name = document.getElementById(`summary-${side}-player`);
        name.innerHTML = available ? sourceAnchor(ace.nickname, vlrLink('player', ace.player_id)) : 'ACS 대표 선정 불가';
    }
};
