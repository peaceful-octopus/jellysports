import datetime
import unittest

from sportyfin.util.listing import matches_filter, parse_matches


def match(**kw):
    base = {
        "id": 1, "title": "Away FC at Home FC", "sport": "basketball", "sport_name": "Basketball",
        "api_id": "event-espn-league-basketball-nba-401", "starts_at": "2026-11-05T00:30:00Z",
        "live": False, "finished": False,
        "home": {"name": "Home FC", "badge": "https://img.example/home.webp"},
        "away": {"name": "Away FC", "badge": "https://img.example/away.webp"},
        "streams": [{"language": "English", "provider": "sc", "embed_url": "https://streamec.st/embed/ch65.php"}],
    }
    base.update(kw)
    return base


class ParseMatchesTests(unittest.TestCase):
    def test_basic_mapping(self):
        (ev,) = parse_matches({"matches": [match()]})
        self.assertEqual(ev.title, "Away FC at Home FC")
        self.assertEqual((ev.home, ev.away), ("Home FC", "Away FC"))
        self.assertEqual(ev.home_badge, "https://img.example/home.webp")
        self.assertEqual(ev.sport, "Basketball")
        self.assertEqual(ev.league, "nba")
        self.assertEqual(ev.kickoff, datetime.datetime(2026, 11, 5, 0, 30, tzinfo=datetime.timezone.utc))
        self.assertEqual(ev.embed_url, "https://streamec.st/embed/ch65.php")

    def test_finished_skipped(self):
        self.assertEqual(parse_matches({"matches": [match(finished=True)]}), [])

    def test_requires_english_embedcenter_stream(self):
        spanish = [{"language": "Spanish", "embed_url": "https://streamec.st/embed/ch10.php"}]
        other_host = [{"language": "English", "embed_url": "https://redirectus.net/streameast.html?id=1"}]
        self.assertEqual(parse_matches({"matches": [match(streams=spanish), match(id=2, streams=other_host)]}), [])

    def test_first_english_embedcenter_stream_wins(self):
        streams = [
            {"language": "English", "embed_url": "https://redirectus.net/streame.html?key=sc-ch5"},
            {"language": "Spanish", "embed_url": "https://streamec.st/embed/ch10.php"},
            {"language": "English", "embed_url": "https://streamec.st/embed/ch5.php"},
        ]
        (ev,) = parse_matches({"matches": [match(streams=streams)]})
        self.assertEqual(ev.embed_url, "https://streamec.st/embed/ch5.php")

    def test_teams_parsed_from_title_when_missing(self):
        (ev,) = parse_matches({"matches": [match(home=None, away=None)]})
        self.assertEqual((ev.away, ev.home), ("Away FC", "Home FC"))

    def test_vs_title_means_home_first(self):
        (ev,) = parse_matches({"matches": [match(home=None, away=None, title="Home FC vs Away FC")]})
        self.assertEqual((ev.home, ev.away), ("Home FC", "Away FC"))

    def test_keys_are_stable_and_distinct(self):
        a = parse_matches({"matches": [match(id=1), match(id=2)]})
        b = parse_matches({"matches": [match(id=1), match(id=2)]})
        self.assertEqual([e.key for e in a], [e.key for e in b])
        self.assertNotEqual(a[0].key, a[1].key)

    def test_missing_start_time_skipped(self):
        self.assertEqual(parse_matches({"matches": [match(starts_at=None)]}), [])


class FilterTests(unittest.TestCase):
    def setUp(self):
        (self.ev,) = parse_matches({"matches": [match()]})

    def test_no_filters_matches_all(self):
        self.assertTrue(matches_filter(self.ev, []))

    def test_matches_sport_league_and_title(self):
        for term in ("basketball", "NBA", "home fc"):
            self.assertTrue(matches_filter(self.ev, [term]), term)

    def test_non_matching(self):
        self.assertFalse(matches_filter(self.ev, ["hockey"]))

    def test_any_of_several(self):
        self.assertTrue(matches_filter(self.ev, ["hockey", "nba"]))


if __name__ == "__main__":
    unittest.main()
