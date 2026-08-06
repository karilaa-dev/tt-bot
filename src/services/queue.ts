export class QueueManager {
  private readonly counts = new Map<number, number>();

  constructor(readonly maxPerUser: number) {}

  count(userId: number): number { return this.counts.get(userId) ?? 0; }

  async withSlot<T>(userId: number, operation: () => Promise<T>, bypassLimit = false): Promise<{ acquired: true; value: T } | { acquired: false }> {
    const current = this.count(userId);
    if (!bypassLimit && this.maxPerUser > 0 && current >= this.maxPerUser) return { acquired: false };
    this.counts.set(userId, current + 1);
    try { return { acquired: true, value: await operation() }; }
    finally {
      const next = this.count(userId) - 1;
      if (next <= 0) this.counts.delete(userId); else this.counts.set(userId, next);
    }
  }
}
