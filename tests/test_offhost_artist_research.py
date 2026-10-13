#!/usr/bin/env python3
"""No-network contract tests for the off-host artist researcher."""
import unittest
from scripts.research_artist_identities_offhost import names_from, normalize

class ArtistInputTest(unittest.TestCase):
    def test_list_rows(self):
        self.assertEqual(list(names_from([{"name":"Phoenix"},{"artist":"The Horrors"}])),["Phoenix","The Horrors"])
    def test_dict_by_slug(self):
        self.assertEqual(list(names_from({"phoenix":{"name":"Phoenix"},"the-horrors":{"name":"The Horrors"}})),["Phoenix","The Horrors"])
    def test_wrapper(self):
        self.assertEqual(list(names_from({"artists":[{"name":"Cat Power"}]})),["Cat Power"])
    def test_unicode_equivalent_case(self):
        self.assertEqual(normalize(" PUP "),"pup")
    def test_empty_data(self):
        self.assertEqual(list(names_from({})),[])

if __name__=="__main__":
    unittest.main()
