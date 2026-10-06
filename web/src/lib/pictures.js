// The people's photos on the map (the interface and the Activity): each one is cut into a circle with a ring of the color of the person's name, as one picture, and given
// to Sigma's image program, which draws it over the whole point. The map draws pictures in a square otherwise, and a face would come out with corners.
import { createNodeImageProgram } from '@sigma/node-image';

export const imageProgram = createNodeImageProgram({ size: { mode: 'force', value: 128 }, objectFit: 'cover', drawingMode: 'background', padding: 0, keepWithinCircle: true, colorAttribute: 'color' });

// Centered, as large as fits. The ring is about a tenth of the width.
export async function circular(blob, ringColor) {
  const bitmap = await createImageBitmap(blob);
  const size = 128;
  const ring = 11;
  const canvas = Object.assign(document.createElement('canvas'), { width: size, height: size });
  const context = canvas.getContext('2d');
  context.fillStyle = ringColor;
  context.beginPath();
  context.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
  context.fill();
  context.beginPath();
  context.arc(size / 2, size / 2, size / 2 - ring, 0, Math.PI * 2);
  context.clip();
  const side = Math.min(bitmap.width, bitmap.height);
  context.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, ring, ring, size - 2 * ring, size - 2 * ring);
  bitmap.close();
  return URL.createObjectURL(await new Promise((resolve) => canvas.toBlob(resolve, 'image/png')));
}

// Fetches the photos of the nodes that have one (`node.avatar` is a path of the application), a few at a time, and puts them on the map. `request(path)` gives the fetch (the
// Activity adds its token). What was fetched is kept (`urls`: person -> local address, or null): a new map only draws it again.
export function pictureLoader(map, request) {
  const urls = new Map();
  async function fetchOne(node) {
    if (!urls.has(node.id)) {
      try {
        const response = await request(node.avatar);
        urls.set(node.id, response.ok ? await circular(await response.blob(), node.color || '#dbdee1') : null);
      } catch {
        urls.set(node.id, null);
      }
    }
    if (urls.get(node.id)) map.setPicture(node.id, urls.get(node.id));
  }
  async function show(nodes) {
    const queue = nodes.filter((n) => n.avatar);
    await Promise.all(Array.from({ length: 6 }, async () => {
      for (let node = queue.shift(); node; node = queue.shift()) await fetchOne(node);
    }));
  }
  return { show, urls };
}
