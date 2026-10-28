import unittest

from inkwell.text import excerpt, reading_time


class TextTests(unittest.TestCase):
    def test_reading_time_is_at_least_one_minute(self):
        self.assertEqual(reading_time("just a few words"), 1)

    def test_excerpt_cuts_at_a_word(self):
        self.assertEqual(excerpt("one two three", limit=8), "one two…")


if __name__ == "__main__":
    unittest.main()
