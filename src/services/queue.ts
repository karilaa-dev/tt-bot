interface QueueJob<T> {
  operation: () => Promise<T>;
  resolve: (result: QueueResult<T>) => void;
  reject: (error: unknown) => void;
}

interface QueueState {
  active: boolean;
  jobs: Array<QueueJob<unknown>>;
}

export interface QueueOptions {
  group?: boolean;
}

export type QueueRejectionReason = "capacity" | "shutdown";

export type QueueResult<T> =
  | { acquired: true; value: T }
  | { acquired: false; reason: QueueRejectionReason };

export class QueueManager {
  private readonly queues = new Map<number, QueueState>();
  private readonly readyKeys: number[] = [];
  private readonly readySet = new Set<number>();
  private accepting = true;
  private activeJobs = 0;

  constructor(readonly privateCapacity = 3, readonly groupCapacity = 10, readonly maxActiveJobs = 25) {
    if (!Number.isSafeInteger(privateCapacity) || privateCapacity < 1) throw new Error("Private queue capacity must be a positive integer");
    if (!Number.isSafeInteger(groupCapacity) || groupCapacity < 1) throw new Error("Group queue capacity must be a positive integer");
    if (!Number.isSafeInteger(maxActiveJobs) || maxActiveJobs < 1) throw new Error("Active job limit must be a positive integer");
  }

  count(key: number): number {
    const state = this.queues.get(key);
    return state ? state.jobs.length + Number(state.active) : 0;
  }

  activeCount(): number { return this.activeJobs; }
  capacity(group = false): number { return group ? this.groupCapacity : this.privateCapacity; }
  rejectionReason(key: number, group = false): QueueRejectionReason | null {
    if (!this.accepting) return "shutdown";
    return this.count(key) >= this.capacity(group) ? "capacity" : null;
  }
  hasCapacity(key: number, group = false): boolean { return this.rejectionReason(key, group) === null; }

  withSlot<T>(key: number, operation: () => Promise<T>, options: QueueOptions = {}): Promise<QueueResult<T>> {
    if (!this.accepting) return Promise.resolve({ acquired: false, reason: "shutdown" });
    const capacity = this.capacity(options.group);
    let state = this.queues.get(key);
    if (!state) {
      state = { active: false, jobs: [] };
      this.queues.set(key, state);
    }
    if (state.jobs.length + Number(state.active) >= capacity) {
      return Promise.resolve({ acquired: false, reason: "capacity" });
    }

    const result = new Promise<QueueResult<T>>((resolve, reject) => {
      state.jobs.push({ operation, resolve, reject } as QueueJob<unknown>);
    });
    this.markReady(key, state);
    this.schedule();
    return result;
  }

  shutdown(): void {
    if (!this.accepting) return;
    this.accepting = false;
    this.readyKeys.length = 0;
    this.readySet.clear();
    for (const [key, state] of this.queues) {
      for (const job of state.jobs.splice(0)) job.resolve({ acquired: false, reason: "shutdown" });
      if (!state.active) this.queues.delete(key);
    }
  }

  private markReady(key: number, state: QueueState): void {
    if (!this.accepting || state.active || state.jobs.length === 0 || this.readySet.has(key)) return;
    this.readySet.add(key);
    this.readyKeys.push(key);
  }

  private schedule(): void {
    while (this.accepting && this.activeJobs < this.maxActiveJobs) {
      const key = this.readyKeys.shift();
      if (key === undefined) return;
      this.readySet.delete(key);
      const state = this.queues.get(key);
      if (!state || state.active || state.jobs.length === 0) continue;
      const job = state.jobs.shift()!;
      state.active = true;
      this.activeJobs++;
      void this.run(key, state, job);
    }
  }

  private async run(key: number, state: QueueState, job: QueueJob<unknown>): Promise<void> {
    try {
      job.resolve({ acquired: true, value: await job.operation() });
    } catch (error) {
      job.reject(error);
    } finally {
      state.active = false;
      this.activeJobs--;
      if (state.jobs.length === 0) this.queues.delete(key);
      else this.markReady(key, state);
      this.schedule();
    }
  }
}
