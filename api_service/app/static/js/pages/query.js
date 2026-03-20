/* ==========================================================================
   Lakehouse Dashboard — SQL Query Page
   Ad-hoc Trino SQL query interface for exploration.
   ========================================================================== */

const QueryPage = (() => {

    function init() {
        const container = document.getElementById('page-content');
        container.innerHTML = render();
        bindEvents();
    }

    function destroy() {
        // Nothing to clean up
    }

    function render() {
        return `
            <div class="page-header">
                <h1 class="page-header__title">SQL Query</h1>
                <p class="page-header__subtitle">
                    Execute ad-hoc Trino SQL against the Iceberg Lakehouse.
                </p>
            </div>

            <div class="dashboard-grid dashboard-grid--full">
                ${Components.panel({
                    id: 'panel-query',
                    title: 'Query Editor',
                    icon: '\u{1F50D}',
                    spanFull: true,
                    actions: `
                        <button class="btn btn--primary btn--sm" id="btn-run-query">Run Query</button>
                    `,
                    content: `
                        <textarea id="sql-input"
                            style="width:100%;min-height:120px;background:var(--color-bg-secondary);
                                   color:var(--color-text-primary);border:1px solid var(--color-border);
                                   border-radius:var(--radius-sm);padding:12px;font-family:var(--font-mono);
                                   font-size:0.85rem;resize:vertical;outline:none;"
                            placeholder="SELECT * FROM iceberg.static_db.static_prims LIMIT 10"
                        >SELECT * FROM iceberg.static_db.static_prims LIMIT 10</textarea>
                        <div style="margin-top:8px;font-size:0.75rem;color:var(--color-text-muted);">
                            Catalog: <code>iceberg</code> &middot;
                            Static schema: <code>static_db</code> &middot;
                            Tip: Use <code>SHOW TABLES FROM iceberg.static_db</code> to explore.
                        </div>
                    `,
                })}
            </div>

            <div class="dashboard-grid dashboard-grid--full" style="margin-top:16px;">
                ${Components.panel({
                    id: 'panel-results',
                    title: 'Query Results',
                    icon: '\u{1F4CA}',
                    spanFull: true,
                    content: `
                        <div id="query-results">
                            ${Components.emptyState({
                                icon: '\u{2328}',
                                text: 'Run a query to see results',
                                hint: 'Results will appear here as a table.',
                            })}
                        </div>
                    `,
                })}
            </div>

            <!-- Quick Query Templates -->
            <div style="margin-top:16px;">
                <span style="font-size:0.8rem;color:var(--color-text-muted);font-weight:600;">
                    Quick Queries:
                </span>
                <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;">
                    <button class="btn btn--sm quick-query" data-sql="SHOW SCHEMAS FROM iceberg">
                        Show Schemas
                    </button>
                    <button class="btn btn--sm quick-query" data-sql="SHOW TABLES FROM iceberg.static_db">
                        Show Tables
                    </button>
                    <button class="btn btn--sm quick-query" data-sql="SELECT * FROM iceberg.static_db.static_prims LIMIT 20">
                        Static Prims
                    </button>
                    <button class="btn btn--sm quick-query" data-sql="SELECT count(*) as total FROM iceberg.static_db.static_prims">
                        Count Prims
                    </button>
                </div>
            </div>
        `;
    }

    function bindEvents() {
        const runBtn = document.getElementById('btn-run-query');
        if (runBtn) runBtn.addEventListener('click', executeQuery);

        // Ctrl+Enter to run
        const textarea = document.getElementById('sql-input');
        if (textarea) {
            textarea.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                    e.preventDefault();
                    executeQuery();
                }
            });
        }

        // Quick query buttons
        document.querySelectorAll('.quick-query').forEach(btn => {
            btn.addEventListener('click', () => {
                const sql = btn.dataset.sql;
                const textarea = document.getElementById('sql-input');
                if (textarea) textarea.value = sql;
                executeQuery();
            });
        });
    }

    async function executeQuery() {
        const textarea = document.getElementById('sql-input');
        const resultsDiv = document.getElementById('query-results');
        if (!textarea || !resultsDiv) return;

        const sql = textarea.value.trim();
        if (!sql) return;

        resultsDiv.innerHTML = '<div style="padding:20px;text-align:center;">Executing query...</div>';

        try {
            const data = await LakehouseAPI.querySQL(sql);
            renderResults(data, resultsDiv);
        } catch (err) {
            resultsDiv.innerHTML = `
                <div style="padding:20px;color:var(--color-danger);">
                    <strong>Query Error:</strong><br>
                    <code style="font-size:0.8rem;">${err.message}</code>
                </div>
            `;
        }
    }

    function renderResults(data, container) {
        if (!data) {
            container.innerHTML = Components.emptyState({ text: 'No results returned' });
            return;
        }

        // Handle different response formats
        const columns = data.columns || [];
        const rows = data.rows || data.data || [];

        if (rows.length === 0) {
            container.innerHTML = Components.emptyState({
                text: 'Query returned 0 rows',
                hint: `${columns.length} columns in schema.`,
            });
            return;
        }

        // If rows are arrays, convert to objects
        const isArray = Array.isArray(rows[0]);

        const headerHtml = columns.length > 0
            ? columns.map(c => `<th>${c}</th>`).join('')
            : (isArray
                ? rows[0].map((_, i) => `<th>col_${i}</th>`).join('')
                : Object.keys(rows[0]).map(k => `<th>${k}</th>`).join('')
            );

        const bodyHtml = rows.map(row => {
            const cells = isArray
                ? row.map(v => `<td class="mono">${formatCell(v)}</td>`).join('')
                : (columns.length > 0
                    ? columns.map(c => `<td class="mono">${formatCell(row[c])}</td>`).join('')
                    : Object.values(row).map(v => `<td class="mono">${formatCell(v)}</td>`).join('')
                );
            return `<tr>${cells}</tr>`;
        }).join('');

        container.innerHTML = `
            <div style="font-size:0.78rem;color:var(--color-text-muted);margin-bottom:8px;">
                ${rows.length} row(s) returned
            </div>
            <div style="overflow-x:auto;">
                <table class="data-table">
                    <thead><tr>${headerHtml}</tr></thead>
                    <tbody>${bodyHtml}</tbody>
                </table>
            </div>
        `;
    }

    function formatCell(value) {
        if (value === null || value === undefined) return '<span style="color:var(--color-text-muted);">NULL</span>';
        if (typeof value === 'object') return JSON.stringify(value);
        const str = String(value);
        return str.length > 100 ? str.substring(0, 100) + '...' : str;
    }

    return {
        title: 'SQL Query',
        init,
        destroy,
    };
})();
