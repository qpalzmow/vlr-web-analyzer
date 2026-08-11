// App Initialization
document.addEventListener('DOMContentLoaded', () => {
    initUITheme();
    fetchMatches();
    
    // Wire up events
    tierSelect.addEventListener('change', () => {
        populateEventsDropdown();
    });
    
    regionSelect.addEventListener('change', () => {
        populateEventsDropdown();
    });
    
    eventSelect.addEventListener('change', () => {
        populateMatchesDropdown();
    });
    
    matchSelect.addEventListener('change', () => {
        handleMatchSelection();
    });
    
    analyzeBtn.addEventListener('click', () => {
        runAnalysis();
    });

    // Pause live score polling when tab is not visible
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopLiveScorePolling();
        } else if (selectedMatch && selectedMatch.live_score && selectedMatch.live_score.status === 'live') {
            startLiveScorePolling();
        }
    });
});
