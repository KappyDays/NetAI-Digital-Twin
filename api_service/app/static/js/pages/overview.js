/* ==========================================================================
   Lakehouse Dashboard — Overview Page
   Main dashboard with Top-View Heatmap + Time-Series Chart + KPIs
   ========================================================================== */

const OverviewPage = (() => {
    let pollTimers = [];
    let storeUnwatchers = [];
    let selectedTimeRange = '1h';
    let selectedHeatmapSpace = null;   // Currently selected space from heatmap click
    let selectedChartTimestamp = null;  // Currently selected timestamp from chart click

    function init() {
        const container = document.getElementById('page-content');
        container.innerHTML = render();
        bindEvents();
        loadKPIs();
        initHeatmap();
        initTimeChart();
        startPolling();
        bindStoreWatchers();
    }

    function destroy() {
        pollTimers.forEach(clearInterval);
        pollTimers = [];
        storeUnwatchers.forEach(fn => fn());
        storeUnwatchers = [];
        selectedHeatmapSpace = null;
        selectedChartTimestamp = null;
        // Remove global clear handler
        delete window.clearAllSyncSelections;
    }

    /**
     * Bind to DashboardState (from the data-polling-service layer)
     * for reactive updates — supplements legacy polling gracefully.
     */
    function bindStoreWatchers() {
        if (typeof DashboardState === 'undefined') return;

        // Congestion data -> update heatmap and space table reactively
        storeUnwatchers.push(
            DashboardState.watch('congestion', (data) => {
                updateHeatmapFromStore(data);
                updateSpaceTableFromStore(data);
            })
        );

        // Congestion time-series -> update chart reactively
        storeUnwatchers.push(
            DashboardState.watch('congestionTimeseries', () => {
                updateTimeChartFromStore();
            })
        );

        // KPIs from store
        storeUnwatchers.push(
            DashboardState.watch('*', () => {
                updateKPIsFromStore();
            })
        );
    }

    /** Update KPIs from the reactive store (no extra fetch) */
    function updateKPIsFromStore() {
        if (typeof DashboardState === 'undefined') return;
        const stats = DashboardState.getSummaryStats();
        const strip = document.getElementById('kpi-strip');
        if (!strip) return;

        const spaces = DashboardState.state.congestion.spaces || [];
        const avgCongestion = spaces.length > 0
            ? (spaces.reduce((sum, s) => sum + (s.congestion_level || 0), 0) / spaces.length).toFixed(2)
            : '\u2014';
        const peakSpace = spaces.length > 0
            ? spaces.reduce((max, s) => (s.congestion_level || 0) > (max.congestion_level || 0) ? s : max, spaces[0])
            : null;

        strip.innerHTML = [
            Components.kpiCard({ label: 'Total Spaces', value: stats.totalSpaces || 0 }),
            Components.kpiCard({ label: 'Static Prims', value: stats.totalStaticPrims || 0 }),
            Components.kpiCard({ label: 'Dynamic Objects', value: stats.totalDynamicObjects || 0 }),
            Components.kpiCard({ label: 'Avg Congestion', value: avgCongestion }),
            Components.kpiCard({
                label: 'Peak Zone',
                value: peakSpace ? peakSpace.space_id : '\u2014',
            }),
        ].join('');
    }

    /** Update Plotly heatmap from store's congestion data */
    function updateHeatmapFromStore(congestionData) {
        const el = document.getElementById('heatmap-chart');
        if (!el || typeof Plotly === 'undefined') return;

        const spaces = congestionData.spaces || [];
        if (!spaces.length) return;

        // Build a simple 1xN heatmap from space congestion levels
        const spaceIds = spaces.map(s => s.space_id);
        const levels = spaces.map(s => s.congestion_level || 0);

        try {
            Plotly.restyle(el, {
                z: [[levels]],
                x: [spaceIds],
                y: [['Congestion']],
            });
        } catch (_) {}
    }

    /** Update Plotly time chart from store's timeseries data */
    function updateTimeChartFromStore() {
        if (typeof DashboardState === 'undefined') return;
        const chartData = DashboardState.getChartData();
        const el = document.getElementById('time-chart');
        if (!el || typeof Plotly === 'undefined') return;
        if (!chartData.labels.length) return;

        try {
            const traces = chartData.datasets.map((ds, i) => ({
                x: chartData.labels,
                y: ds.data,
                type: 'scatter',
                mode: 'lines+markers',
                name: ds.spaceId,
                line: { width: 2, shape: 'spline' },
                marker: { size: 3 },
                fill: 'tozeroy',
                fillcolor: `rgba(76, 139, 245, ${0.08 + i * 0.03})`,
            }));

            Plotly.react(el, traces, {
                ...DashboardConfig.PLOTLY_LAYOUT,
                xaxis: {
                    ...DashboardConfig.PLOTLY_LAYOUT.xaxis,
                    title: { text: 'Time', font: { color: '#6b7185', size: 11 } },
                    type: 'date',
                },
                yaxis: {
                    ...DashboardConfig.PLOTLY_LAYOUT.yaxis,
                    title: { text: 'Object Count', font: { color: '#6b7185', size: 11 } },
                },
            }, { responsive: true, displayModeBar: false });
        } catch (_) {}
    }

    /** Update space table from store's congestion data */
    function updateSpaceTableFromStore(congestionData) {
        const tbody = document.getElementById('space-table-body');
        if (!tbody) return;

        const spaces = congestionData.spaces || [];
        if (!spaces.length) return;

        tbody.innerHTML = spaces.map(s => `
            <tr>
                <td><strong>${s.space_id}</strong></td>
                <td class="mono">/World/${s.space_id}</td>
                <td class="mono">\u2014</td>
                <td class="mono">${s.object_count || 0}</td>
                <td>${Components.congestionBadge(s.congestion_level || 0)}</td>
                <td class="mono">${s.timestamp || '\u2014'}</td>
            </tr>
        `).join('');

        // Update space select
        const spaceSelect = document.getElementById('heatmap-space-select');
        if (spaceSelect && spaces.length > 0) {
            const currentVal = spaceSelect.value;
            spaceSelect.innerHTML = '<option value="all">All Spaces</option>' +
                spaces.map(s =>
                    `<option value="${s.space_id}">${s.space_id}</option>`
                ).join('');
            spaceSelect.value = currentVal;
        }
    }

    function render() {
        return `
            <!-- KPI Strip -->
            <div class="kpi-strip" id="kpi-strip">
                ${Components.kpiCard({ label: 'Total Spaces', value: '—', trend: '' })}
                ${Components.kpiCard({ label: 'Static Prims', value: '—', trend: '' })}
                ${Components.kpiCard({ label: 'Dynamic Objects', value: '—', trend: '' })}
                ${Components.kpiCard({ label: 'Avg Congestion', value: '—', trend: '' })}
                ${Components.kpiCard({ label: 'Peak Zone', value: '—', trend: '' })}
            </div>

            <!-- Time Range Controls -->
            ${Components.timeRangeButtons(selectedTimeRange)}

            <!-- Sync Status Banner (hidden by default) -->
            <div class="sync-status-banner" id="sync-status-banner" style="display:none;"></div>

            <!-- Main Visualization Grid -->
            <div class="dashboard-grid">
                <!-- Top-View Heatmap (left) -->
                ${Components.panel({
                    id: 'panel-heatmap',
                    title: 'Spatial Congestion — Top View',
                    icon: '\u{1F5FA}',
                    bodyClass: 'panel__body--heatmap panel__body--no-padding',
                    actions: `
                        <select class="select" id="heatmap-space-select">
                            <option value="all">All Spaces</option>
                        </select>
                        <button class="btn btn--sm" id="btn-heatmap-refresh">Refresh</button>
                    `,
                    content: '<div id="heatmap-chart" style="width:100%;height:100%;min-height:400px;"></div>',
                })}

                <!-- Time-Series Chart (right) -->
                ${Components.panel({
                    id: 'panel-timechart',
                    title: 'Congestion Over Time',
                    icon: '\u{1F4C8}',
                    bodyClass: 'panel__body--chart panel__body--no-padding',
                    actions: `
                        <select class="select" id="timechart-metric-select">
                            <option value="avg_congestion">Avg Congestion</option>
                            <option value="object_count">Object Count</option>
                            <option value="peak_congestion">Peak Congestion</option>
                        </select>
                    `,
                    content: '<div id="time-chart" style="width:100%;height:100%;min-height:320px;"></div>',
                })}
            </div>

            <!-- Bottom Row: Space Summary Table -->
            <div class="dashboard-grid dashboard-grid--full">
                ${Components.panel({
                    id: 'panel-space-table',
                    title: 'Space Summary',
                    icon: '\u{1F4CB}',
                    spanFull: true,
                    actions: '<button class="btn btn--sm" id="btn-table-refresh">Refresh</button>',
                    content: `
                        <table class="data-table" id="space-summary-table">
                            <thead>
                                <tr>
                                    <th>Space</th>
                                    <th>Path</th>
                                    <th>Static Prims</th>
                                    <th>Dynamic Objects</th>
                                    <th>Congestion</th>
                                    <th>Last Updated</th>
                                </tr>
                            </thead>
                            <tbody id="space-table-body">
                                <tr><td colspan="6" style="text-align:center;padding:40px;">
                                    Loading space data...
                                </td></tr>
                            </tbody>
                        </table>
                    `,
                })}
            </div>
        `;
    }

    /* ---- Event Bindings ---- */
    function bindEvents() {
        // Time range buttons
        document.querySelectorAll('.time-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('time-btn--active'));
                e.target.classList.add('time-btn--active');
                selectedTimeRange = e.target.dataset.range;
                refreshTimeChart();
            });
        });

        // Refresh buttons
        const heatmapRefresh = document.getElementById('btn-heatmap-refresh');
        if (heatmapRefresh) heatmapRefresh.addEventListener('click', refreshHeatmap);

        const tableRefresh = document.getElementById('btn-table-refresh');
        if (tableRefresh) tableRefresh.addEventListener('click', loadSpaceTable);

        // Space select for heatmap
        const spaceSelect = document.getElementById('heatmap-space-select');
        if (spaceSelect) spaceSelect.addEventListener('change', refreshHeatmap);

        // ── Bidirectional Heatmap <-> Chart Interaction ──

        // 1) Heatmap click → filter time chart to selected space
        bindHeatmapToChartInteraction();

        // 2) Time chart click → update heatmap to show that time snapshot
        bindChartToHeatmapInteraction();

        // 3) Global clear function for sync banner
        window.clearAllSyncSelections = function() {
            selectedHeatmapSpace = null;
            selectedChartTimestamp = null;
            const banner = document.getElementById('sync-status-banner');
            if (banner) banner.style.display = 'none';

            // Restore chart to all spaces
            updateTimeChartFilter(null);
            // Restore heatmap to live data
            restoreHeatmapToLive();
            // Clear heatmap highlight
            const el = document.getElementById('heatmap-chart');
            if (el && typeof Plotly !== 'undefined') {
                try { Plotly.relayout(el, { shapes: [] }); } catch (_) {}
            }
        };
    }

    /** Heatmap → Chart: clicking a heatmap zone filters the time chart */
    function bindHeatmapToChartInteraction() {
        const heatmapEl = document.getElementById('heatmap-chart');
        if (!heatmapEl || typeof Plotly === 'undefined') return;

        heatmapEl.on('plotly_click', (eventData) => {
            if (!eventData || !eventData.points || !eventData.points.length) return;

            const point = eventData.points[0];
            const spaceId = point.x;  // space ID from x-axis of heatmap

            // Toggle selection
            const syncBanner = document.getElementById('sync-status-banner');
            if (selectedHeatmapSpace === spaceId) {
                selectedHeatmapSpace = null;
                updateTimeChartFilter(null);
                if (syncBanner) syncBanner.style.display = 'none';
            } else {
                selectedHeatmapSpace = spaceId;
                updateTimeChartFilter(spaceId);
                if (syncBanner) {
                    syncBanner.style.display = 'flex';
                    syncBanner.innerHTML = getSyncBannerHTML('space', spaceId);
                }
            }

            // Visual highlight on heatmap
            highlightHeatmapSpace(spaceId);
        });
    }

    /** Chart → Heatmap: clicking a time point on the chart syncs the heatmap */
    function bindChartToHeatmapInteraction() {
        const timeChartEl = document.getElementById('time-chart');
        if (!timeChartEl || typeof Plotly === 'undefined') return;

        timeChartEl.on('plotly_click', (eventData) => {
            if (!eventData || !eventData.points || !eventData.points.length) return;

            const point = eventData.points[0];
            const timestamp = point.x;

            const syncBanner = document.getElementById('sync-status-banner');

            // Toggle: click same time deselects
            if (selectedChartTimestamp === timestamp) {
                selectedChartTimestamp = null;
                restoreHeatmapToLive();
                if (syncBanner) syncBanner.style.display = 'none';
            } else {
                selectedChartTimestamp = timestamp;
                updateHeatmapToTimepoint(timestamp);
                if (syncBanner) {
                    syncBanner.style.display = 'flex';
                    const timeLabel = formatTimeLabel(timestamp);
                    syncBanner.innerHTML = getSyncBannerHTML('time', timeLabel);
                }
            }
        });
    }

    /** Update the time chart to show only data for the selected space */
    function updateTimeChartFilter(spaceId) {
        if (typeof DashboardState === 'undefined') return;
        const chartData = spaceId
            ? DashboardState.getChartData(spaceId)
            : DashboardState.getChartData();
        const el = document.getElementById('time-chart');
        if (!el || typeof Plotly === 'undefined') return;
        if (!chartData.labels.length) return;

        try {
            const traces = chartData.datasets.map((ds, i) => ({
                x: chartData.labels,
                y: ds.data,
                type: 'scatter',
                mode: 'lines+markers',
                name: ds.spaceId,
                line: { width: spaceId ? 3 : 2, shape: 'spline' },
                marker: { size: spaceId ? 5 : 3 },
                fill: 'tozeroy',
                fillcolor: `rgba(76, 139, 245, ${0.08 + i * 0.03})`,
            }));

            Plotly.react(el, traces, {
                ...DashboardConfig.PLOTLY_LAYOUT,
                xaxis: {
                    ...DashboardConfig.PLOTLY_LAYOUT.xaxis,
                    title: { text: spaceId ? `Time (${spaceId})` : 'Time', font: { color: '#6b7185', size: 11 } },
                    type: 'date',
                },
                yaxis: {
                    ...DashboardConfig.PLOTLY_LAYOUT.yaxis,
                    title: { text: 'Object Count', font: { color: '#6b7185', size: 11 } },
                },
            }, { responsive: true, displayModeBar: false });
        } catch (_) {}
    }

    /** Update heatmap to show congestion at a specific time point */
    function updateHeatmapToTimepoint(timestamp) {
        if (typeof DashboardState === 'undefined') return;
        const el = document.getElementById('heatmap-chart');
        if (!el || typeof Plotly === 'undefined') return;

        // Get all space values at this timestamp from timeseries data
        const bySpace = DashboardState.state.congestionTimeseries.bySpace;
        const spaceIds = Object.keys(bySpace);
        const values = spaceIds.map(sid => {
            const series = bySpace[sid] || [];
            // Find the closest time bucket to the clicked timestamp
            const targetTime = new Date(timestamp).getTime();
            let closest = series[0];
            let minDiff = Infinity;
            for (const pt of series) {
                const diff = Math.abs(new Date(pt.timeBucket).getTime() - targetTime);
                if (diff < minDiff) {
                    minDiff = diff;
                    closest = pt;
                }
            }
            return closest ? closest.objectCount : 0;
        });

        if (!spaceIds.length) return;

        // Compute normalized congestion levels
        const maxVal = Math.max(...values, 1);
        const levels = values.map(v => v / maxVal);

        try {
            Plotly.restyle(el, {
                z: [[levels]],
                x: [spaceIds],
                y: [['Congestion']],
                text: [[values.map((v, i) => `${spaceIds[i]}: ${v} objects`)]],
                hovertemplate: '%{text}<br>Level: %{z:.2f}<extra></extra>',
            });

            // Add annotation to show selected time
            Plotly.relayout(el, {
                annotations: [{
                    text: `\u23F1 ${formatTimeLabel(timestamp)}`,
                    showarrow: false,
                    xref: 'paper',
                    yref: 'paper',
                    x: 1,
                    y: 1.08,
                    font: { color: '#4c8bf5', size: 12, family: "'Inter', sans-serif" },
                    bgcolor: 'rgba(76, 139, 245, 0.15)',
                    borderpad: 4,
                }],
            });
        } catch (_) {}
    }

    /** Restore heatmap to live data */
    function restoreHeatmapToLive() {
        selectedChartTimestamp = null;
        const el = document.getElementById('heatmap-chart');
        if (el && typeof Plotly !== 'undefined') {
            try {
                Plotly.relayout(el, { annotations: [] });
            } catch (_) {}
        }
        // Re-trigger live data refresh
        if (typeof DashboardState !== 'undefined') {
            updateHeatmapFromStore(DashboardState.state.congestion);
        }
    }

    /** Highlight a specific space on the heatmap */
    function highlightHeatmapSpace(spaceId) {
        const el = document.getElementById('heatmap-chart');
        if (!el || typeof Plotly === 'undefined') return;

        const spaces = DashboardState?.state.congestion.spaces || [];
        if (!spaces.length) return;

        // Add border annotation around selected space
        if (selectedHeatmapSpace) {
            const idx = spaces.findIndex(s => s.space_id === selectedHeatmapSpace);
            if (idx >= 0) {
                Plotly.relayout(el, {
                    shapes: [{
                        type: 'rect',
                        xref: 'x',
                        yref: 'y',
                        x0: idx - 0.45,
                        x1: idx + 0.45,
                        y0: -0.45,
                        y1: 0.45,
                        line: { color: '#3b82f6', width: 3 },
                        fillcolor: 'rgba(59, 130, 246, 0)',
                    }],
                });
            }
        } else {
            Plotly.relayout(el, { shapes: [] });
        }
    }

    /** Generate sync status banner HTML */
    function getSyncBannerHTML(type, label) {
        const icon = type === 'space' ? '\u{1F5FA}' : '\u23F1';
        const desc = type === 'space'
            ? `Chart filtered to space: <strong>${label}</strong>`
            : `Heatmap showing data at: <strong>${label}</strong>`;
        return `
            <span class="sync-banner__icon">${icon}</span>
            <span class="sync-banner__text">${desc}</span>
            <button class="sync-banner__clear" onclick="clearAllSyncSelections()">
                \u2715 Clear
            </button>
        `;
    }

    /** Format ISO timestamp to readable time */
    function formatTimeLabel(isoStr) {
        try {
            const d = new Date(isoStr);
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch {
            return String(isoStr).slice(11, 19);
        }
    }

    /* ---- KPI Loading ---- */
    async function loadKPIs() {
        try {
            const [healthData, congestionData] = await Promise.allSettled([
                LakehouseAPI.healthDeep(),
                LakehouseAPI.getCongestion(),
            ]);

            const strip = document.getElementById('kpi-strip');
            if (!strip) return;

            // Extract values with fallbacks
            const health = healthData.status === 'fulfilled' ? healthData.value : {};
            const congestion = congestionData.status === 'fulfilled' ? congestionData.value : {};

            const spaces = congestion.spaces || [];
            const totalSpaces = spaces.length || 0;
            const totalStatic = spaces.reduce((sum, s) => sum + (s.static_count || 0), 0);
            const totalDynamic = spaces.reduce((sum, s) => sum + (s.dynamic_count || 0), 0);
            const avgCongestion = spaces.length > 0
                ? (spaces.reduce((sum, s) => sum + (s.congestion || 0), 0) / spaces.length).toFixed(2)
                : '—';
            const peakSpace = spaces.length > 0
                ? spaces.reduce((max, s) => (s.congestion || 0) > (max.congestion || 0) ? s : max, spaces[0])
                : null;

            strip.innerHTML = [
                Components.kpiCard({ label: 'Total Spaces', value: totalSpaces }),
                Components.kpiCard({ label: 'Static Prims', value: totalStatic }),
                Components.kpiCard({ label: 'Dynamic Objects', value: totalDynamic }),
                Components.kpiCard({ label: 'Avg Congestion', value: avgCongestion }),
                Components.kpiCard({
                    label: 'Peak Zone',
                    value: peakSpace ? peakSpace.name || peakSpace.space_id : '—',
                }),
            ].join('');
        } catch (err) {
            console.warn('[Overview] KPI load error:', err);
        }
    }

    /* ---- Heatmap ---- */
    function initHeatmap() {
        const el = document.getElementById('heatmap-chart');
        if (!el) return;

        // Initialize with demo data — will be replaced by real API data
        const gridX = DashboardConfig.HEATMAP.DEFAULT_GRID_X;
        const gridY = DashboardConfig.HEATMAP.DEFAULT_GRID_Y;

        const z = Array.from({ length: gridY }, () =>
            Array.from({ length: gridX }, () => 0)
        );

        const xLabels = Array.from({ length: gridX }, (_, i) => `X${i}`);
        const yLabels = Array.from({ length: gridY }, (_, i) => `Y${i}`);

        const data = [{
            z: z,
            x: xLabels,
            y: yLabels,
            type: 'heatmap',
            colorscale: DashboardConfig.HEATMAP.COLOR_SCALE,
            zmin: 0,
            zmax: 1,
            hoverongaps: false,
            hovertemplate: 'Zone: %{x}, %{y}<br>Congestion: %{z:.2f}<extra></extra>',
            colorbar: {
                title: { text: 'Congestion', font: { color: '#9aa0b2' } },
                tickfont: { color: '#9aa0b2' },
                thickness: 15,
                outlinewidth: 0,
            },
        }];

        const layout = {
            ...DashboardConfig.PLOTLY_LAYOUT,
            margin: { l: 50, r: 10, t: 10, b: 50 },
            xaxis: {
                ...DashboardConfig.PLOTLY_LAYOUT.xaxis,
                title: { text: 'X Position', font: { color: '#6b7185', size: 11 } },
                side: 'bottom',
            },
            yaxis: {
                ...DashboardConfig.PLOTLY_LAYOUT.yaxis,
                title: { text: 'Y Position', font: { color: '#6b7185', size: 11 } },
            },
        };

        Plotly.newPlot(el, data, layout, {
            responsive: true,
            displayModeBar: false,
        });

        refreshHeatmap();
    }

    async function refreshHeatmap() {
        try {
            const spaceSelect = document.getElementById('heatmap-space-select');
            const spaceId = spaceSelect ? spaceSelect.value : 'all';
            const params = spaceId !== 'all' ? { space_id: spaceId } : {};
            const data = await LakehouseAPI.getCongestion(params);

            if (data && data.heatmap) {
                const el = document.getElementById('heatmap-chart');
                if (!el) return;

                Plotly.restyle(el, {
                    z: [data.heatmap.z],
                    x: [data.heatmap.x],
                    y: [data.heatmap.y],
                });
            }
        } catch (err) {
            console.warn('[Overview] Heatmap refresh error:', err);
        }
    }

    /* ---- Time-Series Chart ---- */
    function initTimeChart() {
        const el = document.getElementById('time-chart');
        if (!el) return;

        const data = [{
            x: [],
            y: [],
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Avg Congestion',
            line: {
                color: DashboardConfig.PLOTLY_LAYOUT.font.color,
                width: 2,
                shape: 'spline',
            },
            marker: { size: 4, color: '#4c8bf5' },
            fill: 'tozeroy',
            fillcolor: 'rgba(76, 139, 245, 0.08)',
        }];

        const layout = {
            ...DashboardConfig.PLOTLY_LAYOUT,
            xaxis: {
                ...DashboardConfig.PLOTLY_LAYOUT.xaxis,
                title: { text: 'Time', font: { color: '#6b7185', size: 11 } },
                type: 'date',
            },
            yaxis: {
                ...DashboardConfig.PLOTLY_LAYOUT.yaxis,
                title: { text: 'Congestion Index', font: { color: '#6b7185', size: 11 } },
                range: [0, 1],
            },
        };

        Plotly.newPlot(el, data, layout, {
            responsive: true,
            displayModeBar: false,
        });

        refreshTimeChart();
    }

    async function refreshTimeChart() {
        try {
            const range = DashboardConfig.TIME_RANGES[selectedTimeRange];
            const params = { time_range: selectedTimeRange };
            const data = await LakehouseAPI.getCongestion(params);

            if (data && data.time_series) {
                const el = document.getElementById('time-chart');
                if (!el) return;

                Plotly.restyle(el, {
                    x: [data.time_series.timestamps],
                    y: [data.time_series.values],
                });
            }
        } catch (err) {
            console.warn('[Overview] Time chart refresh error:', err);
        }
    }

    /* ---- Space Table ---- */
    async function loadSpaceTable() {
        try {
            const data = await LakehouseAPI.getCongestion();
            const tbody = document.getElementById('space-table-body');
            if (!tbody) return;

            const spaces = data && data.spaces ? data.spaces : [];

            if (spaces.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6">${
                    Components.emptyState({
                        icon: '\u{1F4E6}',
                        text: 'No space data available yet',
                        hint: 'Ingest static/dynamic data via the API to see results here.',
                    })
                }</td></tr>`;
                return;
            }

            tbody.innerHTML = spaces.map(s => `
                <tr>
                    <td><strong>${s.name || s.space_id}</strong></td>
                    <td class="mono">${s.path || '—'}</td>
                    <td class="mono">${s.static_count || 0}</td>
                    <td class="mono">${s.dynamic_count || 0}</td>
                    <td>${Components.congestionBadge(s.congestion || 0)}</td>
                    <td class="mono">${s.last_updated || '—'}</td>
                </tr>
            `).join('');

            // Update space select in heatmap
            const spaceSelect = document.getElementById('heatmap-space-select');
            if (spaceSelect && spaces.length > 0) {
                const currentVal = spaceSelect.value;
                spaceSelect.innerHTML = '<option value="all">All Spaces</option>' +
                    spaces.map(s =>
                        `<option value="${s.space_id}">${s.name || s.space_id}</option>`
                    ).join('');
                spaceSelect.value = currentVal;
            }
        } catch (err) {
            console.warn('[Overview] Space table error:', err);
        }
    }

    /* ---- Polling ---- */
    function startPolling() {
        loadSpaceTable();
        pollTimers.push(setInterval(loadKPIs, DashboardConfig.POLL_INTERVAL_FAST));
        pollTimers.push(setInterval(refreshHeatmap, DashboardConfig.POLL_INTERVAL_FAST));
        pollTimers.push(setInterval(refreshTimeChart, DashboardConfig.POLL_INTERVAL_NORMAL));
        pollTimers.push(setInterval(loadSpaceTable, DashboardConfig.POLL_INTERVAL_NORMAL));
    }

    return {
        title: 'Overview',
        init,
        destroy,
    };
})();
