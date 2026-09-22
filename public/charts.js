// Chart.js Manager
let careerAcsChartInstance = null;
let acsTrendChartInstance = null;

function destroyCharts() {
    if (careerAcsChartInstance) {
        careerAcsChartInstance.destroy();
        careerAcsChartInstance = null;
    }
    if (acsTrendChartInstance) {
        acsTrendChartInstance.destroy();
        acsTrendChartInstance = null;
    }
}

function hasCareerPlayerStats(ace) {
    return ace?.available === true && ace.nickname && ace.nickname !== 'N/A' && Number.isFinite(ace.acs);
}

function renderCareerAcsChart(aceA, aceB, emptyMessage = '확인 가능한 현역 선수 기록 없음') {
    const canvas = document.getElementById('career-acs-chart');
    const empty = document.getElementById('career-acs-empty');
    if (careerAcsChartInstance) {
        careerAcsChartInstance.destroy();
        careerAcsChartInstance = null;
    }
    const players = [
        { ace: aceA, color: '#0ea5e9', team: selectedMatch?.team_a || 'Team A' },
        { ace: aceB, color: '#f97316', team: selectedMatch?.team_b || 'Team B' }
    ].filter(player => hasCareerPlayerStats(player.ace));
    const canDraw = players.length > 0 && typeof Chart !== 'undefined';
    if (canvas) canvas.hidden = !canDraw;
    if (empty) {
        empty.hidden = canDraw;
        empty.textContent = players.length && !canDraw ? '차트를 불러오지 못했습니다. 위 카드에서 수치를 확인하세요.' : emptyMessage;
    }
    if (!canvas || !canDraw) return;
    canvas.setAttribute('aria-label', players.map(({ ace, team }) => `${team} ${ace.nickname}: 커리어 ACS ${ace.acs.toFixed(1)}`).join(', '));

    careerAcsChartInstance = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: players.map(({ ace, team }) => `${team} · ${ace.nickname}`),
            datasets: [{
                label: '커리어 ACS',
                data: players.map(({ ace }) => ace.acs),
                backgroundColor: players.map(({ color }) => color),
                maxBarThickness: 36
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: item => `커리어 ACS: ${item.raw.toFixed(1)}` } }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    min: 0,
                    title: { display: true, text: '커리어 ACS', color: '#94a3b8' },
                    grid: { color: 'rgba(255,255,255,0.1)' },
                    ticks: { color: '#94a3b8' }
                },
                y: { grid: { display: false }, ticks: { color: '#cbd5e1', font: { size: 10 } } }
            }
        }
    });
}

function parseFormScore(formItem) {
    if (!formItem) return 50;
    const str = String(formItem).toUpperCase();
    if (str.startsWith('W')) {
        if (str.includes('2-0')) return 100;
        if (str.includes('2-1')) return 75;
        return 90;
    }
    if (str.startsWith('L')) {
        if (str.includes('1-2')) return 30;
        if (str.includes('0-2')) return 10;
        return 20;
    }
    return 50;
}

function renderAcsTrendChart(formA, formB) {
    const canvas = document.getElementById('acs-trend-chart');
    if (!canvas || typeof Chart === 'undefined') return;

    if (acsTrendChartInstance) {
        acsTrendChartInstance.destroy();
        acsTrendChartInstance = null;
    }

    const nameA = selectedMatch ? selectedMatch.team_a : 'Team A';
    const nameB = selectedMatch ? selectedMatch.team_b : 'Team B';

    // Deterministic Form Rating without Math.random()
    const trendA = (formA || []).map(parseFormScore).reverse();
    const trendB = (formB || []).map(parseFormScore).reverse();

    const maxLen = Math.max(trendA.length, trendB.length);
    trendA.unshift(...Array(maxLen - trendA.length).fill(null));
    trendB.unshift(...Array(maxLen - trendB.length).fill(null));
    const labels = Array.from({ length: maxLen }, (_, i) => `${maxLen - i}경기 전`);

    acsTrendChartInstance = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: `${nameA} 모멘텀`,
                    data: trendA,
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.12)',
                    tension: 0.3,
                    fill: true
                },
                {
                    label: `${nameB} 모멘텀`,
                    data: trendB,
                    borderColor: '#fb923c',
                    backgroundColor: 'rgba(251, 146, 60, 0.12)',
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#94a3b8', font: { size: 10 } } }
            },
            scales: {
                x: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: {
                    ticks: { color: '#64748b', stepSize: 25 },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    min: 0,
                    max: 100
                }
            }
        }
    });
}
