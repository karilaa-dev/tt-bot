export const STATS_CALLBACK_PREFIX = "stats_noop";
export interface CallbackButton { text: string; callback_data: string }

export function formatStat(value: number): string {
  if (value >= 999_950) return `${Number((value / 1_000_000).toFixed(1))}M`;
  if (value >= 1_000) return `${Number((value / 1_000).toFixed(1))}K`;
  return String(value);
}

export function statsRow(likes?: number | null, views?: number | null): CallbackButton[] {
  const row: CallbackButton[] = [];
  if (likes != null) row.push({ text: `❤️ ${formatStat(likes)}`, callback_data: STATS_CALLBACK_PREFIX });
  if (views != null) row.push({ text: `👁 ${formatStat(views)}`, callback_data: STATS_CALLBACK_PREFIX });
  return row;
}
