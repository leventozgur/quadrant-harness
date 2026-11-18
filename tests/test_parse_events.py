"""parse_events: final text, token totals, counters, timestamps (existing behaviour only)."""
import json
import unittest

import hx


def ev(**kwargs):
    return json.dumps(kwargs)


def text(ts, message_id, body):
    return ev(type="text", timestamp=ts, sessionID="ses_x",
              part={"messageID": message_id, "text": body})


def finish(ts, inp=0, out=0, reasoning=0, read=0, write=0):
    return ev(type="step_finish", timestamp=ts, sessionID="ses_x",
              part={"tokens": {"input": inp, "output": out, "reasoning": reasoning,
                               "cache": {"read": read, "write": write}}})


class ParseEventsTest(unittest.TestCase):
    def test_final_text_is_the_last_message(self):
        raw = "\n".join([text(1000, "m1", "ilk metin"), text(1100, "m2", "son metin")])
        final = hx.parse_events(raw)[0]
        self.assertEqual("son metin", final)

    def test_final_text_joins_all_parts_of_the_last_message(self):
        raw = "\n".join([text(1000, "m1", "eski"), text(1100, "m2", "mer"), text(1200, "m2", "haba")])
        final = hx.parse_events(raw)[0]
        self.assertEqual("merhaba", final)

    def test_step_finish_tokens_are_summed(self):
        raw = "\n".join([finish(1000, inp=100, out=20, reasoning=5, read=50, write=10),
                         finish(2000, inp=200, out=40, reasoning=7, read=30, write=2)])
        final, tok, steps, tools, errors, secs, step_toks = hx.parse_events(raw)
        self.assertEqual("", final)
        self.assertEqual(2, steps)
        self.assertEqual({"input": 300, "output": 60, "reasoning": 12,
                          "cache_read": 80, "cache_write": 12}, tok)
        self.assertEqual(2, len(step_toks))
        self.assertEqual(100, step_toks[0]["input"])
        self.assertEqual(50, step_toks[0]["cache_read"])
        self.assertEqual(7, step_toks[1]["reasoning"])

    def test_tool_events_are_counted(self):
        raw = "\n".join([
            ev(type="tool_use", timestamp=1000, sessionID="ses_x",
               part={"tool": "shell", "state": {"input": {"command": "ls"}}}),
            ev(type="tool", timestamp=1001, sessionID="ses_x", part={"tool": "read"}),
            text(1002, "m1", "bitti"),
        ])
        _, _, steps, tools, errors, _, _ = hx.parse_events(raw)
        self.assertEqual(2, tools)
        self.assertEqual(0, steps)
        self.assertEqual(0, errors)

    def test_error_events_are_counted(self):
        raw = "\n".join([
            ev(type="error", timestamp=1000, sessionID="ses_x", error={"message": "boom"}),
            ev(type="error", timestamp=1001, sessionID="ses_x", error={"message": "boom2"}),
            text(1002, "m1", "yine de bitti"),
        ])
        _, _, _, _, errors, _, _ = hx.parse_events(raw)
        self.assertEqual(2, errors)

    def test_non_json_and_broken_lines_are_ignored(self):
        raw = "\n".join([
            "bu bir log satiri",
            "{bozuk json",
            "[1, 2, 3]",
            "",
            text(1000, "m1", "gecerli"),
        ])
        final, tok, steps, tools, errors, secs, step_toks = hx.parse_events(raw)
        self.assertEqual("gecerli", final)
        self.assertEqual(0, steps)
        self.assertEqual(0, tools)
        self.assertEqual(0, errors)
        self.assertEqual(0, tok["input"])
        self.assertEqual([], step_toks)
        self.assertIsNone(secs)

    def test_single_timestamp_gives_no_seconds(self):
        raw = text(1000, "m1", "tek")
        secs = hx.parse_events(raw)[5]
        self.assertIsNone(secs)

    def test_seconds_span_first_to_last_timestamp(self):
        raw = "\n".join([text(1000, "m1", "a"), text(1500, "m1", "b"), text(2100, "m1", "c")])
        secs = hx.parse_events(raw)[5]
        self.assertEqual(1.1, secs)

    def test_empty_input(self):
        final, tok, steps, tools, errors, secs, step_toks = hx.parse_events("")
        self.assertEqual("", final)
        self.assertEqual(0, steps)
        self.assertEqual(0, tools)
        self.assertEqual(0, errors)
        self.assertIsNone(secs)
        self.assertEqual([], step_toks)
        self.assertEqual(0, sum(tok.values()))


if __name__ == "__main__":
    unittest.main()
