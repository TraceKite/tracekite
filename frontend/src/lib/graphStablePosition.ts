export function stableJitter(id: string, axis: number): number {
  let hash = 2166136261 ^ axis;
  for (let index = 0; index < id.length; index++) {
    hash ^= id.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) / 0xffffffff - 0.5) * 1.5;
}
