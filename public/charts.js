// Chart.js Manager
let aceRadarChartInstance = null;
let acsTrendChartInstance = null;

function destroyCharts() {
    if (aceRadarChartInstance) {
        aceRadarChartInstance.destroy();
        aceRadarChartInstance = null;
    }
    if (acsTrendChartInstance) {
        acsTrendChartInstance.destroy();
        acsTrendChartInstance = null;
    }
}

function renderAceRadarChart(aceA, aceB) {
    const canvas = document.getElementById('ace-radar-chart');
    if (!canvas || typeof Chart === 'undefined') return;

    if (aceRadarChartInstance) {
        aceRadarChartInstance.destroy();
        aceRadarChartInstance = null;
    }

    const nickA = (aceA && aceA.nickname !== 'N/A') ? aceA.nickname : (selectedMatch ? selectedMatch.team_a + ' Ace' : 'Team A Ace');
    const nickB = (aceB && aceB.nickname !== 'N/A') ? aceB.nickname : (selectedMatch ? selectedMatch.team_b + ' Ace' : 'Team B Ace');

    const acsA = aceA ? (aceA.acs || 0) : 0;
    const acsB = aceB ? (aceB.acs || 0) : 0;
    const kdMarginA = aceA ? (aceA.kd_margin || 0) : 0;
    const kdMarginB = aceB ? (aceB.kd_margin || 0) : 0;
    const agentsCountA = (aceA && Array.isArray(aceA.agents)) ? aceA.agents.filter(a => a !== 'N/A').length : 1;
    const agentsCountB = (aceB && Array.isArray(aceB.agents)) ? aceB.agents.filter(a => a !== 'N/A').length : 1;

    // Normalized 0-100 real metrics without hardcoded constants
    const metricsA = [
        Math.min(100, Math.round(acsA / 3.0)),                         // ACS Score (300 ACS = 100)
        Math.max(0, Math.min(100, Math.round(50 + kdMarginA * 2.5))),  // K/D Margin Index
        Math.min(100, agentsCountA * 33),                             // Agent Pool Breadth
        Math.max(0, Math.min(100, Math.round(acsA / 2.5)))             // Impact Rating
    ];
    const metricsB = [
        Math.min(100, Math.round(acsB / 3.0)),
        Math.max(0, Math.min(100, Math.round(50 + kdMarginB * 2.5))),
        Math.min(100, agentsCountB * 33),
        Math.max(0, Math.min(100, Math.round(acsB / 2.5)))
    ];

    aceRadarChartInstance = new Chart(canvas, {
        type: 'radar',
        data: {
            labels: ['전투 지수 (ACS)', '킬/데스 마진', '요원 풀 다양성', '임팩트 레이팅'],
            datasets: [
                {
                    label: nickA,
                    data: metricsA,
                    backgroundColor: 'rgba(14, 165, 233, 0.25)',
                    borderColor: '#0ea5e9',
                    pointBackgroundColor: '#0ea5e9'
                },
                {
                    label: nickB,
                    data: metricsB,
                    backgroundColor: 'rgba(249, 115, 22, 0.25)',
                    borderColor: '#f97316',
                    pointBackgroundColor: '#f97316'
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
                r: {
                    angleLines: { color: 'rgba(255,255,255,0.1)' },
                    grid: { color: 'rgba(255,255,255,0.1)' },
                    pointLabels: { color: '#cbd5e1', font: { size: 10 } },
                    ticks: { display: false, min: 0, max: 100 }
                }
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
