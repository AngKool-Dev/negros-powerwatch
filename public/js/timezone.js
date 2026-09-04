const TIMEZONE = 'Asia/Manila';

export function formatPHT(isoString) {
    if (!isoString) return 'Unknown';
    const d = new Date(isoString);
    return d.toLocaleString('en-PH', {
        timeZone: TIMEZONE,
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

export function formatPHTTime(isoString) {
    if (!isoString) return 'Unknown';
    const d = new Date(isoString);
    return d.toLocaleString('en-PH', {
        timeZone: TIMEZONE,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

export function formatPHTDateTime(isoString) {
    if (!isoString) return 'Unknown';
    const d = new Date(isoString);
    return d.toLocaleString('en-PH', {
        timeZone: TIMEZONE,
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}
