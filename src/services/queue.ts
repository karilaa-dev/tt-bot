interface QueueState {
  count: number;
  tail: Promise<void>;
}

export interface QueueOptions {
  group?: boolean;
  bypassLimit?: boolean;
}

export class QueueManager {
  private readonly queues = new Map<number, QueueState>();

  constructor(readonly privateCapacity = 3, readonly groupCapacity = 10) {
    if (!Number.isSafeInteger(privateCapacity) || privateCapacity < 1) throw new Error("Private queue capacity must be a positive integer");
    if (!Number.isSafeInteger(groupCapacity) || groupCapacity < 1) throw new Error("Group queue capacity must be a positive integer");
  }

  count(key: number): number { return this.queues.get(key)?.count ?? 0; }
  capacity(group = false): number { return group ? this.groupCapacity : this.privateCapacity; }
  hasCapacity(key: number, group = false): boolean { return this.count(key) < this.capacity(group); }

  async withSlot<T>(key: number, operation: () => Promise<T>, options: QueueOptions = {}): Promise<{ acquired: true; value: T } | { acquired: false }> {
    const capacity = this.capacity(options.group);
    let state = this.queues.get(key);
    if (!state) {
      state = { count: 0, tail: Promise.resolve() };
      this.queues.set(key, state);
    }
    if (!options.bypassLimit && state.count >= capacity) return { acquired: false };

    state.count++;
    const previous = state.tail;
    let release!: () => void;
    const turn = new Promise<void>((resolve) => { release = resolve; });
    state.tail = previous.then(() => turn);
    await previous;
    try { return { acquired: true, value: await operation() }; }
    finally {
      release();
      state.count--;
      if (state.count === 0 && this.queues.get(key) === state) this.queues.delete(key);
    }
  }
}
