// How dates are written for the person, in French. One place, so that the pages say the same thing the same way.

const DAY = { day: 'numeric', month: 'short', year: 'numeric' };

/** « 3 oct. 2026 », or `empty` when there is no date. */
export const day = (iso, empty = '—') => (iso ? new Date(iso).toLocaleDateString('fr-FR', DAY) : empty);

/** « il y a 12 s », « il y a 5 min », « il y a 3 h », « il y a 2 j »: `now` is the current time in ms (a page that keeps it in a state refreshes the text as time goes). */
export function ago(iso, now = Date.now()) {
  if (!iso) return '—';
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 90) return `il y a ${seconds} s`;
  if (seconds < 5400) return `il y a ${Math.round(seconds / 60)} min`;
  if (seconds < 129600) return `il y a ${Math.round(seconds / 3600)} h`;
  return `il y a ${Math.round(seconds / 86400)} j`;
}

/** « 0 lien », « 1 lien », « 2 liens »: in French zero and one are singular. */
export const plural = (n, one, many) => (n < 2 ? one : many);
