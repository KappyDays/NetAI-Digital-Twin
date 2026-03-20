/* ==========================================================================
   Lakehouse Dashboard — API Client
   Thin wrapper around fetch() for all Lakehouse API calls.
   ========================================================================== */

const LakehouseAPI = (() => {
    const BASE = () => DashboardConfig.API_BASE;

    /**
     * Generic fetch wrapper with error handling.
     */
    async function request(endpoint, options = {}) {
        const url = `${BASE()}${endpoint}`;
        const defaults = {
            headers: { 'Content-Type': 'application/json' },
        };
        const config = { ...defaults, ...options };

        try {
            const response = await fetch(url, config);
            if (!response.ok) {
                const body = await response.text();
                throw new Error(`HTTP ${response.status}: ${body}`);
            }
            return await response.json();
        } catch (err) {
            console.error(`[LakehouseAPI] ${endpoint}:`, err);
            throw err;
        }
    }

    return {
        /* ---- Health ---- */
        health() {
            return request('/health');
        },

        healthDeep() {
            return fetch(window.location.origin + '/health')
                .then(r => r.json());
        },

        /* ---- Static Prims ---- */
        getStaticPrims(space_id) {
            const params = space_id ? `?space_id=${encodeURIComponent(space_id)}` : '';
            return request(`/static/prims${params}`);
        },

        /* ---- Dynamic Objects ---- */
        listDynamicTables() {
            return request('/dynamic-objects/tables');
        },

        getDynamicData(objectId, params = {}) {
            const query = new URLSearchParams(params).toString();
            const qs = query ? `?${query}` : '';
            return request(`/dynamic-objects/${encodeURIComponent(objectId)}/data${qs}`);
        },

        /* ---- Congestion ---- */
        getCongestion(params = {}) {
            const query = new URLSearchParams(params).toString();
            const qs = query ? `?${query}` : '';
            return request(`/congestion${qs}`);
        },

        /* ---- Ad-hoc Query ---- */
        querySQL(sql) {
            return request('/query', {
                method: 'POST',
                body: JSON.stringify({ sql }),
            });
        },

        /* ---- Spaces ---- */
        getSpaces() {
            return request('/static/spaces');
        },
    };
})();
