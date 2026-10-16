import re
import unittest
from pathlib import Path


CRON = Path(__file__).resolve().parents[1] / "rssbox-patches" / "rt_cron"


def minutes(expression):
    result = set()
    for part in expression.split(","):
        range_part, *step_part = part.split("/")
        step = int(step_part[0]) if step_part else 1
        if range_part == "*":
            start, end = 0, 59
        elif "-" in range_part:
            start, end = map(int, range_part.split("-"))
        else:
            start = end = int(range_part)
        result.update(range(start, end + 1, step))
    return result


class CronScheduleTest(unittest.TestCase):
    def test_hourly_job_is_bounded_and_does_not_skip_private_feed_ids(self):
        hourly = next(line for line in CRON.read_text().splitlines()
                      if "--frequency 60" in line)
        self.assertIn("timeout --signal=TERM 45m", hourly)
        self.assertNotIn("--exclude-feed", hourly)

    def test_feed_jobs_never_compete_at_the_same_minute(self):
        jobs = []
        for line in CRON.read_text().splitlines():
            match = re.search(r"--frequency (\d+)", line)
            if match:
                fields = line.split()
                jobs.append((int(match.group(1)), minutes(fields[0]), fields[1], fields[4]))
        self.assertEqual({job[0] for job in jobs}, {5, 15, 30, 60, 1440, 10080})
        for hour in range(24):
            for weekday in range(7):
                active = [
                    (frequency, minute)
                    for frequency, minute_set, hour_field, weekday_field in jobs
                    if hour_field == "*" or int(hour_field) == hour
                    if weekday_field == "*" or int(weekday_field) == weekday
                    for minute in minute_set
                ]
                self.assertEqual(len(active), len({minute for _, minute in active}), (hour, weekday, active))


if __name__ == "__main__":
    unittest.main()
