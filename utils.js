/**
 * The Traitors - Shared Utilities
 * Common JavaScript functions used across all HTML pages
 */

/**
 * Format a timestamp as a human-readable date
 * @param {string|number} timestamp - ISO date string or Unix timestamp
 * @returns {string} Formatted date string
 */
function formatDate(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleDateString('en-US', {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Format a duration in seconds as human-readable
 * @param {number} seconds - Duration in seconds
 * @returns {string} Formatted duration string (e.g., "5m 30s", "1h 15m")
 */
function formatDuration(seconds) {
    if (!seconds || seconds === 0) return '-';
    if (seconds < 60) return `${Math.round(seconds)}s`;

    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);

    if (mins >= 60) {
        const hours = Math.floor(mins / 60);
        const remainMins = mins % 60;
        return remainMins > 0 ? `${hours}h\u00A0${remainMins}m` : `${hours}h`;
    }

    return secs > 0 ? `${mins}m\u00A0${secs}s` : `${mins}m`;
}

/**
 * Format a cost value as currency
 * @param {number} cost - Cost in dollars
 * @returns {string} Formatted cost string (e.g., "$1.50")
 */
function formatCost(cost) {
    if (!cost || cost === 0) return '-';
    return `$${cost.toFixed(2)}`;
}

/**
 * Format a large number with K/M suffixes
 * @param {number} num - Number to format
 * @returns {string} Formatted number string (e.g., "1.5M", "250K")
 */
function formatNumber(num) {
    if (!num || num === 0) return '-';
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

/**
 * Format a model name to a shorter display name
 * @param {string} model - Full model name
 * @returns {string} Shortened display name
 */
function formatModelName(model) {
    if (!model) return '-';

    // Common model name mappings
    const mappings = {
        'claude-3-5-haiku-20241022': 'Haiku 3.5',
        'claude-3-5-sonnet-20241022': 'Sonnet 3.5',
        'claude-3-opus-20240229': 'Opus 3',
        'claude-3-sonnet-20240229': 'Sonnet 3',
        'claude-3-haiku-20240307': 'Haiku 3',
        'gemini-2.0-flash-lite': 'Gemini Flash',
        'gemini-2.0-flash': 'Gemini Flash',
        'gemini-1.5-pro': 'Gemini Pro',
        'llama3.2': 'Llama 3.2',
        'llama3.1': 'Llama 3.1',
    };

    return mappings[model] || model;
}

/**
 * Get URL parameter by name
 * @param {string} name - Parameter name
 * @returns {string|null} Parameter value or null if not found
 */
function getUrlParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name);
}

/**
 * Show a loading state in a container
 * @param {HTMLElement} container - Container element
 * @param {string} message - Loading message (default: "Loading...")
 */
function showLoading(container, message = 'Loading...') {
    container.innerHTML = `<div class="loading">${message}</div>`;
}

/**
 * Show an error state in a container
 * @param {HTMLElement} container - Container element
 * @param {string} message - Error message
 */
function showError(container, message) {
    container.innerHTML = `<div class="error">${message}</div>`;
}

/**
 * Show a "no data" state in a container
 * @param {HTMLElement} container - Container element
 * @param {string} message - Message to show
 */
function showNoData(container, message) {
    container.innerHTML = `<div class="no-data">${message}</div>`;
}

/**
 * Fetch JSON data with error handling
 * @param {string} url - URL to fetch
 * @returns {Promise<Object>} Parsed JSON data
 * @throws {Error} If fetch fails or response is not OK
 */
async function fetchJSON(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return response.json();
}

/**
 * Escape HTML special characters to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Create a badge element
 * @param {string} text - Badge text
 * @param {string} type - Badge type ('traitor', 'faithful', 'config', 'legacy')
 * @returns {HTMLElement} Badge span element
 */
function createBadge(text, type) {
    const badge = document.createElement('span');
    badge.className = `badge ${type}`;
    badge.textContent = text;
    return badge;
}

/**
 * Set up table sorting
 * @param {HTMLTableElement} table - Table element
 * @param {Function} renderFn - Function to re-render table body with sorted data
 * @param {Array} data - Data array to sort
 */
function setupTableSort(table, renderFn, data) {
    let currentSort = { column: null, direction: 'asc' };

    const headers = table.querySelectorAll('th.sortable');
    headers.forEach(th => {
        th.addEventListener('click', () => {
            const column = th.dataset.column;

            // Determine new sort direction
            if (currentSort.column === column) {
                currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.column = column;
                currentSort.direction = 'asc';
            }

            // Update header classes
            headers.forEach(h => {
                h.classList.remove('sorted-asc', 'sorted-desc');
            });
            th.classList.add(`sorted-${currentSort.direction}`);

            // Sort data
            const sortedData = [...data].sort((a, b) => {
                let aVal = a[column];
                let bVal = b[column];

                // Handle nested values (e.g., 'stats.wins')
                if (column.includes('.')) {
                    const parts = column.split('.');
                    aVal = parts.reduce((obj, key) => obj?.[key], a);
                    bVal = parts.reduce((obj, key) => obj?.[key], b);
                }

                // Handle nulls
                if (aVal == null) aVal = 0;
                if (bVal == null) bVal = 0;

                // Compare
                if (typeof aVal === 'string') {
                    return currentSort.direction === 'asc'
                        ? aVal.localeCompare(bVal)
                        : bVal.localeCompare(aVal);
                }

                return currentSort.direction === 'asc' ? aVal - bVal : bVal - aVal;
            });

            renderFn(sortedData);
        });
    });
}

/**
 * Debounce a function call
 * @param {Function} fn - Function to debounce
 * @param {number} delay - Delay in milliseconds
 * @returns {Function} Debounced function
 */
function debounce(fn, delay) {
    let timeoutId;
    return function (...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
}
