"""est_cost: unknown model, #suffix, context tiers, cache rates (fake price entries are removed again)."""
import unittest

import hx

MODEL = "test/unit-fake"
LEGACY = "test/unit-legacy"
FAKE_PRICE = {
    "input": 1.0, "output": 2.0, "cache_read": 100.0, "cache_write": 500.0,
    "tier_ctx": 1000,
    "tier": {"input": 10.0, "output": 20.0, "cache_read": 1000.0, "cache_write": 5000.0},
}


class EstCostTest(unittest.TestCase):
    def setUp(self):
        prices = hx.CFG["prices"]
        prices[MODEL] = dict(FAKE_PRICE)
        prices[LEGACY] = [1.0, 2.0]  # legacy [input, output] form
        self.addCleanup(prices.pop, MODEL, None)
        self.addCleanup(prices.pop, LEGACY, None)

    def test_unknown_model_returns_none(self):
        self.assertIsNone(hx.est_cost("no/such-model-xyz", {"input": 1000}))

    def test_hash_suffix_is_ignored(self):
        tokens = {"input": 500}  # below tier_ctx, so the base rate is used
        self.assertAlmostEqual(0.0005, hx.est_cost(MODEL, tokens), places=6)
        self.assertEqual(hx.est_cost(MODEL, tokens), hx.est_cost(MODEL + "#high", tokens))

    def test_tier_price_applies_above_the_context_limit(self):
        # ctx = 2000 > tier_ctx 1000 -> tier input 10.0 / 1M
        self.assertAlmostEqual(0.02, hx.est_cost(MODEL, {"input": 2000}), places=6)

    def test_base_price_at_the_context_limit(self):
        # ctx == tier_ctx is not "above" it: base input 1.0 / 1M
        self.assertAlmostEqual(0.001, hx.est_cost(MODEL, {"input": 1000}), places=6)

    def test_cache_tokens_count_towards_the_context_tier(self):
        # ctx = 1500 > 1000 -> tier cache_read 1000.0 / 1M (base would be 0.15)
        self.assertAlmostEqual(1.5, hx.est_cost(MODEL, {"cache_read": 1500}), places=6)

    def test_cache_read_and_write_have_their_own_prices(self):
        # ctx = 800 stays in the base tier: 400*100/1M + 400*500/1M = 0.04 + 0.2
        cost = hx.est_cost(MODEL, {"cache_read": 400, "cache_write": 400})
        self.assertAlmostEqual(0.24, cost, places=6)

    def test_reasoning_tokens_are_priced_as_output(self):
        # (250k output + 250k reasoning) * 2.0 / 1M = 1.0
        self.assertAlmostEqual(1.0, hx.est_cost(MODEL, {"output": 250000, "reasoning": 250000}), places=6)

    def test_tiers_false_ignores_the_tier(self):
        # input 2000 * 1.0 / 1M (base rate)
        self.assertAlmostEqual(0.002, hx.est_cost(MODEL, {"input": 2000}, tiers=False), places=6)

    def test_per_step_list_is_summed(self):
        # each step stays below tier_ctx: 500*1.0/1M + 250*2.0/1M = 0.0005 + 0.0005
        steps = [{"input": 500}, {"output": 250}]
        self.assertAlmostEqual(0.001, hx.est_cost(MODEL, steps), places=6)

    def test_aggregate_dict_matches_a_single_step(self):
        tokens = {"input": 500}
        self.assertEqual(hx.est_cost(MODEL, [tokens]), hx.est_cost(MODEL, tokens))

    def test_legacy_list_price_is_supported(self):
        # [1.0, 2.0]: 1M input -> 1.0, 1M output -> 2.0
        self.assertAlmostEqual(1.0, hx.est_cost(LEGACY, {"input": 1000000}), places=6)
        self.assertAlmostEqual(2.0, hx.est_cost(LEGACY, {"output": 1000000}), places=6)


if __name__ == "__main__":
    unittest.main()
