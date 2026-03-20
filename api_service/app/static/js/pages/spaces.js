/* ==========================================================================
   Lakehouse Dashboard — Spaces Page
   Browse /World direct-child spaces, view static prims per space.
   ========================================================================== */

const SpacesPage = (() => {
    let pollTimer = null;

    function init() {
        const container = document.getElementById('page-content');
        container.innerHTML = render();
        loadSpaces();
        pollTimer = setInterval(loadSpaces, DashboardConfig.POLL_INTERVAL_NORMAL);
    }

    function destroy() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
    }

    function render() {
        return `
            <div class="page-header">
                <h1 class="page-header__title">Spaces</h1>
                <p class="page-header__subtitle">
                    /World direct-child Prims — each represents a distinct space in the digital twin.
                </p>
            </div>
            <div class="space-grid" id="spaces-grid">
                <div class="skeleton skeleton--chart" style="height:200px;"></div>
                <div class="skeleton skeleton--chart" style="height:200px;"></div>
                <div class="skeleton skeleton--chart" style="height:200px;"></div>
            </div>
        `;
    }

    async function loadSpaces() {
        try {
            const data = await LakehouseAPI.getCongestion();
            const grid = document.getElementById('spaces-grid');
            if (!grid) return;

            const spaces = data && data.spaces ? data.spaces : [];

            if (spaces.length === 0) {
                grid.innerHTML = Components.emptyState({
                    icon: '\u{1F3D7}',
                    text: 'No spaces discovered yet',
                    hint: 'POST static Prim data via /api/v1/prims to register spaces.',
                });
                return;
            }

            grid.innerHTML = spaces.map(s => Components.spaceCard({
                name: s.name || s.space_id,
                path: s.path || `/World/${s.space_id}`,
                primCount: s.static_count || 0,
                dynamicCount: s.dynamic_count || 0,
                congestion: s.congestion || 0,
            })).join('');
        } catch (err) {
            console.warn('[Spaces] Load error:', err);
        }
    }

    return {
        title: 'Spaces',
        init,
        destroy,
    };
})();
