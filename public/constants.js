// State variables
let allMatches = [];
let filteredMatches = [];
let selectedMatch = null;
let selectedTournamentCategory = 'all';
let tournamentGroups = [];
let tournamentKeyByMatch = new Map();
let teamAEvents = [];
let teamBEvents = [];
let selectedEvents = new Set();
let analysisRunning = false;
let catalogGeneration = null;
let catalogRefreshTimer = null;
let catalogFetchRunning = false;
let sharedSelectionRestored = false;
let analysisAbortController = null;
let liveScoreTimeout = null;
let liveScoreAbortController = null;
const MAX_SELECTED_EVENTS = 24;

// UI Elements
const tierSelect = document.getElementById('tier-select');
const regionSelect = document.getElementById('region-select');
const eventSelect = document.getElementById('event-select');
const matchSelect = document.getElementById('match-select');
const tournamentChecklistContainer = document.getElementById('tournament-checklist-container');
const tournamentChecklist = document.getElementById('tournament-checklist');

const statusIcon = document.getElementById('status-icon');
const statusText = document.getElementById('status-text');
const subStatusText = document.getElementById('sub-status-text');
const statusIconContainer = document.getElementById('status-icon-container');

const analyzeBtn = document.getElementById('analyze-btn');
const progressBarContainer = document.getElementById('progress-bar-container');
const progressBar = document.getElementById('progress-bar');

// Default competitive map pool
const FALLBACK_MAP_POOL = ['Ascent', 'Breeze', 'Haven', 'Lotus', 'Split', 'Summit', 'Sunset'];
