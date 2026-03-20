/* ==========================================================================
   Lakehouse Dashboard — Configuration & Constants
   ========================================================================== */

const DashboardConfig = {
    // API base URL — auto-detect from current location
    API_BASE: window.location.origin + '/api/v1',

    // Polling intervals (milliseconds)
    POLL_INTERVAL_FAST: 3000,     // Real-time panels (heatmap, KPIs)
    POLL_INTERVAL_NORMAL: 10000,  // Charts, tables
    POLL_INTERVAL_SLOW: 30000,    // Health status

    // Heatmap settings
    HEATMAP: {
        COLOR_SCALE: [
            [0.0, '#1a1d29'],    // Empty — background
            [0.1, '#1e3a5f'],    // Very low
            [0.3, '#2563eb'],    // Low
            [0.5, '#f59e0b'],    // Medium
            [0.7, '#ef4444'],    // High
            [1.0, '#dc2626'],    // Critical
        ],
        DEFAULT_GRID_X: 10,
        DEFAULT_GRID_Y: 10,
    },

    // Time range presets
    TIME_RANGES: {
        '5m':  { label: '5m',  seconds: 300 },
        '15m': { label: '15m', seconds: 900 },
        '1h':  { label: '1h',  seconds: 3600 },
        '6h':  { label: '6h',  seconds: 21600 },
        '24h': { label: '24h', seconds: 86400 },
        '7d':  { label: '7d',  seconds: 604800 },
    },

    // Congestion thresholds
    CONGESTION: {
        LOW: 0.3,
        MEDIUM: 0.6,
        HIGH: 0.8,
    },

    // Plotly layout defaults (dark theme)
    PLOTLY_LAYOUT: {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: {
            family: "'Inter', sans-serif",
            color: '#9aa0b2',
            size: 12,
        },
        margin: { l: 50, r: 20, t: 30, b: 40 },
        xaxis: {
            gridcolor: '#2e3348',
            zerolinecolor: '#2e3348',
        },
        yaxis: {
            gridcolor: '#2e3348',
            zerolinecolor: '#2e3348',
        },
    },
};

// Freeze to prevent accidental mutation
Object.freeze(DashboardConfig);
Object.freeze(DashboardConfig.HEATMAP);
Object.freeze(DashboardConfig.TIME_RANGES);
Object.freeze(DashboardConfig.CONGESTION);
Object.freeze(DashboardConfig.PLOTLY_LAYOUT);
