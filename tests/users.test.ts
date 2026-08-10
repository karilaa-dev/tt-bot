import { expect, test } from "bun:test";
import type { Database } from "../src/db/client.ts";
import { getUserIds } from "../src/db/users.ts";

test("user exports include private and group chat IDs by default", async () => {
  let query = "";
  const db = {
    sql: async (strings: TemplateStringsArray) => {
      query = strings.join("?").replace(/\s+/gu, " ").trim();
      return [{ user_id: "-100500" }, { user_id: "101" }];
    },
  } as unknown as Database;

  expect(await getUserIds(db)).toEqual([-100500, 101]);
  expect(query).toBe("SELECT user_id FROM users ORDER BY user_id");
});
