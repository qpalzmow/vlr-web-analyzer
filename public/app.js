// App Initialization
document.addEventListener('DOMContentLoaded', () => {
    initReportNavigation();
    document.getElementById('hero-analyze-btn').addEventListener('click', runAnalysis);
    fetchMatches();
    document.getElementById('match-search').addEventListener('input', event => {
        matchSearchQuery = event.target.value;
        populateEventsDropdown(true);
    });
    document.querySelectorAll('#roster-sort button').forEach(button => button.addEventListener('click', () => {
        careerSort = button.dataset.sort;
        renderRosterTable();
    }));
    document.getElementById('export-link-btn').addEventListener('click', generateShareableLink);
    document.getElementById('export-img-btn').addEventListener('click', exportReportImage);

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
        } else if (selectedMatch && selectedMatch.live_updates_started) {
            startLiveScorePolling();
        }
    });
});
