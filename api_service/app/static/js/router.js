/* ==========================================================================
   Lakehouse Dashboard — Client-Side Router (Hash-based SPA)
   Manages page navigation without full page reloads.
   ========================================================================== */

const Router = (() => {
    const routes = {};
    let currentRoute = null;
    let beforeNavigate = null;

    /**
     * Register a route.
     * @param {string} path  - Hash path (e.g., 'overview', 'spaces', 'query')
     * @param {object} handler - { title, init(), destroy?() }
     */
    function register(path, handler) {
        routes[path] = handler;
    }

    /**
     * Navigate to a route.
     */
    function navigate(path) {
        if (currentRoute && routes[currentRoute] && routes[currentRoute].destroy) {
            routes[currentRoute].destroy();
        }

        currentRoute = path;
        window.location.hash = `#/${path}`;

        // Update nav links
        document.querySelectorAll('.navbar__link').forEach(link => {
            const href = link.getAttribute('href');
            if (href === `#/${path}`) {
                link.classList.add('navbar__link--active');
            } else {
                link.classList.remove('navbar__link--active');
            }
        });

        // Update page title
        const handler = routes[path];
        if (handler) {
            document.title = `${handler.title} — Lakehouse Dashboard`;
            handler.init();
        }
    }

    /**
     * Get current route from hash.
     */
    function getCurrentRoute() {
        const hash = window.location.hash.replace('#/', '') || 'overview';
        return hash;
    }

    /**
     * Initialize router — listen to hash changes.
     */
    function init() {
        window.addEventListener('hashchange', () => {
            const route = getCurrentRoute();
            if (routes[route]) {
                navigate(route);
            } else {
                navigate('overview');
            }
        });

        // Initial navigation
        const route = getCurrentRoute();
        navigate(routes[route] ? route : 'overview');
    }

    return { register, navigate, init, getCurrentRoute };
})();
