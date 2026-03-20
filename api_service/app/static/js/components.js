/* ==========================================================================
   Lakehouse Dashboard — Reusable UI Components
   Template-literal based component rendering.
   ========================================================================== */

const Components = (() => {

    /* ---- KPI Card ---- */
    function kpiCard({ label, value, trend, trendDir = 'neutral' }) {
        const trendClass = `kpi-card__trend--${trendDir}`;
        const trendHtml = trend
            ? `<span class="kpi-card__trend ${trendClass}">${trend}</span>`
            : '';
        return `
            <div class="kpi-card">
                <span class="kpi-card__label">${label}</span>
                <span class="kpi-card__value">${value}</span>
                ${trendHtml}
            </div>
        `;
    }

    /* ---- Panel wrapper ---- */
    function panel({ id, title, icon, actions = '', bodyClass = '', spanFull = false, content = '' }) {
        const fullClass = spanFull ? 'panel--span-full' : '';
        return `
            <div class="panel ${fullClass}" id="${id}">
                <div class="panel__header">
                    <span class="panel__title">
                        <span class="panel__title-icon">${icon || ''}</span>
                        ${title}
                    </span>
                    <div class="panel__actions">${actions}</div>
                </div>
                <div class="panel__body ${bodyClass}">
                    ${content || '<div class="skeleton skeleton--chart"></div>'}
                </div>
            </div>
        `;
    }

    /* ---- Congestion Badge ---- */
    function congestionBadge(value) {
        let level, label;
        if (value < DashboardConfig.CONGESTION.LOW) {
            level = 'low'; label = 'Low';
        } else if (value < DashboardConfig.CONGESTION.MEDIUM) {
            level = 'medium'; label = 'Medium';
        } else {
            level = 'high'; label = 'High';
        }
        return `<span class="badge badge--${level}">${label}</span>`;
    }

    /* ---- Time Range Buttons ---- */
    function timeRangeButtons(activeRange = '1h') {
        const ranges = Object.keys(DashboardConfig.TIME_RANGES);
        const buttons = ranges.map(r => {
            const active = r === activeRange ? 'time-btn--active' : '';
            return `<button class="time-btn ${active}" data-range="${r}">${r}</button>`;
        }).join('');
        return `
            <div class="time-controls">
                <span class="time-controls__label">Time Range:</span>
                ${buttons}
            </div>
        `;
    }

    /* ---- Empty State ---- */
    function emptyState({ icon = '', text = 'No data available', hint = '' }) {
        return `
            <div class="empty-state">
                <div class="empty-state__icon">${icon}</div>
                <div class="empty-state__text">${text}</div>
                ${hint ? `<div class="empty-state__hint">${hint}</div>` : ''}
            </div>
        `;
    }

    /* ---- Loading Skeleton ---- */
    function loadingSkeleton(type = 'chart') {
        return `<div class="skeleton skeleton--${type}"></div>`;
    }

    /* ---- Space Card ---- */
    function spaceCard({ name, path, primCount = 0, dynamicCount = 0, congestion = 0 }) {
        return `
            <div class="space-card" data-space-path="${path}" onclick="Router.navigate('overview')">
                <div class="space-card__name">${name}</div>
                <div class="space-card__path">${path}</div>
                <div class="space-card__stats">
                    <div class="space-card__stat">
                        <span class="space-card__stat-value">${primCount}</span>
                        <span class="space-card__stat-label">Static Prims</span>
                    </div>
                    <div class="space-card__stat">
                        <span class="space-card__stat-value">${dynamicCount}</span>
                        <span class="space-card__stat-label">Dynamic Obj</span>
                    </div>
                    <div class="space-card__stat">
                        <span class="space-card__stat-value">${Components.congestionBadge(congestion)}</span>
                        <span class="space-card__stat-label">Congestion</span>
                    </div>
                </div>
            </div>
        `;
    }

    return {
        kpiCard,
        panel,
        congestionBadge,
        timeRangeButtons,
        emptyState,
        loadingSkeleton,
        spaceCard,
    };
})();
