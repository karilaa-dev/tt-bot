import { describe, expect, test } from "bun:test";
import { QueueManager } from "../src/services/queue.ts";

describe("QueueManager", () => {
  test("queues three private jobs FIFO while running only one extraction", async () => {
    const queue = new QueueManager(3, 10);
    const started: number[] = [];
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const first = queue.withSlot(7, async () => { started.push(1); await gate; return 1; });
    const second = queue.withSlot(7, async () => { started.push(2); return 2; });
    const third = queue.withSlot(7, async () => { started.push(3); return 3; });
    await Bun.sleep(0);
    expect(queue.count(7)).toBe(3);
    expect(started).toEqual([1]);
    expect(await queue.withSlot(7, async () => 4)).toEqual({ acquired: false });
    release();
    expect((await Promise.all([first, second, third])).map((result) => result.acquired ? result.value : null)).toEqual([1, 2, 3]);
    expect(started).toEqual([1, 2, 3]);
    expect(queue.count(7)).toBe(0);
  });

  test("accepts ten group jobs and lets inline bypass capacity without bypassing serialization", async () => {
    const queue = new QueueManager(3, 10);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let active = 0;
    let maximumActive = 0;
    const operation = async () => { active++; maximumActive = Math.max(maximumActive, active); await gate; active--; return true; };
    const jobs = Array.from({ length: 10 }, () => queue.withSlot(-100, operation, { group: true }));
    await Bun.sleep(0);
    expect(queue.count(-100)).toBe(10);
    expect(await queue.withSlot(-100, operation, { group: true })).toEqual({ acquired: false });
    const inline = queue.withSlot(-100, operation, { group: true, bypassLimit: true });
    expect(queue.count(-100)).toBe(11);
    release();
    await Promise.all([...jobs, inline]);
    expect(maximumActive).toBe(1);
    expect(queue.count(-100)).toBe(0);
  });
});
