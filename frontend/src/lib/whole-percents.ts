/** Largest remainder. Rounded one by one, three shares of 33.33 print "33%"
 * three times and the reader adds up 99; these always add up to 100. Every
 * reading of one set of shares - the product's summary and cards, the public
 * check's result (HRP-1148) - takes its percents from here, so they cannot
 * disagree either. `order` settles a tie: the earlier key rounds up. */
export function wholePercents<K extends string>(
  shares: Record<K, number>,
  order: readonly K[],
): Record<K, number> {
  const whole = Object.fromEntries(
    order.map((key) => [key, Math.floor(shares[key])]),
  ) as Record<K, number>;
  const short = 100 - order.reduce((sum, key) => sum + whole[key], 0);
  [...order]
    .sort((a, b) => (shares[b] % 1) - (shares[a] % 1))
    .slice(0, Math.max(0, short))
    .forEach((key) => {
      whole[key] += 1;
    });
  return whole;
}
