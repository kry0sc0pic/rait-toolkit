import unittest

from lms_buddy.render import _multi_page


DOC1 = r'''\documentclass{article}
\newcommand{\labeltext}{First page}
\begin{document}
\labeltext
\end{document}
'''

DOC2 = r'''\documentclass{article}
\newcommand{\labeltext}{Second page}
\begin{document}
\labeltext
\end{document}
'''


class MultiPageRenderTests(unittest.TestCase):
    def test_multi_page_merges_bodies_under_one_document(self):
        merged = _multi_page([DOC1, DOC2])

        self.assertEqual(merged.count(r"\begin{document}"), 1)
        self.assertEqual(merged.count(r"\end{document}"), 1)
        self.assertEqual(merged.count(r"\newpage"), 1)
        self.assertIn(r"\newcommand{\labeltext}{First page}", merged)
        self.assertIn(r"\renewcommand{\labeltext}{Second page}", merged)
        self.assertLess(merged.find(r"\newcommand{\labeltext}{First page}"), merged.find(r"\renewcommand{\labeltext}{Second page}"))

    def test_multi_page_rejects_empty_batches(self):
        with self.assertRaises(ValueError):
            _multi_page([])


if __name__ == "__main__":
    unittest.main()
