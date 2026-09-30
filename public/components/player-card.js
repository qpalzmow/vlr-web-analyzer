MatchUI.renderPlayerCard = function(data, match) {
    for (const side of ['a', 'b']) {
        const ace = data[`ace_${side}`];
        const available = hasCareerPlayerStats(ace);
        MatchUI.text(`impact-${side}-team`, match[`team_${side}`]);
        MatchUI.text(`impact-${side}-acs`, available ? MatchUI.number(ace.acs, 1) : '—');
        MatchUI.text(`impact-${side}-detail`, available ? `${MatchUI.number(ace.rounds)} 라운드 · K/D ${MatchUI.number(ace.kd_ratio, 2)}${ace.partial ? ' · 일부 현역 기록 없음' : ''}` : '현역 선수 커리어 확인 불가');
        const name = document.getElementById(`summary-${side}-player`);
        name.innerHTML = available ? sourceAnchor(ace.nickname, vlrLink('player', ace.player_id)) : '확인 가능한 기록 없음';
    }
};
