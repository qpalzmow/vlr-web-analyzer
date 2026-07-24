// State variables
let allMatches = [];
let filteredMatches = [];
let selectedMatch = null;
let teamAEvents = [];
let teamBEvents = [];
let selectedEvents = new Set();
let analysisRunning = false;
let matchDetailsAbortController = null;
let analysisAbortController = null;
let liveScoreInterval = null;

// Agent badge Tailwind colors mapping
const agentColors = {
    jett: { bg: 'bg-sky-500/10 border-sky-500/20', text: 'text-sky-400' },
    raze: { bg: 'bg-orange-500/10 border-orange-500/20', text: 'text-orange-400' },
    phoenix: { bg: 'bg-red-500/10 border-red-500/20', text: 'text-red-400' },
    sage: { bg: 'bg-teal-500/10 border-teal-500/20', text: 'text-teal-400' },
    sova: { bg: 'bg-blue-500/10 border-blue-500/20', text: 'text-blue-400' },
    breach: { bg: 'bg-amber-500/10 border-amber-500/20', text: 'text-amber-400' },
    omen: { bg: 'bg-indigo-500/10 border-indigo-500/20', text: 'text-indigo-400' },
    brimstone: { bg: 'bg-yellow-800/10 border-yellow-800/20', text: 'text-yellow-600' },
    cypher: { bg: 'bg-slate-500/10 border-slate-500/20', text: 'text-slate-400' },
    reyna: { bg: 'bg-purple-500/10 border-purple-500/20', text: 'text-purple-400' },
    killjoy: { bg: 'bg-yellow-500/10 border-yellow-500/20', text: 'text-yellow-500' },
    viper: { bg: 'bg-emerald-500/10 border-emerald-500/20', text: 'text-emerald-400' },
    skye: { bg: 'bg-green-600/10 border-green-600/20', text: 'text-green-500' },
    yoru: { bg: 'bg-blue-700/10 border-blue-700/20', text: 'text-blue-500' },
    astra: { bg: 'bg-purple-700/10 border-purple-700/20', text: 'text-purple-500' },
    kayo: { bg: 'bg-sky-600/10 border-sky-600/20', text: 'text-sky-400' },
    chamber: { bg: 'bg-slate-700/10 border-slate-700/20', text: 'text-slate-300' },
    neon: { bg: 'bg-cyan-500/10 border-cyan-500/20', text: 'text-cyan-400' },
    fade: { bg: 'bg-slate-600/10 border-slate-600/20', text: 'text-slate-400' },
    harbor: { bg: 'bg-sky-600/10 border-sky-600/20', text: 'text-sky-500' },
    gekko: { bg: 'bg-lime-500/10 border-lime-500/20', text: 'text-lime-400' },
    deadlock: { bg: 'bg-cyan-600/10 border-cyan-600/20', text: 'text-cyan-500' },
    iso: { bg: 'bg-indigo-500/10 border-indigo-500/20', text: 'text-indigo-400' },
    clove: { bg: 'bg-pink-500/10 border-pink-500/20', text: 'text-pink-400' }
};

// UI Elements
const tierSelect = document.getElementById('tier-select');
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
