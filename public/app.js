// App Initialization
document.addEventListener('DOMContentLoaded', () => {
    initUITheme();
    fetchMatches();
    
    // Wire up events
    tierSelect.addEventListener('change', () => {
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
});
