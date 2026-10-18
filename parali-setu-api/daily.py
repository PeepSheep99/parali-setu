"""The daily Cloud Run job (Cloud Scheduler, 06:30 IST):

1. reset the demo season (reset_demo.py), so bookings and the dispatch board
   are current for anyone who opens the site that day;
2. fetch this week's NASA FIRMS fires from Earth Engine (fetch_fire_data.py),
   which also runs the Sentinel-2 field checks that are due and sends fire
   alerts for farms with open bookings through Pub/Sub.

    python daily.py            # both
    python daily.py --no-reset # only the satellite refresh
"""
import argparse

import fetch_fire_data
import reset_demo

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args()
    if not args.no_reset:
        reset_demo.run(include_listings=True)
    fetch_fire_data.run()
