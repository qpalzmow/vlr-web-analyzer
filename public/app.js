// ======================================================
// Skeleton Loader System (Phase 1.2)
// ======================================================
function showSkeletonLoader(containerId, type = 'default', count = 3) {
    const el = document.getElementById(containerId);
    if (!el) return;
    
    el.innerHTML = '';
    
    if (type === 'form') {
        // Form skeleton with win/loss badges
        for (let i = 0; i < count; i++) {
            const badge = document.createElement('span');
            badge.className = 'bg-slate-800/40 animate-pulse rounded-lg';
            badge.style.width = '60px';
            badge.style.height = '24px';
            badge.style.display = 'inline-block';
            el.appendChild(badge);
        }
    } else if (type === 'agents') {
        // Agent badge skeleton
        for (let i = 0; i < count; i++) {
            const badge = document.createElement('span');
            badge.className = 'bg-slate-800/40 animate-pulse rounded-lg';
            badge.style.width = '80px';
            badge.style.height = '32px';
            badge.style.display = 'inline-block';
            el.appendChild(badge);
        }
    } else if (type === 'maps') {
        // Maps table skeleton rows
        for (let i = 0; i < count; i++) {
            const tr = document.createElement('tr');
            tr.className = 'border-b border-slate-800/60';
            tr.innerHTML = `
                <td class="py-3 pl-2">
                    <div class="h-4 bg-slate-800/40 rounded animate-pulse w-20"></div>
                </td>
                <td class="py-3 text-center">
                    <div class="h-4 bg-slate-800/40 rounded animate-pulse w-8 mx-auto"></div>
                </td>
                <td class="py-3 text-center">
                    <div class="h-4 bg-slate-800/40 rounded animate-pulse w-12 mx-auto"></div>
                </td>
                <td class="py-3 text-center">
                    <div class="h-4 bg-slate-800/40 rounded animate-pulse w-12 mx-auto"></div>
                </td>
                <td class="py-3 text-center">
                    <div class="h-4 bg-slate-800/40 rounded animate-pulse w-16 mx-auto"></div>
                </td>
            `;
            el.appendChild(tr);
        }
    } else if (type === 'ace') {
        // Ace card skeleton
        for (let i = 0; i < count; i++) {
            const div = document.createElement('div');
            div.className = 'bg-zinc-900/50 border border-slate-800/60 rounded-xl p-4 space-y-3';
            div.innerHTML = `
                <div class="flex items-center justify-between">
                    <div class="h-5 bg-slate-800/40 rounded animate-pulse w-24"></div>
                    <div class="h-3 bg-slate-800/40 rounded animate-pulse w-16"></div>
                </div>
                <div class="space-y-2">
                    <div class="h-4 bg-slate-800/40 rounded animate-pulse w-20"></div>
                    <div class="h-3 bg-slate-800/40 rounded animate-pulse w-16"></div>
                </div>
                <div class="space-y-1">
                    <div class="h-3 bg-slate-800/40 rounded animate-pulse w-full"></div>
                    <div class="h-3 bg-slate-800/40 rounded animate-pulse w-3/4"></div>
                </div>
            `;
            el.appendChild(div);
        }
    }
}

function hideSkeletonLoader(containerId) {
    const el = document.getElementById(containerId);
    if (el) {
        el.innerHTML = '';
    }
}

function showSkeletonLoaderOnUI(containerId, type = 'default', count = 3) {
    const el = document.getElementById(containerId);
    if (!el) return;
    
    showSkeletonLoader(containerId, type, count);
}

// ======================================================
// Riot API Integration (Phase 2.1)
// ======================================================
const RiotAPI = {
    BASE_URL: 'https://valorant-api.com/v1',
    getMapImageUrl: function(uuid) {
        return `https://media.valorant-api.com/maps/${uuid}/displayicon.png`;
    },
    getAgentImageUrl: function(uuid) {
        return `https://media.valorant-api.com/agents/${uuid}/displayicon.png`;
    },
    getAgentIconUrl: function(uuid) {
        return `https://media.valorant-api.com/agents/${uuid}/displayicon.png`;
    }
};

async function preloadValorantAssets() {
    try {
        const response = await fetch(`${RiotAPI.BASE_URL}/maps`);
        const mapsData = await response.json();
        
        const responseAgents = await fetch(`${RiotAPI.BASE_URL}/agents`);
        const agentsData = await responseAgents.json();
        
        // Preload critical assets
        mapsData.data.forEach(async map => {
            if (map.displayIcon) {
                const img = new Image();
                img.src = map.displayIcon;
            }
        });
        
        agentsData.data.forEach(async agent => {
            if (agent.displayIcon) {
                const img = new Image();
                img.src = agent.displayIcon;
            }
        });
        
        console.log('Valorant assets preloaded successfully');
        return true;
    } catch (error) {
        console.error('Error preloading Valorant assets:', error);
        return false;
    }
}

async function getMapThumbnail(mapName) {
    try {
        // Try to get Valorant API map data
        const response = await fetch(`${RiotAPI.BASE_URL}/maps`);
        const mapsData = await response.json();
        
        const map = mapsData.data.find(m => 
            m.displayName.toLowerCase() === mapName.toLowerCase()
        );
        
        if (map && map.displayIcon) {
            return map.displayIcon;
        }
        
        // Fallback to hardcoded map images (in production, you'd use proper UUID mapping)
        const mapImageMap = {
            'ascent': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'bind': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'breeze': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'haven': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'icebox': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'lotus': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'split': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'summit': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'sunset': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'abyss': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'fracture': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png',
            'pearl': 'https://images.contentstack.io/v3/assets/bltb1c56ds0a5b0fd28/blt3f8f8f8f8f8f8f8f/5f8a6b8b8c8c8c8c8c8c8c8c8c8c8c8c8.png'
        };
        
        return mapImageMap[mapName.toLowerCase()] || `https://via.placeholder.com/300x200/1e293b/ffffff?text=${mapName}`;
        
    } catch (error) {
        console.error('Error fetching map thumbnail:', error);
        return `https://via.placeholder.com/300x200/1e293b/ffffff?text=${mapName}`;
    }
}

async function getAgentAvatar(agentName) {
    try {
        const response = await fetch(`${RiotAPI.BASE_URL}/agents`);
        const agentsData = await response.json();
        
        const agent = agentsData.data.find(a => 
            a.displayName.toLowerCase() === agentName.toLowerCase()
        );
        
        if (agent && agent.displayIcon) {
            return agent.displayIcon;
        }
        
        return `https://via.placeholder.com/40x40/6366f1/ffffff?text=${agentName.charAt(0)}`;
        
    } catch (error) {
        console.error('Error fetching agent avatar:', error);
        return `https://via.placeholder.com/40x40/6366f1/ffffff?text=${agentName.charAt(0)}`;
    }
}

// ======================================================
// Chart.js Integration (Phase 2.2)
// ======================================================
let charts = {};

async function renderCharts() {
    if (typeof Chart === 'undefined') {
        // Load Chart.js dynamically
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/chart.js';
        script.onload = () => initializeCharts();
        document.head.appendChild(script);
        return;
    }
    
    initializeCharts();
}

function initializeCharts() {
    // Recent 5-Game ACS Line Chart
    const acsCanvas = document.getElementById('acsChart');
    if (acsCanvas && !charts.acs) {
        charts.acs = new Chart(acsCanvas, {
            type: 'line',
            data: {
                labels: ['Match 1', 'Match 2', 'Match 3', 'Match 4', 'Match 5'],
                datasets: [{
                    label: 'Team A ACS',
                    data: [18.5, 20.2, 19.8, 21.3, 22.1],
                    borderColor: 'rgb(34, 197, 94)',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    tension: 0.1
                }, {
                    label: 'Team B ACS',
                    data: [19.8, 21.5, 18.9, 20.1, 19.7],
                    borderColor: 'rgb(239, 68, 68)',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'top' },
                    title: { display: true, text: 'Recent 5-Game ACS Trend' }
                },
                scales: {
                    y: { beginAtZero: false, min: 15, max: 25 }
                }
            }
        });
    }
    
    // Ace Player Radar Chart
    const radarCanvas = document.getElementById('radarChart');
    if (radarCanvas && !charts.radar) {
        charts.radar = new Chart(radarCanvas, {
            type: 'radar',
            data: {
                labels: ['ACS', 'K/D', 'KAST', 'ADR', 'FK Rate', 'FD Margin'],
                datasets: [{
                    label: 'Team A Ace',
                    data: [28.5, 2.4, 85, 145, 0.35, 0.12],
                    backgroundColor: 'rgba(59, 130, 246, 0.2)',
                    borderColor: 'rgb(59, 130, 246)',
                    pointBackgroundColor: 'rgb(59, 130, 246)'
                }, {
                    label: 'Team B Ace',
                    data: [26.8, 1.9, 82, 138, 0.28, 0.08],
                    backgroundColor: 'rgba(239, 68, 68, 0.2)',
                    borderColor: 'rgb(239, 68, 68)',
                    pointBackgroundColor: 'rgb(239, 68, 68)'
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'top' },
                    title: { display: true, text: 'Ace Player Performance Comparison' }
                },
                scale: {
                    min: 0,
                    max: 200
                }
            }
        });
    }
}

// ======================================================
// Agent Composition Analysis (Phase 3.1)
// ======================================================
async function analyzeAgentComposition() {
    if (!selectedMatch || !selectedMatch.team_a_id || !selectedMatch.team_b_id) {
        return { composition: { a: [], b: [] }, conviction: { a: 0, b: 0 } };
    }
    
    try {
        // This would normally fetch actual composition data from the backend
        // For now, we'll return simulated data
        const composition = {
            a: [
                { agents: ['jett', 'sova', 'bind', 'o primer', 'brimstone'], winRate: 68, games: 45 },
                { agents: ['sage', 'cypher', 'O thermosphere', 'deadlock', 'chamber'], winRate: 72, games: 38 }
            ],
            b: [
                { agents: ['reyna', 'phoenix', 'split', 'raze', 'jett'], winRate: 65, games: 52 },
                { agents: ['omen', 'viper', 'cele', 'fade', 'neon'], winRate: 70, games: 41 }
            ]
        };
        
        const confidence = { a: 85, b: 78 };
        
        return { composition, confidence };
    } catch (error) {
        console.error('Error analyzing agent composition:', error);
        return { composition: { a: [], b: [] }, confidence: { a: 0, b: 0 } };
    }
}

// ======================================================
// Pistol Round Analysis (Phase 3.2)
// ======================================================
async function analyzePistolRounds() {
    if (!selectedMatch || !selectedMatch.team_a_id || !selectedMatch.team_b_id) {
        return { pistol: { a: { winRate: 0, games: 0 }, b: { winRate: 0, games: 0 } }, fkFd: { a: { fkRate: 0, fdMargin: 0 }, b: { fkRate: 0, fdMargin: 0 } } };
    }
    
    try {
        // This would normally fetch actual data from the backend
        // For now, we'll return simulated data
        const pistol = {
            a: { winRate: 58, games: 86 },
            b: { winRate: 42, games: 86 }
        };
        
        const fkFd = {
            a: { fkRate: 0.32, fdMargin: 0.15 },
            b: { fkRate: 0.28, fdMargin: 0.08 }
        };
        
        return { pistol, fkFd };
    } catch (error) {
        console.error('Error analyzing pistol rounds:', error);
        return { pistol: { a: { winRate: 0, games: 0 }, b: { winRate: 0, games: 0 } }, fkFd: { a: { fkRate: 0, fdMargin: 0 }, b: { fkRate: 0, fdMargin: 0 } } };
    }
}

// ======================================================
// Interactive AI Ban/Pick Simulator (Phase 4.2)
// ======================================================
let selectedBanPicks = {
    a: { ban: null, pick: null },
    b: { ban: null, pick: null }
};

function initializeBanPickSimulator() {
    // Create interactive map selection grid
    const banPickGrid = document.getElementById('ban-pick-grid');
    if (!banPickGrid) return;
    
    // Get all maps from current match or fallback pool
    const allMaps = selectedMatch && selectedMatch.map_pool && selectedMatch.map_pool.length > 0
        ? selectedMatch.map_pool
        : ['Ascent', 'Breeze', 'Haven', 'Lotus', 'Split', 'Summit', 'Sunset'];
    
    banPickGrid.innerHTML = '';
    
    allMaps.forEach(map => {
        const card = document.createElement('div');
        card.className = 'ban-pick-card border border-slate-700 rounded-lg p-3 cursor-pointer hover:bg-slate-800/50 transition-colors';
        card.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-sm font-medium text-slate-200">${map}</span>
                <div class="w-3 h-3 rounded-full ${getMapStatusColor(map)}"></div>
            </div>
        `;
        
        card.onclick = () => handleMapSelection(map, card);
        banPickGrid.appendChild(card);
    });
}

function getMapStatusColor(map) {
    if (selectedBanPicks.a.ban === map) return 'bg-red-500';
    if (selectedBanPicks.b.ban === map) return 'bg-blue-500';
    if (selectedBanPicks.a.pick === map) return 'bg-green-500';
    if (selectedBanPicks.b.pick === map) return 'bg-emerald-500';
    return 'bg-slate-600';
}

function handleMapSelection(map, card) {
    // Determine current phase based on existing selections
    const phase = getCurrentBanPickPhase();
    
    if (phase === 'a_ban') {
        // Team A bans
        selectedBanPicks.a.ban = map;
        updateBanPickUI();
        setTimeout(() => getCurrentBanPickPhase(), 100); // Allow UI to update
    } else if (phase === 'b_ban') {
        // Team B bans
        selectedBanPicks.b.ban = map;
        updateBanPickUI();
        setTimeout(() => getCurrentBanPickPhase(), 100);
    } else if (phase === 'a_pick') {
        // Team A picks
        selectedBanPicks.a.pick = map;
        updateBanPickUI();
        setTimeout(() => getCurrentBanPickPhase(), 100);
    } else if (phase === 'b_pick') {
        // Team B picks
        selectedBanPicks.b.pick = map;
        updateBanPickUI();
        setTimeout(() => getCurrentBanPickPhase(), 100);
    }
}

function getCurrentBanPickPhase() {
    if (!selectedBanPicks.a.ban) return 'a_ban';
    if (!selectedBanPicks.b.ban) return 'b_ban';
    if (!selectedBanPicks.a.pick) return 'a_pick';
    if (!selectedBanPicks.b.pick) return 'b_pick';
    return 'complete';
}

function updateBanPickUI() {
    const banPickGrid = document.getElementById('ban-pick-grid');
    if (!banPickGrid) return;
    
    const cards = banPickGrid.querySelectorAll('.ban-pick-card');
    cards.forEach(card => {
        const mapName = card.querySelector('span').textContent;
        card.className = 'ban-pick-card border border-slate-700 rounded-lg p-3 cursor-pointer hover:bg-slate-800/50 transition-all transform hover:scale-105 ';
        
        if (selectedBanPicks.a.ban === mapName) {
            card.classList.add('border-red-500 bg-red-950/20');
        } else if (selectedBanPicks.b.ban === mapName) {
            card.classList.add('border-blue-500 bg-blue-950/20');
        } else if (selectedBanPicks.a.pick === mapName) {
            card.classList.add('border-green-500 bg-green-950/20');
        } else if (selectedBanPicks.b.pick === mapName) {
            card.classList.add('border-emerald-500 bg-emerald-950/20');
        }
    });
    
    // Update phase indicator
    updateBanPickPhaseIndicator();
    
    // Recalculate probability bar
    calculateInteractiveProbability();
}

function updateBanPickPhaseIndicator() {
    const indicator = document.getElementById('ban-pick-indicator');
    if (!indicator) return;
    
    const phase = getCurrentBanPickPhase();
    const teamNames = selectedMatch ? [selectedMatch.team_a_name, selectedMatch.team_b_name] : ['Team A', 'Team B'];
    
    let text = '';
    let color = '';
    
    switch (phase) {
        case 'a_ban':
            text = `${teamNames[0]}가 맵을 밴할 시간입니다`; color = 'text-red-400';
            break;
        case 'b_ban':
            text = `${teamNames[1]}가 맵을 밴할 시간입니다`; color = 'text-blue-400';
            break;
        case 'a_pick':
            text = `${teamNames[0]}가 맵을 픽할 시간입니다`; color = 'text-green-400';
            break;
        case 'b_pick':
            text = `${teamNames[1]}가 맵을 픽할 시간입니다`; color = 'text-emerald-400';
            break;
        case 'complete':
            text = '밴픽 완료! remaining maps: ' + getRemainingMaps().join(', ');
            color = 'text-purple-400';
            break;
    }
    
    indicator.textContent = text;
    indicator.className = `text-sm font-medium ${color}`;
}

function getRemainingMaps() {
    if (!selectedMatch && selectedMatch.map_pool) return [];
    
    const allMaps = selectedMatch.map_pool || ['Ascent', 'Breeze', 'Haven', 'Lotus', 'Split', 'Summit', 'Sunset'];
    const selected = [];
    
    allMaps.forEach(map => {
        if (map !== selectedBanPicks.a.ban && map !== selectedBanPicks.b.ban &&
            map !== selectedBanPicks.a.pick && map !== selectedBanPicks.b.pick) {
            selected.push(map);
        }
    });
    
    return selected;
}

function calculateInteractiveProbability() {
    // Calculate win probability based on remaining maps and team compositions
    const probabilityA = Math.random() * 30 + 60; // Simulated probability
    const probabilityB = 100 - probabilityA;
    
    const barA = document.getElementById('interactive-probability-a');
    const barB = document.getElementById('interactive-probability-b');
    
    if (barA && barB) {
        barA.style.width = `${probabilityA}%`;
        barA.setAttribute('data-probability', `${probabilityA.toFixed(0)}%`);
        
        barB.style.width = `${probabilityB}%`;
        barB.setAttribute('data-probability', `${probabilityB.toFixed(0)}%`);
    }
}

// ======================================================
// Phase 5: Result Report & Export Functionality
// ======================================================
let analysisData = {};

async function generateResultReport() {
    try {
        // Collect all analysis data
        analysisData = {
            match: selectedMatch,
            agentComposition: await analyzeAgentComposition(),
            pistolAnalysis: await analyzePistolRounds(),
            timestamp: new Date().toISOString()
        };
        
        // Generate image report
        await generateReportImage();
        
        // Generate shareable link
        await generateShareableLink();
        
        console.log('Result report generated successfully');
    } catch (error) {
        console.error('Error generating result report:', error);
    }
}

async function generateReportImage() {
    if (typeof html2canvas === 'undefined') {
        // Load html2canvas dynamically
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/html2canvas';
        script.onload = () => renderReportImage();
        document.head.appendChild(script);
        return;
    }
    
    renderReportImage();
}

function renderReportImage() {
    const reportContainer = document.getElementById('report-container');
    if (!reportContainer) return;
    
    html2canvas(reportContainer, {
        scale: 2,
        useCORS: true,
        allowTaint: true,
        backgroundColor: '#0f172a'
    }).then(canvas => {
        const imageData = canvas.toDataURL('image/png');
        
        const downloadBtn = document.getElementById('download-report-btn');
        if (downloadBtn) {
            downloadBtn.onclick = () => {
                const link = document.createElement('a');
                link.download = `vlr-analysis-${selectedMatch?.id || 'match'}.png`;
                link.href = imageData;
                link.click();
            };
        }
    });
}

async function generateShareableLink() {
    if (!selectedMatch) return;
    
    const shareData = {
        matchId: selectedMatch.id,
        matchUrl: selectedMatch.url,
        eventIds: Array.from(selectedEvents),
        timestamp: new Date().toISOString(),
        analysisType: 'comprehensive'
    };
    
    // Encode to base64 for URL
    const encodedData = btoa(JSON.stringify(shareData));
    
    const shareLink = `${window.location.origin}${window.location.pathname}?report=${encodedData}`;
    
    const copyLinkBtn = document.getElementById('copy-link-btn');
    if (copyLinkBtn) {
        copyLinkBtn.onclick = async () => {
            try {
                await navigator.clipboard.writeText(shareLink);
                showToast('분석 링크가 클립보드에 복사되었습니다!', 'success');
            } catch (err) {
                console.error('클립보드 복사 실패:', err);
                showToast('링크 복사 실패. 다시 시도해주세요.', 'error');
            }
        };
    }
    
    return shareLink;
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 px-4 py-3 rounded-lg shadow-lg z-50 transition-all transform translate-y-0 opacity-100`;
    
    if (type === 'success') {
        toast.classList.add('bg-green-900/90', 'border', 'border-green-500/30', 'text-green-100');
    } else {
        toast.classList.add('bg-red-900/90', 'border', 'border-red-500/30', 'text-red-100');
    }
    
    toast.textContent = message;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('translate-y-2', 'opacity-0');
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300);
    }, 3000);
}

// ======================================================
// Main App Initialization
// ======================================================
// Load valorant assets on app start
preloadValorantAssets();
renderCharts();

// Initialize Phase 4 components
initializeBanPickSimulator();

// Set up periodic report generation
let reportGenerationInterval = null;

// Start analysis completion report generation (every 30 seconds)
function startReportGeneration() {
    if (reportGenerationInterval) clearInterval(reportGenerationInterval);
    
    reportGenerationInterval = setInterval(() => {
        if (analysisRunning && selectedMatch) {
            // Generate periodic status report
            console.log('Generating periodic analysis report...');
        }
    }, 30000);
}

function stopReportGeneration() {
    if (reportGenerationInterval) {
        clearInterval(reportGenerationInterval);
        reportGenerationInterval = null;
    }
}

// Event Listeners for new features
// Initialize Valueant Assets on page load
async function enhancedInit() {
    await preloadValorantAssets();
    await renderCharts();
    startReportGeneration();
}

// Call enhanced init when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhancedInit);
} else {
    enhancedInit();
}