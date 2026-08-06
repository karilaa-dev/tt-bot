import { describe, expect, test } from "bun:test";
import { QueueManager } from "../src/services/queue.ts";

describe("QueueManager", () => {
  test("holds a private slot through the complete FIFO job", async () => {
    const queue = new QueueManager(3, 10, 25);
    const started: number[] = [];
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const first = queue.withSlot(7, async () => { started.push(1); await gate; return 1; });
    const second = queue.withSlot(7, async () => { started.push(2); return 2; });
    const third = queue.withSlot(7, async () => { started.push(3); return 3; });
    await Bun.sleep(0);
    expect(queue.count(7)).toBe(3);
    expect(started).toEqual([1]);
    expect(queue.rejectionReason(7)).toBe("capacity");
    expect(await queue.withSlot(7, async () => 4)).toEqual({ acquired: false, reason: "capacity" });
    release();
    expect((await Promise.all([first, second, third])).map((result) => result.acquired ? result.value : null)).toEqual([1, 2, 3]);
    expect(started).toEqual([1, 2, 3]);
    expect(queue.count(7)).toBe(0);
  });

  test("accepts unlimited global waiting work while running at most 25 jobs", async () => {
    const queue = new QueueManager(3, 10, 25);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let active = 0;
    let maximumActive = 0;
    const jobs = Array.from({ length: 40 }, (_, index) => queue.withSlot(index + 1, async () => {
      active++;
      maximumActive = Math.max(maximumActive, active);
      await gate;
      active--;
      return index;
    }));
    await Bun.sleep(0);
    expect(queue.activeCount()).toBe(25);
    expect(active).toBe(25);
    release();
    const results = await Promise.all(jobs);
    expect(results.every((result) => result.acquired)).toBe(true);
    expect(maximumActive).toBe(25);
    expect(queue.activeCount()).toBe(0);
  });

  test("drops queued jobs on shutdown but lets active work finish", async () => {
    const queue = new QueueManager(3, 10, 25);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const active = queue.withSlot(9, async () => { await gate; return "done"; });
    const queued = queue.withSlot(9, async () => "should not run");
    await Bun.sleep(0);
    queue.shutdown();
    expect(await queued).toEqual({ acquired: false, reason: "shutdown" });
    expect(queue.rejectionReason(10)).toBe("shutdown");
    expect(await queue.withSlot(10, async () => "new")).toEqual({ acquired: false, reason: "shutdown" });
    expect(queue.activeCount()).toBe(1);
    release();
    expect(await active).toEqual({ acquired: true, value: "done" });
    expect(queue.activeCount()).toBe(0);
  });
});
