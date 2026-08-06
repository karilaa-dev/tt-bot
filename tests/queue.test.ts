import { describe, expect, test } from "bun:test";
import { QueueManager } from "../src/services/queue.ts";

describe("QueueManager", () => {
  test("limits concurrent work per key and always releases", async () => {
    const queue = new QueueManager(1);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const first = queue.withSlot(7, async () => { await gate; return "done"; });
    await Bun.sleep(0);
    expect(queue.count(7)).toBe(1);
    expect(await queue.withSlot(7, async () => "no")).toEqual({ acquired: false });
    expect((await queue.withSlot(7, async () => "inline", true))).toEqual({ acquired: true, value: "inline" });
    release(); expect((await first)).toEqual({ acquired: true, value: "done" }); expect(queue.count(7)).toBe(0);
  });
});
