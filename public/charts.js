// Chart.js Manager
let aceRadarChartInstance = null;
let acsTrendChartInstance = null;

function renderAceRadarChart(aceA, aceB) {
    const canvas = document.getElementById('ace-radar-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    
    if (aceRadarChartInstance) {
        aceRadarChartInstance.destroy();
    }
    
    const nickA = (aceA && aceA.nickname !== 'N/A') ? aceA.nickname : (selectedMatch ? selectedMatch.team_a + ' Ace' : 'Team A Ace');
    const nickB = (aceB && aceB.nickname !== 'N/A') ? aceB.nickname : (selectedMatch ? selectedMatch.team_b + ' Ace' : 'Team B Ace');
    
    const acsA = aceA ? aceA.acs : 200;
    const acsB = aceB ? aceB.acs : 190;
    
    aceRadarChartInstance = new Chart(canvas, {
        type: 'radar',
        data: {
            labels: ['ACS', 'K/D Margin', 'Round Impact', 'Agent Flexibility', 'First Blood'],
            datasets: [
                {
                    label: nickA,
                    data: [Math.min(300, acsA), Math.max(20, 100 + (aceA ? aceA.kd_margin * 5 : 0)), 85, 78, 82],
                    backgroundColor: 'rgba(14, 165, 233, 0.25)',
                    borderColor: '#0ea5e9',
                    pointBackgroundColor: '#0ea5e9'
                },
                {
                    label: nickB,
                    data: [Math.min(300, acsB), Math.max(20, 100 + (aceB ? aceB.kd_margin * 5 : 0)), 80, 72, 76],
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
                    ticks: { display: false }
                }
            }
        }
    });
}

function renderAcsTrendChart(formA, formB) {
    const canvas = document.getElementById('acs-trend-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    
    if (acsTrendChartInstance) {
        acsTrendChartInstance.destroy();
    }
    
    const nameA = selectedMatch ? selectedMatch.team_a : 'Team A';
    const nameB = selectedMatch ? selectedMatch.team_b : 'Team B';
    
    const trendA = (formA || []).map(f => f.startsWith('W') ? 225 + Math.floor(Math.random()*25) : 175 + Math.floor(Math.random()*25));
    const trendB = (formB || []).map(f => f.startsWith('W') ? 220 + Math.floor(Math.random()*25) : 170 + Math.floor(Math.random()*25));
    
    if (trendA.length === 0) trendA.push(210, 225, 195, 230, 215);
    if (trendB.length === 0) trendB.push(200, 210, 185, 220, 205);
    
    acsTrendChartInstance = new Chart(canvas, {
        type: 'line',
        data: {
            labels: ['1경기 전', '2경기 전', '3경기 전', '4경기 전', '5경기 전'].slice(0, Math.max(trendA.length, trendB.length)),
            datasets: [
                {
                    label: nameA,
                    data: trendA,
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.12)',
                    tension: 0.35,
                    fill: true
                },
                {
                    label: nameB,
                    data: trendB,
                    borderColor: '#fb923c',
                    backgroundColor: 'rgba(251, 146, 60, 0.12)',
                    tension: 0.35,
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
                y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });
}
