"""Combine two versions of the state file.

Several lanes run on their own schedules and all of them write state/seen.json.
When two land close together, git cannot reconcile them -- a rebase of a JSON
file conflicts, the push step fails, and that run's work is thrown away.

Merging is well defined here because every field is additive: a posting seen by
either run has been seen, and a posting reported by either run has been
reported. So take the union rather than a side.

    python3 -m watcher.merge_state ours.json theirs.json --out merged.json
"""
import argparse
import json
import sys


def load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return {}


def merge(ours, theirs):
    """Union the two, preferring the earliest sighting and latest activity."""
    out = dict(theirs or {})
    out.update({k: v for k, v in (ours or {}).items()
                if k not in ("seen", "reported", "recommended",
                             "seeded_companies", "broken")})

    # seen: keep the earliest first-sighting, since that dates a posting, and
    # the latest last-sighting.
    seen = dict((theirs or {}).get("seen") or {})
    for job_id, record in ((ours or {}).get("seen") or {}).items():
        if not isinstance(record, dict):
            record = {"f": record, "l": record}
        current = seen.get(job_id)
        if not isinstance(current, dict):
            current = {"f": current, "l": current} if current else None
        if current is None:
            seen[job_id] = record
        else:
            seen[job_id] = {
                "f": min(x for x in (current.get("f"), record.get("f")) if x),
                "l": max(x for x in (current.get("l"), record.get("l")) if x),
            }
    out["seen"] = seen

    # reported and seeded_companies are plain sets.
    for key in ("reported", "seeded_companies"):
        out[key] = sorted(set((ours or {}).get(key) or []) |
                          set((theirs or {}).get(key) or []))

    # recommended: keep the most recent date per posting.
    recommended = dict((theirs or {}).get("recommended") or {})
    for job_id, when in ((ours or {}).get("recommended") or {}).items():
        recommended[job_id] = max(when, recommended.get(job_id, ""))
    out["recommended"] = recommended

    # broken: whichever run looked most recently is the better answer.
    ours_run = (ours or {}).get("last_run", "")
    theirs_run = (theirs or {}).get("last_run", "")
    out["broken"] = ((ours or {}).get("broken") if ours_run >= theirs_run
                     else (theirs or {}).get("broken")) or {}
    out["last_run"] = max(ours_run, theirs_run)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ours")
    parser.add_argument("theirs")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    merged = merge(load(args.ours), load(args.theirs))
    with open(args.out, "w") as fh:
        json.dump(merged, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("merged: %d seen, %d reported"
          % (len(merged.get("seen", {})), len(merged.get("reported", []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
