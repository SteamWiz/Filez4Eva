from unittest import TestCase

import filez4eva.__main__


class TestNull(TestCase):

    def test_none(self):
        x = None
        self.assertIsNone(x)
