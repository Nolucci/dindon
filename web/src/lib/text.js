// Searching: ignore case, accents and fancy letters (the same way as the search of the map), and match every word typed, in any order.
export const fold = (text) => String(text ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();

export function matches(query, ...fields) {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const haystack = fields.map(fold).join(' ');
  return words.every((w) => haystack.includes(w));
}

// "/" puts the cursor in the search box of the page (when the person is not already typing somewhere)
export function slash(node) {
  const key = (event) => {
    const tag = (event.target?.tagName ?? '').toLowerCase();
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey || ['input', 'textarea', 'select'].includes(tag) || event.target?.isContentEditable) return;
    event.preventDefault();
    node.focus();
    node.select?.();
  };
  window.addEventListener('keydown', key);
  return { destroy: () => window.removeEventListener('keydown', key) };
}

