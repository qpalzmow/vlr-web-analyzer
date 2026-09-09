// App Initialization
document.addEventListener('DOMContentLoaded', () => {
    initUITheme();
    fetchMatches();
    checkSyncStatus();

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
        } else if (selectedMatch && selectedMatch.details_ready) {
            startLiveScorePolling();
        }
    });
});
